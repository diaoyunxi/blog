---
title: AI 文生图的扩散模型原理
date: 2026-10-18
lang: zh-CN
tags: [扩散模型, 文生图, Stable Diffusion, DiT, Flux]
summary: 系统讲解扩散模型前向加噪与反向去噪、Latent Diffusion、条件注入与主流模型路线
source_issue: https://github.com/diaoyunxi/blog/issues/1
---

# AI 文生图的扩散模型原理

## 背景

文生图（text-to-image）模型能根据一段文字生成对应图像，目前主流技术路线是**扩散模型**（Diffusion Model）。本文从原理到实操，系统梳理扩散模型的核心思想、训练与推理流程、条件注入机制、Latent Diffusion 的优势、采样器选择以及主流模型（SD 系列、Flux、DiT）的对比。

## 核心原理

### 前向加噪与反向去噪

扩散模型的核心思想可以理解为：

- **前向过程（加噪）**：将一张清晰的图像逐步添加高斯噪声，经过 T 步（通常 50~1000 步）后，图像变成几乎纯噪声。这个过程是预定义的，不需要学习。
- **反向过程（去噪）**：训练一个神经网络学习如何一步步从噪声中恢复出清晰图像。推理时从纯噪声出发，逐步去噪，最终得到生成图像。

这个框架最早由 Ho 等人在 2020 年的论文 *Denoising Diffusion Probabilistic Models*（arXiv:2006.11239）中系统化。在该论文中，去噪扩散概率模型（DDPM）在 CIFAR10 上取得了 FID 3.17 的优异成绩。

### 噪声预测网络

网络（通常是 U-Net 或 DiT）的任务是：给定带噪图像 $x_t$ 和时间步 $t$，预测加进去的噪声 $\epsilon$。训练目标是最小化 $\| \epsilon - \epsilon_\theta(x_t, t) \|^2$。

- **U-Net**：卷积网络，带跳连连接，是早期 Stable Diffusion 的标配。
- **DiT（Diffusion Transformer）**：将图像切块后用 Transformer 处理，规模更大，扩展性更好。Flux 等新一代模型采用 DiT 架构。

### 训练 vs 推理

| 阶段 | 做什么 | 需要多少步 |
|------|--------|-----------|
| 训练 | 随机采样时间步，加噪，让网络预测噪声，反向传播更新参数 | 数周 GPU 时间 |
| 推理 | 从纯噪声开始，逐步去噪 | 20~50 步（DDIM/DPM-Solver）或 50~1000 步（DDPM） |

## 文生图：文本编码器与条件注入

### 文本编码器

提示词（prompt）先经过文本编码器（如 CLIP 文本编码器、T5 等）变成一组文本嵌入向量，再通过网络中的**交叉注意力（cross-attention）** 层注入到去噪过程中。图像特征作为 Query，文本嵌入作为 Key/Value，这样网络在每一步去噪时都能"参考"文字语义。

### 分类器自由引导（CFG）

CFG 的核心思想是：同时做两次前向传播——一次带条件（文字），一次不带条件（空文本），然后把两者外插：

```
输出 = 无条件预测 + scale × (条件预测 − 无条件预测)
```

`scale`（即 `guidance_scale`，通常 7~15）越大，生成结果越贴合提示词，但多样性下降、易过饱和。

## Latent Diffusion：为什么更快

Stable Diffusion（Stability AI，2022）的关键创新是把扩散过程放在**潜空间（latent space）** 而非像素空间：

1. 先用 VAE 把图像压缩到小尺寸潜向量（例如 512×512 图像 → 64×64×4）；
2. 在潜空间上做扩散（加噪/去噪），计算量大幅降低；
3. 生成完再用 VAE 解码器还原为像素图像。

因为 U-Net 在低分辨率潜空间上操作，显存占用和计算量都显著低于像素空间扩散，这使得消费级 GPU 也能跑。

## 采样器区别

| 采样器 | 特点 | 典型步数 |
|--------|------|---------|
| **DDPM** | 原始方法，随机采样，最慢但最稳定 | 50~1000 步 |
| **DDIM** | 确定性版本，可加速到 20~50 步，支持任意步数 | 20~50 步 |
| **DPM-Solver** | 基于 ODE 求解器，10~25 步即可出好图 | 10~25 步 |
| **Euler / Heun** | 简化实现，常见于 ComfyUI / SD WebUI | 20~50 步 |

步数少时图像细节可能不足；步数多则收益递减且耗时增加。DPM-Solver 系列在低步数下表现尤其好。

## 主流模型路线

| 模型 | 架构 | 文本编码器 | 特点 |
|------|------|-----------|------|
| **SD 1.5**（2022） | U-Net + VAE | CLIP | 经典，生态丰富 |
| **SDXL**（2023） | U-Net + VAE | CLIP + CLIP-L | 更高分辨率（1024×1024） |
| **Flux**（Black Forest Labs，2024） | DiT | T5 + CLIP | 质量高，提示词理解强 |
| **SD 3 / 3.5**（Stability，2024） | DiT | T5 + CLIP | MMDiT 架构 |

DiT 路线的优势：用 Transformer 替代卷积，容易扩展到更大规模，多模态理解更好。

## 常见坑

- **手部畸形**：扩散模型对手指数量、关节朝向仍容易出错，需要负面提示词或 Inpaint 修复。
- **文字生成差**：早期模型几乎不能正确生成文字（如 "OPENAI" 变成乱码），Flux 和 SD3 在这方面有明显改善但仍未完美。
- **提示词敏感**：同样的词序、措辞差异会导致结果差异较大；建议用结构化提示词（主体 + 风格 + 光影 + 构图）。
- **算力开销**：512×512 推理仍需约 10GB+ 显存（SD 1.5 全精度），1024×1024 更高；FP16/INT8 量化可缓解。
- **CFG 过大**：guidance_scale 超过 15 容易出现色彩过饱和、伪影。

## 实操示例（SD 1.5，diffusers 库）

```python
import torch
from diffusers import StableDiffusionPipeline

pipe = StableDiffusionPipeline.from_pretrained(
    "runwayml/stable-diffusion-v1-5",
    torch_dtype=torch.float16,
).to("cuda")

image = pipe(
    prompt="a cat sitting on a windowsill, watercolor, soft light",
    negative_prompt="blurry, low quality, extra fingers",
    guidance_scale=7.5,
    num_inference_steps=30,
).images[0]

image.save("cat.png")
```

## 小结

扩散模型通过"逐步去噪"的简单思想实现了高质量图像生成。Latent Diffusion 让消费级硬件也能跑，DiT 架构则把可扩展性拉高了一个台阶。理解前向加噪、噪声预测网络、cross-attention 条件注入和 CFG 这四个核心概念，基本就能读懂当前主流文生图模型的架构。

## 参考

- Ho, Jain, Abbeel. *Denoising Diffusion Probabilistic Models*. 2020. https://arxiv.org/abs/2006.11239
- OpenAI CLIP 仓库：https://github.com/openai/CLIP
- Stability AI（Stable Diffusion 开发者）：https://stability.ai
