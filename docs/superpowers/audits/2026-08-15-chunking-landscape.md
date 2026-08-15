# GitHub 切片（Chunking）方案调研

> 日期：2026-08-15
> 方法：GitHub API 仓库搜索 + 关键仓库 README/实现研读（2026-08 实测抓取）
> 目的：验证「简历语义索引」的切片设计是否与业界路线一致，并吸收可借鉴方案。

---

## 1. 业界方案全景（5 级分类，LangChain 官方教程口径）

| 级别 | 方案 | GitHub 代表 | 说明 |
|---|---|---|---|
| L1 | 字符定长切分 | 各种基础实现 | 性能好，语义破坏大 |
| L2 | 递归字符切分 | LangChain RecursiveCharacterTextSplitter | 按分隔符优先级递归 |
| L3 | **文档特定切分** | Unstructured-IO/unstructured（★15.3k）、infiniflow/ragflow deepdoc（★88.5k） | 解析文档结构（标题/表格/列表）再切 |
| L4 | **语义切分（嵌入法）** | LangChain SemanticChunker（实验包） | 句子 embedding 距离阈值断点，无 LLM |
| L5 | **Agentic 切分（LLM）** | FullStackRetrieval-com/RetrievalTutorials（★1.5k） | agent 循环切分，最泛化，token 贵 |
| Bonus | 派生表示索引 | 同 L5 教程 | title 摘要/问题索引等辅助向量 |

## 2. 重点方案详情

### 2.1 LLM 切分（与我们的路线同类）

| 仓库 | 方法 | 关键细节 |
|---|---|---|
| zeroentropy-ai/zchunk（★265） | Llama-70B prompt 切分 | 模型输出**每个位置的切分层级 + logprobs**，按概率决定切点；与 NaiveChunk/SemanticChunk 对比基准 |
| brandonstarxel/chunking_evaluation（★505，Chroma 团队） | **LLMChunker** + ClusterSemanticChunker | LLM 直接输出 chunk 列表；语义聚类切分；提供 **IoU/recall** 评测框架 |
| FullStackRetrieval-com/RetrievalTutorials | L5 Agentic 切分 | agent 循环：读文本→找自然断点→切分，proposition 列表输出 |
| ekimetrics/adaptive-chunking（★376，LREC 2026） | **多策略自动选择** | 关键实证：**LLM regex (GPT) 89.80 分排第 2**（自适应 91.07），语义嵌入法仅 76.49；**Block Integrity（结构块完整）是核心指标** |

### 2.2 结构感知切分（L3，工业级）

- **RAGFlow deepdoc**：文档解析引擎（parser/ 下 pdf/docx/txt 等），识别标题层级/表格/段落块后再切，强调**结构保真**——与我们的「条目级」同源。
- **Unstructured**：把文档解析为元素流（Title/NarrativeText/ListItem/Table），元素级组合成 chunk。

### 2.3 神经模型切分（无 API 成本的 LLM 替代）

- **mirth/chonky**（★419）：**微调 ModernBERT-base 预测切分点**，本地运行、零 API 成本；配 MarkupRemover 先剥标记。长期若 LLM 成本敏感，可自微调一个中文简历切点模型（需标注数据）。

### 2.4 Late Chunking（向量化阶段的替代思路）

- **jina-ai/late-chunking**（★536）：**先整篇过长上下文 embedding 模型，再在 token 层池化出 chunk 向量**——从根上解决"先切后嵌"的上下文丢失（切分不再损失语义）。前提：embedding 模型支持长输入（如 jina v2 8K token；我们用的 bge-large-zh 仅 512 token，**当前不可用**，换模型后可评估）。

### 2.5 反例（不可取）

- **Proposition chunking**（Dense X Retrieval）：LLM 把段落**重写**成原子命题再索引——检索质量好但破坏原文保真，HR 引用场景不可用，印证我们的"禁止改写"硬约束。

## 3. 对我们的设计修正

| # | 借鉴点 | 来源 | 动作 |
|---|---|---|---|
| 1 | LLM 切分是**公认最优梯队**（adaptive 实证 LLM 第 2、zChunk、L5 agentic） | 2.1 | 维持 LLM 边界标注主干 ✓ |
| 2 | **Block Integrity** 是切分质量核心指标 | adaptive-chunking | 条目级粒度策略获得外部背书 ✓ |
| 3 | 切分评测框架：**IoU / recall** + 5 项内在指标（SC/ICC/DCC/BI/RC） | Chroma chunking_evaluation；adaptive | 直接借用于我们的异质评测集，省去自造轮子 |
| 4 | 切分点**打分而非直接切**（logprobs）可做置信度 | zchunk | 低置信切点触发人工复核/降级策略 |
| 5 | 长期成本优化：微调小模型预测切点 | chonky | 标注 500~1000 份真实简历后评估；不是现在 |
| 6 | 换长上下文 embedding 后评估 Late Chunking | jina late-chunking | 记录为候选演进项，当前 bge 512 token 不支持 |

## 4. 与业界对齐后的最终形态

```
L3 结构保真（条目级粒度，Block Integrity）
  + L5 LLM 边界标注（主干，行号 JSON，禁止改写）
  + zChunk 式置信度（可选）
  + 规则降级（LLM 失败/超短文本）
  → embedding 召回 → reranker 精排 → tsvector 兜底
  → Chroma IoU/recall + adaptive 5 指标评测
```

## 5. 参考链接

- https://github.com/FullStackRetrieval-com/RetrievalTutorials （5-level chunking）
- https://github.com/brandonstarxel/chunking_evaluation （Chroma 评测 + LLMChunker）
- https://github.com/ekimetrics/adaptive-chunking （LREC 2026 实证）
- https://github.com/zeroentropy-ai/zchunk （Llama-70B logprobs 切分）
- https://github.com/mirth/chonky （微调神经切分）
- https://github.com/infiniflow/ragflow （deepdoc 结构解析）
- https://github.com/Unstructured-IO/unstructured （文档元素化）
- https://github.com/jina-ai/late-chunking （late chunking）
- https://github.com/isaacus-dev/semchunk （LLM 调用式语义 chunk 库）
