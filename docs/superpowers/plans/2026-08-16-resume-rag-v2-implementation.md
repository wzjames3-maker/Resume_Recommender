# 简历 RAG 链路重构实施方案（v2 修订版）

> 日期：2026-08-16
> 状态：方案（已过独立审查，含 6 处修订 R1-R6）；**实施完成（T1-T8，提交 538a8a8..a90afc2 + 评测修复 2 提交）；真实模型评测结论：λ 默认置 0（证据合成关闭待更大样本），T7 表空回退修复；详见 README-hr「v2 真实模型评测」**
> 设计依据：`docs/superpowers/specs/2026-08-16-resume-rag-v2-design.md`
> 审查输入：`docs/superpowers/audits/2026-08-16-resume-rag-design-fit-assessment.md`
> 基线：367/367 测试全绿；`ruff check apps/hr/` 干净；`makemigrations --check` 无意外变更
> 纪律：不运行真实模型脚本（SENSENOVA/SILICONFLOW key）；不 DROP DATABASE test_maxkb；--keepdb

---

## 总原则

- 每任务独立提交（中文 Conventional Commits）；每任务过单测基线 + 新增测试 + ruff
- 评测脚本提供但由项目方在真实环境执行（含模型 key 的步骤一律不代跑）
- 确定性行为变更 = 一次全量重嵌（T6 合并覆盖 T2 存量 + T6 词条两项变更）

## 任务清单（9 项）

### T1 `feat(hr): PII 掩码前置至 LLM 切片调用之前`（合规优先，独立无依赖）

**文件**：`apps/hr/services/resume_splitter.py`
**改动**：`split_resume_text` 中 sanitize 之后、`lines = text.split("\n")` 之前执行 `text = mask_pii(text)`；删除三处返回点（L223/231/238）的逐 chunk `mask_pii`；`scan_residual_pii` 入库门控保留为 backstop（mask 未覆盖变体仍会被拒）。
**成立性（已代码级验证）**：`_PHONE_RE/_EMAIL_RE/_IDCARD_RE` 均为行内替换、`[已脱敏]` 不含换行 → 行数不变，行号边界协议不受影响；`_ocr_semicolon_to_lines` 在 sanitize 内先于 mask 执行，不受影响。
**保真语义更新**：「相对原文保真」→「相对掩码后原文保真」，同步到设计文档（T8 一并）。
**测试**：新增「掩码前后行数不变」断言；现有 `test_index_resume_accepts_masked_content` / `rejects_residual_pii` 复核（残留用例用 mask 不覆盖但 scan 覆盖的变体，设计本就如此）。
**风险**：LLM 输入形态变化（title 可能出现 `[已脱敏]`）→ dataset30 边界协议命中率由项目方复测；不达标则单任务回滚（无耦合）。

### T2 `feat(hr): 切片标题并入 chunks 检索文本（title 入向量）`

**文件**：`apps/hr/services/resume_index.py`
**方案（主，零内核改动）**：`index_resume` 内将 kernel `DocumentSerializers.Create.save` 替换为 HR 自建模型（一个 atomic 块），**chunks 在 INSERT 时即为 title 前缀文本**，出事务后显式 `embedding_by_document.delay(document_id, embedding_model_id)`（AlreadyQueued → 友好异常）。
**字段构造清单（R1，已对照 paragraph.py:419-426 与 document.py:1085-1097）**：
- `Document(id=uuid.uuid7(), knowledge_id, name=resume.file_name, char_length=sum(len(c) for c in contents), type=KnowledgeType.BASE, user_id, meta={"allow_download": True})`
- `Paragraph(id=uuid.uuid7(), document_id, knowledge_id, content=chunk["content"], title=chunk["title"], chunks=[f"{title}\n{c}" if title else c for c in text_to_chunk(chunk["content"])], position=index+1)`
- status/is_active/hit_num 走模型默认值：**State.PENDING="0" 为默认，embedding 任务 state_list 含 PENDING → 自建后直接 delay 即可被拾取，无需复刻 refresh() 状态置位（R1 简化）**
- content 字段保持原文（保真/展示/回溯不变）；不建 Problem（HR 链路不使用）
**备选（字段对齐 brittle 时）**：kernel save + bulk_update chunks + `embedding_by_paragraph_list.delay`（QueueOnce key 不同，无 AlreadyQueued），接受偶发旧向量、下次重嵌自愈。
**测试**：断言 `Paragraph.chunks[0].startswith(title)` 且 content 不变；存量测试中 patch `Create.save` 的用例改 patch 新函数。
**注意**：`_delete_document` 幂等逻辑、resume.document_id 回写、scan_residual_pii 门控、log_flow 全部保留。

