## [Current Step]
# Cell-Free MIMO Uplink System Modeling

本项目实现了一个基础的 Cell-Free MIMO（无蜂窝 MIMO）上行链路系统建模脚本 `modeling.py`。该模型包含大尺度衰落、小尺度瑞利衰落以及 AQNM (Additive Quantization Noise Model) 量化模型。

## 主要功能

1.  **场景配置**：
    *   在 500m x 500m 区域内随机分布 16 个接入点 (AP) 和 4 个用户 (UE)。
    *   载波频率 2.0 GHz，带宽 20 MHz。
    *   热噪声功率谱密度 -174 dBm/Hz，接收端噪声系数 (NF) 7 dB。
    *   用户发射功率固定为 23 dBm。

2.  **信道模型**：
    *   **路径损耗**：遵循 3GPP TR 38.901 UMi NLOS 模型。
    *   **阴影衰落**：标准差为 8 dB 的对数正态分布。
    *   **小尺度衰落**：服从独立同分布的复高斯瑞利衰落 $\mathcal{CN}(0, 1)$。

3.  **量化器 (AQNM)**：
    *   模拟有限位宽（2, 4, 8 bits）下的信号失真。
    *   量化输出表示为 $z = \alpha y + q$，其中 $q$ 为量化噪声。

4.  **接收端处理**：
    *   各 AP 进行**局部 LMMSE (Local LMMSE)** 处理，根据提供的公式计算用户信号的估计值。
    *   中央处理单元 (CPU) 对各 AP 的局部估计值进行合并，计算端到端解调均方误差 (MSE)。

## 命令行参数说明

可以通过命令行调整以下超参数：

- `--num_ap`: AP 数量（默认 16）。
- `--num_ue`: 用户数量（默认 4）。
- `--area_size`: 区域边长（默认 500 米）。
- `--fc`: 载波频率（默认 2.0 GHz）。
- `--bw`: 带宽（默认 20,000,000 Hz）。
- `--p_tx`: 用户发射功率（默认 23 dBm）。
- `--nf`: 噪声系数（默认 7 dB）。
- `--epochs`: Monte Carlo 仿真次数（默认 1000）。

## 运行方式

运行 `run.bat` 脚本即可自动执行仿真并查看控制台输出的坐标、路径损耗统计以及不同位宽下的 MSE 结果。

## [Current Step]
# Cell-Free MIMO 归一化仿真与和速率计算

本版本对 `modeling.py` 进行了逻辑修正，解决了之前版本中由于 CPU 侧简单信号累加导致的幅度偏差（MSE 异常增大且随位宽增加恶化）的问题。

## 主要更新内容

1.  **CPU 聚合逻辑修正**：
    将 CPU 合并 $L$ 个接入点 (AP) 局部估计值的方法从“直接累加”修改为“**算术平均**”：
    $$\hat{s}_k = \frac{1}{L} \sum_{l=1}^L \hat{s}_{lk}$$
    这一修改消除了合成信号约 16 倍的幅度增益，使得 MSE 回落到合理的物理区间（通常 $MSE < 1$），并恢复了“量化位宽增加，MSE 下降”的正确物理趋势。

2.  **新增和速率 (Sum-rate) 评估**：
    基于仿真得到的平均 MSE，估算用户的有效 SINR 并计算系统平均可达和速率（Spectral Efficiency）：
    - $SINR_k \approx \frac{1 - MSE_k}{MSE_k}$
    - $SumRate = \sum_{k=1}^K \log_2(1 + SINR_k)$ (bits/s/Hz)

3.  **输出优化**：
    程序现在以表格形式清晰输出 2-bit, 4-bit, 8-bit 下的平均 MSE 和平均和速率。

## 命令行参数说明

| 参数 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `--num_ap` | 16 | 接入点 (AP) 数量 |
| `--num_ue` | 4 | 用户 (UE) 数量 |
| `--area_size` | 500 | 仿真区域边长 (m) |
| `--p_tx` | 23 | 用户最大发射功率 (dBm) |
| `--epochs` | 1000 | 蒙特卡洛仿真实验次数 |

## 运行方法

执行目录下的 `run.bat` 即可启动仿真。

## [Current Step]
# Cell-Free MIMO Uplink 仿真建模

