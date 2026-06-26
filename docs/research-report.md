<!-- Phase: Phase 3.1 - Open Source Ecosystem Research -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-23 -->

# 开源生态调研报告

## 调研范围

基于 PRD.md 中的功能需求，调研以下 8 个模块的开源方案：

| 模块 | 对应 PRD 需求 |
|------|---------------|
| RAG 编排框架 | FR-001, FR-006, FR-007, FR-015, FR-016 |
| 简历解析 | FR-010, FR-011, FR-012 |
| 向量数据库 | FR-002, FR-003 |
| Embedding 模型 | FR-002 |
| Reranker | FR-004 |
| Web 框架 | FR-015, FR-017, FR-020 |
| 前端 UI | UC-001 ~ UC-008 |
| 数据存储 | FR-010, FR-019 |

---

## 模块 1：RAG 编排框架（FR-001, FR-006, FR-007, FR-015, FR-016）

### 搜索关键词
"langchain langgraph RAG agent", "llamaindex RAG", "RAG orchestration python"

### 候选方案

#### 方案 A: LangGraph（langchain-ai/langgraph）
- GitHub: https://github.com/langchain-ai/langgraph
- Star: 10k+ | 最近 commit: 2026-06-22（极度活跃）
- 许可证: MIT
- 功能匹配度: ★★★★★
  - 天然支持有状态多轮对话（State Graph）
  - Tool Calling + Conditional Edge 可实现 Intent Router
  - 原生支持 Streaming
  - 与 LangChain 生态无缝集成
  - 内置 Human-in-the-loop、Persistence、Time Travel
- 代码质量: LangChain 官方出品，文档详尽，测试完善
- 维护活跃度: 每日 commit，Issue 响应快
- 社区规模: 10k+ Star，大量生产案例
- 依赖复杂度: 中（依赖 langchain-core）
- 学习成本: 中（需理解 Graph/Node/Edge 概念，但文档好）
- 性能: 满足 NFR（P95 <=3s 取决于 LLM 调用，框架本身开销极小）
- 决策: ✅ 直接复用
- 引入方式: `pip install langgraph`
- 备注: 是本项目最核心的框架选择，Agent Router + Conversation Memory + Tool Calling 均基于 LangGraph 实现

#### 方案 B: LlamaIndex
- GitHub: https://github.com/run-llama/llama_index
- Star: 40k+ | 极度活跃
- 许可证: MIT
- 功能匹配度: ★★★★☆
  - RAG 检索能力极强（多种 Retriever、Node Parser、Response Synthesizer）
  - 但 Agent 编排能力弱于 LangGraph
  - 多轮对话状态管理不如 LangGraph 原生
- 决策: 📝 参考实现
- 备注: 可参考其 Node Parser（语义切分）和 Retriever 设计

#### 方案 C: 自建 RAG Pipeline
- 决策: ❌ 不推荐
- 理由: 1 人团队 + 1 个月工期，从零搭建 Agent 编排 + 状态管理 + Tool Calling 成本过高

### 最终决策
**选择 LangGraph**
理由: Agent 编排能力最强，多轮对话状态管理天然支持，Streaming 原生支持，与 LangChain 生态无缝集成。LlamaIndex 的检索能力可作为参考，但编排层用 LangGraph。

---

## 模块 2：简历解析（FR-010, FR-011, FR-012）

### 搜索关键词
"resume parser python", "PDF extraction structured", "unstructured document parser"

### 候选方案

#### 方案 A: PyPDF2/pdfplumber + python-docx + DeepSeek-OCR + LLM 结构化提取（自研方案）
- 功能匹配度: ★★★★★
  - PDF 解析: PyPDF2 或 pdfplumber（pdfplumber 对表格支持更好）
  - DOCX 解析: python-docx
  - 图片 OCR: DeepSeek-OCR（deepseek-ai/DeepSeek-OCR），云端 API，中文识别效果好
  - 结构化提取: LLM（DeepSeek）+ Pydantic Schema
  - 语义段落切分: LLM 辅助识别段落边界
- 优势:
  - 完全可控，不受第三方 API 限制
  - LLM 提取准确率高（尤其是中文简历）
  - Pydantic Schema 保证输出格式稳定
- 劣势:
  - 需要设计 Prompt
  - LLM 调用有成本
- 决策: ✅ 直接复用（核心方案）
- 引入方式: `pip install PyPDF2 python-docx pydantic`
- 备注: pdfplumber 对复杂排版支持更好，建议优先评估

#### 方案 B: Unstructured.io
- GitHub: unstructured-io/unstructured
- Star: 10k+ | 极度活跃
- 许可证: Apache 2.0
- 功能匹配度: ★★★★☆
  - 支持 PDF/DOCX/HTML/Image 等多种格式
  - 自动检测文档结构（标题/段落/表格）
  - 有云端 API 和本地部署两种模式
