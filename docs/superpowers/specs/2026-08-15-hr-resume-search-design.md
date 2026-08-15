# 简历语义检索设计 v2（阶段 3：双路召回 + RRF 融合 + Rerank + Small-to-Big）

> 日期：2026-08-15（v2 重写：吸收 7 个开源项目检索设计调研，见下 §1）
> 状态：设计定稿（实施依据）
> 依据：../plans/2026-08-15-c-stage-resume-rag.md 阶段 3；../specs/2026-08-15-end-to-end-pipeline-combined-design.md §1.2/§6
> 调研来源：MewAgent（LangGraph 状态机+三级混合）、HireFlow（路由分级）、resume-rag-ranker（画像重排）、smart-ats（薄向量层）、hr-rag-assistant（极简）、Hungreeee（RAG Fusion+Small-to-Big）、xt765/ResumeScreening（Agentic RAG 加权 RRF）

---

## 1. 开源调研 → 本仓库映射（8 条模式逐一定夺）

| # | 开源模式 | 出处 | 本仓库决策 | 理由 |
|---|---|---|---|---|
| 1 | 候选放大 candidate_k = top_k × 3 | MewAgent | ✅ **采纳**：recall_k = top_k × 3（clamp [15, 60]），重排后再截断 | 防召回不足；成本仅 SQL 多返回几行 |
| 2 | 稠密+稀疏双路 + RRF(k=60) | MewAgent/Milvus | ✅ **采纳（Python 侧）**：dense=EmbeddingSearch(cosine) 独立路 + sparse=KeywordsSearch(ts_rank_cd+Termbase) 独立路 → Python 侧 score = Σ 1/(k+rank) 融合 | 两路独立 SQL 已存在（embedding_search.sql / keywords_search.sql），只需一次 embed 两次 handle，RRF 在服务层 5 行实现。**术语澄清**：本仓库"稀疏路"就是**关键词检索**（jieba 分词 → PostgreSQL tsvector → ts_rank_cd 排名，BM25 家族），与 MewAgent 的 BM25 路/xt765 的 BM25 工具同族——不是额外第三路，也没有去掉关键词检索。学习型稀疏向量（bge-m3 sparse/SPLADE，模型产出的高维稀疏向量）为可选增强 E，pgvector 0.8.6 已支持 sparsevec |
| 3 | 路由分级浅/深检索 | HireFlow | ⏳ **可选增强（v2）**：查询词数 ≤3 → shallow（纯 dense）；否则 deep（全管线）；LLM 路由后置 | v1 全走 deep 简单可靠；路由收益待评测 |
| 4 | 评分-重写-再检索循环 | MewAgent grader | ⏳ **可选增强（v2）**：LLM 二分相关性 + step-back/HyDE 重写 | 每查询 2~4 次 LLM 调用，成本高；先做量化对比看 rerank 是否已够 |
| 5 | 画像重排（LLM 一次评 10 人） | resume-rag-ranker | ⏳ **可选增强（v2）**：rerank 后对 top 候选人用结构化画像（Candidate.skills/degree/years/note）做 LLM 批量打分 | 1 次调用/查询；画像字段已具备 |
| 6 | chunk 检索、原文输出（Small-to-Big） | Hungreeee | ✅ **采纳**：段落命中 → document_id → 整份简历/候选人 | 天然支持（简历=Document） |
| 7 | 向量只返回 id、详情回业务库 | smart-ats | ✅ **采纳**：SQL 只返回 paragraph_id+score，content/简历/候选人一律 list_paragraph + ORM 回查；阈值过滤 similarity ≥ 0.2（可配） | 已有模式（hit_test 即如此）；保持向量层最薄 |
| 8 | 全链路 meta 追踪 | MewAgent/HireFlow | ✅ **采纳**：每次检索返回 meta（两路命中数/融合数/rerank 状态/聚合组数/各步耗时/失败原因） | 可观测、可调优、前端可展示检索步骤 |

**明确不采纳**：Milvus 库内 RRFRanker（无第二套向量库）、parent_chunk_store 三级合并（简历两级即 document_id 回溯，无需三级）、sparsevec 稀疏列（tsvector+Termbase 已等价且带用户词典）、Neo4j 图谱（无图谱数据）。

## 2. 检索管线 v2（定稿）

