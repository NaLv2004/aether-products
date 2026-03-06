import numpy as np
import argparse

class LloydMaxQuantizer:
    """
    Lloyd-Max 量化器，内置针对 N(0,1) 分布的 2-bit (4级) 和 4-bit (16级) 查找表。
    """
    def __init__(self, bits):
        self.bits = bits
        if bits == 2:
            # 4 levels for N(0,1): Thresholds: [0, ±0.9816], Codebook: [±0.4528, ±1.510]
            self.thresholds = np.array([-0.9816, 0.0, 0.9816])
            self.codebook = np.array([-1.510, -0.4528, 0.4528, 1.510])
        elif bits == 4:
            # 16 levels for N(0,1)
            self.codebook = np.array([
                -2.733, -2.069, -1.618, -1.256, -0.9424, -0.6568, -0.3881, -0.1284,
                0.1284, 0.3881, 0.6568, 0.9424, 1.256, 1.618, 2.069, 2.733
            ])
            self.thresholds = np.array([
                -2.401, -1.844, -1.437, -1.099, -0.7996, -0.5224, -0.2581, 
                0.0, 0.2581, 0.5224, 0.7996, 1.099, 1.437, 1.844, 2.401
            ])
        else:
            self.thresholds = None
            self.codebook = None

    def quantize(self, x):
        """
        对输入数组 x 进行量化。假设 x 已经归一化为 N(0,1)。
        """
        if self.thresholds is None:
            return x
        # 映射到 codebook 索引
        indices = np.digitize(x, self.thresholds)
        return self.codebook[indices]

def qpsk_mod(bits):
    """
    QPSK 调制：00 -> (1+j)/sqrt(2), 01 -> (-1+j)/sqrt(2), 11 -> (-1-j)/sqrt(2), 10 -> (1-j)/sqrt(2)
    """
    # 每行 K 个符号，输入形状 (1, 2K)
    bits_reshaped = bits.reshape(-1, 2)
    s = (1 - 2 * bits_reshaped[:, 0]) + 1j * (1 - 2 * bits_reshaped[:, 1])
    return s / np.sqrt(2)

def qpsk_demod(symbols):
    """
    QPSK 硬决策解调，返回 bits 数组
    """
    # symbols 形状为 (1, K)
    K = symbols.shape[1]
    bits = np.zeros((1, 2 * K), dtype=int)
    bits[0, 0::2] = (np.real(symbols[0]) < 0).astype(int)
    bits[0, 1::2] = (np.imag(symbols[0]) < 0).astype(int)
    return bits

def get_quantized_estimate(s_chk, G, D, a, quantizer, K):
    """
    对本地估计进行归一化量化并聚合
    """
    # E[|s_check_lk|^2] = |G_lk|^2 / D_l
    # 假设符号能量为 1
    var_check = np.abs(G)**2 / D[:, np.newaxis] 
    std_part = np.sqrt(var_check / 2) # 实部/虚部的标准差
    
    # 防止除零
    std_part = np.maximum(std_part, 1e-12)
    
    # 实部量化
    re_norm = np.real(s_chk) / std_part
    re_q = quantizer.quantize(re_norm) * std_part
    # 虚部量化
    im_norm = np.imag(s_chk) / std_part
    im_q = quantizer.quantize(im_norm) * std_part
    
    s_q = re_q + 1j * im_q
    # LSFD 权重聚合
    return np.sum(a * s_q, axis=0).reshape(1, K)

