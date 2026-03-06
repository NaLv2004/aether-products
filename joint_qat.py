import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
import numpy as np
import argparse
from gnn_detector import CF_MIMO_Env, GNNDetector, qpsk_demod_torch
from lsq_quantizer import LSQQuantizer
from refinement_policy import ResidualLSQ, BitwidthPolicyNet

# ==========================================
# 1. 位宽感知注意力 GNN (Bit-Aware Attention)
# ==========================================

class AttentionGNNDetector(nn.Module):
    """
    位宽感知注意力机制：
    根据当前链路选择的位宽概率分布 (weights)，动态调整 GNN 对信号的关注程度。
    """
    def __init__(self, L, K, hidden_dim=64):
        super(AttentionGNNDetector, self).__init__()
        self.L = L
        self.K = K
        
        # 边特征处理 (Re, Im, Beta)
        self.edge_mlp = nn.Sequential(
            nn.Linear(3, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim)
        )
        
        # 位宽权重映射：将 [p0, p2, p4] 映射到缩放因子向量
        # 允许网络学习如何根据不同比特的选择来“注意”或“抑制”信号（例如 0-bit 时抑制该链路）
        self.bit_attention_mapper = nn.Sequential(
            nn.Linear(3, 16),
            nn.ReLU(),
            nn.Linear(16, hidden_dim),
            nn.Sigmoid()
        )
        
        self.ue_interaction = nn.Sequential(
            nn.Linear(hidden_dim * K, hidden_dim * 2),
            nn.ReLU(),
            nn.Linear(hidden_dim * 2, K * 2)
        )

    def forward(self, signal, beta, weights):
        """
        signal: (B, L, K, 2) - 已量化的复信号实虚部
        beta: (B, L, K, 1) - 大尺度衰落
        weights: (B, L, K, 3) - 位宽概率 (p0, p2, p4)
        """
        B = signal.shape[0]
        # 合并基本特征
        x = torch.cat([signal, beta], dim=-1) # (B, L, K, 3)
        
        # 1. 提取边特征
        e = self.edge_mlp(x) # (B, L, K, hidden_dim)
        
        # 2. 计算位宽感知缩放因子 (Bit-Aware Attention)
        attn = self.bit_attention_mapper(weights) # (B, L, K, hidden_dim)
        
        # 3. 动态调整强度：位宽决定了特征的重要性
        e_attended = e * attn
        
        # 4. 聚合 (Aggregating links to users)
        u = torch.sum(e_attended, dim=1) # (B, K, hidden_dim)
        u_flat = u.view(B, -1)
        out = self.ue_interaction(u_flat)
        return out.view(B, self.K, 2)

# ==========================================
# 2. 联合 QAT 系统
# ==========================================

class JointQATSystem(nn.Module):
    def __init__(self, L, K, hidden_dim=64):
        # 修复主管指出的语法错误
        super(JointQATSystem, self).__init__()
        self.policy_net = BitwidthPolicyNet()
        self.quantizer = ResidualLSQ()
        self.detector = AttentionGNNDetector(L, K, hidden_dim=hidden_dim)
        self.bits_map = torch.tensor([0.0, 2.0, 4.0])

    def forward(self, features, tau=1.0, hard=False):
        B, L, K, _ = features.shape
        device = features.device
        
        # 1. 获取 Beta 特征用于策略网络
        beta = features[..., 2].unsqueeze(-1)
        
        # 2. 策略决策与位宽权重 (Gumbel-Softmax)
        logits = self.policy_net(beta)
        weights = F.gumbel_softmax(logits, tau=tau, hard=hard, dim=-1)
        
        # 3. 累进式量化 (Residual LSQ)
        signal = features[..., :2]
        quant_branches = self.quantizer(signal) # (B, L, K, 2, 3) -> 对应 0, 2, 4 bits
        # 根据权重混合不同位宽的量化结果
        combined_signal = torch.sum(quant_branches * weights.unsqueeze(-2), dim=-1) # (B, L, K, 2)
        
        # 4. 位宽感知探测 (Bit-Aware Detection)
        out = self.detector(combined_signal, beta, weights)
        
        # 计算平均比特率 (用于 Loss Penalty)
        avg_bitrate = torch.sum(weights * self.bits_map.to(device), dim=-1).mean()
        return out, avg_bitrate

# ==========================================
# 3. 训练与对比
# ==========================================