### T3 `feat(hr): 简历级证据合成聚合（仅模式 A）`

**文件**：`apps/hr/services/resume_search.py`
**改动（R3 范围声明）**：仅 `_aggregate`（模式 A 路径）；模式 B 已有 hit_vec 多维信号，**不动**。排序键由「最高段分」改为 `max(段分) + λ·log2(1 + 命中段数)`；`_EVIDENCE_LAMBDA = 0.15` 模块常量；meta.aggregation 增加 `evidence_lambda` / `multi_hit_boosted`。回滚 = 常量置 0（保留代码）。
**测试**：等 max 分下多段命中者胜；λ=0 退化为现行为（回归保护）。

### T4 `feat(hr): 查询理解 v1--规则槽位与结构化预筛`

**文件**：新增 `apps/hr/services/query_understand.py` + `resume_search.py`
**改动**：`extract_slots(query) -> {years_min, degree, cities[], semantic_query}`（年限正则 `(\d+)\s*年`；学历词表；城市词表从 `Candidate.current_city` distinct 动态生成）。auto 模式有硬条件 → conditional 路径：Candidate SQL 预筛（`status=ACTIVE AND years>=n AND degree∈ AND city∈`）→ ResumeFile → document_id 集 → `_recall_dual` 新增 `document_ids` 参数（query_set 加 `.filter(document_id__in=...)`）。
**R2 修订（4 项）**：
1. **semantic_query 为空 → 跳过 L2**：纯条件查询走纯结构化检索（预筛结果按 `years_experience desc, update_time desc` 排序返回，不调 embed）；杜绝 `embed_query("")` 空串。
2. **years_experience 为 NULL → 纳入并标记 `years_unknown: true`**（不静默消失；排序靠后；产品可后续决策是否改为严格排除）。
3. **城市归一**：匹配时 `current_city.rstrip("市")` 双向归一，避免"北京/北京市"漏配。
4. **name 快速通道**：查询命中姓名模式（≤4 汉字无空格）时并跑 `name__icontains`，结果置顶；**phone/email 查找 v1 不做**（掩码设计性不可行，产品确认点，写入 T8 文档）。
**边界**：预筛空 → 返回空 + `meta.search_type="prefilter_empty"`（不做语义兜底误导）；预筛 > 2000 → 跳过预筛记 `meta.prefilter_skipped`（阈值可配）。
**测试**：槽位抽取各类型；空 semantic_query；NULL years；城市变体；预筛空/超阈值；name 通道。

### T5 `feat(hr): candidate_skill 技能归一表与 Skill-AND SQL 化`

**文件**：新增 migration `hr/0018_candidateskill.py`（`hr_candidate_skill(candidate_id, skill_norm, skill_raw)`，unique(candidate, skill_norm)）+ `hr/services/skill_normalize.py` + 回填命令
**改动**：`normalize_skill()`（lower/trim/别名映射 `hr/data/skill_alias.json` 初版 ~50 条，源自 `Job.skill_requirements` 聚合+人工）；`backfill_candidate_skills` 管理命令。
**R4 修订**：`_search_skill_and` 结构化路改 SQL 后，**查询返回 `(candidate_id, skill_norm)` 对而非 EXISTS**——Python 侧按有序技能列表重建 per-doc 命中向量（保留"有序技能优先"排序语义），逐技能放宽逻辑不变；**表为空时回退现有 Candidate.skills JSON 路径**（迁移期兼容）；向量路 OR 合并不动。
**测试**：SQL 路命中/放宽/空表回退；归一映射用例。

### T6 `feat(hr): Termbase 技能词条与全量重嵌命令`

