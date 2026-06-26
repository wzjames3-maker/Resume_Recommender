<!-- Phase: Phase 3 - PRD -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Status: Frozen after review -->
<!-- Date: 2026-06-23 -->

# PRD：企业智能招聘 RAG 推荐系统

## 1. 概述

### 目标

为企业 HR 提供基于自然语言的智能候选人检索与推荐能力，将首轮筛选时间减少 70%，Top-10 采纳率 >= 80%。

### 背景

企业 HR 在招聘过程中面对大量历史简历库（10 万+ 份），筛选候选人主要依赖关键词搜索或人工逐份阅读。关键词搜索无法理解语义（搜"Java 工程师"会遗漏"Spring Boot 后端开发"），人工筛选耗时巨大，推荐结果缺乏可解释性。系统作为 AI 检索推荐层，通过 API 集成现有 ATS，不替代 ATS。

### 非目标（V1 明确不做）

| 非目标 | 说明 |
|--------|------|
| JD 创建 | 不负责生成或管理职位描述 |
| 面试安排 | 不涉及面试调度和日历管理 |
| Offer 管理 | 不涉及薪酬谈判和 Offer 流程 |
| 候选人沟通 | 不负责与候选人的邮件/消息交互 |
| ATS 全流程管理 | 不替代现有 ATS，仅作为 AI 检索推荐层 |
| SaaS 多租户 | V1 为单企业内部部署，不做多租户架构 |
| 实时简历抓取 | 不做从 Boss/猎聘等平台的实时数据抓取 |
| 图片 OCR | V1 使用 DeepSeek-OCR（deepseek-ai/DeepSeek-OCR）支持图片简历解析 |
| 知识问答 | V1 不做薪资/岗位等知识问答（V2 实现） |
| 数据统计 | V1 不做人才库统计分析（V2 实现） |

---

## 2. 用户角色

| 角色 | 描述 | 权限 |
|------|------|------|
| admin（管理员） | 系统管理员，负责简历入库和系统配置 | 全部权限：简历管理（CRUD）、推荐、系统配置、Audit Log 查看 |
| hr（HR 用户） | 日常使用系统的招聘人员 | 推荐查询、候选人查看、简历上传（仅上传，不可删除）、个人对话历史 |
| viewer（只读） | Hiring Manager 等需要查看推荐结果但不操作的人员 | 只读：查看推荐结果、候选人详情 |

---

## 3. 核心用例

### UC-001: 智能候选人检索（recruitment.search）

- **角色**: hr / admin
- **前置条件**: 人才库中已有入库简历
- **主流程**:
  1. HR 输入自然语言招聘需求（如"找5年Java工程师，杭州，985"）
  2. 系统识别 Intent 为 `recruitment.search`
  3. 系统提取 Slots（job_title=Java工程师, experience>=5, city=杭州, education=985）
  4. 系统执行 Hybrid Retrieval（Dense + Sparse）
  5. 系统执行 Metadata Filter（硬约束过滤）
  6. 系统执行 LLM Rerank（多维度加权排序）
  7. 系统返回 Top-N 候选人（含 Score、Reason、Matched Skills、Missing Skills）
- **替代流程**:
  - AF-001: 符合条件的候选人不足 N 个 → 返回实际数量 + 提示"符合条件的候选人共 X 人"
  - AF-002: HR 未指定数量 → 默认返回 10 人
- **异常流程**:
  - EF-001: 意图识别失败 → 触发 Fallback，返回引导性回复
  - EF-002: LLM 调用超时 → 降级为纯向量检索 + 模板化理由
  - EF-003: 向量检索超时 → 返回错误提示，记录 Audit Log

---

### UC-002: 多轮条件修正（recruitment.refine）

- **角色**: hr / admin
- **前置条件**: 已执行过至少一次 recruitment.search
- **主流程**:
  1. HR 输入修正条件（如"女生呢"、"学历高一点"、"不要外包"）
  2. 系统识别 Intent 为 `recruitment.refine`
  3. 系统从 Conversation Memory 取出 last_query + last_filters
  4. 系统合并新 Slots（增量合并 / 条件覆盖 / 排除条件）
  5. 系统根据条件变化类型决策检索范围（last_candidates 内过滤 or 全库重检）
  6. 系统返回更新后的推荐结果
- **替代流程**:
  - AF-001: 过滤后结果为空 → 提示"在上次结果中无匹配，已扩大到全库检索"