def run_joint_qat():
    parser = argparse.ArgumentParser(description="Joint QAT with Bit-Aware Attention")
    parser.add_argument("--epochs", type=int, default=150, help="Total training epochs")
    parser.add_argument("--batch_size", type=int, default=128, help="Batch size for training")
    parser.add_argument("--lr", type=float, default=0.001, help="Learning rate")
    parser.add_argument("--lambda_bit", type=float, default=0.002, help="Penalty factor for average bitrate")
    parser.add_argument("--tau_init", type=float, default=1.0, help="Initial temperature for Gumbel-Softmax")
    parser.add_argument("--eval_trials", type=int, default=1000, help="Number of trials for evaluation")
    args = parser.parse_args()

    env = CF_MIMO_Env()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # 定义模型：联合 QAT 模型 vs 全精度基准
    model = JointQATSystem(env.L, env.K).to(device)
    fp_model = GNNDetector(env.L, env.K, input_dim=3).to(device) # 全精度 GNN 基准
    
    optimizer = optim.Adam(model.parameters(), lr=args.lr)
    fp_optimizer = optim.Adam(fp_model.parameters(), lr=args.lr)
    
    criterion = nn.MSELoss()

    print(f"--- Starting Joint QAT & Full-Precision Training ---")
    print(f"Targeting dynamic bit-allocation. Lambda_bit: {args.lambda_bit}")

    for epoch in range(args.epochs):
        model.train()
        fp_model.train()
        
        # 温度退火：逐渐从连续松弛向量转向 hard 类别选择
        tau = max(0.1, args.tau_init * (0.95 ** (epoch // 5)))
        
        # 生成训练数据 (动态 SNR)
        snr_train = np.random.uniform(5, 15)
        feat, labels, _, _, _, _ = env.generate_data(args.batch_size, snr_train)
        feat, labels = feat.to(device), labels.to(device)
        
        # 1. 训练全精度模型 (FP Baseline)
        fp_optimizer.zero_grad()
        fp_out = fp_model(feat)
        fp_loss = criterion(fp_out, labels)
        fp_loss.backward()
        fp_optimizer.step()
        
        # 2. 训练联合 QAT 模型 (Dynamic Policy)
        optimizer.zero_grad()
        dyn_out, avg_bit = model(feat, tau=tau, hard=False)
        mse_loss = criterion(dyn_out, labels)
        # 总损失 = 探测 MSE + 比特率惩罚
        total_loss = mse_loss + args.lambda_bit * avg_bit
        total_loss.backward()
        optimizer.step()
        
        if (epoch + 1) % 25 == 0:
            print(f"Epoch [{epoch+1}/{args.epochs}] | FP-MSE: {fp_loss.item():.6f} | Q-MSE: {mse_loss.item():.6f} | AvgBit: {avg_bit.item():.4f} | Tau: {tau:.4f}")

    # ==========================================
    # 4. 最终评估与对比 (SNR=10dB)
    # ==========================================
    print("\n" + "="*70)
    print("FINAL EVALUATION AT SNR=10dB")
    print("="*70)
    
    model.eval()
    fp_model.eval()
    
    with torch.no_grad():
        feat, labels, true_bits, _, _, _ = env.generate_data(args.eval_trials, 10.0)
        feat, labels = feat.to(device), labels.to(device)
        
        # --- 1. Full-Precision (FP) ---
        fp_out = fp_model(feat)
        fp_mse = criterion(fp_out, labels).item()
        fp_ber = np.mean(qpsk_demod_torch(fp_out) != true_bits)
        fp_sumrate = np.log2(1 + (1 - fp_mse) / max(fp_mse, 1e-7))

        # --- 2. Dynamic Policy (Joint QAT) ---
        dyn_out, dyn_bitrate = model(feat, tau=0.1, hard=True)
        dyn_mse = criterion(dyn_out, labels).item()
        dyn_ber = np.mean(qpsk_demod_torch(dyn_out) != true_bits)
        dyn_sumrate = np.log2(1 + (1 - dyn_mse) / max(dyn_mse, 1e-7))
        
        # --- 3. Fixed 2-bit Baseline ---
        # 复用量化器和探测器，但强制位宽选择为 2-bit
        B, L, K, _ = feat.shape
        fixed_weights = torch.zeros(B, L, K, 3).to(device)
        fixed_weights[..., 1] = 1.0 # 强制 2-bit
        
        beta = feat[..., 2].unsqueeze(-1)
        signal = feat[..., :2]
        q_branches = model.quantizer(signal)
        fixed_signal = torch.sum(q_branches * fixed_weights.unsqueeze(-2), dim=-1)
        fixed_out = model.detector(fixed_signal, beta, fixed_weights)
        
        fixed_mse = criterion(fixed_out, labels).item()
        fixed_ber = np.mean(qpsk_demod_torch(fixed_out) != true_bits)
        fixed_sumrate = np.log2(1 + (1 - fixed_mse) / max(fixed_mse, 1e-7))

    # 计算性能比 (Dynamic MSE / FP MSE)
    perf_ratio = dyn_mse / fp_mse

    # 打印对比表格
    header = f"{'Scheme':<20} | {'MSE':<10} | {'BER':<10} | {'Avg Bit':<8} | {'Sum-rate':<10}"
    print(header)
    print("-" * len(header))
    print(f"{'Full-Precision':<20} | {fp_mse:<10.6f} | {fp_ber:<10.6f} | {8.00:<8.2f} | {fp_sumrate:<10.4f}")
    print(f"{'Fixed 2-bit':<20} | {fixed_mse:<10.6f} | {fixed_ber:<10.6f} | {2.00:<8.2f} | {fixed_sumrate:<10.4f}")
    print(f"{'Dynamic (Policy)':<20} | {dyn_mse:<10.6f} | {dyn_ber:<10.6f} | {dyn_bitrate.item():<8.2f} | {dyn_sumrate:<10.4f}")
    print("-" * len(header))
    
    print(f"Performance Ratio (Dynamic MSE / FP MSE): {perf_ratio:.4f}")
    
    # 最终结论
    if perf_ratio < 1.15:
        print("Conclusion: Dynamic Policy maintains near-optimal performance with significantly reduced bitrate.")
    else:
        print("Conclusion: Dynamic Policy reduces bitrate but shows non-negligible performance gap.")

    # 策略分布统计
    logits = model.policy_net(beta)
    probs = F.softmax(logits, dim=-1)
    p0 = probs[..., 0].mean().item()
    p2 = probs[..., 1].mean().item()
    p4 = probs[..., 2].mean().item()
    print(f"\nAverage Policy Distribution: 0-bit: {p0:.2%}, 2-bit: {p2:.2%}, 4-bit: {p4:.2%}")

if __name__ == "__main__":
    run_joint_qat()