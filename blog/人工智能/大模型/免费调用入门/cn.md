---
title: 三分钟上手 Agnes 免费 AI API：注册、调用与踩坑指南
date: 2026-10-18
lang: zh-CN
tags: [人工智能, 大模型, API入门, Agnes]
summary: 面向初学者的 Agnes 免费 AI API 快速上手指南，涵盖注册、密钥获取、示例代码与常见踩坑。
source_issue: https://github.com/diaoyunxi/blog/issues/1
---

## 背景

大模型 API 对很多初学者并不友好：注册要绑卡、调用要计费、文档冗长。而 Agnes 官方活动页（agnes-ai.com/campaign）主打"免费 AI API 额度、免费创建 API 密钥、免费调用多模态模型"，面向聊天机器人与 AI Agent 场景，门槛相当低。本文带你三分钟完成从注册到跑通第一次调用的全过程。

## 核心概念

- **Agnes 模型家族**：官方定位为"世界级的多模态（Omni-Modal）AI 模型"，除文本对话外，还支持图像、音频等模态输入（具体可用模型列表以官方 App 端与 API 文档为准，截至 2026-10-18 未找到逐个模型的权威规格表）。
- **API 密钥**：免费注册后即可在 agnes-ai.com 创建 API Key，用于调用 REST 接口，无需信用卡。
- **免费额度**：活动页称注册即送免费 API credits / tokens，额度上限与有效期以活动页实时展示为准。

## 实操步骤

**第一步：注册并创建密钥**

1. 打开 https://agnes-ai.com/campaign ，点击创建账号；
2. 登录控制台，在"API Keys"区域点击创建，复制生成的密钥（形如 `agnes-...`，妥善保存）。

**第二步：发起第一次调用**

```bash
curl https://api.agnes-ai.com/v1/chat/completions \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "agnes-flash",
    "messages": [
      {"role": "user", "content": "用一句话介绍你自己"}
    ]
  }'
```

> 注意：`model` 的具体型号（如 flash、pro、omni 等后缀）以官方文档列表为准，上表中的 `agnes-flash` 仅作示例占位；请求地址与字段名如与官方文档不一致，请以文档为准。

**第三步：用 Python 快速验证**

```python
import requests

resp = requests.post(
    "https://api.agnes-ai.com/v1/chat/completions",
    headers={
        "Authorization": "Bearer YOUR_API_KEY",
        "Content-Type": "application/json",
    },
    json={
        "model": "agnes-flash",
        "messages": [{"role": "user", "content": "hello"}],
    },
)
print(resp.status_code)
print(resp.json())
```

返回 JSON 中通常包含 `choices[0].message.content`（对话文本）与 `usage`（token 用量）字段，结构接近 OpenAI 风格接口，方便迁移。

## 常见坑

1. **401 / 密钥失效**：控制台中删除旧密钥后，旧 Key 立即失效；轮换时先建新的再删旧的。
2. **免费额度耗尽**：返回 402 或活动限制错误码，需等待活动续期或转付费；不要写死重试风暴，加指数退避。
3. **多模态字段不匹配**：文本接口不支持直接传图片 URL 的模型，需换用官方 omni 模型与 `image_url` 等字段，具体以文档为准。
4. **密钥泄漏**：切勿把 API Key 写进前端代码或提交到 Git，使用环境变量注入。

## 小结

Agnes 对"想零成本体验多模态大模型 API"的场景非常友好：注册即得免费 Key、OpenAI 风格接口易于迁移。但务必以官方活动页与 API 文档的实时说明为准，注意免费额度边界与密钥安全。

## 参考

- Agnes 官方活动页（免费 API 额度与 Key）：https://agnes-ai.com/campaign
- Agnes 应用端：https://app.agnes-ai.com
