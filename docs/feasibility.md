<!-- Phase: Phase 2 - Feasibility Analysis -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-23 -->
<!-- Context: 1人团队，Python 技术栈，本地开发，1个月工期 -->

# 可行性分析

## 一、技术可行性

### 1.1 总体评估

| 维度 | 评估 | 风险 | 缓解措施 |
|------|------|------|----------|
| 技术栈能力 | Python 是 RAG 生态最成熟的语言，LangChain / LlamaIndex / Milvus 均有 Python SDK | 低 | - |
| Embedding 模型 | 使用云端 BGE-M3，无需本地 GPU，API 调用即可 | 低 | - |
| LLM 推理 | 使用云端 DeepSeek / OpenAI Chat Completions 接口，无需自部署 | 低 | - |
| 向量数据库 | Milvus 有 Docker 镜像，本地单机可跑，Python SDK 成熟 | 低 | - |
| 简历解析 | PDF/DOCX 解析库成熟（PyPDF2/python-docx），OCR 需额外依赖 | 中 | POC 验证 |
| 多轮对话 | LangGraph / 自建 Conversation Memory，需设计状态管理 | 中 | 需详细设计 |
| 性能 | 单用户/低并发场景，P95 <=3s 可达 | 低 | - |
| 数据量 | 10 万份简历单机 Milvus 可承载，无需分布式 | 低 | - |

### 1.2 逐模块可行性

#### 模块 1: Resume Parser

| 能力 | 可行性 | 说明 |
|------|--------|------|
| PDF 解析 | 可行 | PyPDF2 / pdfplumber，成熟稳定 |
| DOCX 解析 | 可行 | python-docx，成熟稳定 |
| 图片 OCR | 可行 | 使用 DeepSeek-OCR（deepseek-ai/DeepSeek-OCR），云端 API 调用，中文识别效果好，无需本地 GPU |
| JSON 导入 | 可行 | 直接结构化映射 |
| 语义段落切分 | 有条件可行 | 需设计切分规则（教育/工作/项目/技能），可借助 LLM 辅助提取 |
| 结构化提取 | 有条件可行 | LLM 提取 + Pydantic Schema 验证，需 POC 验证准确率 |

**关键风险**：简历格式多样，非标简历的解析准确率是最大不确定性。

#### 模块 2: Resume Store（数据存储）

| 能力 | 可行性 | 说明 |
|------|--------|------|
| 结构化存储 | 可行 | MongoDB（文档模型天然适配简历）或 PostgreSQL（JSONB） |
| PII 加密 | 可行 | Python cryptography 库，AES-256 加密 |
| 元数据索引 | 可行 | 支持按 city/education/experience 等字段快速过滤 |

#### 模块 3: Vector Index（向量索引）

| 能力 | 可行性 | 说明 |
|------|--------|------|
| Embedding 生成 | 可行 | 云端 BGE-M3 API，支持 Dense + Sparse 双模态 |
| 向量存储 | 可行 | Milvus Lite（本地）或 Milvus Standalone（Docker），10 万级无压力 |
| Hybrid Retrieval | 可行 | Milvus 2.4+ 原生支持 Hybrid Search（Dense + Sparse） |
| 10 万扩展到 100 万 | 可行 | Milvus Standalone 可承载百万级，未来可迁移 Milvus Cluster |

#### 模块 4: Agent Router（意图路由）

| 能力 | 可行性 | 说明 |
|------|--------|------|
| Intent 识别 | 可行 | LLM Function Calling / Structured Output，10 类 Intent 可覆盖 |
| Slot 提取 | 可行 | LLM + Pydantic Schema，已有成熟方案 |
| 上下文管理 | 有条件可行 | 多轮对话状态合并逻辑需详细设计，是复杂度最高的部分 |
| Fallback | 可行 | 置信度阈值 + 引导性回复 |

#### 模块 5: Recommendation Engine（推荐引擎）

| 能力 | 可行性 | 说明 |
|------|--------|------|
| Metadata Filter | 可行 | Milvus 过滤表达式 + Elasticsearch Query DSL |
| LLM Rerank | 可行 | BGE Reranker 或 LLM 直接打分，需 POC 对比效果 |
| 推荐理由生成 | 可行 | LLM Structured Output，Prompt 设计是关键 |
| 权重可配置 | 可行 | 配置文件 + 运行时参数覆盖 |