def simulate():
    parser = argparse.ArgumentParser(description="Cell-Free MIMO Baselines: C-MMSE, LSFD, Quantized LSFD")
    parser.add_argument("--num_ap", type=int, default=16)
    parser.add_argument("--num_ue", type=int, default=4)
    parser.add_argument("--area_size", type=float, default=200.0)
    parser.add_argument("--fc", type=float, default=2.0, help="Carrier frequency in GHz")
    parser.add_argument("--bw", type=float, default=20e6, help="Bandwidth in Hz")
    parser.add_argument("--nf", type=float, default=7.0, help="Noise figure in dB")
    parser.add_argument("--epochs", type=int, default=2000, help="Monte Carlo trials")
    args = parser.parse_args()

    L, K = args.num_ap, args.num_ue
    # 噪声功率计算 (dBm)
    noise_pwr_dbm = -174 + 10 * np.log10(args.bw) + args.nf
    sigma2_n = 10**((noise_pwr_dbm - 30) / 10)

    # 固定位置以获得稳定的平均大尺度衰落
    np.random.seed(42)
    ap_pos = np.random.uniform(0, args.area_size, (L, 2))
    ue_pos = np.random.uniform(0, args.area_size, (K, 2))
    dist = np.linalg.norm(ap_pos[:, np.newaxis, :] - ue_pos[np.newaxis, :, :], axis=2)
    dist = np.maximum(dist, 10.0) # 最小距离 10m
    
    # 路径损耗模型 (Cost231 Hata 简化版)
    pl_db = 35.3 * np.log10(dist) + 22.4 + 21.3 * np.log10(args.fc)
    beta = 10**(-pl_db / 10)
    avg_beta = np.mean(beta)

    print(f"--- CF-MIMO Baseline Simulation ---")
    print(f"Scenario: {L} APs, {K} UEs, {args.area_size}m x {args.area_size}m")
    print(f"Debug: Avg PathLoss = {-10*np.log10(avg_beta):.2f} dB")
    
    snr_db_range = [0, 5, 10, 15, 20]
    results = {
        "C-MMSE": [],
        "LSFD-Full": [],
        "LSFD-2bit": [],
        "LSFD-4bit": []
    }

    quant2 = LloydMaxQuantizer(2)
    quant4 = LloydMaxQuantizer(4)

    print("-" * 80)
    print(f"{'SNR (dB)':<10} | {'C-MMSE':<15} | {'LSFD-Full':<15} | {'LSFD-2bit':<15} | {'LSFD-4bit':<15}")
    print("-" * 80)

    for snr_db in snr_db_range:
        # 修正功率分配：snr_db 定义为 AP 侧的平均接收 SNR
        # SNR = (P_tx * avg_beta) / sigma2_n
        P_tx = 10**(snr_db / 10) * sigma2_n / avg_beta
        
        errors = {k: 0 for k in results.keys()}
        total_bits = args.epochs * K * 2
        
        # 运行蒙特卡洛仿真
        for _ in range(args.epochs):
            # 1. 生成数据与 QPSK 调制
            bits = np.random.randint(0, 2, (1, 2 * K))
            s = qpsk_mod(bits) # (K,)
            
            # 2. 信道生成 (Rayleigh fading)
            h_small = (np.random.randn(L, K) + 1j * np.random.randn(L, K)) / np.sqrt(2)
            G = np.sqrt(P_tx * beta) * h_small
            
            # 3. 接收信号 (L APs)
            n = (np.random.randn(L) + 1j * np.random.randn(L)) * np.sqrt(sigma2_n / 2)
            y = G @ s + n # (L,)
            
            # --- (A) Centralized MMSE (C-MMSE) ---
            # Formula: (G^H G + sigma2_n * I)^-1 @ G^H @ y
            G_H = np.conj(G).T
            W_cmmse = np.linalg.inv(G_H @ G + sigma2_n * np.eye(K)) @ G_H
            s_cmmse = (W_cmmse @ y).reshape(1, K)
            
            # --- (B) LSFD (Full Precision) ---
            # Local detection at each AP
            D = np.sum(np.abs(G)**2, axis=1) + sigma2_n # (L,)
            W_local = np.conj(G) / D[:, np.newaxis] # (L, K)
            s_check = W_local * y[:, np.newaxis] # (L, K)
            
            # Central processing unit (CPU) aggregation using large scale fading weights
            # a_lk = beta_lk / sum_i(beta_ik)
            a = beta / np.sum(beta, axis=0) # (L, K)
            s_lsfd = np.sum(a * s_check, axis=0).reshape(1, K)
            
            # --- (C) Quantized LSFD (2-bit and 4-bit) ---
            s_lsfd_2b = get_quantized_estimate(s_check, G, D, a, quant2, K)
            s_lsfd_4b = get_quantized_estimate(s_check, G, D, a, quant4, K)

            # 4. 解调与误差统计
            errors["C-MMSE"] += np.sum(bits != qpsk_demod(s_cmmse))
            errors["LSFD-Full"] += np.sum(bits != qpsk_demod(s_lsfd))
            errors["LSFD-2bit"] += np.sum(bits != qpsk_demod(s_lsfd_2b))
            errors["LSFD-4bit"] += np.sum(bits != qpsk_demod(s_lsfd_4b))

        # 记录并打印该 SNR 下的结果
        row = [snr_db]
        for k in ["C-MMSE", "LSFD-Full", "LSFD-2bit", "LSFD-4bit"]:
            ber = errors[k] / total_bits
            results[k].append(ber)
            row.append(ber)
        
        print(f"{row[0]:<10d} | {row[1]:<15.6f} | {row[2]:<15.6f} | {row[3]:<15.6f} | {row[4]:<15.6f}")

    print("-" * 80)
    print(f"Simulation completed for {args.epochs} trials.")

if __name__ == "__main__":
    simulate()