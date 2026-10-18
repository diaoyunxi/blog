---
title: 检索增强生成入门：原理、实操与常见坑
date: 2026-10-18
lang: zh-CN
tags: [检索增强生成, 大模型, 向量检索, 知识图谱]
summary: 面向中文读者的 RAG 入门文章，讲解核心概念、搭建步骤、常见坑与扩展方向。
source_issue: https://github.com/diaoyunxi/blog/issues/1
---

# 检索增强生成（RAG）入门：原理、实操与常见坑

## 背景

大语言模型（LLM）有两类痛点：一是知识截止，训练数据之后的事件、版本、价格它可能并不掌握；二是幻觉，面对它"没学过"的事实，模型会一本正经地编造。检索增强生成（Retrieval-Augmented Generation，下称 RAG）就是为了解决这两个问题而生的工程范式：**先把相关证据检索出来，再让模型"看着证据写答案"**。

与微调不同，RAG 不需要重训模型，知识可以随时增删，可解释性强，成本可控，因此成为企业落地大模型最主流的路径之一。

## 核心概念

一条典型的 RAG 流水线包含四个环节：

1. **切块（Chunking）**：把长文档切成固定长度或语义相邻的片段，作为检索的最小单元。
2. **向量化（Embedding）**：用嵌入模型把每个片段编码成稠密向量，存入向量数据库。
3. **检索（Retrieval）**：用户提问先做嵌入，按相似度或混合排序（如 BM25 + 向量）取出 Top-K 片段。
4. **生成（Generation）**：把"检索到的片段 + 用户问题"拼进提示词，交给 LLM 生成答案，通常要求"只依据给定材料作答，材料不足请说明"。

进阶变体包括：带重排（Rerank）的两阶段检索、带知识图谱的 GraphRAG、带反思回搜的 Self-RAG、以及多路召回 + 融合（HyDE、混合排序）等。

## 实操步骤（最小可运行示例）

以下用 Python + 常见开源组件搭一条 60 行内的玩具 RAG，假设你已安装 `sentence-transformers`、`chromadb` 与任一 LLM SDK：

```python
import chromadb
from sentence_transformers import SentenceTransformer
from sentence_transformers.util import cos_sim

emb = SentenceTransformer("all-MiniLM-L6-v2")
client = chromadb.PersistentClient(path="./demo")
col = client.get_or_create_collection("docs")

# 1. 切块：按 300 字 + 50 字重叠简单切
def chunk(text, size=300, overlap=50):
    out, i = [], 0
    while i < len(text):
        out.append(text[i:i+size])
        i += size - overlap
    return out

docs = chunk("在此处粘贴你的语料……")
col.add(documents=docs, ids=[str(i) for i in range(len(docs))])

# 2. 检索
q = "Agnes 3.0 Flash 由哪家公司开发？"
qv = emb.encode(q)
cands = col.get(ids=None, include=["documents"])
scores = cos_sim(qv, emb.encode(cands["documents"]))
top = scores.argsort()[0][::-1][:3]

# 3. 生成
ctx = "\n".join(cands["documents"][i] for i in top)
prompt = (
    "仅依据以下材料作答，材料不足请明确说'材料不足'：\n"
    f"材料：{ctx}\n\n问题：{q}"
)
# answer = llm.generate(prompt)   # 接入你的 LLM SDK
```

要点：**提示词里必须显式约束"只依据材料作答"**，否则模型仍会走自由发挥的幻觉路线。

## 常见坑

- **切块太大丢细节，切块太小丢上下文**：经验上 256~512 token 起步，配合 10%~20% 重叠；长文档可加"层级切块"（段落 → 章节摘要 → 全文摘要）。
- **只靠向量召回不够**：专有名词、版本号、错误码在向量空间里往往不敏感，务必加 BM25 或关键词召回做混合排序。
- **Top-K 太大反而稀释**：把 10 条不相关片段塞进提示词，模型会"被带偏"，一般 3~5 条配合 Rerank 更好。
- **没有引用标注**：用户问"来源在哪"时答不上来，建议在生成提示里要求输出引用编号，并在前端展示对应片段。
- **嵌入模型不匹配语料语言**：中英混排时，优先选多语言或对应语言的嵌入模型，否则召回质量骤降。

## 小结

RAG 的价值不在模型，而在**"检索得准、上下文装得下、提示词约束得住"**这三件事。工程上建议按以下顺序迭代：先把单路向量召回打通 → 加入混合检索与重排 → 接入引用展示与评测（如用固定问答集跑 MRR / 命中率）→ 视效果决定是否需要 GraphRAG 或多轮反思。

## 参考

- 检索增强生成概念与流程：参见各大 LLM 厂商的 RAG 文档；截至 2026-10-18，本次检索未找到单一权威来源可引用，故此处仅作概念性描述。
- Chroma 向量数据库使用示例：https://docs.trychroma.com/（官方文档，未在本次会话中抓取正文）
- Sentence-Transformers 仓库：https://github.com/UKPLab/sentence-transformers
- Agnes-3.0-flash 模型来源（Sapiens AI）：本次会话的联网搜索未返回可核实的企业与模型页面，故正文不对其参数与基准数据做进一步断言。