**文件**：新增管理命令 `seed_resume_termbase` / `reindex_resume_knowledge`
**改动**：词条源 = skill_alias + Job.skill_requirements；幂等（先清后插简历知识库词条）；`KeywordsSearch().handle` 内部已按 knowledge_id 自动生效，检索代码零改动。`reindex_resume_knowledge` 逐文档 `embedding_by_document.delay`。
**R6 风险标注**：重嵌窗口 `drop_knowledge_index` → 期间检索降级为 seq scan（不失败），**建议低峰执行**；逐文档 delay 在大库时排队，可接受。**本次重嵌一次性覆盖 T2（title 入 chunks 存量）+ T6（词条分词）**。
**注意**：`_sparse_query` 硬编码停用词表（经验/工作/熟悉/精通等）与词条设计冲突说明写入命令 docstring；单测只验证编排（mock），真实重嵌由项目方执行。

### T7 `feat(hr): 技能条件接入预筛（EXISTS）`

**文件**：`resume_search.py` / `query_understand.py`
**改动**：T4 预筛扩展 skills 维度：`EXISTS(candidate_skill)`（依赖 T5）；与向量 Skill-AND 路并存（预筛保证精确，向量路负责证据段落）。skills 槽位抽取走 T5 归一表。
**测试**：技能预筛命中/未命中；与模式 B 并存不冲突。

### T8 `docs(hr): 设计文档与交接文档同步`

**文件**：`docs/superpowers/specs/2026-08-16-resume-rag-v2-design.md`（§9 自审记录追加实施偏差）、`docs/superpowers/specs/2026-08-15-hr-resume-search-design.md`（§9 偏差记录）、`HANDOFF.md`、`README-hr.md`
**内容**：T1 保真语义更新（掩码后原文）；T2 chunks 语义（title 前缀）；T4 预筛契约（NULL years / 城市归一 / name 通道 / phone-email 不做及原因）；T5 归一表；T6 词条与重嵌命令用法；测试数演进。

### 评测与验收（每 Phase 一次，项目方真实环境）

- 单测基线 367 → 递增全绿；ruff 干净；`makemigrations --check` 无意外变更
- dataset30 复测：T1 后边界协议命中率；T2+T6 重嵌后 browse 类 recall@3/MRR 前后对比；T4 后 conditional 类**条件精确率必须 = 1.0**
- 消融：λ∈{0, 0.15}、预筛 on/off、title-chunks on/off
- 分类型评测集（lookup/conditional/browse/skill-AND 各 30+）由项目方标注，runner 提供

## 执行顺序与依赖

```
T1（独立）→ T2 → T3 → T4 → T5 → T6（全量重嵌，吸收 T2 存量）→ T7 → T8
```

## 风险与回滚

| 风险 | 缓解 |
|---|---|
| T2 自建模型字段对齐遗漏 | 字段清单已逐项对照（R1）；备选方案兜底；存量测试改造覆盖 |
| 存量简历 chunks 无 title（重嵌前新旧混排） | T6 统一重嵌；T2→T6 窗口尽量短 |
| 掩码前置影响 LLM 边界质量 | dataset30 复测把关，不达标 T1 单任务回滚（无耦合） |
| λ 扰动既有排序 | 常量置 0 即回旧行为（保留代码） |
| 重嵌窗口检索降级 | 低峰执行；seq scan 不失败 |
| T5 归一表数据质量 | 回填命令 + 人工抽检 + 表空时 JSON 路径回退 |

## 自审记录（v2 修订版相对初稿）

- R1（T2）：默认状态即 PENDING，自建后直接 delay，无需复刻 refresh 状态置位；给出逐字段构造清单
- R2（T4）：semantic_query 空 → 纯结构化检索；NULL years 纳入并标记；城市双向归一；name 快速通道；phone/email v1 不做（产品确认点）
- R3（T3）：显式声明证据合成仅模式 A
- R4（T5）：SQL 返回 (candidate_id, skill_norm) 对，Python 重建 hit_vec 保有序语义
- R5：新增 T8 文档同步任务
- R6（T6）：重嵌窗口风险标注 + 低峰执行
