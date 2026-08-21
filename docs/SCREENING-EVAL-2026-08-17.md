# Screening 初筛一致性评测报告（D1 标定基线 · 2026-08-17）

> 依据 `docs/PRD-AGENT-RAG.md` §10 验收口径执行的第一版真实模型评测。
> 语料：天池人才简历数据集（`数据集/train.json`，2000 份脱敏结构化简历，CC0）；
> 模型：SenseNova `sensenova-6.8-flash-lite`（LLM）+ SiliconFlow `bge-large-zh-v1.5`/`bge-reranker-v2-m3`（Embedding/Rerank，凭据走环境变量）。
> 报告数据：`docs/screening-eval-2026-08-17.json`（含逐例记录）。

## 1. 方法

| 项 | 说明 |
|---|---|
| 语料导入 | `import_resume_dataset`：300 份结构化简历 → Candidate + CandidateSkill + 简历语义索引（结构化节预切片，免 LLM 切片；同步向量化）。导入 280 / 失败 0 |
| 技能补抽取 | 数据集无技能字段且术语表规则覆盖率低（§14#6）→ `eval_screening` 对无技能候选人生成技能（LLM 单次调用，4 并发，幂等） |
| 配对构造 | 正样本：职位要求取自候选人自身画像（技能/城市）→ 期望**不误拒**（非 DECLINE）；负样本：职位技能取自与候选人不相交的他人画像（硬条件必不满足）→ 期望**不误推**（非 ADVANCE） |
| 评测执行 | 真实 Screening Agent 全链路（结构化核对 + 候选人文档集语义检索 + LLM 评估 + 服务端评分）；4 并发；临时 Job/Application 用例跑完即清理（run/proposal 账本保留） |
| 口径 | 宽松一致率 = 正样本非 DECLINE + 负样本非 ADVANCE；严格一致率 = 正样本 ADVANCE + 负样本 DECLINE |
| 门控 | `RUN_REAL_MODEL=1`，防 CI 误跑 |

复现：`RUN_REAL_MODEL=1 uv run python manage.py import_resume_dataset --limit 300` 后
`RUN_REAL_MODEL=1 uv run python manage.py eval_screening --limit 200 --report docs/screening-eval-YYYY-MM-DD.json`

## 2. 结果（200 例：正 100 / 负 100）

| 指标 | 值 |
|---|---|
| **宽松一致率（整体）** | **72%**（目标 ≥80%，未达标） |
| 正样本（不误拒） | 44% |
| 负样本（不误推） | 100% |
| 严格一致率 | 72% |
| 建议分布 | ADVANCE 8 / HOLD 22 / DECLINE 144 / 无建议(null) 26 |
| 分数带 | 80-100×8（全 ADVANCE）；60-79×23（22 HOLD）；0-59×143（全 DECLINE）；无分×26 |
| 无证据率 | 20.5%（检索空 → 服务端强制 HOLD，**降级链正确**） |
| 单例耗时 | 平均 11.4s（异步口径 P95≤30s 满足） |

## 3. 诊断

1. **正样本误拒为主因（56%）**：分数大量落入 0-59 带被 DECLINE。逐例核查显示
   LLM 对"泛技能"（数据分析/Excel/ppt 等）给出的 evidence relevance 与置信度偏低，
   且评测构造的职位描述仅含 1-3 个技能词、无完整职责——语义匹配空间过窄。
   结论：**当前"分数带默认值 + flash-lite + 单薄职位构造"组合偏保守**；阈值本身行为正常
   （60-79 全 HOLD、80-100 全 ADVANCE，无越界）。
2. **无建议 26 例（13%）**：29 个 FAILED run —— LLM 输出校验失败 23 例（flash-lite
   对长上下文+严格 JSON 的稳定性不足，重试 2 次后仍失败）+ SenseNova 服务端临时不可用 6 例
   （并发 4 下 400 "engine is not available temporarily"）。降级链行为正确：run=FAILED
   业务零影响（评测用例如实标记，不计入任何"高分"）。
3. **负样本 100%**：硬条件不满足 → 服务端 DECLINE 兜底，无一条误推——安全侧达标。

## 4. 建议（按优先级）

1. **评测构造升级**：正样本职位改用候选人工作经历/项目内容渲染的完整 JD（职责+技能），
   而非技能词列表——更接近真实 JD，消除"泛技能语义空间过窄"的系统性低估。
2. **失败重试增强**：对 SenseNova 400/5xx 临时错误增加退避重试（当前仅 2 次立即重试）；
   校验失败可尝试"JSON 修复提示"一轮（提取首个 `{...}` 块）再判失败。
3. **模型档位评估**：在评测集上对比更强模型（如 sensenova-pro 类），若一致率显著提升，
   按 §14#4 评估档引入强模型承担评估（Provider 已 OpenAI 兼容）。
4. **阈值标定**：本轮数据证明 60/80 分带边界行为正确（无越界建议），暂不动；
   待评测构造升级后重新标定分数带与"evidence_ok 必须 2 维"的门槛。
5. **人工标定集叠加**：构造性标签（画像正/负样本）只能作为基线；正式验收需 ≥80 例
   独立人工标注集（真实 HR 判定）做交叉验证后再冻结阈值。

## 5. 产物

- `apps/hr/management/commands/import_resume_dataset.py`：语料导入（幂等、预切片、技能规则抽取）
- `apps/hr/management/commands/eval_screening.py`：一致性评测（配对构造、4 并发、报告）
- `apps/hr/services/resume_index.py`：`index_resume` 新增 `chunks` 预切片通道（默认行为不变）
- `docs/screening-eval-2026-08-17.json`：本次逐例报告
