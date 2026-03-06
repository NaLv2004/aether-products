import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
import argparse

# ==========================================
# 1. 物理环境与数据生成
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
        
        bits = np.random.randint(0, 2, (batch_size, 2 * self.K))
        bits_reshaped = bits.reshape(batch_size, self.K, 2)
        s_complex = ((1 - 2 * bits_reshaped[:, :, 0]) + 1j * (1 - 2 * bits_reshaped[:, :, 1])) / np.sqrt(2)
        
        h_small = (np.random.randn(batch_size, self.L, self.K) + 1j * np.random.randn(batch_size, self.L, self.K)) / np.sqrt(2)
        G = np.sqrt(P_tx * self.beta) * h_small
        
        n = (np.random.randn(batch_size, self.L) + 1j * np.random.randn(batch_size, self.L)) * np.sqrt(self.sigma2_n / 2)
        y = np.einsum('blk,bk->bl', G, s_complex) + n
        
        D = np.sum(np.abs(G)**2, axis=2) + self.sigma2_n
        s_check = (np.conj(G) / D[:, :, np.newaxis]) * y[:, :, np.newaxis]
        
        features = np.zeros((batch_size, self.L, self.K, 3))
        features[..., 0] = np.real(s_check)
        features[..., 1] = np.imag(s_check)
        features[..., 2] = np.tile(self.beta, (batch_size, 1, 1))
        
        labels = np.zeros((batch_size, self.K, 2))
        labels[..., 0] = np.real(s_complex)
        labels[..., 1] = np.imag(s_complex)
        
        return torch.FloatTensor(features), torch.FloatTensor(labels), bits, G, s_complex, y

# ==========================================
# 2. GNN 架构设计 (增强版)
# ==========================================

class GNNDetector(nn.Module):
    def __init__(self, L, K, hidden_dim=64, input_dim=3):
        super(GNNDetector, self).__init__()
        self.L = L
        self.K = K
        
        # Layer 1: AP -> UE (处理边特征并聚合)
        # 输入维度可调，支持 Task-aware Attention (6-dim)
        self.edge_mlp = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU()
        )
        
        self.ue_interaction = nn.Sequential(
            nn.Linear(hidden_dim * K, hidden_dim * 2),
            nn.ReLU(),
            nn.Linear(hidden_dim * 2, hidden_dim * 2),
            nn.ReLU(),
            nn.Linear(hidden_dim * 2, K * 2)
        )

    def forward(self, x):
        # x shape: (B, L, K, input_dim)
        B = x.shape[0]
        e = self.edge_mlp(x) # (B, L, K, hidden_dim)
        u = torch.sum(e, dim=1) # (B, K, hidden_dim)
        u_flat = u.view(B, -1)
        out = self.ue_interaction(u_flat)
        return out.view(B, self.K, 2)

def qpsk_demod_torch(s_real_imag):
    B, K, _ = s_real_imag.shape
    bits = np.zeros((B, 2 * K), dtype=int)
    bits[:, 0::2] = (s_real_imag[:, :, 0].detach().cpu().numpy() < 0).astype(int)
    bits[:, 1::2] = (s_real_imag[:, :, 1].detach().cpu().numpy() < 0).astype(int)
    return bits