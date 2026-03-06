import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
import numpy as np
import argparse
from gnn_detector import CF_MIMO_Env, GNNDetector, qpsk_demod_torch
from lsq_quantizer import LSQQuantizer

class ResidualLSQ(nn.Module):
    """
    累进式量化模块 (Successive Refinement Quantizer)
    """
    def __init__(self):
        super(ResidualLSQ, self).__init__()
        self.base_quant = LSQQuantizer(bit_width=2)
        self.refine_quant = LSQQuantizer(bit_width=2)

    def forward(self, x):
        # Branch 0: 0-bit
        b0 = torch.zeros_like(x)
        # Branch 1: 2-bit
        b1 = self.base_quant(x)
        # Branch 2: 4-bit
        residual = x - b1
        b2 = b1 + self.refine_quant(residual)
        return torch.stack([b0, b1, b2], dim=-1)

class BitwidthPolicyNet(nn.Module):
    """
    位宽决策网络：优化输入特征为 Log-scaled Beta。
    """
    def __init__(self, hidden_dim=32):
        super(BitwidthPolicyNet, self).__init__()
        self.mlp = nn.Sequential(
            nn.Linear(1, 16),
            nn.ReLU(),
            nn.Linear(16, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, 3)
        )
        # 权重初始化：最后一层设为较小值，使初始概率均衡
        nn.init.uniform_(self.mlp[-1].weight, -0.01, 0.01)
        nn.init.constant_(self.mlp[-1].bias, 0)

    def forward(self, beta):
        # beta 形状: (B, L, K, 1)，值域约 1e-12 ~ 1e-7
        # 1. 对数缩放 (dB)
        log_beta = 10 * torch.log10(beta + 1e-20)
        # 2. 归一化：将 [-120, -70] 映射到约 [-1, 1]
        norm_beta = (log_beta + 95.0) / 25.0
        return self.mlp(norm_beta)

class RefinementPolicySystem(nn.Module):
    def __init__(self, L, K, hidden_dim=64, policy_hidden=32):
        super(RefinementPolicySystem, self).__init__()
        self.policy_net = BitwidthPolicyNet(hidden_dim=policy_hidden)
        self.quantizer = ResidualLSQ()
        # 探测器输入维度改为 6: [Re, Im, Beta, p0, p2, p4]
        self.detector = GNNDetector(L, K, hidden_dim=hidden_dim, input_dim=6)
        self.bits_map = torch.tensor([0.0, 2.0, 4.0])

    def forward(self, features, tau=1.0, hard=False):
        B, L, K, _ = features.shape
        device = features.device
        
        # 1. 策略网络决策
        beta = features[..., 2].unsqueeze(-1) # (B, L, K, 1)
        logits = self.policy_net(beta) # (B, L, K, 3)
        
        # 2. Gumbel-Softmax
        weights = F.gumbel_softmax(logits, tau=tau, hard=hard, dim=-1) # (B, L, K, 3)
        
        # 3. 量化
        signal = features[..., :2]
        quantized_branches = self.quantizer(signal) # (B, L, K, 2, 3)
        
        # 4. 组合信号
        combined_signal = torch.sum(quantized_branches * weights.unsqueeze(-2), dim=-1) # (B, L, K, 2)
        
        # 5. Task-aware 特征拼接: (Re, Im, Beta, p0, p2, p4)
        # weights 已经包含了比特选择信息
        enhanced_features = torch.cat([combined_signal, beta, weights], dim=-1) # (B, L, K, 6)
        
        # 探测器预测
        out = self.detector(enhanced_features) # (B, K, 2)
        
        avg_bitrate = torch.sum(weights * self.bits_map.to(device), dim=-1).mean()
        return out, avg_bitrate