**查询理解前置（新增）**：入口先做**查询分解**——LLM 解析用户查询为**按重要程度排序的技能列表**（扩展 ai_parser 的 _SEARCH_PROMPT_TEMPLATE 输出结构：技能逐项列出、不得合并复合词、**按重要程度降序排列，最重要的在最前**）：
- "会 java python fastapi agent rag 的人" → skills = [java, python, fastapi, agent, rag]（java/python 是主要技能排前，agent/rag 加分项排后）
- 解析失败/无技能 → 视为整句查询（走模式 A）
- 技能数 = 1 → 走模式 A（单技能与整句等价）
- 技能数 ≥ 2 → 走**模式 B：技能复合检索（Skill-AND）**
- **技能数封顶 10**（超出取前 10，meta.skills_truncated=true）：每技能 1 次 embed + 1 轮双路查询，封顶控制成本与延迟

**重要程度 = 检索顺序（不是权重分数）**：LLM 只负责**排序**，排序决定了进入双路召回的先后——
1. **重要的技能先进入双路查询**（dense+sparse+RRF），其召回结果先落候选池、质量更高；
2. **排序依据**：简历按"命中技能在有序列表中的位置"比较——命中靠前技能的简历优先（命中向量字典序，见模式 B §4），**不是加权求和**；
3. **放宽顺序**：先放宽到只要求靠前的 m 个技能命中，再向后逐级放宽（meta.skill_relaxed 记录放宽到第几顺位）；
4. 语义分仅在同位次命中内做二次排序（段落分均值），不参与跨位次比较。

### 模式 A：整句检索（单意图/无技能查询）

```
  → ① 校验 + 权限（hr_access_required；VIEWER 结果脱敏）
  → ② 取简历知识库（无 → 400 简历语义索引尚未建立）
  → ③ 一次 embedding（query → 向量；get_embedding_model_by_knowledge_id）
  → ④ 双路独立召回（candidate_k = top_k × 3，同知识库，排除 is_active=False 文档）：
       dense  ：EmbeddingSearch.handle → [{paragraph_id, similarity}] rank_d
       sparse ：KeywordsSearch.handle（=关键词检索：jieba→tsvector→ts_rank_cd）→ [{paragraph_id, similarity}] rank_s
  → ⑤ RRF 融合（k=60）：score(d) = 1/(k+rank_d(d)) + 1/(k+rank_s(d))（单路命中另一路记 0）
       fused = 融合分 top(candidate_k)；同时保留 dense_score/sparse_score 单列展示
  → ⑥ list_paragraph 补全 content/title/document_id
  → ⑦ Rerank 精排：HrConfig.rerank_model_id → bge-reranker-v2-m3
       rerank(query, [fused 段落 content], top_n=top_k)
       未配置/失败 → 降级：按 RRF 融合分取 top_k（meta.reranked=false）
  → ⑧ Small-to-Big + 聚合打分：段落 → document_id → ResumeFile → Candidate；
       每简历聚合分 = 0.7 × max(段落分) + 0.3 × avg(段落分)（resume-rag-ranker 模式），
       多段落命中合并为一条，段落列表按分排序（Small-to-Big 保留上下文）
  → ⑨ 输出 items + meta（全链路追踪）+ SEARCH 审计（查询原文不入库）
```

### 模式 B：技能复合检索（Skill-AND，多技能 AND 查询）

```python
# "会 java python fastapi agent rag 的人" 的检索方式：
# 不是整句向量化（会把 5 个技能混成一个向量、丢失 AND 约束），而是：
# 1) LLM 查询分解 → 有序技能列表 skills = [java, python, fastapi, agent, rag]（重要在前）
#    （扩展 ai_parser 模板：逐项列出、按重要程度降序；LLM 不做数值权重，只排顺序）
# 2) 结构化路（并行）：Candidate.skills 与 skills 的命中向量（按有序列表逐位判断）→ 精确候选
# 3) 语义路（顺序进入双路！核心）：对每个技能**按序**单独 embedding + 双路召回 + RRF：
#    round 1: java   → 双路查询 → 候选池 A（命中 java 的段落）
#    round 2: python → 双路查询 → 候选池 B（A ∪ 命中 python 的段落）
#    round 3: fastapi → 双路查询 → 候选池 C
#    ...（agent/rag 最后进入，只补充）
#    技能是短词，单技能查询比整句更精准；先进入的技能结果质量优先。
# 4) 简历级有序聚合（核心，命中向量字典序——不是加权求和）：
#    hit_vec[resume] = [技能1命中?, 技能2命中?, …]（按有序列表顺序）
#    排序：hit_vec 按字典序比较——命中靠前技能优先（[1,1,0,0,0] > [1,0,1,0,0] > [0,1,1,0,0]）
#    同 hit_vec 内再用段落分均值（semantic）二次排序
# 5) 顺序放宽：top_k 不足时按顺位放宽——先要求前 2 个技能命中，不足 → 前 1 个，
#    仍不足 → 无技能约束（整句）（meta.skill_relaxed 记录放宽到第几顺位）
# 6) Rerank 精排 top_k（对候选段落，query 用原查询）
```