- 优势: 一站式解析，格式覆盖广
- 劣势: 中文简历支持不确定；本地部署依赖较多（Tesseract OCR 等）；黑盒程度高
- 决策: 📝 参考实现
- 备注: 可作为 V2 的升级选项，V1 先用自研方案验证效果

#### 方案 C: LlamaParse
- LlamaIndex 官方文档解析 API
- 功能匹配度: ★★★★☆
- 优势: 云端 API，解析质量高
- 劣势: 付费；依赖外部服务；中文效果未知
- 决策: ❌ 不采用（V1 避免外部付费依赖）

#### 方案 D: ResumeParserAI（参考项目）
- GitHub: itsrahulap/ResumeParserAI
- 描述: Streamlit + Gemini 解析 PDF 简历
- 决策: 📝 参考实现
- 备注: 可参考其 Prompt 设计和 Pydantic Schema 结构

### 最终决策
**选择 PyPDF2/pdfplumber + python-docx + LLM 结构化提取**
理由: 完全可控，LLM 提取准确率高，中文简历支持好，无外部付费依赖。pdfplumber 对复杂排版支持更好，优先评估。

---

## 模块 3：向量数据库（FR-002, FR-003）

### 搜索关键词
"milvus vector database", "qdrant vector search", "chromadb python"

### 候选方案

#### 方案 A: Milvus Standalone
- GitHub: https://github.com/milvus-io/milvus
- Star: 33k+ | 最近 commit: 2026-06-23（极度活跃）
- 许可证: Apache 2.0
- Python SDK: pymilvus（Star: 2.5k+，活跃）
- LangChain 集成: langchain-milvus（官方维护）
- 功能匹配度: ★★★★★
  - 原生支持 Hybrid Search（Dense + Sparse）
  - BGE-M3 的 Dense + Sparse 双模态输出可直接写入
  - 支持 Metadata Filter（表达式过滤）
  - 10 万级数据单机无压力，可扩展到百万级
  - 支持 Dynamic Schema
- 代码质量: 企业级，CNCF 毕业项目
- 维护活跃度: 每日 commit，版本迭代快
- 社区规模: 33k+ Star，大量生产案例
- 性能: 百万级 768 维向量检索 P99 < 100ms
- 决策: ✅ 直接复用
- 引入方式: `pip install pymilvus` + Docker 部署 Milvus Standalone
- 备注: 有 Milvus Lite（纯 Python，无需 Docker），开发阶段可用 Lite，生产用 Standalone

#### 方案 B: Qdrant
- GitHub: qdrant/qdrant
- Star: 23k+ | 活跃
- 许可证: Apache 2.0
- 功能匹配度: ★★★★☆
  - 性能优秀，Rust 实现
  - 但 Hybrid Search（Dense + Sparse）支持弱于 Milvus
  - LangChain 集成有，但不如 langchain-milvus 官方
- 决策: 📝 备选方案
- 备注: 如果 Milvus Docker 部署遇到问题，Qdrant 是最佳替代

#### 方案 C: ChromaDB
- GitHub: chroma-core/chroma
- Star: 18k+ | 活跃
- 功能匹配度: ★★★☆☆
  - 轻量级，适合原型开发
  - 但 Hybrid Search 不原生支持
  - 百万级数据性能不确定
- 决策: ❌ 不采用（不满足 Hybrid Search 需求）

### 最终决策
**选择 Milvus Standalone**
理由: 原生 Hybrid Search，BGE-M3 双模态直接写入，LangChain 官方集成，33k+ Star，企业级质量。开发阶段可用 Milvus Lite 免 Docker。

---

## 模块 4：Embedding 模型（FR-002）

### 搜索关键词
"BGE M3 embedding", "bge-m3 dense sparse", "FlagEmbedding BAAI"

### 候选方案

#### 方案 A: BGE-M3（BAAI/bge-m3）
- 来源: BAAI（北京智源研究院）
- 模型: BAAI/bge-m3
- 功能匹配度: ★★★★★
  - 支持 Dense + Sparse + ColBERT 三种检索模式
  - 中文效果优秀（MTEB 中文榜单前列）
  - 支持多语言（100+ 语言）
  - 最大支持 8192 Token 输入
  - Sparse 向量可直接用于 Milvus Hybrid Search
- 部署方式:
  - 云端 API: 通过硅基流动、OpenAI Compatible 等平台调用
  - 本地部署: 需要 GPU（用户确认使用云端）
- 决策: ✅ 直接复用
- 引入方式: 云端 API 调用（OpenAI Compatible 接口）
- 备注: Dense + Sparse 双模态是本项目 Hybrid Retrieval 的基础

