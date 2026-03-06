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

## [Current Step]
# GNN Detector for Cell-Free MIMO

本项目实现了一个基于异构图神经网络 (Heterogeneous GNN) 的多用户信号检测器，旨在 Cell-Free MIMO 场景下通过深度学习消除多用户干扰 (MUI)，并超越传统的 LSFD (Large-Scale Fading Decoding) 基准。

## 功能特性
1. **物理环境模拟**：严格遵循 `baselines.py` 的参数，包括 16 AP, 4 UE, 3GPP UMi 路径损耗和 Rayleigh 衰落。
2. **GNN 架构**：
   - **边处理层**：将 AP 产生的本地估计值与大尺度衰落系数 $\beta$ 结合作为特征。
   - **UE 聚合层**：每个 UE 节点聚合来自所有 16 个 AP 的空间特征。
   - **交互层**：通过全连接层模拟 CPU 端的全局信息交换，有效抵消多用户间的干扰。
3. **性能验证**：在 SNR 0-20dB 范围内进行测试，并计算相对于 LSFD 的误码率 (BER) 改善百分比。

## 参数说明
- `--train_epochs`: 训练迭代次数 (默认 100)。
- `--batch_size`: 每步训练的样本数 (默认 128)。
- `--lr`: 学习率 (默认 0.001)。
- `--hidden_dim`: GNN 隐藏层维度 (默认 64)。
- `--eval_trials`: 评估时的蒙特卡洛实验样本数 (默认 1000)。

## 运行方式
执行 `run.bat` 即可开始训练并在控制台观察 BER 对比表格。

## 预期结果
在高 SNR (20dB) 下，GNN 检测器由于能够学习到非线性的干扰模式，通常比线性加权的 LSFD 展现出 15% 以上的 BER 降低。

## [Current Step]
# LSQ 量化器 (Learned Step-size Quantization) 实现

该模块实现了 Esser et al. 提出的 **LSQ (Learned Step-size Quantization)** 可微量化器。它是构建可学习位宽神经网络的核心组件，支持通过梯度下降优化量化步长（Step-size）。

## 功能特性

1.  **LSQFunction**: 自定义 `torch.autograd.Function`，实现了直通估计器 (Straight-Through Estimator, STE)。
    -   **前向**: 执行 `v_hat = round(clamp(v/s, v_min, v_max)) * s`。
    -   **反向**: 按照论文公式计算对输入张量 `v` 和步长 `s` 的梯度。
2.  **LSQQuantizer**:
    -   支持 **2-bit** (范围: -2 to 1) 和 **3-bit** (范围: -4 to 3) 量化。
    -   **自动初始化**: 使用第一个 batch 输入张量的统计特性（`2 * E[|v|] / sqrt(v_max)`）自动初始化步长 `s`。
    -   **参数化**: 步长 `s` 被定义为 `nn.Parameter`，可参与模型整体训练。

## 命令行参数

`lsq_quantizer.py` 提供以下可配置超参数：

-   `--bit_width`: 量化位宽，可选 `2` 或 `3`。
-   `--lr`: 步长 `s` 的优化学习率，默认 `0.01`。
-   `--num_elements`: 验证脚本中生成的随机测试张量的大小。

## 运行方式

直接运行 `run.bat` 或在命令行执行：

## [Current Step]
# 累进式位宽策略网络 (Successive Refinement Policy Network)

本项目实现了 Cell-Free MIMO 系统中接入点 (AP) 侧的可学习位宽分配机制。通过动态决策每个链路的量化比特数，平衡通信开销与探测精度。

## 1. 核心模块说明

- **ResidualLSQ**: 
    - 采用残差量化结构实现 0, 2, 4 bits 三档位宽。
    - 4-bit 传输被拆分为 2-bit 基础量化和 2-bit 残差量化，符合累进式传输逻辑。
    - 底层调用 `LSQQuantizer` 确保量化阶梯（Step-size）可学习。

- **BitwidthPolicyNet**:
    - 一个轻量级 MLP，根据 AP 到 UE 的大尺度衰落系数 $\beta_{lk}$ 预测最优位宽。
    - 逻辑：对于信道质量极差的链路，分配 0-bit 以节省带宽；对于中等质量分配 2-bit；对于高质量链路分配 4-bit。

- **Gumbel-Softmax**:
    - 使得离散的位宽选择过程可导。
    - 训练时使用软采样（`hard=False`）进行梯度回传，评估时使用硬采样（`hard=True`）模拟真实量化决策。

## 2. 损失函数

训练目标结合了信号检测的准确性和比特率成本：
$$Loss = MSE + \lambda_{bit} \times \text{Average\_Bitrate}$$
其中 $\lambda_{bit}$ 是一个超参数，用于控制性能与压缩率的权衡。

## 3. 命令行参数

- `--train_epochs`: 训练迭代轮数 (默认: 100)。
- `--lambda_bit`: 比特率惩罚系数。增加此值将引导网络选择更低的位宽 (默认: 0.01)。
- `--lr`: 学习率 (默认: 0.001)。
- `--tau`: Gumbel-Softmax 的温度参数。较低的温度使概率分布更接近 One-hot (默认: 1.0)。