**为什么技能要单独检索而不是整句**：整句 "java python fastapi agent rag" 的 embedding 是一个混合向量——
- 语义上"java 工程师"和"会 java 的人"分布不同，混合向量对任一技能都不精准；
- 简历 A 只提 java、简历 B 只提 python，整句检索可能把两者都排在前面，但**没有一份简历同时满足 AND**；
- 技能单独检索 + 命中向量字典序聚合后，"命中靠前技能多"的简历自然排最前——AND 语义与重要程度顺序同时显式成立。

**为什么是"顺序"而不是"权重"**：用户说"会 java python fastapi agent rag 的人"时，java/python 是主要技能、agent/rag 是加分项。两种实现方式：
- **权重方案**（已否决）：给每个技能算分数系数（required=3/preferred=2…）——打分公式复杂、系数难调、不好解释；
- **顺序方案（采纳）**：LLM 只排顺序，**重要的技能先进入双路召回**——顺序即优先级：
  - 实现简单（一个有序列表，无系数）；
  - 检索执行天然体现优先级（先查的重要技能先落候选池）；
  - 排序用命中向量字典序（可解释：谁先满足重要技能谁排前）；
  - 放宽也是按顺位（先保重要技能，再逐步放开）。
- 一句话：**重要程度决定"谁先进双路查询"，不决定"谁的分值高"**。

**命中判定（排序与放宽的基准）**：技能 s 命中简历 r ⇔ s 在 r 的任意段落中 dense similarity ≥ 阈值（默认 0.2，与召回阈值同源可配）——**命中判定只看 dense 路分数**（尺度稳定可比），RRF/rerank 分数不参与命中判定，只用于同 hit_vec 内的二次排序与最终精排。

**候选池不截断**：每轮技能召回后，候选池 = 已收段落 ∪ 新技能段落（**不按 top 截断**）——放宽到"只要求 java"时，java 低分简历仍在池中，放宽才有效；最终输出时才按排序键取 top_k。

**AND 语义的精确定义（避免歧义）**：模式 B 的"AND"指**命中向量的字典序排序**（全命中 > 只命中前段 > 未命中靠前技能），不是 SQL 式硬性 AND 过滤——排序即筛选，避免"技能全命中才返回"导致空结果。放宽顺位 m 控制参与排序的前缀长度：m=len(skills)（默认）→ 全部技能参与命中向量；m 递减 → 只比较前 m 个技能，后面的技能不参与排序（也不影响放宽）。结构化路的 m 与语义路共用此顺位：结构化路命中数 ≥ 语义路放宽线即可进入候选。

**短技能词的精度互补**：英文短词（java/fastapi）dense 路区分度差（"java"与"JavaScript"向量相近）——dense 路负责语义召回（会漏的靠它捞），**sparse 路（tsvector 精确词匹配）负责专名精确命中**，两路 RRF 互补；"java"被 jieba 切为整词、tsquery 精确匹配，sparse 路天然精确。量化评测中如短词误命中仍偏高，再评估技能词加限定语（"会 java 的候选人"）作为查询文本（可选增强 F）。

**结构化路与语义路的关系**：结构化路（Candidate.skills 与有序列表前段交集）命中的候选人 = 精确满足，直接进候选（命中向量按实际交集构造）；语义路捕获"技能写在正文但没进结构化字段"（如 fastapi/agent/rag 常在项目描述里）的简历。两路统一按命中向量字典序排序，同一候选人两路都命中时按段落并集计算 hit_vec（不重复计）。

**降级链（渐进可用，每级都可独立关闭）**：rerank → RRF 融合 → dense 单路 → 空结果+meta
- rerank 未配置：跳过精排，聚合排序直出
- 关键词路失败（Termbase 缺失等）：dense 单路 + meta.sparse_failed=true
- 技能解析失败（LLM 不可用）：退化模式 A（整句检索）
- 知识库无文档：空 items（200）

## 3. API 设计