#### 方案 B: OpenAI text-embedding-3-large
- 功能匹配度: ★★★★☆
  - 英文效果优秀
  - 但中文效果弱于 BGE-M3
  - 不支持 Sparse 向量（需额外 BM25）
- 决策: 📝 备选方案
- 备注: 如果 BGE-M3 云端 API 不稳定，可降级到 OpenAI

#### 方案 C: Jina Embeddings v3
- 功能匹配度: ★★★★☆
  - 多语言支持好
  - 支持 Late Interaction
  - 但社区和 LangChain 集成不如 BGE-M3
- 决策: 📝 备选方案

### 最终决策
**选择 BGE-M3（云端 API）**
理由: Dense + Sparse 双模态天然适配 Milvus Hybrid Search，中文效果最优，用户已确认使用云端 BGE-M3。

---

## 模块 5：Reranker（FR-004）

### 搜索关键词
"BGE reranker", "cross-encoder rerank", "LLM rerank"

### 候选方案

#### 方案 A: BGE Reranker（BAAI/bge-reranker-v2-m3）
- 来源: BAAI
- 功能匹配度: ★★★★★
  - 与 BGE-M3 同系列，中文效果好
  - Cross-Encoder 架构，排序精度高
  - 支持多语言
- 部署方式:
  - 云端 API: 通过硅基流动等平台
  - 本地部署: 需要 GPU
- 决策: ✅ 直接复用
- 引入方式: 云端 API 调用
- 备注: 与 BGE-M3 同系列，API 调用方式一致

#### 方案 B: LLM 直接 Rerank
- 方式: 用 DeepSeek/GPT 对候选简历逐一打分
- 优势: 不需要额外模型
- 劣势: 延迟高（N 次 LLM 调用）、成本高
- 决策: 📝 参考实现
- 备注: 可作为 BGE Reranker 不可用时的降级方案

#### 方案 C: Cohere Rerank API
- 功能匹配度: ★★★★☆
- 优势: 商业级质量
- 劣势: 付费 API，中文效果不确定
- 决策: ❌ 不采用

### 最终决策
**选择 BGE Reranker v2 M3（云端 API）**
理由: 与 BGE-M3 同系列，中文效果好，API 调用方式一致。LLM 直接 Rerank 作为降级方案。

---

## 模块 6：Web 框架（FR-015, FR-017, FR-020）

### 候选方案

#### 方案 A: FastAPI
- GitHub: https://github.com/fastapi/fastapi
- Star: 85k+ | 极度活跃
- 许可证: MIT
- 功能匹配度: ★★★★★
  - Python 生态最流行的异步 Web 框架
  - 原生支持 Streaming（SSE）
  - 原生支持 OpenAPI/Swagger 文档
  - Pydantic 数据验证（与 LangChain/LLM Schema 一致）
  - JWT 认证成熟（fastapi.security）
  - 中间件支持（Audit Log）
- 决策: ✅ 直接复用
- 引入方式: `pip install fastapi uvicorn`

#### 方案 B: Flask
- 功能匹配度: ★★★☆☆
  - 同步框架，Streaming 支持弱
  - 异步支持不如 FastAPI
- 决策: ❌ 不采用

### 最终决策
**选择 FastAPI**
理由: 异步原生、Streaming 支持好、Pydantic 一致、文档自动生成、社区最活跃。

---

## 模块 7：前端 UI（UC-001 ~ UC-008）

### 候选方案

#### 方案 A: Streamlit
- GitHub: https://github.com/streamlit/streamlit
- Star: 40k+ | 极度活跃
- 许可证: Apache 2.0
- 功能匹配度: ★★★★☆
  - 纯 Python 开发前端，无需 JS
  - st.chat_message / st.chat_input 原生支持聊天界面
  - 支持 Streaming
  - 开发效率极高（1 天可完成）
- 优势: 1 人团队最低成本
- 劣势: 自定义 UI 能力有限；性能一般（不适合高并发）；会话管理需额外处理
- 决策: ✅ 直接复用（V1）
- 引入方式: `pip install streamlit`

#### 方案 B: Gradio
- GitHub: https://github.com/gradio-app/gradio
- Star: 38k+ | 极度活跃
- 功能匹配度: ★★★★☆
  - 类似 Streamlit，纯 Python
  - Chatbot 组件原生支持
  - 更适合 ML Demo 场景
- 决策: 📝 备选方案

#### 方案 C: Next.js + Shadcn/UI
- 功能匹配度: ★★★★★
  - 最专业的前端方案
  - 完全自定义 UI
- 劣势: 需要前端开发能力，1 人团队负担大
- 决策: ❌ V1 不采用（V2 升级选项）

### 最终决策
**选择 Streamlit（V1）**
理由: 纯 Python、1 天完成、聊天界面原生支持、Streaming 支持。V2 可升级到 Next.js。

---

## 模块 8：数据存储（FR-010, FR-019）