- **异常流程**:
  - EF-001: 无上文（首次对话就发"女生呢"）→ 提示"请先描述您的招聘需求"
  - EF-002: 合并后 Slots 冲突 → 以新值覆盖旧值

---

### UC-003: 候选人详情查看（candidate.lookup）

- **角色**: hr / admin / viewer
- **前置条件**: 已有推荐结果
- **主流程**:
  1. HR 输入查看请求（如"第一个人是谁"、"看看张三的简历"）
  2. 系统识别 Intent 为 `candidate.lookup`
  3. 系统从 last_candidates 中定位候选人（按位置或按姓名）
  4. 系统查询 Resume Store 获取完整简历数据
  5. 系统返回结构化候选人详情（含 PII 脱敏）
- **替代流程**:
  - AF-001: 姓名匹配到多人 → 列出候选项让 HR 选择
- **异常流程**:
  - EF-001: 候选人未找到 → 提示"未找到该候选人，请检查姓名"
  - EF-002: 无上文 → 提示"请先进行候选人检索"

---

### UC-004: 候选人对比（recruitment.compare）

- **角色**: hr / admin
- **前置条件**: 已有推荐结果，且至少有 2 位候选人
- **主流程**:
  1. HR 输入对比请求（如"对比前两个候选人"）
  2. 系统识别 Intent 为 `recruitment.compare`
  3. 系统获取目标候选人的完整简历数据
  4. 系统生成多维度对比分析（技能、经验、项目、教育）
  5. 系统返回对比表格 + 综合建议
- **替代流程**:
  - AF-001: 对比对象超过 3 人 → 提示"最多支持 3 人同时对比"
- **异常流程**:
  - EF-001: 指定的候选人不存在 → 提示"请指定有效的候选人"

---

### UC-005: 简历上传入库（resume.upload）

- **角色**: hr / admin
- **前置条件**: 无
- **主流程**:
  1. HR 上传简历文件（PDF / DOCX / JSON）
  2. 系统调用 Resume Parser 解析简历
  3. 系统提取结构化信息（姓名、技能、经历、教育、项目）
  4. 系统写入 Resume Store
  5. 系统生成 Embedding → 写入 Milvus
  6. 系统更新 Elasticsearch 索引
  7. 系统返回入库状态 + 解析摘要
- **替代流程**:
  - AF-001: 批量上传 → 逐份解析，返回批量结果摘要
- **异常流程**:
  - EF-001: 文件格式不支持 → 提示"仅支持 PDF/DOCX/JSON 格式"
  - EF-002: 解析失败 → 提示"简历解析失败，已保留原文，可手动补充信息"
  - EF-003: 重复上传 → 提示"检测到相似简历，是否覆盖？"

---

### UC-006: 简历管理（resume.manage）

- **角色**: admin
- **前置条件**: 简历已入库
- **主流程**:
  1. admin 输入管理指令（如"删除这份简历"、"重新解析这份简历"）
  2. 系统识别 Intent 为 `resume.manage`
  3. 系统定位目标简历
  4. 系统执行操作（delete / re-parse / update）
  5. 系统同步更新 Resume Store + Vector Index + ES
  6. 系统返回操作结果
- **替代流程**:
  - AF-001: 删除操作 → 二次确认"确认删除 XXX 的简历？"
- **异常流程**:
  - EF-001: 权限不足（hr 角色尝试删除）→ 提示"仅管理员可执行此操作"
  - EF-002: 简历不存在 → 提示"未找到该简历"

---

### UC-007: 知识问答（knowledge.qa）

- **角色**: hr / admin
- **前置条件**: 无
- **主流程**:
  1. HR 输入知识性问题（如"Java工程师薪资范围"）
  2. 系统识别 Intent 为 `knowledge.qa`
  3. 系统通过 Knowledge RAG 检索相关知识
  4. 系统生成回答
  5. 系统返回回答 + 来源
- **替代流程**: 无
- **异常流程**:
  - EF-001: 无法回答 → 提示"暂无相关信息，建议咨询行业报告"

> **注**：UC-007 为 P2 优先级，V1 可不实现。

---

### UC-008: 数据统计（analytics）

- **角色**: hr / admin / viewer
- **前置条件**: 人才库中有数据
- **主流程**:
  1. HR 输入统计查询（如"人才库有多少Java工程师"）
  2. 系统识别 Intent 为 `analytics`
  3. 系统查询 Resume Store 聚合统计
  4. 系统返回统计结果 + 分布详情
- **替代流程**: 无
- **异常流程**:
  - EF-001: 查询维度不支持 → 提示"支持按技能/城市/学历/经验统计"