### 3.1 POST /admin/api/workspace/{workspace_id}/hr/resumes/search

请求：
```json
{
  "query": "有幕墙系统设计经验的候选人",
  "top_k": 5,          // 最终返回条数，默认 5，clamp [1, 20]
  "recall_k": 15,      // 候选放大召回段数，默认 = top_k*3，clamp [5, 60]
  "similarity": 0.2,   // 阈值（dense 路 similarity 下限），默认 0.2，clamp [0, 2]
  "mode": "auto"       // auto(自动分解:技能≥2→Skill-AND,否则整句) | hybrid | dense | phrase(强制整句) | skills(强制技能分解)
}
```

响应：
```json
{
  "items": [
    {
      "rank": 1,
      "candidate": {
        "id": "…", "name": "李冠光",
        "phone": "138****5678", "email": "ab***@example.com",
        "highest_degree": "硕士", "years_experience": 5,
        "skills": ["幕墙设计", "项目管理"], "status": "ACTIVE"
      },
      "resume": {"id": "…", "file_name": "李冠光.docx", "extension": "docx"},
      "score": {"resume": 0.87, "rerank": 0.91, "rrf": 0.021, "dense": 0.78, "sparse": 0.31},
      "paragraphs": [
        {"id": "…", "title": "工作经历-深圳大运置业 后端", "content": "…", "score": 0.91}
      ],
      "document_id": "…"
    }
  ],
  "meta": {
    "search_type": "hybrid_rrf_reranked",   // 模式A: hybrid_rrf_reranked | hybrid_rrf | dense_only | phrase_fallback
                                             // 模式B: skill_ordered_reranked | skill_ordered | skill_ordered_fallback
    "mode": "auto",                          // auto|hybrid|dense|phrase|skills（实际执行模式）
    "skills": ["java", "python", "fastapi", "agent", "rag"],  // 模式B：有序技能列表（重要在前）
    "recall": {"dense": 15, "sparse": 9, "fused": 15, "candidate_k": 15, "rounds": 5},
    "rerank": {"enabled": true, "model": "bge-reranker-v2-m3", "top_n": 5, "failed": false},
    "aggregation": {"grouped_resumes": 6, "dropped_orphan_paragraphs": 2, "skill_relaxed": 2},
    "elapsed_ms": {"total": 342, "recall": 85, "rerank": 210, "aggregate": 12},
    "query": {"length": 18, "truncated": false}
  }
}
```

- **score 字段尺度**（可解释性约定）：
  - `rrf`：RRF 融合分（≈1/(60+rank) 量级，仅模式内相对比较）；
  - `dense`/`sparse`：两路原始分（dense≈余弦相似度 0~1；sparse≈ts_rank_cd 0~1）；
  - `rerank`：bge-reranker 的 relevance_score（0~1，精排依据）；
  - `resume`：简历聚合分（模式 A = 0.7×max+0.3×avg 段落分；模式 B = 命中向量顺位 + 段落分均值），**仅同模式内可比**；
  - 排序键：模式 A 用 resume 聚合分、模式 B 用命中向量字典序（见 §2），rerank 分数是精排后的最终展示分。
- 权限：`@hr_access_required`；VIEWER phone/email 脱敏（复用 `_masked_phone/_masked_email`）
- 审计：`write_audit_log(ws, user, "SEARCH", "RESUME", detail={query_len, top_k, mode, hit_count, search_type})`——**查询原文不落审计**（PII 治理，与 A3 审计规范一致）
- 输入校验：query 必填 ≤2000 字符；参数越界 400；`mode` 仅 auto|hybrid|dense|phrase|skills

### 3.2 配置扩展（AI 设置）

- `HrConfig` 增加 `rerank_model_id`（CharField 可空，迁移 0016）；`GET/PUT /hr/ai/config` 返回/保存 `{llm_model_id, rerank_model_id}`，rerank 校验 `model_type == RERANKER` 且工作区可见
- 不配 rerank → 检索正常降级（RRF 排序），AI 配置页可看到未配置提示

## 4. 模块设计（hr/services/resume_search.py）

