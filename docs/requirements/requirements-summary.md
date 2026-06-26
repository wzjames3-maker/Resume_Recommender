<!-- Phase: Phase 1 - Requirements -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- File: requirements-summary.md -->
<!-- Date: 2026-06-23 -->

# Phase 1 需求收集总结

## 交付物清单

| 文件 | 内容 | 状态 |
|------|------|------|
| 01-user-journey.md | 用户旅程（主旅程 + 3个子旅程） | Done |
| 02-intent-inventory.md | 意图清单（10类 Intent + 详细定义） | Done |
| 03-slot-definition.md | 参数定义（3类 Slot + 提取示例） | Done |
| 04-domain-model.md | 领域模型（10个实体 + 关系图） | Done |
| 05-business-rules.md | 业务规则（17条 BR） | Done |
| 06-output-contract.md | 输出契约（8种响应结构 + 错误码） | Done |
| 07-non-functional.md | 非功能需求（16条 NFR） | Done |

---

## 核心决策记录

### D-01: 产品定位
- 企业内部智能招聘助手（Enterprise AI Recruiting Assistant）
- 单企业内部部署，V1 不做 SaaS 多租户
- 作为 AI 检索推荐层，通过 API 集成现有 ATS

### D-02: 推荐策略
- 采用软匹配（Soft Match），非严格布尔匹配
- 三阶段: Hybrid Retrieval -> Metadata Filter -> LLM Rerank
- 排序权重可配置（默认: 技能40% + 经验25% + 项目20% + 行业10% + 教育5%）

### D-03: 多轮对话
- 支持增量合并、条件覆盖、条件重置三种 Refine 策略
- 依赖 Conversation Memory 维护上下文
- Refine 时智能决策是否重新全库检索

### D-04: 意图体系
- 10类 Intent，覆盖招聘检索、候选人管理、知识问答、数据分析
- Intent Router 支持上下文感知（多轮对话）
- Fallback 必须给出引导性回复

### D-05: 数据规模
- V1: 10万份简历，可扩展至100万+
- 按语义段落切分，不按固定 Token 长度切块
- 支持 PDF / DOCX / 图片 OCR / JSON

### D-06: 输出规范
- 每条推荐必须包含: score + reason + matched_skills + missing_skills + score_breakdown
- PII 数据默认脱敏
- 统一错误码体系

### D-07: 非功能约束
- P95 响应时间 <=3s，支持 Streaming
- 必须支持 Explainability 和 Audit Log
- LLM 和向量库均可替换（抽象接口）

---

## 待确认事项

以下事项需要在 Phase 2（可行性分析）或 Phase 3（PRD）中进一步明确：

| # | 事项 | 影响范围 | 优先级 |
|---|------|----------|--------|
| 1 | Embedding 模型选型（BGE / OpenAI / Jina） | 检索质量 | P0 |
| 2 | LLM 选型（GPT-4 / Claude / Qwen / DeepSeek） | 全局 | P0 |
| 3 | Resume Parser 实现方案（自研 vs Unstructured.io vs LlamaParse） | 简历解析质量 | P0 |
| 4 | 性别字段是否需要过滤（法律法规合规性） | 数据模型 + 业务规则 | P1 |
| 5 | 技能标准化词典的维护方式 | Skill 质量 | P1 |
| 6 | 简历加密存储的密钥管理方案 | 安全性 | P1 |
| 7 | 生产环境部署架构（K8s 资源规划） | 部署 | P2 |

---

## Phase 1 Checklist 自检

| # | 检查项 | 状态 |
|---|--------|------|
| 1 | 用户旅程覆盖主要场景 | Done |
| 2 | 意图清单完整（10类 Intent） | Done |
| 3 | Slot 定义清晰（3类，含示例） | Done |
| 4 | 领域模型定义完整（10个实体） | Done |
| 5 | 业务规则可执行（17条 BR） | Done |
| 6 | 输出契约明确（8种结构 + 错误码） | Done |
| 7 | 非功能需求量化（16条 NFR） | Done |
| 8 | 核心决策已记录 | Done |
| 9 | 待确认事项已列出 | Done |

All checks passed. Phase 1 完成，可进入 Phase 2（可行性分析）。