> **注**：UC-008 为 P2 优先级，V1 可不实现。

---

## 4. 功能需求

| ID | 需求 | 优先级 | 对应用例 |
|----|------|--------|----------|
| FR-001 | 支持自然语言招聘查询，系统自动识别 Intent 和 Slots | P0 | UC-001 |
| FR-002 | 支持 Hybrid Retrieval（Dense 向量 + Sparse 关键词）+ Small→Big 多粒度召回策略 | P0 | UC-001 |
| FR-003 | 支持 Metadata Filter（工作年限、学历、城市、性别等硬约束过滤） | P0 | UC-001 |
| FR-004 | 支持 LLM Rerank 多维度加权排序（权重可配置） | P0 | UC-001 |
| FR-005 | 每条推荐结果包含 Score、Reason、Matched Skills、Missing Skills、Score Breakdown | P0 | UC-001 |
| FR-006 | 支持多轮对话条件修正（recruitment.refine），含增量合并、条件覆盖、排除条件 | P0 | UC-002 |
| FR-007 | 支持 Conversation Memory（last_query, last_filters, last_candidates） | P0 | UC-002 |
| FR-008 | 支持候选人详情查看（按位置/姓名定位） | P0 | UC-003 |
| FR-009 | 支持候选人对比（多维度并排对比 + 综合建议） | P1 | UC-004 |
| FR-010 | 支持简历上传（PDF / DOCX / JSON） | P0 | UC-005 |
| FR-011 | 支持 Resume Parser（PyPDF2/pdfplumber + python-docx + DeepSeek-OCR + LLM 结构化提取） | P0 | UC-005 |
| FR-012 | 支持多粒度 Chunk 切分（Small Chunk 单句级精准检索 + Parent Chunk Section 级上下文 + Full Resume），保留层级关系和 Metadata | P0 | UC-005 |
| FR-013 | 支持 Skill 标准化（大小写统一、同义词映射） | P1 | UC-005 |
| FR-014 | 支持简历管理（删除、重新解析），仅 admin 角色 | P1 | UC-006 |
| FR-015 | 支持 Streaming 流式输出 | P0 | UC-001, UC-002 |
| FR-016 | 支持 Fallback 意图兜底 + 引导性回复 | P0 | 全部 |
| FR-017 | 支持 API 认证（JWT） | P1 | 全部 |
| FR-018 | 支持 RBAC 角色权限（admin / hr / viewer） | P1 | 全部 |
| FR-019 | 支持 PII 数据加密存储 + 脱敏展示 | P1 | UC-003, UC-005 |
| FR-020 | 支持 Audit Log（记录每次交互的 Query/Intent/Slots/Result/Latency/Tokens） | P0 | 全部 |
| FR-021 | 支持通用闲聊（chat），无明确业务意图时进行友好对话 | P3 | - |
| FR-022 | 支持知识问答（Knowledge RAG） | P2 | UC-007 |
| FR-023 | 支持数据统计（聚合查询） | P2 | UC-008 |

---

## 5. 非功能需求

| ID | 需求 | 指标 | 说明 |
|----|------|------|------|
| NFR-001 | 初始推荐响应时间 | P95 <= 3s, P99 <= 5s | recruitment.search 端到端 |
| NFR-002 | 条件修正响应时间 | P95 <= 2s, P99 <= 3s | recruitment.refine 端到端 |
| NFR-003 | 候选人详情响应时间 | P95 <= 1s, P99 <= 2s | candidate.lookup 端到端 |
| NFR-004 | Streaming 首 Token 时间 | <= 800ms | 用户感知的首字输出延迟 |
| NFR-005 | 并发用户数 | >= 50 | 同时在线用户 |
| NFR-006 | 推荐查询 QPS | >= 20 | 推荐接口吞吐 |
| NFR-007 | 简历入库 QPS | >= 10 | 简历上传接口吞吐 |
| NFR-008 | 意图识别准确率 | >= 90% | 10 类 Intent 整体准确率 |
| NFR-009 | Fallback 率 | <= 5% | 意图识别失败的比例 |
| NFR-010 | 推荐可解释性 | 每条必须包含 Score + Reason + Skills + Missing | HR 可直接转述给业务部门 |
| NFR-011 | Audit Log 完整性 | 100% 交互记录 | 包含 Query/Intent/Slots/Result/Latency/Tokens |
| NFR-012 | Audit Log 保留期 | >= 180 天 | 支持按 user/conversation/时间查询 |
| NFR-013 | PII 加密存储 | AES-256 | 手机号、邮箱加密存储 |
| NFR-014 | PII 脱敏展示 | 默认脱敏 | 手机号 138****1234, 邮箱 zhang***@gmail.com |
| NFR-015 | API 认证 | JWT | 所有接口必须认证 |
| NFR-016 | RBAC | admin/hr/viewer | 三级角色权限 |
| NFR-017 | 系统可用性 | 99.5% | 每月宕机 <= 3.6 小时 |
| NFR-018 | 故障恢复时间 | <= 30 分钟 | RTO |
| NFR-019 | 数据备份 | 每日增量 + 每周全量 | - |
| NFR-020 | LLM 降级 | LLM 不可用时降级为纯检索 + 模板理由 | 保证核心链路可用 |
| NFR-021 | Recall@10 | >= 0.85 | Top-10 结果中包含相关候选人 |
| NFR-022 | MRR | >= 0.7 | 第一个相关结果的排名质量 |
| NFR-023 | NDCG@10 | >= 0.75 | 排序质量 |
| NFR-024 | Faithfulness | >= 0.9 | 推荐理由与简历内容一致性 |
| NFR-025 | Top-10 采纳率 | >= 80% | HR 反馈的实际采纳率 |
| NFR-026 | 首轮筛选时间减少 | >= 70% | 与人工筛选对比 |