本项目实现了 Cell-Free MIMO 上行链路在量化精度受限（AQNM 模型）下的系统性能仿真。

## 主要改进与功能
1.  **物理层参数校验**：
    *   使用 3GPP TR 38.901 UMi (Urban Micro) 路径损耗模型 ($d$ 为米，$f_c$ 为 GHz)。
    *   程序自动计算并打印 AP 处的平均接收 SNR，确保仿真环境处于合理的通信区间（如 0~10 dB 左右）。
2.  **鲁棒的 MRC 合并逻辑**：
    *   在 CPU 端执行基于去偏置 (De-biased) 信号的 MRC 处理。
    *   合并公式为：$\hat{s}_k = \frac{\sum_{l=1}^L h_{lk}^* \tilde{z}_l}{\sum_{l=1}^L |h_{lk}|^2 + \sigma_{eff}^2}$。
    *   该公式确保了估计值 $\hat{s}_k$ 的幅度与原始信号 $s_k$ 匹配，将 MSE 严格控制在 $[0, 1]$ 区间。
3.  **AQNM 量化模型**：
    *   考虑了位宽 $b \in \{2, 4, 8\}$ 对信号衰减因子 $\alpha$ 和加性量化噪声 $\sigma_q^2$ 的影响。
4.  **性能指标**：
    *   **MSE**：均方误差，反映估计准确度。
    *   **Sum-rate**：系统总频谱效率，基于 $SINR \approx \frac{1-MSE}{MSE}$ 计算。

## 参数说明
可以通过命令行修改以下超参数：
*   `--num_ap`: 接入点 (AP) 数量，默认 16。
*   `--num_ue`: 用户 (UE) 数量，默认 4。
*   `--p_tx`: 用户发射功率 (dBm)，默认 23。
*   `--fc`: 载波频率 (GHz)，默认 2.0。
*   `--epochs`: 蒙特卡洛仿真次数，默认 1000。

## 运行方式
执行 `run.bat` 即可开始仿真并观察结果。

## [Current Step]
# 局部信息驱动的 Cell-Free MIMO 系统建模 (第一步)

本项目重写了 `modeling.py`，实现了局部处理驱动的系统建模，包含 AP 侧局部估计、位宽受限的 AQNM 量化以及 CPU 侧的聚合逻辑。

## 主要功能
1. **AP 侧局部处理**：每个 AP $l$ 仅利用局部信道状态信息 $h_{lk}$ 计算用户 $k$ 的局部 LMMSE 估计值 $\hat{s}_{lk}$。
2. **AQNM 量化模型**：实现了针对局部估计值的离散位宽量化（$b \in \{0, 2, 4, 8\}$）。量化噪声方差基于估计值的瞬时理论功率计算。
3. **CPU 聚合**：CPU 接收各 AP 的量化估计值，执行去偏置聚合（$\hat{s}_k = \frac{1}{L} \sum z_{lk}/\alpha_{lk}$）。
4. **性能评估**：通过 Monte Carlo 仿真计算不同位宽配置下的平均 MSE、Sum-rate 以及总回传带宽消耗。

## 参数说明
- `--num_ap`: AP 数量 (L)，默认 16。
- `--num_ue`: 用户数量 (K)，默认 4。
- `--area_size`: 仿真区域边长 (米)，默认 500。
- `--p_tx`: 用户发射功率 (dBm)，默认 23。
- `--epochs`: Monte Carlo 仿真次数，建议 1000 以上以获得稳定结果。

## 运行方式
执行 `run.bat` 即可启动仿真并在控制台查看性能指标对比表。

## [Current Step]
# Cell-Free MIMO 去偏置聚合仿真

本程序解决了之前仿真中 MSE 无法随位宽下降的问题。通过引入**去偏置聚合 (De-biased Aggregation)** 物理模型，修正了局部 LMMSE 估计值幅度过小导致的合成偏差。

## 物理建模改进

1.  **局部 LMMSE (Local LMMSE)**：
    AP $l$ 针对用户 $k$ 的滤波系数定义为 $w_{lk} = \frac{G_{lk}^*}{\sum_{i=1}^K |G_{li}|^2 + \sigma^2}$。