## 4. 运行与验证

脚本 `refinement_policy.py` 会在训练结束后自动对比：
1. **固定 2-bit**: 所有链路统一分配 2 bits。
2. **动态策略**: 同样在平均约 2-bit 的约束下（通过调节 $\lambda_{bit}$），观察 MSE 是否由于优化了分配方案而下降。

输出将包含每个 Epoch 的 Loss 变化，以及在 SNR=10dB 下的 MSE 和平均比特率对比表。

## [Current Step]
# Successive Refinement Policy 训练优化说明

本脚本 `refinement_policy.py` 实现了基于 Gumbel-Softmax 的动态位宽分配策略。网络根据大尺度衰落系数 $\beta$ 为每个 AP-UE 链路选择最优位宽（0, 2, 4 bits），并使用 GNN 探测器进行联合优化。

### 修复与改进内容
1.  **Bug 修复**：修复了在打印 `Policy Probs` 时由于 Tensor 仍处于计算图中导致的 `RuntimeError`。增加了 `.detach()` 调用。
2.  **增加训练轮数**：默认 `--train_epochs` 提升至 200，确保动态策略有足够的收敛时间。
3.  **温度衰减策略 (Tau Cooling)**：
    - 引入了 Gumbel-Softmax 温度衰减：`tau = max(0.1, args.tau * (0.95 ** (epoch // 10)))`。
    - 在训练初期使用高温度进行“软搜索”，后期降低温度以逼近硬选择（Hard Selection）。
4.  **学习率衰减**：引入 `StepLR` 每 50 个 epoch 学习率减半，提高后期训练的平稳性。
5.  **基准对比增强**：在评估时，将训练好的 `base_quant` 提取出来作为 "Fixed 2-bit" 基准，验证探测器对不同位宽分布的适应性。

### 命令行参数
- `--train_epochs`: 训练总轮数 (默认 200)。
- `--lr`: 初始学习率 (默认 0.001)。
- `--lambda_bit`: 比特率惩罚系数 (默认 0.01)。系数越大，网络越倾向于分配更低的比特数。
- `--tau`: Gumbel-Softmax 初始温度 (默认 1.0)。

### 输出结果说明
- 脚本运行结束后，将打印 `Metric` 对比表（Fixed 2-bit vs Dynamic Policy）。
- 关键输出：`Policy Probs vs Beta (Sampled)` 表格。通过该表可以观察到，随着 $\beta$（信号强度）的增大，网络是否成功学会了从分配 0-bit 转换到分配 2-bit 甚至 4-bit。

## [Current Step]
# 优化版 Successive Refinement 策略与 Task-aware GNN

本脚本实现了针对 CF-MIMO 系统的前向反馈位宽优化策略。

### 主要改进点：
1. **策略网络输入特征优化**：将原始的大尺度衰落系数 $\beta$ 转换为对数域（dB），并进行归一化处理。这解决了 MLP 面对极小输入量级时的梯度消失和输出塌缩问题。
2. **Task-aware GNN 探测器**：
   - 探测器输入维度从 3 扩展至 6。
   - 新增特征包括位宽选择的 Gumbel-Softmax 权重向量 $[p_0, p_2, p_4]$。
   - 这使得 GNN 能够感知当前的量化精度，从而在聚合来自不同 AP 的信息时，自动降低 0-bit 分支（噪声）的权重。
3. **性能指标增强**：
   - 引入 **Sum-rate** 指标：$R = \log_2(1 + (1-MSE)/MSE)$。
   - 策略网络最后一层使用较小的初始化权重，确保训练初期探索的公平性。

### 关键超参数说明：
- `--train_epochs`: 训练轮数（建议 200 以保证策略收敛）。
- `--lambda_bit`: 比特率惩罚系数。调节此参数可使 `Dynamic Policy` 的平均比特率逼近基准（如 2.0）。
- `--tau`: Gumbel-Softmax 的初始温度，随训练进行退火。

### 预期结果：
随着 Beta 增大，网络应倾向于分配更高比特（P(4-bit) 增加）；在 Beta 极小时，网络应倾向于选择 P(0-bit) 以节省开销且不引入强噪声。

## [Current Step]
# 第 6 步：联合量化感知训练 (Joint QAT)

本项目实现了针对 CF-MIMO 系统的联合量化感知训练框架。核心目标是优化比特分配策略与 GNN 探测器的协同性能。

## 主要功能

1.  **位宽感知注意力 (Bit-Aware Attention)**:
    -   设计了 `AttentionGNNDetector`。
    -   该探测器不再是简单地拼接位宽信息，而是通过 `bit_attention_mapper` 将策略网络输出的位宽概率 `[p0, p2, p4]` 映射为隐藏层的注意力缩放因子。
    -   这使得 GNN 能够根据链路的量化精度动态调整对各条边特征的依赖程度（例如，对于 0-bit 分配的链路，其特征会被显著抑制）。

