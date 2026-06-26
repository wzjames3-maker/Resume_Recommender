<!-- Phase: Phase 3.5 - Technical Selection (Frozen) -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-23 -->
<!-- Status: Frozen -->

# 技术选型决策

## 输入
- PRD.md（冻结版）— 22 条 FR + 26 条 NFR
- research-report.md（调研结论）— 8 个模块全部 ✅ 直接复用
- feasibility.md（可行性分析）— 1 人团队，Python 技术栈，1 个月工期
- design/ 目录（UI/UX 设计）— Streamlit 聊天界面 + 登录页

---

## 决策项 1：后端语言

### 候选
| 方案 | 优点 | 缺点 | 团队熟悉度 | 调研结论 |
|------|------|------|------------|----------|
| Python | RAG 生态最成熟；LangChain/LangGraph/Milvus/pymilvus 均为 Python SDK；单人团队一致性最高 | 高并发性能不如 Go/Rust | ★★★★★ | 全部调研方案均为 Python 生态 |
| Go | 高并发性能优秀；内存占用低 | RAG 生态弱；无 LangGraph SDK；需要自己封装 LLM 调用 | ★★☆☆☆ | 与调研结论冲突 |
| Java | 企业级成熟；Spring 生态丰富 | RAG 生态弱；开发效率低；Milvus Java SDK 质量不如 Python | ★★★☆☆ | 与调研结论冲突 |

### 决策：Python
### 理由：
1. RAG 生态全部在 Python（LangGraph / pymilvus / FlagEmbedding）
2. 1 人团队必须技术栈统一，避免多语言维护
3. 调研结论 8 个模块全部为 Python 生态
4. PRD 的 QPS >= 20 在 Python + FastAPI 异步下完全可达
### 风险：CPU 密集型操作（如大批量 Embedding）性能不如 Go
### 缓解：批量 Embedding 使用异步并发（asyncio）；生产环境可水平扩展

---

## 决策项 2：后端框架

### 候选
| 方案 | 优点 | 缺点 | 调研结论 |
|------|------|------|----------|
| FastAPI | 异步原生；Streaming SSE 支持好；Pydantic 数据验证（与 LangChain 一致）；自动生成 OpenAPI 文档；社区最活跃（85k+ Star） | 相比 Flask 生态略年轻 | ✅ 直接复用 |
| Flask | 生态成熟；简单易用 | 同步框架；Streaming 支持弱；需要额外扩展 | ❌ 不满足 Streaming 需求 |
| Django | 全栈框架；Admin 后台 | 太重；不适合 API-first 架构 | ❌ 过重 |

### 决策：FastAPI
### 理由：
1. PRD 要求 Streaming（NFR-004: 首 Token <= 800ms），FastAPI 原生 SSE 支持
2. Pydantic 与 LangChain StructuredOutput / LLM Schema 完全一致
3. 自动生成 OpenAPI 文档，减少 API 文档维护成本
4. 调研结论 ✅ 直接复用
### 风险：无
### 缓解：无

---

## 决策项 3：Agent 编排框架

### 候选
| 方案 | 优点 | 缺点 | 调研结论 |
|------|------|------|----------|
| LangGraph | Agent 编排最强；有状态多轮对话天然支持（StateGraph）；Tool Calling + Conditional Edge；Streaming 原生；与 LangChain 生态无缝集成 | 学习曲线（需理解 Graph/Node/Edge） | ✅ 直接复用 |
| LlamaIndex | RAG 检索能力极强；Node Parser 设计好 | Agent 编排弱；多轮对话状态管理不如 LangGraph | 📝 参考实现 |
| 自建状态机 | 完全可控 | 1 人团队开发成本过高；需要自己实现 Tool Calling、Persistence、Streaming | ❌ 不推荐 |

