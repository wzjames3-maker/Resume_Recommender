<!-- Phase: Phase 1 - Requirements -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- File: 07-non-functional.md -->
<!-- Date: 2026-06-23 -->

# 07 - 非功能需求（Non-functional Requirements）

## 一、性能需求

### NFR-01: 响应时间

| 场景 | P95 目标 | P99 目标 |
|------|----------|----------|
| 初始推荐（recruitment.search） | <=3s | <=5s |
| 条件修正（recruitment.refine） | <=2s | <=3s |
| 候选人详情（candidate.lookup） | <=1s | <=2s |
| 候选人对比（recruitment.compare） | <=2s | <=3s |
| 知识问答（knowledge.qa） | <=3s | <=5s |
| 数据统计（analytics） | <=1s | <=2s |
| 简历解析（resume.upload 单份） | <=5s | <=10s |
| 简历解析（批量 100 份） | <=5min | <=10min |

### NFR-02: Streaming

- 推荐结果支持 Streaming 流式返回
- 首 Token 响应时间 <=800ms
- 用户体验目标: 0.8s 开始输出，2-3s 推荐完成

### NFR-03: 吞吐量

| 指标 | 目标 |
|------|------|
| 并发用户数 | >=50 |
| QPS（推荐查询） | >=20 |
| QPS（简历入库） | >=10 |

---

## 二、可解释性需求

### NFR-04: Explainability

每条推荐结果必须包含完整的可解释信息：

| 字段 | 要求 |
|------|------|
| score | 0-100 综合匹配分 |
| reason | 自然语言推荐理由，至少2条 |
| matched_skills | 匹配的技能列表 |
| missing_skills | 缺失的技能列表 |
| matched_experience | 匹配的经验摘要 |
| score_breakdown | 各维度评分拆解 |

目的: HR 可以直接将推荐理由转述给业务部门，无需额外解释。

---

## 三、审计日志需求

### NFR-05: Audit Log

每次用户交互必须记录以下信息：

| 字段 | 说明 |
|------|------|
| timestamp | 交互时间 |
| user_id | 用户标识 |
| conversation_id | 会话 ID |
| user_query | 用户原始输入 |
| intent | 识别的意图 |
| slots | 提取的 Slots |
| retrieved_candidates | 召回的候选人 ID 列表 |
| final_recommendations | 最终推荐的候选人 ID 列表 |
| prompt | 发送给 LLM 的 Prompt（用于 Debug） |
| llm_output | LLM 原始输出 |
| latency_ms | 端到端耗时 |
| llm_tokens | 消耗的 Token 数 |
| error | 错误信息（如有） |

**约束**：
- Audit Log 中不记录 PII 明文（手机号、邮箱等）
- 日志保留期: 至少 180 天
- 支持按 user_id / conversation_id / 时间范围查询

---

## 四、安全需求

### NFR-06: API 认证

- 所有 API 接口必须认证（JWT / API Key）
- 支持基于角色的访问控制（RBAC）
- 角色划分: admin（管理员）、hr（HR 用户）、viewer（只读）

### NFR-07: PII 数据保护

| 数据 | 存储 | 传输 | 展示 |
|------|------|------|------|
| 手机号 | AES 加密 | HTTPS | 脱敏（138****1234） |
| 邮箱 | AES 加密 | HTTPS | 脱敏（zhang***@gmail.com） |
| 身份证号 | AES 加密 | HTTPS | 默认不返回 |
| 简历原文 | 明文存储 | HTTPS | 权限控制 |

### NFR-08: 操作审计

- 所有敏感操作必须记录: 简历删除、批量导入、权限变更
- 操作日志包含: 操作人、操作类型、操作对象、操作时间、操作结果

---

## 五、评估指标

### NFR-09: RAG 质量评估

系统上线后需定期评估以下指标：

| 指标 | 目标 | 评估方式 |
|------|------|----------|
| Recall@10 | >=0.85 | Top-10 结果中包含相关候选人的比例 |
| MRR (Mean Reciprocal Rank) | >=0.7 | 第一个相关结果的排名倒数均值 |
| NDCG@10 | >=0.75 | 排序质量评估 |
| Faithfulness | >=0.9 | 推荐理由与简历内容的一致性 |
| Answer Relevancy | >=0.85 | 推荐结果与查询的相关性 |

### NFR-10: 业务指标

| 指标 | 目标 | 数据来源 |
|------|------|----------|
| Top-10 采纳率 | >=80% | HR 反馈 |
| 首轮筛选时间 | 减少70% | 时间对比 |
| 意图识别准确率 | >=90% | Audit Log 分析 |
| Fallback 率 | <=5% | Audit Log 统计 |

---

## 六、可用性需求

### NFR-11: 系统可用性

| 指标 | 目标 |
|------|------|
| SLA | 99.5%（每月宕机 <=3.6 小时） |
| 故障恢复时间 | <=30 分钟 |
| 数据备份 | 每日增量备份，每周全量备份 |

### NFR-12: 降级策略

当 LLM 服务不可用时：
- 降级为纯向量检索 + 关键词检索，跳过 LLM Rerank
- 推荐理由使用模板化生成，而非 LLM 生成
- 告警通知运维团队

---

## 七、部署需求

### NFR-13: 部署方式

- V1 采用单企业内部部署（On-Premise）
- 支持 Docker Compose 部署（开发/测试环境）
- 支持 Kubernetes 部署（生产环境）
- 配置与代码分离，支持环境变量覆盖

### NFR-14: 可观测性

- 日志: 结构化 JSON 日志，支持 ELK 收集
- 指标: Prometheus Metrics（QPS、延迟、Token 消耗、错误率）
- 链路追踪: OpenTelemetry（可选，V2 实现）

---

## 八、兼容性需求

### NFR-15: LLM 可替换

- LLM 调用层抽象为统一接口
- 支持快速切换: OpenAI GPT-4 / Claude / 开源模型（Qwen / DeepSeek）
- 切换 LLM 时不需要修改业务代码

### NFR-16: 向量库可替换

- 向量检索层抽象为统一接口
- V1 使用 Milvus，未来可切换为 Qdrant / Weaviate / Pinecone