2.  **AQNM 量化**：
    量化噪声方差基于理论功率 $E[|\hat{s}_{lk}|^2] = \frac{|G_{lk}|^2}{\sum_{i=1}^K |G_{li}|^2 + \sigma^2}$ 计算，符合 $z_{lk} = \alpha \hat{s}_{lk} + q_{lk}$。
3.  **去偏置聚合**：
    定义本地增益 $a_{lk} = w_{lk} G_{lk}$。CPU 接收到量化信号后，通过下式进行聚合：
    $$\hat{s}_k = \frac{\sum_{l=1}^L (z_{lk} / \alpha)}{\sum_{l=1}^L a_{lk}}$$
    该公式消除了 LMMSE 带来的幅度偏差，使得 MSE 能够反映真实的信噪比情况。

## 命令行参数

- `--num_ap`: AP 数量 (默认 16)
- `--num_ue`: 用户数量 (默认 4)
- `--p_tx`: 用户发射功率 (dBm, 默认 23)
- `--epochs`: 蒙特卡洛仿真次数 (默认 2000，推荐较大值以获得平滑曲线)

## 预期结果

随着量化位宽 $b$ 从 2 增加到 8：
- **Avg MSE**: 显著下降（例如从 0.8 下降至 0.2 左右）。
- **Sum-rate**: 显著上升。

## [Current Step]
# Cell-Free MIMO 仿真：量化与去偏置聚合优化

本项目仿真了 Cell-Free MIMO 上行链路中，采用去偏置 LMMSE 估计与 AQNM 量化模型时，系统性能（MSE 与 Sum-rate）随量化位宽的变化情况。

## 更新说明
针对之前仿真中 MSE 随位宽变化不明显的问题，进行了如下改进：
1. **SNR 环境优化**：将仿真区域 `--area_size` 从 500m 减小到 200m，并修正了发射功率 `--p_tx` 为 23dBm，以确保 AP 处的接收信噪比处于合理范围，从而凸显量化噪声的影响。
2. **物理逻辑修正**：
   - 确保 `quantize_estimate` 中的 $\alpha$ 和 $\rho$ 严格对应。
   - 增加了聚合估计值的模值校验（Debug Print），验证去偏置逻辑。
3. **指标计算修正**：
   - 为每个用户独立计算 $MSE_k = \mathbb{E}[|s_k - \hat{s}_k|^2]$。
   - 可达速率计算公式修正为 $R_k = \log_2(1 + \frac{1-MSE_k}{MSE_k})$，最后求和得到总速率。

## 参数说明
- `--area_size`: 仿真区域边长 (默认 200m)。
- `--p_tx`: 用户发射功率 (默认 23 dBm)。
- `--num_ap`: AP 数量 $L=16$。
- `--num_ue`: 用户数量 $K=4$。
- `--epochs`: 蒙特卡洛模拟次数。

## 运行方式
执行 `run.bat` 即可启动仿真：

## [Current Step]
# Cell-Free MIMO 传统算法基准仿真

本项目实现了 Cell-Free MIMO 上行链路中的几种经典接收机算法，用于评估分布式架构下的误码率 (BER) 性能，并量化回传量化对性能的影响。

## 实现功能

1.  **调制方式**: QPSK 调制与硬决策解调。
2.  **信道模型**: 
    - 3GPP UMi 通道模型。
    - 瑞利衰落 (i.i.d. Rayleigh fading)。
    - 考虑大尺度衰落 $\beta$。
3.  **接收算法**:
    - **Centralized MMSE (C-MMSE)**: 假设所有接收信号在中心处理单元 (CPU) 进行全精度聚合，并应用 LMMSE 检测。作为性能上限。
    - **LSFD (Large-Scale Fading Decoding)**: 
        - AP 侧：执行局部 LMMSE 滤波，获得用户符号的局部估计。
        - CPU 侧：利用大尺度衰落系数 $\beta$ 进行线性加权聚合。
    - **Quantized LSFD (2-bit & 4-bit)**: 
        - 在 AP 侧局部滤波后，使用 Lloyd-Max 量化器（针对高斯分布优化）对估计值的实部和虚部分开进行量化，模拟受限回传容量。

## 超参数说明

可以通过命令行参数调整仿真设置：

