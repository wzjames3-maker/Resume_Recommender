# 简历 RAG v2 设计思路（目标态设计）

> 日期：2026-08-16
> 状态：设计稿（经代码级自审修订 v2；未实施）
> 输入：`2026-08-16-kernel-rag-fullflow-review.md`（内核实现级）+ `2026-08-16-resume-rag-design-fit-assessment.md`（设计适配性）
> 约束：非 EE MaxKB 内核；Embedding=bge-large-zh（512 token）；LLM=sensenova-6.8；Rerank=bge-reranker-v2-m3；pgvector
> 核心原则：**检索原子=简历，证据原子=段落；结构化优先、语义补位**

---

## 1. 设计目标

| 目标 | 含义 |
|---|---|
| G1 精确条件可保证 | 年限/学历/城市/状态等条件 100% 由 SQL 语义保证，不允许向量近似 |
| G2 语义命中可解释 | 每份命中简历给出证据段落（title+分数），HR 可核验 |
| G3 结构感知贯穿全程 | 章节/字段信息从切片流到检索与展示，不在任何层断流 |
| G4 合规默认 | PII 掩码先于任何 LLM 调用；展示按角色最小可见 |
| G5 降级链完备 | LLM/embed/rerank 任一失效检索仍可用 |
| G6 成本可控 | 每查询 ≤1 LLM（查询理解）+ 1 embed + 1 rerank |

## 2. 总体架构：五层检索

```
用户查询
L0 路由层   意图分类+槽位抽取（1 次 LLM，规则兜底）
  {intent: lookup|conditional|browse, skills[], years_min, degree, city[], semantic_query}
  ├─ lookup -----> SQL 精确找（姓名/电话/邮箱，Candidate.name 有索引）
  ├─ conditional -> L1 结构化层：Candidate SQL 预筛（保证 G1）
  │                    │ document_id 集合
  │                    ▼
  │               L2 语义层：双路召回（dense+sparse）限定预筛集内
  └─ browse ──────────────────────────────┘（无预筛直达 L2）
                       ▼
                L3 证据层：RRF -> rerank -> 简历级证据合成
                       ▼
                L4 呈现层：简历卡片（字段+证据段+PII 角色掩码）

数据面：简历 -> 解析 -> [结构化字段 + 章节序列] -> 切片{title, section_type, content}
        -> 索引三副本：dense 向量 / sparse tsvector / 结构化字段(+技能归一表)
```

## 3. 各层详细设计

### 3.1 解析与结构抽取

- **合并 LLM 调用**：切片边界与字段抽取（技能/年限/学历/城市归一）共用一次 LLM 调用（一个 prompt 同时输出行号边界 + 字段 JSON）。省一次调用、少一次 PII 暴露面。
- **PII 掩码前置**（修复评估文档缺陷 E）：发给 LLM 前先 `mask_pii`。行号安全性：现有掩码模式（手机/身份证/银行卡）均为行内替换、不含换行，**行数不变**，行号边界协议不受影响。保真语义更新为「相对掩码后原文保真」，`scan_residual_pii` 残留扫描保留为 backstop。手机/邮箱/姓名等结构化字段由**规则从原文抽取**入 Candidate（现有 resume_parser 路径），不依赖 LLM 从掩码文本恢复。
- 产出：`{fields, sections:[{section_type,line_range}], chunks}`；section_type 枚举：基本信息/教育/工作/项目/技能/其他（`_SECTION_RE` 扩展映射）。

### 3.2 切片协议（现状已验证，小增强）

- 保留：LLM 行号边界 + L2 校验 + 规则降级（dataset30：30/30 保真、29/30 LLM 路径）。
- 新增：chunk 元数据 `{section_type}`（title 已有）；同 section 连续小段（<100 字）在 **chunks 层**合并（content 不动），减少碎片。
- 500 字上限不变。

### 3.3 索引三副本

**机制精确化（自审修正，兼作对评估文档的勘误）**：内核 `list_embedding_text.sql` 的 text 列已 `concat_ws(E'\\n', title, content)`，但 `base_vector.chunk_data` **优先使用 Paragraph.chunks 字段**（创建时由 `text_to_chunk(content)` 派生、不含 title），故 title 实际不参与向量化与 tsvector（`tokenize_by_paragraph` 亦只用 chunks）。「标题断流」结论不变，机制如上。

| 副本 | v2 输入 | 落地杠杆 |
|---|---|---|
| dense | chunks 派生自 `"{title}\\n{content}"` | **杠杆 B（推荐，HR 侧零内核改动）**：`resume_index` 创建段落后补写 `chunks=["{title}\\n"+c for c in text_to_chunk(content)]`；content 保持原文（保真/展示/回溯不受影响）。杠杆 A（内核 1 行）：`ParagraphSerializer` chunks 派生时并入 title（L255/L426），与 list_embedding_text.sql 的 text 列意图一致化，但影响全部知识库，需重嵌+评测，后置 |
| sparse | 同上 + Termbase | **Termbase 在 HR 稀疏路已自动接入**（`KeywordsSearch().handle` 内部按 knowledge_id 查 Termbase，pg_vector.py:294-298；入库侧 `_batch_save` 同样生效）。落地 = 向 HR 知识库插入技能同义词词条 + **全量重嵌**（使 search_vector 分词与查询侧一致）。注意 `_sparse_query` 停用词表硬编码（经验/工作/熟悉/精通等），词条设计需避开 |
| 结构化 | Candidate 字段 + 新增 `candidate_skill(candidate_id, skill_norm, skill_raw)` 归一表 | Skill-AND 从逐技能向量召回 + Python 过滤，改为 SQL EXISTS；归一映射由字典冻结机制治理 |