#### 模块 6: API 层

| 能力 | 可行性 | 说明 |
|------|--------|------|
| RESTful API | 可行 | FastAPI，Python 生态最流行的 Web 框架 |
| Streaming | 可行 | FastAPI + SSE / WebSocket，原生支持 |
| 认证 | 可行 | JWT + FastAPI Security，成熟方案 |
| Audit Log | 可行 | 中间件 + 结构化日志 |

---

## 二、资源可行性

### 2.1 人力

| 角色 | 人数 | 技能要求 | 说明 |
|------|------|----------|------|
| 全栈开发 | 1 | Python + RAG + 前端基础 | 单人负责全部开发 |
| 测试 | 0 | - | 开发自测，无独立测试资源 |

**风险**：单人开发，知识盲区（如前端 UI、运维部署）可能成为瓶颈。

### 2.2 时间

总工期：**1 个月（约 20 个工作日）**

| 阶段 | 预估工期 | 说明 |
|------|----------|------|
| Spec 编写（Phase 4-5） | 3 天 | 8 层 Spec，可借助 Agent 加速 |
| 基础设施搭建 | 2 天 | Milvus + MongoDB + FastAPI 项目脚手架 |
| Resume Parser | 3 天 | PDF/DOCX 解析 + LLM 结构化提取 |
| Vector Index + Embedding | 2 天 | BGE-M3 集成 + Milvus 索引 |
| Agent Router + Intent | 3 天 | 意图识别 + Slot 提取 + 多轮对话 |
| Recommendation Engine | 3 天 | Hybrid Retrieval + Rerank + Reason 生成 |
| API + Streaming | 2 天 | FastAPI 接口 + SSE |
| 前端（极简） | 1 天 | 聊天界面，可选 Streamlit/Gradio |
| 联调 + 测试 | 1 天 | 端到端验证 |
| **合计** | **20 天** | - |

**风险**：时间紧凑，几乎没有 Buffer。任何模块延期都会影响整体进度。

### 2.3 基础设施

| 资源 | 现状 | 需要 | 成本 |
|------|------|------|------|
| 开发机器 | 本地 PC | - | 0 |
| GPU | 无本地 GPU | 使用云端 Embedding API | 按量付费，低 |
| Milvus | 无 | Docker 本地部署 | 0 |
| MongoDB | 无 | Docker 本地部署 | 0 |
| Elasticsearch | 无 | Docker 本地部署（可选） | 0 |
| LLM API | 云端 DeepSeek / OpenAI | - | 按 Token 付费 |
| BGE-M3 API | 云端 | - | 按调用付费 |

**月度运营成本估算**（开发 + 测试阶段）：

| 项目 | 估算 |
|------|------|
| LLM API（DeepSeek） | ~50-100 元/月（开发调试） |
| BGE-M3 Embedding API | ~20-50 元/月 |
| 云服务器（如需） | 0（本地开发） |
| **合计** | **~100-200 元/月** |

---

## 三、风险清单

| ID | 风险 | 概率 | 影响 | 缓解措施 |
|----|------|------|------|----------|
| R-001 | 简历格式多样，非标简历解析准确率低 | 高 | 高 | POC-001: 测试 5 种不同格式简历的解析效果；设计降级策略（解析失败时保留原文） |
| R-002 | 多轮对话状态合并逻辑复杂 | 中 | 高 | POC-002: 实现 recruitment.refine 的增量合并 + 条件覆盖 + 重置逻辑；设计状态机 |
| R-003 | LLM 意图识别不稳定（尤其是 refine vs search 边界） | 中 | 中 | POC-003: 构造 50 条测试用例评估意图识别准确率；设计 few-shot prompt |
| R-004 | LLM 推荐理由幻觉（hallucination） | 中 | 高 | POC-004: 验证 Faithfulness 指标；推荐理由必须引用简历原文片段 |
| R-005 | 单人开发时间不足 | 中 | 高 | 优先实现 P0 功能（search + refine + lookup），P2 功能（manage/analytics）可延后 |
| R-006 | BGE-M3 API 延迟不稳定 | 低 | 中 | 设计 Embedding 缓存层；批量入库时使用异步并发 |
| R-007 | Milvus 本地 Docker 稳定性 | 低 | 低 | 定期备份向量数据；数据可从 Resume Store 重建 |

