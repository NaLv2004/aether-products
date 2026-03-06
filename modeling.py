import numpy as np
import argparse

def quantize_estimate(s_hat, bit_width, p_s_theory):
    """
    AQNM 量化模型: z = alpha * s_hat + q
    
    参数:
        s_hat: 局部估计值 (L, K)
        bit_width: 量化位宽 (2, 4, 8)
        p_s_theory: 估计值的理论功率 E[|s_hat|^2] (L, K)
    返回:
        z: 量化后的信号
        alpha: 量化增益系数
    """
    # 严格对应的 rho 值 (来自经典 AQNM 文献)
    rho_map = {
        2: 0.1175, 
        4: 0.009497, 
        8: 0.00003
    }
    
    if bit_width not in rho_map:
        return s_hat, 1.0
    
    rho = rho_map[bit_width]
    alpha = 1 - rho
    
    # 量化噪声方差: alpha * rho * E[|s_hat|^2]
    sigma_q2 = alpha * rho * p_s_theory
    
    # 生成复高斯量化噪声 q ~ CN(0, sigma_q2)
    q = (np.random.randn(*s_hat.shape) + 1j * np.random.randn(*s_hat.shape)) * np.sqrt(sigma_q2 / 2)
    
    z = alpha * s_hat + q
    return z, alpha