### 3.4 L0 查询理解

- 一次 LLM 输出 `{intent, skills[], years_min, degree, city[], semantic_query}`。
- 规则兜底（LLM 不可用）：正则抽年限（`(\\d+)\\s*年`）、学历/城市词表；intent 缺省 browse。
- semantic_query = 去掉精确条件后的剩余语义词（避免"5 年以上 Java"整句 embed 稀释语义）。

### 3.5 L1 结构化预筛（G1 的保证）

- SQL：`status=ACTIVE AND years_experience>=n AND highest_degree∈(...) AND current_city∈(...) AND EXISTS(技能)`。
- 接入点（自审修正）：**HR `_recall_dual` 自建 query_set（resume_search.py:103）追加 `.filter(document_id__in=预筛文档集)`**；内核 `pg_vector.query` 虽有 document_id_list 参数，但 HR 路径不经由它。候选->文档映射经 ResumeFile.document_id。
- 边界：预筛为空 -> 返回空+meta（明确"无满足条件候选人"，不做语义兜底误导）；预筛 > 阈值（建议 2000）-> 放弃预筛转 browse+检索后过滤。

### 3.6 L2 语义召回

- 双路 + RRF 不变（已评测验证），在预筛集内执行；稀疏词上限 4 -> 6（配合 Termbase 归一）。
- section 显式加权（Phase 3）：需 Embedding 行带元数据，暂缓--title 入 chunks 后已天然部分生效。

### 3.7 L3 证据合成（修复缺陷 A）

- 段落级：RRF -> rerank（现有）。
- 简历级聚合升级：`score_resume = max(段分) + λ·log(1+命中段数)`，λ 初值 0.15，**绑定消融评测调参**；技能组合类沿用 hit_skills 向量并推广至 conditional 类。
- 输出 top-3 证据段 `{title, snippet, score}`（G2）。

### 3.8 L4 呈现与合规

- 简历卡片 = 结构化字段（`_mask_for_role` 角色掩码）+ 证据段引用 + 原文行号回溯高亮（切片协议保留行号区间）。

## 4. 关键取舍

| 备选 | 不采用原因 |
|---|---|
| doc 级单向量 | 简历长、语义稀释；chunk+聚合已验证 |
| ColBERT / late-interaction | 运维复杂度、pgvector 生态外 |
| GraphRAG | 简历实体关系简单，结构化字段+SQL 已覆盖 |
| 向量库 metadata 过滤 | Embedding 行无 metadata 列；document_id 过滤零改动 |
| 调权重 fusion | RRF 免调参已验证 |
| 查询理解与技能分解分两次 LLM | 延迟成本翻倍；合并单次 JSON 输出 |

## 5. 降级链

```
LLM 挂     -> 规则槽位抽取 + browse（检索不中断）
embed 挂   -> 稀疏单路 + 结构化层（sparse_failed 标记沿用）
rerank 挂  -> RRF 序（现有）
全挂       -> 纯 SQL 结构化检索（L1 独立可用）
```

## 6. 评测计划（修复缺陷 F）

- 分查询类型标注集各 30+：lookup / conditional / browse / skill-AND。
- 指标：conditional 类**条件精确率必须=1.0**（SQL 保证验证）；browse 类 recall@3/MRR；skill-AND hit-rate。
- 消融：title 入 chunks 前后、L1 预筛前后、证据合成前后--同一集复测，每个 Phase 一次。

## 7. 实施路线

| Phase | 内容 | 量级 |
|---|---|---|
| P1 快赢 | title 入 chunks（杠杆 B）；PII 掩码前置；证据合成聚合；查询理解 v1（规则槽位） | 1-2 天 |
| P2 结构化 | candidate_skill 归一表 + Skill-AND SQL 化；Termbase 词条 + 全量重嵌；L1 预筛接入 | 3-5 天 |
| P3 演进 | LLM 合并调用（切片+字段抽取）；section 显式加权；增量更新；分类型评测自动化 | 后置 |

每 Phase 过单测基线（当前 367）+ 评测集复测，独立提交。

## 8. 风险

1. 掩码前置对 LLM 字段/边界标注质量的影响 -> 规则抽取规避 PII 字段；dataset30 复测边界协议命中率；
2. 查询理解 +1 LLM 调用（~1s）-> 常见模式缓存；conditional 缺省走规则路径；
3. candidate_skill 字典治理 -> LLM 抽取+人工抽检+字典冻结；
4. λ 调参主观性 -> 绑定消融评测，不接受无评测调参；
5. title 入 chunks 改变检索行为 -> 仅 HR 知识库生效（杠杆 B），dataset30 前后对比。

## 9. 自审记录（v2 相对初稿的修正）

1. title 入向量杠杆从"改 embedding 输入"精确化为 **chunks 派生**（发现 list_embedding_text.sql 的 text 列已 concat title 但被 chunks 优先级覆盖）；并勘误评估文档中"title 既不进 embedding 也不进 search_vector"的机制描述（结论不变）。
2. Termbase 从"启用"修正为"**已自动接入**，落地=词条+全量重嵌"（KeywordsSearch.handle 内部已查 Termbase）。
3. L1 预筛接入点从"内核 pg_vector.query(document_id_list)"修正为"**HR _recall_dual 自建 query_set 加 document_id 过滤**"（HR 不走内核 query）。