### 决策：LangGraph
### 理由：
1. PRD 要求 10 类 Intent + 多轮对话状态管理（FR-006, FR-007），LangGraph StateGraph 天然支持
2. Conditional Edge 可实现 Intent Router（根据 Intent 分发到不同 Workflow）
3. 内置 Persistence（对话历史持久化）和 Human-in-the-loop
4. Streaming 原生支持，与 FastAPI SSE 无缝对接
5. 调研结论 ✅ 直接复用
### 风险：LangGraph 版本迭代快，API 可能变化
### 缓解：锁定版本号；核心逻辑封装在自定义 Node 中，降低对 LangGraph API 的直接依赖

---

## 决策项 4：向量数据库

### 候选
| 方案 | 优点 | 缺点 | 调研结论 |
|------|------|------|----------|
| Milvus Standalone | 原生 Hybrid Search（Dense + Sparse）；BGE-M3 双模态直接写入；10 万级无压力；LangChain 官方集成（langchain-milvus）；33k+ Star | Docker 部署需要资源 | ✅ 直接复用 |
| Qdrant | Rust 实现，性能优秀 | Hybrid Search 支持弱于 Milvus；LangChain 集成非官方 | 📝 备选 |
| ChromaDB | 轻量级，适合原型 | 不支持原生 Hybrid Search；百万级性能不确定 | ❌ 不满足需求 |

### 决策：Milvus Standalone（Docker）+ 开发阶段可用 Milvus Lite
### 理由：
1. PRD 要求 Hybrid Retrieval（FR-002: Dense + Sparse），Milvus 原生支持
2. BGE-M3 输出 Dense + Sparse 双模态向量，Milvus 可直接存储和检索
3. langchain-milvus 官方集成，与 LangGraph 无缝对接
4. 开发阶段用 Milvus Lite（纯 Python，无需 Docker），降低开发环境配置成本
5. 调研结论 ✅ 直接复用
### 风险：Milvus Docker 部署需要 4GB+ 内存
### 缓解：开发阶段用 Milvus Lite 免 Docker；生产环境单机部署即可

---

## 决策项 5：Embedding 模型

### 候选
| 方案 | 优点 | 缺点 | 调研结论 |
|------|------|------|----------|
| BGE-M3（云端 API） | Dense + Sparse 双模态；中文效果最优（MTEB 榜单）；支持 8192 Token；与 Milvus Hybrid Search 天然匹配 | 依赖云端 API | ✅ 直接复用 |
| OpenAI text-embedding-3-large | 英文效果优秀；API 稳定 | 中文弱于 BGE-M3；不支持 Sparse 向量 | 📝 备选 |
| Jina Embeddings v3 | 多语言支持好 | 社区和集成不如 BGE-M3 | 📝 备选 |

### 决策：BGE-M3（云端 API）
### 理由：
1. Dense + Sparse 双模态是 Hybrid Retrieval 的基础，BGE-M3 原生支持
2. 中文简历场景下，中文效果是首要考量
3. 用户已确认使用云端 BGE-M3
4. 调研结论 ✅ 直接复用
### 风险：云端 API 延迟不稳定
### 缓解：设计 Embedding 缓存层；批量入库时使用异步并发

---

## 决策项 6：Reranker

### 候选
| 方案 | 优点 | 缺点 | 调研结论 |
|------|------|------|----------|
| BGE Reranker v2 M3（云端） | 与 BGE-M3 同系列；中文效果好；Cross-Encoder 精度高 | 依赖云端 API；无 GPU 本地部署不可行 | ✅ 直接复用 |
| LLM 直接 Rerank | 不需要额外模型 | 延迟高（N 次 LLM 调用）；成本高 | 📝 降级方案 |
| Cohere Rerank | 商业级质量 | 付费；中文效果不确定 | ❌ 不采用 |

### 决策：BGE Reranker v2 M3（云端 API）+ LLM 直接 Rerank 作为降级方案
### 理由：
1. 与 BGE-M3 同系列，API 调用方式一致
2. Cross-Encoder 排序精度高于 Bi-Encoder
3. 调研结论 ✅ 直接复用
### 风险：云端 API 不可用
### 缓解：降级为 LLM 直接 Rerank（DeepSeek 打分）；再降级为纯向量检索分数排序