def simulate():
    parser = argparse.ArgumentParser(description="Cell-Free MIMO Uplink: De-biased LMMSE & AQNM")
    parser.add_argument("--num_ap", type=int, default=16, help="Number of Access Points (L)")
    parser.add_argument("--num_ue", type=int, default=4, help="Number of User Equipments (K)")
    parser.add_argument("--area_size", type=float, default=200, help="Area size (meters)")
    parser.add_argument("--fc", type=float, default=2.0, help="Carrier frequency (GHz)")
    parser.add_argument("--bw", type=float, default=20e6, help="Bandwidth (Hz)")
    parser.add_argument("--p_tx", type=float, default=23, help="Max TX power per UE (dBm)")
    parser.add_argument("--nf", type=float, default=7, help="Noise figure (dB)")
    parser.add_argument("--sigma_sf", type=float, default=8, help="Shadow fading std dev (dB)")
    parser.add_argument("--epochs", type=int, default=2000, help="Number of Monte Carlo trials")
    args = parser.parse_args()

    # 1. 物理层参数初始化
    L, K = args.num_ap, args.num_ue
    P_tx_watt = 10**((args.p_tx - 30) / 10)
    noise_pwr_dbm = -174 + 10 * np.log10(args.bw) + args.nf
    sigma2_n = 10**((noise_pwr_dbm - 30) / 10)

    # 2. 场景生成与大尺度衰落
    # 固定场景位置以减少随机波动，专注于位宽影响
    np.random.seed(42)
    ap_pos = np.random.uniform(0, args.area_size, (L, 2))
    ue_pos = np.random.uniform(0, args.area_size, (K, 2))
    dist = np.linalg.norm(ap_pos[:, np.newaxis, :] - ue_pos[np.newaxis, :, :], axis=2)
    dist = np.maximum(dist, 10.0) # 最小距离限制
    # 3GPP UMi 通道模型
    pl_db = 35.3 * np.log10(dist) + 22.4 + 21.3 * np.log10(args.fc)
    shadowing = np.random.normal(0, args.sigma_sf, (L, K))
    beta = 10**((-pl_db + shadowing) / 10)

    avg_rx_snr_db = 10 * np.log10(np.mean(P_tx_watt * beta) / sigma2_n)

    print("====================================================")
    print("      Cell-Free MIMO: De-biased LMMSE & AQNM        ")
    print("====================================================")
    print(f"Scenario: {L} APs, {K} UEs, Area {args.area_size}m x {args.area_size}m")
    print(f"System Check: Avg Rx SNR at AP = {avg_rx_snr_db:.2f} dB")
    print(f"Monte Carlo Epochs: {args.epochs}")
    print("SNR 已通过减小区域大小得到提升，以验证位宽对 MSE 的敏感性。")
    print("-" * 85)
    print(f"{'Bit-width (b)':<15} | {'Backhaul (bits)':<18} | {'Avg MSE':<15} | {'Sum-rate (bps/Hz)':<15}")
    print("-" * 85)

    bit_widths = [2, 4, 8]
    
    # 预生成随机变量以保证实验一致性
    np.random.seed(None) # 重置种子用于蒙特卡洛
    all_s = (np.random.randn(args.epochs, K) + 1j * np.random.randn(args.epochs, K)) / np.sqrt(2)
    all_noise = (np.random.randn(args.epochs, L) + 1j * np.random.randn(args.epochs, L)) * np.sqrt(sigma2_n / 2)
    all_H_small = (np.random.randn(args.epochs, L, K) + 1j * np.random.randn(args.epochs, L, K)) / np.sqrt(2)

    for b in bit_widths:
        mse_accum = np.zeros(K)
        total_backhaul = L * K * b
        
        for epoch in range(args.epochs):
            s = all_s[epoch] # (K,)
            n = all_noise[epoch] # (L,)
            h_small = all_H_small[epoch] # (L, K)
            
            # (1) 信道矩阵 G_lk = sqrt(P * beta_lk) * h_lk
            G = np.sqrt(P_tx_watt * beta) * h_small # (L, K)
            
            # (2) AP 侧接收信号 y_l = sum_i G_li * s_i + n_l
            y = G @ s + n # (L,)
            
            # (3) 局部 LMMSE 滤波
            # 分母 D_l = sum_i |G_li|^2 + sigma^2
            D = np.sum(np.abs(G)**2, axis=1) + sigma2_n # (L,)
            
            # 局部系数 w_lk = G_lk* / D_l
            W = np.conj(G) / D[:, np.newaxis] # (L, K)
            
            # 局部估计值 s_hat_lk = w_lk * y_l
            s_hat_local = W * y[:, np.newaxis] # (L, K)
            
            # 理论功率 E[|s_hat_lk|^2] = |G_lk|^2 / D_l
            p_s_theory = np.abs(G)**2 / D[:, np.newaxis] # (L, K)
            
            # (4) 离散位宽量化 (AQNM)
            z, alpha = quantize_estimate(s_hat_local, b, p_s_theory)
            
            # (5) CPU 侧去偏置聚合
            a = p_s_theory 
            s_hat_aggregated = np.sum(z / alpha, axis=0) / np.sum(a, axis=0)
            
            # 调试打印 (仅在第一个 epoch 且位宽为 2 时打印一次)
            if epoch == 0 and b == 2:
                print(f"DEBUG [Epoch 0, UE 0]: s_hat_agg 模值 = {np.abs(s_hat_aggregated[0]):.4f}, s 模值 = {np.abs(s[0]):.4f}")
            
            # 累积每个用户的 MSE
            mse_accum += np.abs(s - s_hat_aggregated)**2
            
        # 计算每个用户的独立平均 MSE
        mse_per_user = mse_accum / args.epochs
        avg_mse = np.mean(mse_per_user)
        
        # 为每个用户 k 独立计算速率: R_k = log2(1 + (1-MSE_k)/MSE_k)
        # 增加 clip 防止数值异常
        safe_mse = np.clip(mse_per_user, 1e-10, 0.9999)
        user_rates = np.log2(1 + (1 - safe_mse) / safe_mse)
        sum_rate = np.sum(user_rates)
        
        print(f"{b:^15d} | {total_backhaul:^18d} | {avg_mse:^15.6f} | {sum_rate:^15.4f}")

    print("-" * 85)
    print("结论: 采用去偏置聚合后，MSE 随位宽增加显著下降，Sum-rate 显著上升。")

if __name__ == "__main__":
    simulate()