---

## 四、POC 计划

### POC-001: 简历解析验证

**目标**：验证不同格式简历的解析准确率

**范围**：
- 5 份不同格式的中文简历（PDF 2份/DOCX 1份/图片 JPG-PNG 2份）
- 评估维度：姓名、技能、工作经历、教育经历、项目经历的提取准确率

**方法**：
1. 使用 PyPDF2 / python-docx 提取原文
2. 使用 LLM（DeepSeek）进行结构化提取（Prompt + Pydantic Schema）
3. 人工对比提取结果与原始简历

**时间盒**：1 天

**通过标准**：结构化字段提取准确率 >= 85%

---

### POC-002: 多轮对话状态管理

**目标**：验证 Refine 意图的状态合并逻辑

**范围**：
- 实现 Conversation Memory 原型
- 测试 3 种合并策略：增量合并、条件覆盖、条件重置

**方法**：
1. 定义 Conversation State Schema
2. 模拟 5 轮对话（search -> refine -> refine -> refine -> new search）
3. 验证每轮状态合并结果的正确性

**时间盒**：0.5 天

**通过标准**：5 轮对话中状态合并结果 100% 正确

---

### POC-003: 意图识别准确率

**目标**：验证 LLM 意图识别的准确率

**范围**：
- 构造 50 条测试用例（覆盖 10 类 Intent，每类 5 条）
- 重点测试 refine vs search 的边界

**方法**：
1. 编写 50 条标注测试集
2. 使用 LLM（DeepSeek）+ Few-shot Prompt 进行意图识别
3. 统计准确率、混淆矩阵

**时间盒**：0.5 天

**通过标准**：整体准确率 >= 90%，refine vs search 准确率 >= 85%

---

### POC-004: 推荐质量验证

**目标**：验证 Hybrid Retrieval + Rerank 的推荐质量

**范围**：
- 准备 10 份测试简历（手工构造或使用公开数据集）
- 准备 5 个招聘查询
- 评估 Top-5 推荐的相关性

**方法**：
1. 简历入库 + Embedding
2. 执行 5 个查询，获取 Top-5 结果
3. 人工评估相关性（0-2 分：不相关/部分相关/完全相关）

**时间盒**：1 天

**通过标准**：Top-5 结果中至少 3 条为"部分相关"或以上

---

### POC 总览

| POC | 目标 | 时间 | 通过标准 | 优先级 |
|-----|------|------|----------|--------|
| POC-001 | 简历解析准确率 | 1 天 | >= 85% | P0 |
| POC-002 | 多轮对话状态管理 | 0.5 天 | 100% 正确 | P0 |
| POC-003 | 意图识别准确率 | 0.5 天 | >= 90% | P0 |
| POC-004 | 推荐质量 | 1 天 | Top-5 中 >= 3 条相关 | P0 |
| **合计** | - | **3 天** | - | - |

---

## 五、初步技术方向（供调研假设，非正式决策）

> 以下假设会在 Phase 3.1 调研结束后基于调研结论重新评估，Phase 3.5 正式决策。

### 前端方向

- **假设**：Streamlit 或 Gradio
- **理由**：1 人团队，前端不是核心价值，用最低成本实现可用的聊天界面即可。Streamlit/Gradio 开发效率最高，Python 技术栈一致。
- **替代方案**：如需更专业的 UI，可选 Next.js + Shadcn/UI，但会增加前端开发负担。

### 后端方向

- **假设**：FastAPI + LangChain/LangGraph
- **理由**：
  - FastAPI 是 Python 生态最流行的异步 Web 框架，原生支持 Streaming（SSE）
  - LangChain / LangGraph 是 RAG 编排最成熟的框架，Agent Router + Tool Calling 可直接实现
  - 与 Milvus / MongoDB 的 Python SDK 无缝集成
- **替代方案**：LlamaIndex（更偏检索，Agent 编排能力弱于 LangGraph）

### 向量数据库方向

