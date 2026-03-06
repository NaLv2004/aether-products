import torch
import torch.nn as nn
import torch.optim as optim
import argparse

class LSQFunction(torch.autograd.Function):
    """
    LSQ (Learned Step-size Quantization) Custom Autograd Function.
    实现前向离散化和后向梯度估计 (STE)。
    """
    @staticmethod
    def forward(ctx, v, s, v_min, v_max):
        # 计算 v/s
        v_scaled = v / s
        
        # 裁剪并取整 (Clamp and Round)
        v_clipped = torch.clamp(v_scaled, v_min, v_max)
        v_rounded = torch.round(v_clipped)
        
        # 反量化
        v_hat = v_rounded * s
        
        # 保存用于 backward 的张量
        # 注意：v_min 和 v_max 是标量常量，ctx 中直接存储即可
        ctx.save_for_backward(v_scaled, s)
        ctx.v_min = v_min
        ctx.v_max = v_max
        
        return v_hat

    @staticmethod
    def backward(ctx, grad_output):
        v_scaled, s = ctx.saved_tensors
        v_min = ctx.v_min
        v_max = ctx.v_max
        
        # 1. 计算对 v 的梯度 (在 clamp 范围内为 1, 范围外为 0)
        mask_in_range = (v_scaled >= v_min) & (v_scaled <= v_max)
        grad_v = grad_output.clone()
        grad_v[~mask_in_range] = 0
        
        # 2. 计算对 s 的梯度
        # 根据 LSQ 论文：
        # - 在范围内：grad_s = (round(v/s) - v/s) * grad_output
        # - 在范围下限以下：grad_s = v_min * grad_output
        # - 在范围上限以上：grad_s = v_max * grad_output
        v_rounded = torch.round(torch.clamp(v_scaled, v_min, v_max))
        
        mask_below = (v_scaled < v_min)
        mask_above = (v_scaled > v_max)
        
        grad_s_coeff = torch.where(mask_in_range, 
                                   v_rounded - v_scaled, 
                                   torch.where(mask_below, 
                                               torch.tensor(float(v_min), device=v_scaled.device), 
                                               torch.tensor(float(v_max), device=v_scaled.device)))
        
        grad_s = (grad_output * grad_s_coeff).sum().reshape(s.shape)
        
        # 返回梯度，v_min 和 v_max 为不可学习参数，返回 None
        return grad_v, grad_s, None, None

class LSQQuantizer(nn.Module):
    def __init__(self, bit_width=2):
        super(LSQQuantizer, self).__init__()
        self.bit_width = bit_width
        
        # 根据需求定义量化范围
        if bit_width == 2:
            self.v_min = -2.0
            self.v_max = 1.0
        elif bit_width == 3:
            self.v_min = -4.0
            self.v_max = 3.0
        else:
            raise ValueError("Only bit_width=2 or 3 is supported as per instructions.")
            
        # 步长 s 初始化为 Parameter，初始值设为 1.0 (后续在 forward 第一个 batch 时重置)
        self.s = nn.Parameter(torch.tensor(1.0))
        self.register_buffer('init_done', torch.tensor(0, dtype=torch.bool))

    def forward(self, x):
        # 步长初始化：使用第一个 batch 的统计特性
        if self.training and not self.init_done:
            # 初始化公式：s = 2 * E[|v|] / sqrt(v_max)
            with torch.no_grad():
                init_val = 2 * x.abs().mean() / (self.v_max ** 0.5)
                self.s.data.copy_(init_val)
            self.init_done.fill_(True)
            print(f"[LSQQuantizer] Step-size 's' initialized to: {self.s.item():.6f}")

        return LSQFunction.apply(x, self.s, self.v_min, self.v_max)

def main():
    parser = argparse.ArgumentParser(description="LSQ Quantizer Verification Script")
    parser.add_argument("--bit_width", type=int, default=2, choices=[2, 3], help="Bit width for quantization (2 or 3)")
    parser.add_argument("--lr", type=float, default=0.01, help="Learning rate for step-size optimization")
    parser.add_argument("--num_elements", type=int, default=10, help="Number of elements in the test tensor")
    args = parser.parse_args()

    print(f"--- Starting LSQ Quantization Verification ({args.bit_width}-bit) ---")

    # 1. 生成正态分布张量
    torch.manual_seed(42)
    input_tensor = torch.randn(args.num_elements, requires_grad=False)
    
    # 2. 实例化量化器
    quantizer = LSQQuantizer(bit_width=args.bit_width)
    optimizer = optim.Adam(quantizer.parameters(), lr=args.lr)

    # 3. 前向传播
    output_tensor = quantizer(input_tensor)
    
    # 4. 计算 MSE Loss 并反向传播
    # 使用原始张量作为目标进行重建验证
    loss = torch.nn.functional.mse_loss(output_tensor, input_tensor)
    loss.backward()

    # 5. 打印关键信息
    print(f"\n[Statistics]")
    print(f"Input Tensor (first 5): {input_tensor[:5].tolist()}")
    print(f"Quantized Tensor (first 5): {output_tensor[:5].tolist()}")
    print(f"Loss (MSE): {loss.item():.6f}")
    
    # 检查梯度
    if quantizer.s.grad is not None:
        print(f"Step-size 's' gradient: {quantizer.s.grad.item():.6f}")
    else:
        print("Error: Step-size gradient not found.")

    # 6. 执行一次更新
    old_s = quantizer.s.item()
    optimizer.step()
    new_s = quantizer.s.item()
    
    print(f"Step-size 's' before update: {old_s:.6f}")
    print(f"Step-size 's' after update (Adam, lr={args.lr}): {new_s:.6f}")
    print(f"Delta 's': {new_s - old_s:.6f}")

    # 7. 离散化效果验证
    unique_levels = torch.unique(output_tensor / quantizer.s)
    print(f"\n[Verification] Quantized levels (scaled by s): {unique_levels.tolist()}")
    print("Expected levels: integers within range [v_min, v_max]")
    print("--- Verification Finished ---")

if __name__ == "__main__":
    main()