- `--num_ap`: 接入点 (AP) 数量，默认 16。
- `--num_ue`: 用户 (UE) 数量，默认 4。
- `--area_size`: 仿真区域大小 (m x m)，默认 200x200。
- `--epochs`: 蒙特卡洛实验次数，默认 1000。
- SNR 范围: 程序内部固定从 0dB 到 20dB (步长 5dB)。

## 运行方式

执行以下命令运行基准测试：

## [Current Step]
# Cell-Free MIMO 传统算法基准测试 (修复版)

本程序实现了 Cell-Free MIMO 系统在 Uplink 场景下的几种传统接收算法基准测试。

## 修复说明
1. **功率分配逻辑修复**：修正了发射功率 $P_{tx}$ 的计算。现在 $P_{tx} = \frac{\text{SNR}_{\text{linear}} \cdot \sigma^2}{E[\beta]}$，确保定义的 SNR 真正对应于 AP 侧的平均接收信噪比，避免了之前因未考虑路径损耗导致接收功率极低（BER=0.5）的问题。
2. **量化归一化优化**：在 Lloyd-Max 量化之前，对局部估计值 $s_{check,lk}$ 的方差进行了精确计算。基于 $E[|s_{check,lk}|^2] = \frac{|G_{lk}|^2}{\sum_i |G_{li}|^2 + \sigma^2}$ 动态调整归一化系数，确保量化器输入严格符合 $N(0,1)$ 映射要求。
3. **参数暴露与调试**：增加了平均路径损耗和对应 $P_{tx}$ (dBm) 的输出，方便验证物理层参数的合理性。

## 主要算法
- **C-MMSE (Centralized MMSE)**: 假设所有 AP 的原始信号都汇总到 CPU 进行联合解调，是性能的上界。
- **LSFD (Large-Scale Fading Decoding)**: 
    - **Full**: 每个 AP 进行本地匹配滤波（基于本地信道估计），CPU 根据大尺度衰落系数进行最优线性合并。
    - **2-bit / 4-bit**: 在 LSFD 的基础上，模拟 Fronthaul 链路的量化过程，使用 Lloyd-Max 量化器。

## 运行方式
执行 `run.bat` 即可运行。

### 参数说明
- `--num_ap`: AP 数量 (默认 16)
- `--num_ue`: 用户数量 (默认 4)
- `--epochs`: 蒙特卡洛实验次数 (默认 2000)
- `--area_size`: 仿真区域边长 (m)
- `--fc`: 载波频率 (GHz)

## [Current Step]
# Cell-Free MIMO 性能基准测试

本项目实现了无小区 (Cell-Free) MIMO 系统中的上行链路信号检测基准算法，重点对比了中心化 MMSE 检测与带有量化限制的本地合并 (LSFD) 性能。

## 主要修复与改进
1. **语法修复**：修复了 `baselines.py` 末尾 `simulate()` 函数调用时多余的括号导致的 `SyntaxError`。
2. **功率分配逻辑**：严格执行 `P_tx = 10**(snr_db / 10) * sigma2_n / avg_beta`，确保 `snr_db` 代表 AP 侧的平均接收信噪比。
3. **量化归一化**：在 `get_quantized_estimate` 中，对本地估计值进行了严谨的归一化处理。根据推导，$E[|s_{check, lk}|^2] = |G_{lk}|^2 / D_l$，据此计算实部和虚部的标准差并映射到标准正态分布的 Lloyd-Max 量化器。
4. **检测算法**：
   - **C-MMSE**: 使用公式 $(G^H G + \sigma^2_n I)^{-1} G^H y$。
   - **LSFD**: AP 侧进行最大比合并（本地 MMSE 简化版），中心侧进行基于大尺度衰落系数的加权聚合。

## 参数说明
可以通过命令行参数调整仿真配置：
- `--num_ap`: 接入点 (AP) 数量，默认 16。
- `--num_ue`: 用户 (UE) 数量，默认 4。
- `--area_size`: 仿真区域边长（米），默认 200.0。
- `--epochs`: 蒙特卡洛仿真次数，默认 2000。
- `--fc`: 载波频率 (GHz)。

## 运行方式
直接运行 `run.bat` 即可开始仿真：