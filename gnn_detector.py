import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
import argparse
from tqdm import tqdm

# ==========================================
# 1. 物理环境与数据生成 (与 baselines.py 一致)
# ==========================================

class CF_MIMO_Env:
    def __init__(self, L=16, K=4, area_size=200.0, fc=2.0, bw=20e6, nf=7.0):
        self.L = L
        self.K = K
        self.area_size = area_size
        self.fc = fc
        self.bw = bw
        self.nf = nf
        
        # 噪声功率计算
        noise_pwr_dbm = -174 + 10 * np.log10(bw) + nf
        self.sigma2_n = 10**((noise_pwr_dbm - 30) / 10)
        
        # 固定位置与大尺度衰落
        np.random.seed(42)
        self.ap_pos = np.random.uniform(0, area_size, (L, 2))
        self.ue_pos = np.random.uniform(0, area_size, (K, 2))
        dist = np.linalg.norm(self.ap_pos[:, np.newaxis, :] - self.ue_pos[np.newaxis, :, :], axis=2)
        dist = np.maximum(dist, 10.0)
        pl_db = 35.3 * np.log10(dist) + 22.4 + 21.3 * np.log10(fc)
        self.beta = 10**(-pl_db / 10)
        self.avg_beta = np.mean(self.beta)

    def generate_data(self, batch_size, snr_db):
        """ 生成训练/测试数据批次 """
        P_tx = 10**(snr_db / 10) * self.sigma2_n / self.avg_beta
        
        # 1. 符号生成 (QPSK)
        bits = np.random.randint(0, 2, (batch_size, 2 * self.K))
        bits_reshaped = bits.reshape(batch_size, self.K, 2)
        s_complex = ((1 - 2 * bits_reshaped[:, :, 0]) + 1j * (1 - 2 * bits_reshaped[:, :, 1])) / np.sqrt(2) # (B, K)
        
        # 2. 信道生成 (Rayleigh)
        h_small = (np.random.randn(batch_size, self.L, self.K) + 1j * np.random.randn(batch_size, self.L, self.K)) / np.sqrt(2)
        G = np.sqrt(P_tx * self.beta) * h_small # (B, L, K)
        
        # 3. 接收信号与本地估计
        # y = G @ s + n
        n = (np.random.randn(batch_size, self.L) + 1j * np.random.randn(batch_size, self.L)) * np.sqrt(self.sigma2_n / 2)
        y = np.einsum('blk,bk->bl', G, s_complex) + n # (B, L)
        
        # 局部 LMMSE 基础: s_check_lk = (g_lk^* / D_l) * y_l
        D = np.sum(np.abs(G)**2, axis=2) + self.sigma2_n # (B, L)
        s_check = (np.conj(G) / D[:, :, np.newaxis]) * y[:, :, np.newaxis] # (B, L, K)
        
        # 特征提取: Re(s_check), Im(s_check), beta
        # 输入形状: (B, L, K, 3)
        features = np.zeros((batch_size, self.L, self.K, 3))
        features[..., 0] = np.real(s_check)
        features[..., 1] = np.imag(s_check)
        features[..., 2] = np.tile(self.beta, (batch_size, 1, 1))
        
        # 标签: Re(s), Im(s)
        labels = np.zeros((batch_size, self.K, 2))
        labels[..., 0] = np.real(s_complex)
        labels[..., 1] = np.imag(s_complex)
        
        return torch.FloatTensor(features), torch.FloatTensor(labels), bits, G, s_complex, y

# ==========================================
# 2. GNN 架构设计 (Heterogeneous GNN)
# ==========================================