---

## 决策项 7：LLM 推理

### 候选
| 方案 | 优点 | 缺点 | 调研结论 |
|------|------|------|----------|
| DeepSeek（主力） | 性价比高；中文能力强；OpenAI Compatible 接口 | API 稳定性不如 OpenAI | 用户已确认 |
| OpenAI GPT-4o（备选） | 效果最好；API 最稳定 | 成本高 | 用户已确认 |
| Qwen（阿里） | 中文能力强 | API 生态不如 OpenAI Compatible | 可选 |

### 决策：DeepSeek（主力）+ OpenAI（备选）
### 理由：
1. 用户已确认使用云端 DeepSeek + OpenAI Chat Completions 接口
2. 统一 OpenAI Compatible 接口，切换零成本
3. DeepSeek 性价比高，适合开发阶段大量调试
### 风险：DeepSeek API 高峰期延迟高
### 缓解：降级到 OpenAI；设计超时重试机制

---

## 决策项 8：数据存储

### 候选
| 方案 | 优点 | 缺点 | 调研结论 |
|------|------|------|----------|
| MongoDB | 文档模型天然适配简历（嵌套结构）；Dynamic Schema 适配不同格式简历；pymongo 成熟 | 事务支持弱于关系型 | ✅ 直接复用 |
| PostgreSQL + JSONB | 强一致性；事务支持好 | 简历嵌套结构用 JSONB 不如 MongoDB 自然 | 📝 备选 |

### 决策：MongoDB
### 理由：
1. 简历数据天然是嵌套文档（Education/Experience/Project/Skill 嵌套在 Resume 下）
2. Dynamic Schema 适配不同格式简历（PDF/DOCX/JSON 结构可能不同）
3. 调研结论 ✅ 直接复用
4. V1 场景不需要强事务（简历入库是幂等操作）
### 风险：无强事务
### 缓解：V1 场景不需要；如未来需要可引入 MongoDB 4.0+ 多文档事务

---

## 决策项 9：前端框架

### 候选
| 方案 | 优点 | 缺点 | 调研结论 |
|------|------|------|----------|
| Streamlit | 纯 Python；聊天界面原生支持（st.chat_message）；1 天完成；与后端技术栈一致 | 自定义 UI 能力有限；性能一般；会话管理需额外处理 | ✅ 直接复用 |
| Gradio | 纯 Python；Chatbot 组件原生 | 更适合 ML Demo，不够"产品化" | 📝 备选 |
| Next.js + Shadcn/UI | 最专业；完全自定义 | 需要前端开发能力；1 人团队负担大 | ❌ V1 不采用 |

### 决策：Streamlit
### 理由：
1. 1 人团队 + 1 个月工期，前端不是核心价值，用最低成本实现
2. st.chat_message / st.chat_input 原生支持聊天界面，无需自建
3. 纯 Python，与后端技术栈一致，降低维护成本
4. 调研结论 ✅ 直接复用
### 风险：Streamlit 会话管理（每个浏览器 Tab 独立状态）
### 缓解：通过 st.session_state + 后端 Conversation API 管理状态；V2 可升级到 Next.js

---

## 决策项 10：认证方案

### 候选
| 方案 | 优点 | 缺点 | 调研结论 |
|------|------|------|----------|
| JWT（PyJWT + FastAPI Security） | 无状态；与 FastAPI 原生集成；简单 | Token 无法主动失效 | ✅ 直接复用 |
| Session + Redis | 可主动失效 | 需要 Redis；有状态 | 增加复杂度 |
| OAuth 2.0 | 第三方登录 | V1 不需要第三方登录 | ❌ V1 不需要 |

### 决策：JWT（PyJWT + FastAPI Security）
### 理由：
1. PRD 要求 API 认证（FR-017），JWT 是 FastAPI 最标准的方案
2. 无状态，不需要额外存储
3. 与 RBAC（FR-018）配合简单（Token 中嵌入角色信息）
### 风险：Token 无法主动失效（用户登出后 Token 仍有效直到过期）
### 缓解：Token 有效期设为 24 小时；敏感操作要求二次验证（V2）

