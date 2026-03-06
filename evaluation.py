import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
import numpy as np
import argparse
from gnn_detector import CF_MIMO_Env, GNNDetector, qpsk_demod_torch
from joint_qat import JointQATSystem

# ==========================================
# 1. 训练函数
# ==========================================

def train_evaluation_models(args):
    env = CF_MIMO_Env()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # 定义模型
    model = JointQATSystem(env.L, env.K).to(device)
    fp_model = GNNDetector(env.L, env.K, input_dim=3).to(device)
    
    optimizer = optim.Adam(model.parameters(), lr=args.lr)
    fp_optimizer = optim.Adam(fp_model.parameters(), lr=args.lr)
    criterion = nn.MSELoss()

    print(f"--- Training Phase: 150 Epochs @ SNR=10dB ---")
    for epoch in range(args.epochs):
        model.train()
        fp_model.train()
        
        # 温度退火
        tau = max(0.1, args.tau_init * (0.95 ** (epoch // 5)))
        
        # 生成 10dB 训练数据
        feat, labels, _, _, _, _ = env.generate_data(args.batch_size, 10.0)
        feat, labels = feat.to(device), labels.to(device)
        
        # 训练全精度基准
        fp_optimizer.zero_grad()
        fp_out = fp_model(feat)
        fp_loss = criterion(fp_out, labels)
        fp_loss.backward()
        fp_optimizer.step()
        
        # 训练联合 QAT 模型 (Dynamic)
        optimizer.zero_grad()
        dyn_out, avg_bit = model(feat, tau=tau, hard=False)
        mse_loss = criterion(dyn_out, labels)
        total_loss = mse_loss + args.lambda_bit * avg_bit
        total_loss.backward()
        optimizer.step()
        
        if (epoch + 1) % 50 == 0:
            print(f"Epoch [{epoch+1}/{args.epochs}] | FP-MSE: {fp_loss.item():.6f} | Q-MSE: {mse_loss.item():.6f} | AvgBit: {avg_bit.item():.4f}")
            
    return model, fp_model, env, device

# ==========================================
# 2. 硬选择推理与 SNR 扫描
# ==========================================

def evaluate_ber_vs_snr(model, fp_model, env, snr_list, device, num_trials=2000):
    model.eval()
    fp_model.eval()
    results = []

    print(f"\n--- SNR Scanning Phase: [0, 5, 10, 15, 20] dB ---")
    
    for snr in snr_list:
        with torch.no_grad():
            feat, labels, true_bits, _, _, _ = env.generate_data(num_trials, snr)
            feat, labels = feat.to(device), labels.to(device)
            
            # 1. Full-Precision
            fp_out = fp_model(feat)
            fp_ber = np.mean(qpsk_demod_torch(fp_out) != true_bits)
            
            # 2. Dynamic Policy (Hard Selection)
            # 使用极小 tau 确保确定性选择
            dyn_out, dyn_bit = model(feat, tau=0.01, hard=True)
            dyn_ber = np.mean(qpsk_demod_torch(dyn_out) != true_bits)
            
            # 3. Fixed 2-bit Baseline
            # 手动注入 2-bit 权重 [0, 1, 0]
            B, L, K, _ = feat.shape
            fixed_weights = torch.zeros(B, L, K, 3).to(device)
            fixed_weights[..., 1] = 1.0 # Index 1 is 2-bit
            
            beta = feat[..., 2].unsqueeze(-1)
            signal = feat[..., :2]
            q_branches = model.quantizer(signal)
            fixed_signal = torch.sum(q_branches * fixed_weights.unsqueeze(-2), dim=-1)
            fixed_out = model.detector(fixed_signal, beta, fixed_weights)
            fixed_ber = np.mean(qpsk_demod_torch(fixed_out) != true_bits)
            
            results.append({
                'snr': snr,
                'fp_ber': fp_ber,
                'fixed_ber': fixed_ber,
                'dyn_ber': dyn_ber,
                'avg_bit': dyn_bit.item()
            })
            print(f"SNR: {snr:2d}dB | FP-BER: {fp_ber:.5f} | Fixed2b-BER: {fixed_ber:.5f} | Dynamic-BER: {dyn_ber:.5f} (Bit: {dyn_bit.item():.2f})")
            
    return results

# ==========================================
# 3. 鲁棒性验证 (AP Survival Analysis)
# ==========================================

def evaluate_robustness(model, env, snr, dropped_list, device, num_trials=2000):
    model.eval()
    results = []
    print(f"\n--- Robustness Phase: Dropping APs @ {snr}dB ---")

    for n_drop in dropped_list:
        with torch.no_grad():
            feat, labels, true_bits, _, _, _ = env.generate_data(num_trials, snr)
            feat, labels = feat.to(device), labels.to(device)
            B, L, K, _ = feat.shape
            
            # 获取策略网络的原始决策
            beta = feat[..., 2].unsqueeze(-1)
            logits = model.policy_net(beta)
            # 执行硬选择 (Argmax)
            indices = logits.argmax(dim=-1)
            weights = torch.zeros(B, L, K, 3).to(device).scatter_(-1, indices.unsqueeze(-1), 1.0)
            
            # 模拟链路故障：随机选择 N 个 AP 强制关断 (0-bit)
            if n_drop > 0:
                drop_indices = np.random.choice(L, n_drop, replace=False)
                for idx in drop_indices:
                    weights[:, idx, :, :] = 0.0
                    weights[:, idx, :, 0] = 1.0 # Force 0-bit (shut down)
            
            # 运行探测器
            signal = feat[..., :2]
            q_branches = model.quantizer(signal)
            combined_signal = torch.sum(q_branches * weights.unsqueeze(-2), dim=-1)
            out = model.detector(combined_signal, beta, weights)
            
            ber = np.mean(qpsk_demod_torch(out) != true_bits)
            results.append({'dropped': n_drop, 'ber': ber})
            print(f"Dropped APs: {n_drop} | System BER: {ber:.5f}")
            
    return results

# ==========================================
# 4. 复杂度分析
# ==========================================

def print_complexity(model):
    print("\n" + "="*50)
    print("COMPLEXITY ANALYSIS")
    print("="*50)
    
    # 策略网络复杂度
    policy_params = sum(p.numel() for p in model.policy_net.parameters())
    detector_params = sum(p.numel() for p in model.detector.parameters())
    
    print(f"1. AP-side PolicyNet Params: {policy_params}")
    print(f"2. Centralized GNN Detector Params: {detector_params}")
    print("-" * 50)
    print("Qualitative Comparison (LMMSE vs. Proposed):")
    print("- LMMSE: Requires Matrix Inversion per AP (O(K^3)). Computationally heavy for high-density networks.")
    print("- Dynamic Policy: Only MLP inference at AP (O(K * hidden)). Extremely lightweight.")
    print("- Aggregation: Proposed uses Bit-Aware Attention to dynamically ignore faulty/0-bit links.")
    print("="*50 + "\n")

# ==========================================
# 5. 主程序
# ==========================================

def main():
    parser = argparse.ArgumentParser(description="Step 7: Hard Selection & Robustness")
    parser.add_argument("--epochs", type=int, default=150)
    parser.add_argument("--batch_size", type=int, default=128)
    parser.add_argument("--lr", type=float, default=0.001)
    parser.add_argument("--lambda_bit", type=float, default=0.002)
    parser.add_argument("--tau_init", type=float, default=1.0)
    args = parser.parse_args()

    # 1. 训练
    model, fp_model, env, device = train_evaluation_models(args)
    
    # 2. SNR 扫描对比
    snr_list = [0, 5, 10, 15, 20]
    snr_results = evaluate_ber_vs_snr(model, fp_model, env, snr_list, device)
    
    # 3. 鲁棒性验证
    dropped_list = [0, 2, 4, 8]
    robust_results = evaluate_robustness(model, env, 10.0, dropped_list, device)
    
    # 4. 复杂度打印
    print_complexity(model)
    
    # 5. 最终总结表格
    print("--- BER PERFORMANCE COMPARISON TABLE ---")
    header = f"{'SNR':<6} | {'Full-Prec':<12} | {'Fixed 2-bit':<12} | {'Dynamic (Ours)':<15}"
    print(header)
    print("-" * len(header))
    for res in snr_results:
        print(f"{res['snr']:<6} | {res['fp_ber']:<12.6f} | {res['fixed_ber']:<12.6f} | {res['dyn_ber']:<15.6f}")
    
    # 增益计算 (at 10dB)
    res_10db = next(item for item in snr_results if item['snr'] == 10)
    gain = (res_10db['fixed_ber'] - res_10db['dyn_ber']) / (res_10db['fixed_ber'] + 1e-9) * 100
    print(f"\n[Result] At SNR=10dB, Proposed Dynamic Policy achieves {gain:.2f}% BER reduction over Fixed 2-bit.")

if __name__ == "__main__":
    main()