2.  **全精度基准 (Full-Precision GNN)**:
    -   同步训练一个无量化的 GNN 模型作为性能上界（100% 性能）。
    -   用于计算 `Performance Ratio = Dynamic MSE / FP MSE`。

3.  **联合优化与退火**:
    -   同时优化 `BitwidthPolicyNet`、`ResidualLSQ` 和 `AttentionGNNDetector`。
    -   使用 Gumbel-Softmax 进行离散决策的梯度估计。
    -   实现了温度 `tau` 的指数退火，确保训练从平滑分布过渡到硬性决策。

## 关键参数

| 参数 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `--epochs` | 150 | 训练轮数 |
| `--lambda_bit` | 0.002 | 比特率惩罚系数，调节该值可平衡性能与位宽。目标平均位宽约 2.5 bits。 |
| `--tau_init` | 1.0 | Gumbel-Softmax 初始温度 |
| `--batch_size` | 128 | 批大小 |

## 预期结果

脚本在运行结束时会输出详细的对比表格。预期的性能目标是：
-   `Dynamic Policy` 的 MSE 与 `Full-Precision` 的比值在 1.1 以内（即达到全精度的 90% 以上性能）。
-   平均比特率稳定在 2.5 bits 左右。
-   相比 `Fixed 2-bit`，`Dynamic Policy` 能在相似或略高的比特率下显著降低 MSE 和 BER。

## [Current Step]
# Joint QAT with Bit-Aware Attention Mechanism

本模块实现了联合量化感知训练 (Joint QAT)，旨在为 CF-MIMO 系统中的接入点 (AP) 到 CPU 的链路动态分配位宽。

## 主要功能
1. **错误修复**：修正了 `JointQATSystem` 中的 `super().__init__` 调用错误。
2. **位宽感知注意力 (Bit-Aware Attention)**：`AttentionGNNDetector` 引入了位宽感知映射器。它根据每个链路当前的位宽选择概率 (weights)，动态调整 GNN 对该链路信号的“注意力”权重。例如，当策略选择 0-bit (链路关断) 时，注意力权重趋近于 0。
3. **对比评估**：
    - **Full-Precision (FP)**：无量化 GNN 基准。
    - **Fixed 2-bit**：所有链路固定使用 2-bit LSQ 量化的基准。
    - **Dynamic (Policy)**：由 `BitwidthPolicyNet` 根据大尺度衰落 $\beta$ 动态决定 0/2/4 bit 分配的联合方案。
4. **性能指标**：计算 MSE, BER, 平均比特率以及系统和速率 (Sum-rate)，并输出 **Performance Ratio (Dynamic MSE / FP MSE)**。

## 命令行参数
- `--epochs`: 训练总轮数 (默认 150)。
- `--lr`: 学习率 (默认 0.001)。
- `--lambda_bit`: 比特率惩罚系数 (默认 0.002)。增加此值会降低平均比特率，但可能增大 MSE。
- `--eval_trials`: 评估时的测试样本数 (默认 1000)。

## 运行方式
执行 `run.bat` 即可开始训练并观察 SNR=10dB 下的三方案对比表格。

## [Current Step]
# Step 7: 硬选择推理与鲁棒性验证 (evaluation.py)

该脚本实现了研究计划的第七步，重点关注模型在离散化决策下的表现、跨信噪比的泛化能力以及面对节点故障时的生存能力。

## 主要功能

1.  **联合训练集成**：
    - 集成了 `joint_qat.py` 中的 `JointQATSystem`。
    - 在 SNR=10dB 下进行 150 个 Epoch 的联合优化，使模型学习针对具体信道质量的位宽分配策略。

2.  **硬选择推理 (Hard Inference)**：
    - 在推理阶段，通过设置 `tau=0.01` 和 `hard=True` 的 Gumbel-Softmax 或直接 Argmax，将概率连续分布强制转换为确定的离散比特选择（0, 2, 或 4 bit）。

3.  **SNR 扫描性能对比**：
    - 测试范围：[0, 5, 10, 15, 20] dB。
    - 对比方案：
        - **Full-Precision (全精度)**：性能上限。
        - **Fixed 2-bit (固定 2比特)**：传统的统一量化方案。
        - **Proposed Dynamic Policy (动态策略)**：本研究提出的根据信道条件自动分配位宽的方案。

4.  **鲁棒性验证 (AP Survival Analysis)**：
    - 模拟回传链路故障。随机挑选 0, 2, 4, 8 个 AP 并强制关闭（0-bit）。
    - 验证位宽感知注意力机制（Bit-Aware Attention）是否能通过其余正常工作的 AP 进行空间补偿。

5.  **复杂度分析**：
    - 统计 AP 侧 `BitwidthPolicyNet` 的参数量。
    - 定性对比 LMMSE（涉及 $O(K^3)$ 矩阵求逆）与所提方案（轻量级 MLP）的计算成本。

## 参数说明

- `--epochs`: 训练轮数（默认 150）。
- `--lr`: 学习率（默认 0.001）。
- `--lambda_bit`: 位宽惩罚系数（默认 0.002），用于平衡 BER 和前传开销。
- `--tau_init`: Gumbel-Softmax 初始温度。

## 运行方式