---

## 决策项 11：缓存方案

### 候选
| 方案 | 优点 | 缺点 |
|------|------|------|
| 不需要缓存 | 简化架构 | 重复 Embedding 调用有成本 |
| Redis | 高性能；支持多种数据结构 | 增加部署复杂度 |
| 本地内存缓存（cachetools） | 零部署成本 | 进程重启丢失；多进程不共享 |

### 决策：Redis（主缓存）+ cachetools（Embedding 热数据本地二级缓存）
### 理由：
1. 会话 TTL 管理、意图缓存、推荐理由缓存、Embedding 缓存均需要 Redis 的分布式缓存能力
2. cachetools 保留作为 Embedding 热数据的 L1 本地缓存，减少 Redis 网络往返
3. Redis 为后续消息队列（ARQ）提供基础设施，零额外部署成本
### 风险：增加 Redis 部署依赖
### 缓解：Docker Compose 一键部署；与 Milvus/MongoDB 统一容器化管理

---

## 决策项 12：部署方式

### 候选
| 方案 | 优点 | 缺点 |
|------|------|------|
| Docker Compose | 简单；适合单机部署 | 不支持自动扩缩容 |
| Kubernetes | 自动扩缩容；生产级 | 运维复杂；1 人团队负担大 |
| 裸机部署 | 最简单 | 环境不一致；难迁移 |

### 决策：Docker Compose（开发 + 生产）
### 理由：
1. 1 人团队 + 单机部署，Docker Compose 最简单
2. 所有组件（Milvus + MongoDB + FastAPI + Streamlit）可通过一个 docker-compose.yml 管理
3. 环境一致性：开发 = 生产
### 风险：不支持自动扩缩容
### 缓解：V1 单机足够；V2 如需扩展再迁移 K8s

---

## 决策项 13：消息队列

### 候选
| 方案 | 优点 | 缺点 | 与 FastAPI 契合度 |
|------|------|------|-------------------|
| ARQ | 原生 asyncio；轻量；基于 Redis；与 FastAPI 完美契合；Starlette 内核 | 生态不如 Celery 丰富；无内置监控面板 | ★★★★★ |
| Celery | 工业级标准；功能全面（监控 Flower、定时任务、重试策略）；社区最大 | 配置重；Worker 进程管理复杂；非原生 asyncio（需 celery[async]） | ★★★☆☆ |
| RQ | 简单易用；基于 Redis；学习曲线低 | 不支持 asyncio（需线程桥接）；功能简陋 | ★★☆☆☆ |

### 决策：ARQ（基于 Redis 的异步任务队列）
### 理由：
1. 简历解析是 I/O 密集型长任务（OCR+LLM+Embedding，10~30s），同步处理会阻塞 API
2. ARQ 原生 asyncio，与 FastAPI 契合度最高
3. 依赖已有 Redis 基础设施，零额外部署成本
4. 1 人团队需要最简方案
### 风险：无内置监控面板（不如 Celery Flower）
### 缓解：V1 通过结构化日志 + Redis CLI 监控；V2 如需可迁移到 Celery
### 引入方式：`pip install arq`

---

## 决策项 14：日志与监控

### 决策：结构化 JSON 日志（Python logging + json formatter）
### 理由：
1. PRD 要求 Audit Log（FR-020），结构化日志便于查询
2. V1 单机部署，日志写入文件即可
3. V2 可接入 ELK
### 引入方式：`pip install python-json-logger`

---

## 调研结论对技术选型的约束

| 调研结论 | 约束的技术决策 | 理由 |
|----------|---------------|------|
| LangGraph（Python） | 后端必须用 Python | LangGraph 仅有 Python SDK |
| Milvus + pymilvus（Python） | 后端必须用 Python | pymilvus 仅有 Python SDK |
| BGE-M3（云端 API，OpenAI Compatible） | 无语言约束 | HTTP API，任何语言可调用 |
| FastAPI + Pydantic | 数据验证层统一为 Pydantic | 与 LangChain StructuredOutput 一致 |
| Streamlit（Python） | 前端必须用 Python | Streamlit 仅有 Python 版本 |