```python
# 常量
_RRF_K = 60
_RESUME_SCORE_MAX_WEIGHT = 0.7   # 模式A 简历聚合：max 段分权重（段落级，与技能顺序无关）
_RESUME_SCORE_AVG_WEIGHT = 0.3   # 模式A 简历聚合：avg 段分权重（段落级，与技能顺序无关）
_DEFAULT_SIMILARITY = 0.2
_MAX_QUERY_LENGTH = 2000

def search_resumes(workspace_id, query, top_k=5, recall_k=None, similarity=0.2,
                   mode="auto", hr_role=None, user_id=None) -> dict:
    """入口：返回 {"items": [...], "meta": {...}}。逐步走降级链，任何一级失败不抛 500。"""

def _recall_dual(query, knowledge, embedding_model, candidate_k, similarity, mode):
    """双路召回：一次 embed，分别调 EmbeddingSearch/KeywordsSearch.handle，
    返回 {dense: [{paragraph_id, similarity}], sparse: [{paragraph_id, similarity}]}。"""

def _rrf_fuse(dense, sparse, k=_RRF_K) -> list[dict]:
    """Python RRF：score(d) = Σ 1/(k+rank)；返回 [{paragraph_id, rrf, dense, sparse}] 降序。"""

def _rerank(query, fused, rerank_model, top_n) -> tuple[list, bool]:
    """bge-reranker-v2-m3 精排；异常 → (按 rrf 排序结果, False)。"""

def _aggregate(paragraphs, resume_map) -> list[SearchResult]:
    """Small-to-Big + 简历聚合：0.7*max + 0.3*avg；同简历合并；孤儿段落仍返回 resume 级。"""

def _parse_skills(query, llm_model) -> list[str]:
    """LLM 查询分解为**有序技能列表**（复用 ai_parser 模板并扩展：逐项列出、按重要程度降序）；
    失败返回 []（退模式 A）。"""

def _hit_vector_key(hit_vec) -> tuple:
    """命中向量字典序排序键：命中靠前技能优先（[1,1,0,0,0] > [1,0,1,0,0]）。"""

def _search_skill_and(skills, structured_hits, knowledge, embedding_model, candidate_k, similarity, top_k):
    """模式 B 主干：按序逐技能双路召回（重要先进入）→ 候选池累积 → 命中向量字典序排序 → 顺位放宽 → rerank。"""
```

复用点（不改内核）：
- `vector.hit_test` 不直接调（它内部每次 embed）；改用 `VectorStore.get_embedding_vector()` 拿 store 后直接调 `EmbeddingSearch()/KeywordsSearch()` 的 `handle`（一次 embed 两次检索），query_set 构造照抄 hit_test 模式（`filter(knowledge_id=…, is_active=True).exclude(document_id__in=…)`）
- `get_embedding_model_by_knowledge_id`（knowledge/serializers/common.py）、`list_paragraph`（同文件）原样复用
- `get_model_instance_by_model_workspace_id`（models_provider/tools.py）取 RERANKER 实例（top_n 默认 3 已内置）

## 5. 测试计划

### 5.1 单测（hr/tests.py，ResumeSearchTests，mock 不调真实模型）

| 用例 | 验证 |
|---|---|
| 双路召回 + RRF 融合（mock 两路结果） | 融合分正确、dense/sparse 单列保留 |
| 单路命中（dense 有 sparse 无） | 融合分 = 单路贡献，不丢结果 |
| rerank 精排生效 | top_k 截断、rerank 分排序、meta.reranked=true |
| rerank 未配置 → 降级 | 按 rrf 排序、meta.reranked=false |
| rerank 异常 → 降级 | 不抛异常，仍返回结果 |
| 聚合打分 | 0.7*max+0.3*avg 正确、多段落合并、段落列表保留 |
| 孤儿段落（无候选人） | 仍返回 resume 级结果 + meta 计数 |
| 知识库不存在 / 无文档 | 400 / 200 空 items |
| VIEWER 脱敏 | phone/email 掩码 |
| SEARCH 审计 | 动作记录、query 原文不在 detail |
| 参数校验 | query 缺失/超长/mode 非法/top_k 越界 400 |
| mode=dense | 只走 dense 路（评测用） |
| 模式 B：查询分解（mock LLM 返回 5 技能有序列表） | 走 Skill-AND、顺序保持（java/python 在前） |
| 模式 B：顺序进入双路 | 调用顺序 = 技能顺序（先 java 后 agent）、候选池累积 |
| 模式 B：命中向量字典序 | [1,1,0,0,0] > [1,0,1,0,0] > [0,1,1,0,0]，排序正确 |
| 模式 B：顺位放宽 | 前 2 命中不足 top_k → 放宽前 1 → 整句，meta.skill_relaxed 记录顺位 |
| 模式 B：候选池不截断 | 放宽后低分简历仍在池中（放宽不失效） |
| 模式 B：技能解析失败 | 退化模式 A 整句检索，meta.mode=phrase |
| 模式 B：结构化路命中 | Candidate.skills 含前 m 技能 → 命中向量按实际交集构造、统一排序 |

