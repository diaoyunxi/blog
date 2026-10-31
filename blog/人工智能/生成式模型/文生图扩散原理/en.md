---
title: How Diffusion Models Power Text-to-Image
date: 2026-10-18
lang: en
tags: [Diffusion Models, Text-to-Image, Stable Diffusion, DiT, Flux]
summary: A systematic walkthrough of forward noising and reverse denoising, latent diffusion, conditioning injection, and the main model families
source_issue: https://github.com/diaoyunxi/blog/issues/1
---

# How Diffusion Models Power Text-to-Image

## Background

Text-to-image models generate an image that matches a piece of text. The dominant technical approach today is the **diffusion model**. This article walks through the core ideas, the training and inference pipelines, the conditioning mechanism, the advantages of latent diffusion, sampler selection, and a comparison of the mainstream model families (SD series, Flux, DiT).

## Core Principles

### Forward Noising and Reverse Denoising

The central idea of a diffusion model can be stated simply:

- **Forward process (noising)**: starting from a clean image, Gaussian noise is added step by step; after T steps (typically 50 to 1000) the image is essentially pure noise. This process is predefined and requires no learning.
- **Reverse process (denoising)**: a neural network is trained to recover a clean image from noise one step at a time. At inference time we start from pure noise and denoise step by step until an image emerges.

This framework was first systematized by Ho et al. in their 2020 paper *Denoising Diffusion Probabilistic Models* (arXiv:2006.11239), where DDPM reached an FID of 3.17 on CIFAR10.

### The Noise-Prediction Network

The network — typically a U-Net or a DiT — takes a noisy image $x_t$ and a timestep $t$, and predicts the noise that was added: $\epsilon$. The training objective is to minimize $\| \epsilon - \epsilon_\theta(x_t, t) \|^2$.

- **U-Net**: a convolutional network with skip connections, the standard choice for early Stable Diffusion models.
- **DiT (Diffusion Transformer)**: patches the image and processes it with a Transformer, scaling better and generalizing more easily. Flux and other next-generation models use the DiT architecture.

### Training vs. Inference

| Stage | What happens | How many steps |
|------|--------------|----------------|
| Training | Sample a random timestep, add noise, let the network predict it, backpropagate | Weeks of GPU time |
| Inference | Start from pure noise and denoise step by step | 20–50 steps (DDIM/DPM-Solver) or 50–1000 steps (DDPM) |

## Text-to-Image: the Text Encoder and Conditioning Injection

### The Text Encoder

The prompt first passes through a text encoder (such as a CLIP text encoder or T5) and becomes a set of text embeddings. These are then injected into the denoising process through **cross-attention** layers. Image features act as the Query, text embeddings as the Key/Value, so the network can "consult" the text semantics at every denoising step.

### Classifier-Free Guidance (CFG)

The core idea of CFG is to run the forward pass twice — once with the condition (the text) and once without it (an empty prompt) — and then extrapolate between the two:

```
output = unconditional prediction + scale × (conditional prediction − unconditional prediction)
```

The larger the `scale` (usually `guidance_scale`, 7 to 15), the more closely the result follows the prompt, but diversity drops and oversaturation becomes more likely.

## Latent Diffusion: Why It Is Faster

The key innovation of Stable Diffusion (Stability AI, 2022) was to run the diffusion process in **latent space** rather than in pixel space:

1. A VAE first compresses the image into a small latent tensor (for example 512×512 → 64×64×4);
2. Diffusion (noising/denoising) happens in that latent space, cutting the compute dramatically;
3. Once generation finishes, the VAE decoder restores a pixel-space image.

Because the U-Net operates on a low-resolution latent, both memory footprint and compute are far lower than in pixel space — which is what makes consumer GPUs viable.

## Sampler Differences

| Sampler | Characteristics | Typical steps |
|---------|-----------------|---------------|
| **DDPM** | The original method, stochastic sampling; slowest but the most stable | 50–1000 steps |
| **DDIM** | Deterministic variant, can be accelerated to 20–50 steps, supports arbitrary step counts | 20–50 steps |
| **DPM-Solver** | Based on ODE solvers; good images in as few as 10–25 steps | 10–25 steps |
| **Euler / Heun** | Simplified implementations, common in ComfyUI / SD WebUI | 20–50 steps |

With few steps, fine detail may be missing; with many steps the returns diminish while runtime grows. The DPM-Solver family performs especially well at low step counts.

## Mainstream Model Families

| Model | Architecture | Text encoders | Characteristics |
|-------|--------------|---------------|-----------------|
| **SD 1.5** (2022) | U-Net + VAE | CLIP | The classic choice, with a rich ecosystem |
| **SDXL** (2023) | U-Net + VAE | CLIP + CLIP-L | Higher resolution (1024×1024) |
| **Flux** (Black Forest Labs, 2024) | DiT | T5 + CLIP | High quality, strong prompt comprehension |
| **SD 3 / 3.5** (Stability, 2024) | DiT | T5 + CLIP | The MMDiT architecture |

The advantage of the DiT line: replacing convolution with a Transformer makes it easy to scale up, and multimodal understanding improves.

## Common Pitfalls

- **Deformed hands**: diffusion models still routinely get the number of fingers and joint orientations wrong; negative prompts or Inpainting are the usual workarounds.
- **Poor text rendering**: early models could barely spell anything (e.g. "OPENAI" turning into gibberish). Flux and SD3 improved this markedly, though it is still not perfect.
- **Prompt sensitivity**: even small changes in word order or phrasing can shift the result noticeably. Structured prompts work better (subject + style + lighting + composition).
- **Compute cost**: 512×512 inference still needs roughly 10GB+ of VRAM for SD 1.5 at full precision, more at 1024×1024; FP16/INT8 quantization helps.
- **Excessive CFG**: a guidance_scale above 15 tends to produce oversaturated colors and artifacts.

## A Practical Example (SD 1.5 with diffusers)

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

## Summary

Diffusion models achieve high-quality image generation through the simple idea of "denoising step by step". Latent diffusion brings consumer hardware into play, and the DiT architecture raises the ceiling on scalability. Understanding four core concepts — forward noising, the noise-prediction network, cross-attention conditioning, and CFG — is enough to read the architecture of any mainstream text-to-image model.

## References

- Ho, Jain, Abbeel. *Denoising Diffusion Probabilistic Models*. 2020. https://arxiv.org/abs/2006.11239
- OpenAI CLIP repository: https://github.com/openai/CLIP
- Stability AI (the makers of Stable Diffusion): https://stability.ai