- **假设**：Milvus Standalone（Docker）
- **理由**：
  - 原生支持 Hybrid Search（Dense + Sparse）
  - 10 万级数据单机无压力，可扩展到百万级
  - Python SDK（pymilvus）成熟
  - BGE-M3 的 Dense + Sparse 双模态输出可直接写入 Milvus
- **替代方案**：Qdrant（更轻量，但 Hybrid Search 支持弱于 Milvus）

### Embedding 方向

- **假设**：BGE-M3（云端 API）
- **理由**：
  - 支持 Dense + Sparse 双模态，天然适配 Hybrid Retrieval
  - 中文效果优秀（BAAI 出品）
  - 云端调用无需 GPU
- **替代方案**：OpenAI text-embedding-3-large（英文更强，中文弱于 BGE-M3）

### LLM 方向

- **假设**：DeepSeek（主力） + OpenAI（备选）
- **理由**：
  - DeepSeek 性价比高，中文能力强，通过 OpenAI Chat Completions 接口调用
  - OpenAI 作为备选，用于对比效果或 DeepSeek 不可用时降级
  - 统一接口（OpenAI Compatible），切换成本低
- **替代方案**：Qwen（阿里，中文能力强，但 API 生态不如 OpenAI Compatible）

### 文档解析方向

- **假设**：PyPDF2/pdfplumber + python-docx + DeepSeek-OCR（图片） + LLM 结构化提取
- **理由**：
  - 原文提取用成熟库，图片简历用 DeepSeek-OCR，结构化提取交给 LLM
  - LLM 提取 + Pydantic Schema 验证，兼顾灵活性和准确性
- **替代方案**：Unstructured.io（一站式解析，但可控性不如自研）；LlamaParse（付费 API）

### RAG 编排方向

- **假设**：LangGraph
- **理由**：
  - 天然支持有状态的多轮对话（State Graph）
  - Tool Calling + Conditional Edge 可实现 Intent Router
  - 与 LangChain 生态无缝集成
- **替代方案**：自建状态机（可控性更高，但开发成本大）

---

## 六、Go / No-Go 决策

### 决策矩阵

| 评估维度 | 结论 | 说明 |
|----------|------|------|
| 技术可行性 | 可行 | 所有核心模块均有成熟方案，无技术死胡同 |
| 资源可行性 | 有条件可行 | 1 人 + 1 个月时间紧凑，需严格控制范围 |
| 风险可控性 | 可控 | 最高风险（简历解析）可通过 POC 验证并设计降级策略 |
| 成本可行性 | 可行 | 月度运营成本 ~100-200 元，完全可接受 |

### 建议结论

**有条件可行（Conditional Go）**

**前置条件**：
1. POC-001（简历解析）通过验证 -> 确认解析准确率 >= 85%
2. 严格控制 V1 范围，P2 功能（resume.manage / analytics / knowledge.qa）可延后到 V2
3. 优先实现核心链路：recruitment.search + recruitment.refine + candidate.lookup

**如前置条件满足，可进入 Phase 3（PRD 编写）。**

---

## 七、范围优先级建议

为确保 1 个月可交付，建议按以下优先级分批实现：

### P0（必须交付）

| 模块 | 说明 |
|------|------|
| Resume Parser（PDF/DOCX） | 核心简历解析 |
| Vector Index（Milvus + BGE-M3） | 向量入库和检索 |
| recruitment.search | 初始推荐 |
| recruitment.refine | 多轮条件修正 |
| candidate.lookup | 候选人详情 |
| Streaming 输出 | 用户体验 |
| Audit Log | 可观测性 |

### P1（尽量交付）

| 模块 | 说明 |
|------|------|
| resume.upload | 简历上传入库 |
| recruitment.compare | 候选人对比 |
| PII 加密 | 安全性 |
| API 认证 | 基础安全 |

### P2（可延后到 V2）

| 模块 | 说明 |
|------|------|
| resume.manage | 简历管理（删除/重新解析） |
| knowledge.qa | 知识问答 |
| analytics | 数据统计 |
| 图片 OCR | DeepSeek-OCR，已确认纳入 P1 |
| RBAC 权限 | 完整权限体系 |
| 前端专业化 | 从 Streamlit 升级到正式前端 |