### 候选方案

#### 方案 A: MongoDB
- 功能匹配度: ★★★★★
  - 文档模型天然适配简历（嵌套结构）
  - Dynamic Schema 适配不同格式简历
  - Python SDK（pymongo）成熟
  - LangChain 集成有 langchain-mongodb
- 决策: ✅ 直接复用
- 引入方式: `pip install pymongo` + Docker 部署 MongoDB

#### 方案 B: PostgreSQL + JSONB
- 功能匹配度: ★★★★☆
  - 关系型 + JSONB 兼顾结构化和灵活性
  - 但简历嵌套结构用 MongoDB 更自然
- 决策: 📝 备选方案

### 最终决策
**选择 MongoDB**
理由: 文档模型天然适配简历结构，Dynamic Schema 处理不同格式简历，Docker 部署简单。

---

## 调研结论汇总

| 模块 | 决策 | 选定方案 | 引入方式 | 理由 |
|------|------|----------|----------|------|
| RAG 编排 | ✅ 直接复用 | LangGraph | `pip install langgraph` | Agent 编排最强，多轮对话天然支持 |
| 简历解析 | ✅ 直接复用 | PyPDF2/pdfplumber + python-docx + LLM | `pip install PyPDF2 python-docx` | 完全可控，LLM 提取准确率高 |
| 向量数据库 | ✅ 直接复用 | Milvus Standalone | `pip install pymilvus` + Docker | 原生 Hybrid Search，BGE-M3 直接写入 |
| Embedding | ✅ 直接复用 | BGE-M3（云端 API） | OpenAI Compatible API | Dense+Sparse 双模态，中文最优 |
| Reranker | ✅ 直接复用 | BGE Reranker v2 M3（云端 API） | 云端 API | 与 BGE-M3 同系列，中文效果好 |
| Web 框架 | ✅ 直接复用 | FastAPI | `pip install fastapi uvicorn` | 异步原生，Streaming 支持好 |
| 前端 UI | ✅ 直接复用 | Streamlit | `pip install streamlit` | 纯 Python，1 天完成 |
| 数据存储 | ✅ 直接复用 | MongoDB | `pip install pymongo` + Docker | 文档模型适配简历结构 |

---

## 技术栈全景

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend                                 │
│                      Streamlit (Python)                         │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP / SSE
                             v
┌─────────────────────────────────────────────────────────────────┐
│                        API Layer                                │
│                   FastAPI + Uvicorn                              │
│              (JWT Auth + Audit Log + Streaming)                  │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             v
┌─────────────────────────────────────────────────────────────────┐
│                    Agent Orchestration                           │
│                      LangGraph                                  │
│         (Intent Router + Tool Calling + State Memory)           │
└────────────────────────────┬────────────────────────────────────┘
                             │
              ┌──────────────┼──────────────┐
              v              v              v
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  Resume      │  │  Retrieval   │  │  Reranker    │
│  Parser      │  │  Engine      │  │  BGE Reranker│
│  PDF/DOCX    │  │  Milvus      │  │  v2 M3       │
│  + LLM       │  │  Hybrid      │  │  (云端)       │
│  提取         │  │  Search      │  │              │
└──────────────┘  └──────────────┘  └──────────────┘
       │                │
       v                v
┌──────────────┐  ┌──────────────┐
│  MongoDB     │  │  Milvus      │
│  Resume Store│  │  Vector DB   │
│  (结构化存储)  │  │  (Dense+     │
│              │  │   Sparse)    │
└──────────────┘  └──────────────┘
                          │
                          v
                   ┌──────────────┐
                   │  BGE-M3      │
                   │  Embedding   │
                   │  (云端 API)   │
                   └──────────────┘
```

---

## 对后续环节的影响

### 技术选型约束
- 前端必须用 Python（Streamlit），不需要 Node.js
- 后端必须用 Python（FastAPI + LangGraph）
- 向量库必须支持 Hybrid Search（Milvus）
- Embedding 必须支持 Dense + Sparse（BGE-M3）

### Spec 编写
- 标记为 ✅ 直接复用 的模块不需要写完整 Spec，直接引用库文档
- 需要写 Spec 的自定义部分:
  - Intent Router（LangGraph State 设计）
  - Resume Parser（LLM Prompt + Pydantic Schema）
  - Conversation Memory（状态合并逻辑）
  - Recommendation Engine（排序权重 + Reason 生成）

### 任务拆分
- ✅ 直接复用的模块任务量小（集成配置为主）
- 自定义模块任务量大（Intent Router、Parser、推荐引擎）

### 开发量估算
- 复用比例: ~60%（框架/库/模型均为成熟方案）
- 自定义比例: ~40%（业务逻辑、Prompt 设计、状态管理）
- 这个比例对 1 人 + 1 个月的工期是可行的