**结论**：全部技术栈统一为 Python，无多语言维护负担。

---

## 最终技术栈全景

```
┌─────────────────────────────────────────────────────────────────┐
│                        层级                                      │
├─────────────────────────────────────────────────────────────────┤
│  Frontend       │ Streamlit                                      │
│  API            │ FastAPI + Uvicorn                               │
│  Auth           │ JWT (PyJWT + FastAPI Security)                  │
│  Agent          │ LangGraph (Intent Router + Tool Calling)        │
│  LLM            │ DeepSeek (主) / OpenAI (备) - OpenAI Compatible │
│  Embedding      │ BGE-M3 (云端 API) - Dense + Sparse              │
│  Reranker       │ BGE Reranker v2 M3 (云端 API)                   │
│  Vector DB      │ Milvus Standalone (Docker) / Milvus Lite (开发)  │
│  Resume Store   │ MongoDB (Docker)                                │
│  Cache          │ Redis (Docker) + cachetools (L1 本地缓存)         │
│  Logging        │ python-json-logger (结构化 JSON)                │
│  Task Queue     │ ARQ (基于 Redis)                                  │
│  Deployment     │ Docker Compose                                  │
│  Language       │ Python 3.11+                                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Python 依赖清单（核心）

```
# Agent 编排
langgraph>=0.4
langchain-core>=0.3
langchain-openai>=0.3

# Web 框架
fastapi>=0.115
uvicorn[standard]>=0.34
pydantic>=2.0

# 向量数据库
pymilvus>=2.4.6  # 最低 2.4.6（SPARSE_FLOAT_VECTOR 完整支持），推荐 2.5+

# 数据存储
pymongo>=4.9

# 认证
PyJWT>=2.9
passlib[bcrypt]>=1.7

# 文档解析
PyPDF2>=3.0
python-docx>=1.1
pdfplumber>=0.11
Pillow>=10.0  # DeepSeek-OCR 图片处理

# 前端
streamlit>=1.40

# 缓存 & 队列
cachetools>=5.5
redis>=5.0

# 异步任务队列
arq>=0.26

# 日志
python-json-logger>=3.2

# 工具
python-multipart>=0.0.18
httpx>=0.28
```

---

## 决策项 15：异步任务队列

### 候选
| 方案 | 优点 | 缺点 | 与 FastAPI 契合度 |
|------|------|------|-------------------|
| ARQ | 原生 asyncio；轻量；基于 Redis；与 FastAPI 完美契合；Starlette 内核 | 生态不如 Celery 丰富；无内置监控面板 | ★★★★★ |
| Celery | 工业级标准；功能全面（监控 Flower、定时任务、重试策略）；社区最大 | 配置重；Worker 进程管理复杂；非原生 asyncio（需 celery[async]） | ★★★☆☆ |
| RQ | 简单易用；基于 Redis；学习曲线低 | 不支持 asyncio（需线程桥接）；功能简陋 | ★★☆☆☆ |

### 决策：ARQ
### 理由：
1. 1 人团队 + Python asyncio 技术栈，ARQ 是唯一原生 asyncio 的选择
2. 简历解析任务（OCR → LLM → Embedding → Milvus）是 I/O 密集型，asyncio 的并发模型最适合
3. 依赖已有 Redis 基础设施，零额外部署成本
4. 代码量最小（一个 async 函数就是一个 Worker Task）
5. 与 FastAPI 的 BackgroundTasks 概念一致，但基于 Redis 持久化（进程重启不丢任务）
### 风险：无内置监控面板（不如 Celery Flower）
### 缓解：V1 通过结构化日志 + Redis CLI 监控；V2 如需可迁移到 Celery
### 引入方式：`pip install arq`