### 5.2 真实模型冒烟（installer/resume_search_smoke.py，渐进）

1. 入库 5~10 份数据集简历（复用 resume_pipeline_smoke.py 或直接 SQL 造数）
2. 6 个查询：实体型"有幕墙系统设计经验"、技能型"熟悉 Python 和 Django"、自然语言型"有销售管理经验的候选人"、复合型"3 年以上财务主管经验"、**技能复合型"会 java python fastapi agent rag 的人"（模式 B：5 技能有序 → 按序进入双路 → 命中向量排序）**、**顺序对比型"精通 java 熟悉 python 了解 rag"（验证技能进入双路的先后顺序生效）**
3. 每查询打印：dense top5 / sparse top5 / RRF top5 / rerank top5 排序对比 + 命中候选人 + meta
4. 验收：rerank 排序与 RRF 差异可见；meta 字段完整；降级路径可手动触发验证

### 5.3 量化对比报告（阶段 3.3，落盘 audits/2026-08-15-c-stage-rerank-eval.md）

- 语料：数据集 30 份简历入库（向量化）
- 锚点查询 10~15 个（实体型 5~7 + 自然语言型 5~8，从简历内容反向构造，标注目标简历）
- 对比：结构化基线（组合搜索 recall@5）vs dense-only vs RRF 融合 vs RRF+rerank vs **Skill-AND（模式 B，技能复合查询）**
- 指标：recall@5（各模式）、rerank 后 recall@3、Top-1 准确率、MRR、平均排序位置
- 结论：RRF 是否优于单 dense、rerank 是否再提升、语义是否优于结构化基线（PRD 完成定义）

## 6. 可选增强（v2，按评测收益决策，每项独立小任务）

| 增强 | 内容 | 触发条件 | 成本 |
|---|---|---|---|
| A 路由分级 | 词数 ≤3 → 纯 dense（快）；否则全管线 | 评测显示简单查询 rerank 收益低 | 0（规则） |
| B 查询重写循环 | LLM grader 判相关性不过 → step-back/HyDE 重写再查 | rerank 后 recall@3 仍低 | ~2-4 次 LLM/查询 |
| C 画像重排 | rerank 后 LLM 用结构化画像批量打分（1 次/查询） | 需要可解释匹配分 | ~1 次 LLM/查询 |
| D RAG Fusion 子查询 | 长复合查询 LLM 拆子句分别召回 RRF | 复合查询表现差 | ~1 次 LLM/查询 |
| E 学习型稀疏向量 | bge-m3 sparse / SPLADE 编码段落与查询为稀疏向量（pgvector sparsevec 列 + HNSW 稀疏索引），替换或补充 jieba+tsvector 关键词路 | 关键词路在专有名词/同义/未登录词上表现差，量化对比显示关键词路拖后腿 | 入库每段 +1 次模型调用（bge-m3 可同时出 dense+sparse，一次调用双份）+ 新列/新索引迁移 |

## 7. 预算（阶段 3 增量）

| 项 | 量 |
|---|---|
| Embedding（查询向量） | ~60 次（模式 A 每查询 1 次；模式 B 每技能 1 次（技能数 ≤ 10 封顶，如 5 技能=5 次）；评测 + 冒烟合计） |
| Rerank（/rerank 端点） | ~15 次（每查询 1 次） |
| LLM | 0（仅可选增强 B/C/D 时） |
| SQL | 零新增（复用 embedding_search/keywords_search.sql） |

## 8. 验收（出口标准）

1. ResumeSearchTests 全绿（mock 离线）
2. 真实模型冒烟通过（六类查询 rerank 排序生效、meta 完整、降级可触发）
3. 量化对比报告落盘：RRF 融合 ≥ dense-only、rerank 后 recall@3 ≥ RRF、语义检索 Top-K 相关性优于结构化基线（PRD §9.2 C 阶段完成定义）
4. 全量 342 + 新增回归通过；`makemigrations --check` 干净（仅 HrConfig.rerank_model_id 迁移 0016）

> 关联：实施计划 ../plans/2026-08-15-c-stage-resume-rag.md 阶段 3；综合设计 §1.2/§6；HANDOFF §5.3