---

## 6. 里程碑

| 里程碑 | 内容 | 预计时间 | 交付物 |
|--------|------|----------|--------|
| M1 | 基础设施 + Resume Parser | 第 1 周 | Milvus/MongoDB/FastAPI 脚手架 + PDF/DOCX/OCR 解析 + LLM 结构化提取 |
| M2 | 检索与推荐核心 | 第 2 周 | Hybrid Retrieval + Metadata Filter + LLM Rerank + recruitment.search |
| M3 | 多轮对话 + 候选人操作 | 第 3 周 | Conversation Memory + recruitment.refine + candidate.lookup + compare |
| M4 | API + 安全 + 联调 | 第 4 周 | FastAPI 接口 + Streaming + Audit Log + JWT + 联调测试 |

---

## 7. 开放问题

| ID | 问题 | 影响范围 | 状态 |
|----|------|----------|------|
| O-001 | 性别过滤是否需要考虑法律法规合规性？某些地区可能禁止基于性别的招聘筛选 | 数据模型 + 业务规则 | 待确认 |
| O-002 | 技能标准化词典如何维护？手工维护 vs LLM 自动推断？ | Skill 质量 | 待确认，建议 V1 先用 LLM 推断 + 人工审核 |
| O-003 | Embedding 模型选型 | 检索质量 | 已解决 ✅ Phase 3.1 确认选 BGE-M3（云端 API） |
| O-004 | LLM 选型 | 全局 | 已解决 ✅ Phase 3.5 确认 DeepSeek（主）+ OpenAI（备） |
| O-005 | Milvus 性能上限 | 部署 | 已解决 ✅ 调研确认 10 万级单机无压力，可扩展到百万级 |
| O-006 | 简历解析的 LLM Prompt 如何设计才能保证结构化提取准确率？ | Resume Parser | 待 POC-001 验证 |
| O-007 | Refine 时何时全库重检 vs last_candidates 内过滤的边界条件？ | 多轮对话 | 待 POC-002 验证 |

---

## 附录 A：排序权重默认配置

| 维度 | 默认权重 | 可配置 |
|------|----------|--------|
| 技能匹配度 | 40% | 是 |
| 工作经验匹配 | 25% | 是 |
| 项目经历相关性 | 20% | 是 |
| 行业经验 | 10% | 是 |
| 教育背景 | 5% | 是 |

不同岗位可有不同的权重配置（如算法岗位可提高教育背景权重）。

## 附录 B：错误码定义

| 错误码 | HTTP Status | 说明 |
|--------|-------------|------|
| INVALID_INPUT | 400 | 输入参数无效 |
| UNAUTHORIZED | 401 | 未认证 |
| FORBIDDEN | 403 | 权限不足 |
| RESUME_NOT_FOUND | 404 | 候选人未找到 |
| RESUME_PARSE_FAILED | 422 | 简历解析失败 |
| INTENT_RECOGNITION_FAILED | 422 | 意图识别失败 |
| RETRIEVAL_TIMEOUT | 504 | 检索超时 |
| LLM_ERROR | 502 | LLM 调用失败 |
| INTERNAL_ERROR | 500 | 内部错误 |