class GNNDetector(nn.Module):
    def __init__(self, L, K, hidden_dim=64):
        super(GNNDetector, self).__init__()
        self.L = L
        self.K = K
        
        # Layer 1: AP -> UE (处理边特征并聚合)
        self.edge_mlp = nn.Sequential(
            nn.Linear(3, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU()
        )
        
        # Layer 2: UE Interaction (CPU/Inter-UE)
        # 这里的输入是所有 UE 聚合后的特征 K * hidden_dim
        self.ue_interaction = nn.Sequential(
            nn.Linear(hidden_dim * K, hidden_dim * 2),
            nn.ReLU(),
            nn.Linear(hidden_dim * 2, hidden_dim * 2),
            nn.ReLU(),
            nn.Linear(hidden_dim * 2, K * 2) # 每个 UE 输出 (Re, Im)
        )

    def forward(self, x):
        # x shape: (B, L, K, 3)
        B = x.shape[0]
        
        # 1. 边处理
        e = self.edge_mlp(x) # (B, L, K, hidden_dim)
        
        # 2. 聚合到 UE 节点 (Sum over APs)
        u = torch.sum(e, dim=1) # (B, K, hidden_dim)
        
        # 3. UE 间信息交换 (Flatten K nodes and use MLP to handle MUI)
        u_flat = u.view(B, -1) # (B, K * hidden_dim)
        out = self.ue_interaction(u_flat) # (B, K * 2)
        
        return out.view(B, self.K, 2)

# ==========================================
# 3. 辅助函数
# ==========================================

def qpsk_demod_torch(s_real_imag):
    # s_real_imag: (B, K, 2)
    B, K, _ = s_real_imag.shape
    bits = np.zeros((B, 2 * K), dtype=int)
    # Re < 0 -> bit1=1, Im < 0 -> bit2=1
    bits[:, 0::2] = (s_real_imag[:, :, 0].detach().cpu().numpy() < 0).astype(int)
    bits[:, 1::2] = (s_real_imag[:, :, 1].detach().cpu().numpy() < 0).astype(int)
    return bits

def lsfd_baseline(G, y, beta, sigma2_n):
    # G: (B, L, K), y: (B, L), beta: (L, K)
    B, L, K = G.shape
    D = np.sum(np.abs(G)**2, axis=2) + sigma2_n
    s_check = (np.conj(G) / D[:, :, np.newaxis]) * y[:, :, np.newaxis]
    
    a = beta / np.sum(beta, axis=0) # (L, K)
    s_lsfd = np.sum(a[np.newaxis, :, :] * s_check, axis=1) # (B, K)
    
    # 转换为与 GNN 输出一致的格式以计算 BER
    res = np.zeros((B, K, 2))
    res[..., 0] = np.real(s_lsfd)
    res[..., 1] = np.imag(s_lsfd)
    return res

# ==========================================
# 4. 主程序
# ==========================================

def main():
    parser = argparse.ArgumentParser(description="GNN Multi-user Detector for CF-MIMO")
    parser.add_argument("--train_epochs", type=int, default=100)
    parser.add_argument("--batch_size", type=int, default=128)
    parser.add_argument("--lr", type=float, default=0.001)
    parser.add_argument("--hidden_dim", type=int, default=64)
    parser.add_argument("--eval_trials", type=int, default=1000)
    args = parser.parse_args()

    env = CF_MIMO_Env()
    model = GNNDetector(env.L, env.K, args.hidden_dim)
    optimizer = optim.Adam(model.parameters(), lr=args.lr)
    criterion = nn.MSELoss()

    print(f"Starting GNN Training... (Total Epochs: {args.train_epochs})")
    
    # --- 训练阶段 ---
    for epoch in range(args.train_epochs):
        model.train()
        # 训练时 SNR 随机分布在 0-20dB
        snr_train = np.random.uniform(0, 20)
        feat, labels, _, _, _, _ = env.generate_data(args.batch_size, snr_train)
        
        optimizer.zero_grad()
        outputs = model(feat)
        loss = criterion(outputs, labels)
        loss.backward()
        optimizer.step()
        
        if (epoch + 1) % 10 == 0:
            print(f"Epoch [{epoch+1}/{args.train_epochs}], Loss: {loss.item():.6f}, Training SNR: {snr_train:.2f} dB")

    # --- 评估阶段 ---
    print("\nStarting Evaluation and Comparison...")
    snr_range = [0, 5, 10, 15, 20]
    model.eval()
    
    results_gnn = []
    results_lsfd = []

    print("-" * 65)
    print(f"{'SNR (dB)':<10} | {'LSFD BER':<15} | {'GNN BER':<15} | {'Improvement %':<15}")
    print("-" * 65)

    with torch.no_grad():
        for snr in snr_range:
            feat, labels, true_bits, G, s_comp, y = env.generate_data(args.eval_trials, snr)
            
            # GNN 预测
            gnn_out = model(feat)
            gnn_bits = qpsk_demod_torch(gnn_out)
            gnn_ber = np.mean(gnn_bits != true_bits)
            results_gnn.append(gnn_ber)
            
            # LSFD Baseline 预测
            lsfd_out = lsfd_baseline(G, y, env.beta, env.sigma2_n)
            # 使用解调逻辑 (reuse torch helper)
            lsfd_bits = qpsk_demod_torch(torch.FloatTensor(lsfd_out))
            lsfd_ber = np.mean(lsfd_bits != true_bits)
            results_lsfd.append(lsfd_ber)
            
            improvement = (lsfd_ber - gnn_ber) / lsfd_ber * 100 if lsfd_ber > 0 else 0
            print(f"{snr:<10d} | {lsfd_ber:<15.6f} | {gnn_ber:<15.6f} | {improvement:<15.2f}%")

    print("-" * 65)
    final_imp = (results_lsfd[-1] - results_gnn[-1]) / results_lsfd[-1] * 100 if results_lsfd[-1] > 0 else 0
    print(f"Final Improvement at {snr_range[-1]}dB: {final_imp:.2f}%")
    if final_imp >= 15.0:
        print("Target Achieved: GNN BER improvement is >= 15% at high SNR.")
    else:
        print("Target Warning: GNN BER improvement is below 15%. Consider increasing epochs or hidden_dim.")

if __name__ == "__main__":
    main()