def train_and_eval():
    parser = argparse.ArgumentParser(description="Optimized Successive Refinement Policy")
    parser.add_argument("--train_epochs", type=int, default=200)
    parser.add_argument("--batch_size", type=int, default=128)
    parser.add_argument("--lr", type=float, default=0.001)
    parser.add_argument("--lambda_bit", type=float, default=0.005, help="Weight for bitrate penalty")
    parser.add_argument("--tau", type=float, default=1.0)
    parser.add_argument("--eval_trials", type=int, default=1000)
    args = parser.parse_args()

    env = CF_MIMO_Env()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = RefinementPolicySystem(env.L, env.K).to(device)
    optimizer = optim.Adam(model.parameters(), lr=args.lr)
    scheduler = optim.lr_scheduler.StepLR(optimizer, step_size=70, gamma=0.5)
    criterion = nn.MSELoss()

    print(f"Starting Optimized Training (Log-scaling & Task-aware GNN)...")

    for epoch in range(args.train_epochs):
        model.train()
        current_tau = max(0.1, args.tau * (0.96 ** (epoch // 5)))
        
        snr_train = np.random.uniform(5, 15)
        feat, labels, _, _, _, _ = env.generate_data(args.batch_size, snr_train)
        feat, labels = feat.to(device), labels.to(device)
        
        optimizer.zero_grad()
        outputs, avg_bitrate = model(feat, tau=current_tau, hard=False)
        mse_loss = criterion(outputs, labels)
        
        # Loss = MSE + lambda * Bitrate
        total_loss = mse_loss + args.lambda_bit * avg_bitrate
        total_loss.backward()
        optimizer.step()
        scheduler.step()
        
        if (epoch + 1) % 20 == 0:
            print(f"Epoch [{epoch+1}/{args.train_epochs}], Loss: {total_loss.item():.6f}, MSE: {mse_loss.item():.6f}, AvgBit: {avg_bitrate.item():.4f}, Tau: {current_tau:.4f}")

    # --- 评估 ---
    print("\n--- Final Evaluation (SNR=10dB) ---")
    model.eval()
    with torch.no_grad():
        feat, labels, true_bits, _, _, _ = env.generate_data(args.eval_trials, 10.0)
        feat, labels = feat.to(device), labels.to(device)
        
        # 1. Dynamic Policy
        dyn_out, dyn_bitrate = model(feat, tau=0.1, hard=True)
        dyn_mse = criterion(dyn_out, labels).item()
        dyn_ber = np.mean(qpsk_demod_torch(dyn_out) != true_bits)
        # Sum-rate calculation: R = log2(1 + (1-MSE)/MSE)
        dyn_sumrate = np.log2(1 + (1 - dyn_mse) / (max(dyn_mse, 1e-7)))
        
        # 2. Fixed 2-bit Baseline (需要构造 6-dim 输入以适配 detector)
        B, L, K, _ = feat.shape
        fixed_weights = torch.zeros(B, L, K, 3).to(device)
        fixed_weights[..., 1] = 1.0 # 2-bit branch
        
        signal = feat[..., :2]
        beta_feat = feat[..., 2].unsqueeze(-1)
        q_branches = model.quantizer(signal)
        fixed_signal = torch.sum(q_branches * fixed_weights.unsqueeze(-2), dim=-1)
        fixed_features = torch.cat([fixed_signal, beta_feat, fixed_weights], dim=-1)
        fixed_out = model.detector(fixed_features)
        
        fixed_mse = criterion(fixed_out, labels).item()
        fixed_ber = np.mean(qpsk_demod_torch(fixed_out) != true_bits)
        fixed_sumrate = np.log2(1 + (1 - fixed_mse) / (max(fixed_mse, 1e-7)))

    print(f"{'Metric':<20} | {'Fixed 2-bit':<15} | {'Dynamic (Policy)':<15}")
    print("-" * 55)
    print(f"{'MSE':<20} | {fixed_mse:<15.6f} | {dyn_mse:<15.6f}")
    print(f"{'BER':<20} | {fixed_ber:<15.6f} | {dyn_ber:<15.6f}")
    print(f"{'Avg Bitrate':<20} | {2.00:<15.2f} | {dyn_bitrate.item():<15.2f}")
    print(f"{'Sum-rate (bps/Hz)':<20} | {fixed_sumrate:<15.4f} | {dyn_sumrate:<15.4f}")
    print("-" * 55)

    # 打印策略分布
    beta_samples = torch.linspace(env.beta.min(), env.beta.max(), 8).view(-1, 1, 1, 1).to(device)
    policy_logits = model.policy_net(beta_samples)
    policy_probs = F.softmax(policy_logits, dim=-1).squeeze()
    
    print("\nPolicy Probs vs Beta (Sampled):")
    print(f"{'Beta (Linear)':<15} | {'P(0-bit)':<10} | {'P(2-bit)':<10} | {'P(4-bit)':<10}")
    print("-" * 55)
    for i in range(len(beta_samples)):
        b_val = beta_samples[i].item()
        probs = policy_probs[i].detach().cpu().numpy()
        print(f"{b_val:<15.2e} | {probs[0]:<10.4f} | {probs[1]:<10.4f} | {probs[2]:<10.4f}")

if __name__ == "__main__":
    train_and_eval()