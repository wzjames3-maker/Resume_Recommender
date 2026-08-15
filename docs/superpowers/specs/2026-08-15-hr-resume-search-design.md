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

**查询理解前置（新增）**：入口先做**查询分解**——LLM 解析用户查询为**带重要程度的技能列表**（扩展 ai_parser 的 _SEARCH_PROMPT_TEMPLATE 输出结构：技能逐项列出、不得合并复合词、**每项标注重要程度 required/preferred/nice_to_have**）：
- "会 java python fastapi agent rag 的人" →
  [ {skill: java, importance: required}, {skill: python, importance: required},
    {skill: fastapi, importance: preferred}, {skill: agent, importance: nice_to_have},
    {skill: rag, importance: nice_to_have} ]
  （"会 X"=required；"熟悉/了解/加分"=preferred/nice_to_have；LLM 无法判断默认 required）
- 解析失败/无技能 → 视为整句查询（走模式 A）
- 技能数 = 1 → 走模式 A（单技能与整句等价）
- 技能数 ≥ 2 → 走**模式 B：技能复合检索（Skill-AND）**

**重要程度的作用（三级权重）**：

| 级别 | 权重 | 语义 | 放宽策略 |
|---|---|---|---|
| required | 3.0 | 硬性必会（"会/精通/需要 X"） | 先决条件：required 未全命中不进入 top 候选 |
| preferred | 2.0 | 优先加分（"熟悉/优先"） | 第二步放宽：required 全命中后按 preferred 命中数排序 |
| nice_to_have | 1.0 | 加分项（"了解/有更好"） | 最后放宽：仅作为总分微调 |

简历总分 = Σ(命中技能 weight) / Σ(全部技能 weight) × 100（技能覆盖度）+ 语义加权分（命中的技能各自段落分均值）——先按覆盖度保证 AND 语义，再用语义分在同覆盖度内排序。

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
# 1) LLM 查询分解 → skills = [{java, required}, {python, required}, {fastapi, preferred},
#                             {agent, nice_to_have}, {rag, nice_to_have}]
#    （扩展 ai_parser 模板：每技能带重要程度；"会/精通"→required，"熟悉/优先"→preferred，"了解/有更好"→nice）
# 2) 结构化路（并行）：Candidate.skills 含 required 全部技能的候选人 → AND 精确过滤（已有组合搜索能力）
#    命中即"铁证"，直接列为候选，按 required→preferred 覆盖度排序
# 3) 语义路（并行）：对每个技能**单独** embedding + 双路召回 + RRF（同模式 A ④⑤，k=5 → 5 次 embed）
#    每个技能各自返回该技能最相关的段落 top(m) —— 技能是短词，单技能查询更精准
# 4) 简历级加权聚合（核心）：按 document_id 聚合技能命中矩阵
#    hits[resume][skill] = 该技能在该简历任意段落中的最高分（> 阈值即"命中该技能"）
#    coverage = Σ(命中技能 weight) / Σ(全部技能 weight)          # 权重: required=3.0/preferred=2.0/nice=1.0
#    semantic = mean(命中技能段落分)                               # 同覆盖度内用语义分排序
#    resume.score = coverage × 100 + semantic（先保证 AND 语义，再语义精排）
# 5) 分级放宽（重要程度感知）：required 未全命中 → 不进入候选；
#    required 全命中但候选不足 top_k → 放宽 preferred 命中数要求（k-1 → 0）；
#    仍不足 → 允许缺 1 个 required（meta.skill_relaxed 记录放宽级别）
# 6) Rerank 精排 top_k（对候选段落）
```

**为什么技能要单独检索而不是整句**：整句 "java python fastapi agent rag" 的 embedding 是一个混合向量——
- 语义上"java 工程师"和"会 java 的人"分布不同，混合向量对任一技能都不精准；
- 简历 A 只提 java、简历 B 只提 python，整句检索可能把两者都排在前面，但**没有一份简历同时满足 AND**；
- 技能单独检索 + 简历级加权聚合后，"required 全命中 + preferred/nice 命中多"的简历自然排最前——AND 语义与重要程度同时显式成立。

**为什么需要重要程度排序**：用户说"会 java python fastapi agent rag 的人"时，java/python 是硬条件、agent/rag 只是加分——若全部技能等权，一个"5 项都只提一句"的简历可能压过一个"java/python 精通但没提 agent"的简历（后者才是用户要的）。LLM 标注重要程度后，**required 是筛子、preferred 是排序、nice 是微调**，避免等权 AND 把真正合适的人挤下去。

**结构化路与语义路的关系**：结构化路（Candidate.skills 含 required）命中的候选人 = 精确满足，权重最高；语义路捕获"技能写在正文但没进结构化字段"（如 fastapi/agent/rag 常在项目描述里）的简历。两路按 coverage 统一排序。

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
    "search_type": "hybrid_rrf_reranked",
    "recall": {"dense": 15, "sparse": 9, "fused": 15, "candidate_k": 15},
    "rerank": {"enabled": true, "model": "bge-reranker-v2-m3", "top_n": 5, "failed": false},
    "aggregation": {"grouped_resumes": 6, "dropped_orphan_paragraphs": 2},
    "elapsed_ms": {"total": 342, "recall": 85, "rerank": 210, "aggregate": 12},
    "query": {"length": 18, "truncated": false}
  }
}
```

- 权限：`@hr_access_required`；VIEWER phone/email 脱敏（复用 `_masked_phone/_masked_email`）
- 审计：`write_audit_log(ws, user, "SEARCH", "RESUME", detail={query_len, top_k, mode, hit_count, search_type})`——**查询原文不落审计**（PII 治理，与 A3 审计规范一致）
- 输入校验：query 必填 ≤2000 字符；参数越界 400；`mode` 仅 auto|hybrid|dense

### 3.2 配置扩展（AI 设置）

- `HrConfig` 增加 `rerank_model_id`（CharField 可空，迁移 0016）；`GET/PUT /hr/ai/config` 返回/保存 `{llm_model_id, rerank_model_id}`，rerank 校验 `model_type == RERANKER` 且工作区可见
- 不配 rerank → 检索正常降级（RRF 排序），AI 配置页可看到未配置提示

## 4. 模块设计（hr/services/resume_search.py）

```python
# 常量
_RRF_K = 60
_RESUME_SCORE_MAX_WEIGHT = 0.7   # 聚合：max 段分权重
_RESUME_SCORE_AVG_WEIGHT = 0.3   # 聚合：avg 段分权重
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

_IMPORTANCE_WEIGHT = {"required": 3.0, "preferred": 2.0, "nice_to_have": 1.0}

def _parse_skills(query, llm_model) -> list[dict]:
    """LLM 查询分解为 [{skill, importance}]（复用 ai_parser 模板并扩展输出 required/preferred/nice_to_have）；
    失败返回 []（退模式 A）。"""

def _coverage_score(hits, skills) -> float:
    """覆盖度 = Σ(命中技能 weight) / Σ(全部技能 weight)；required 未全命中返回 0（不进入候选）。"""

def _search_skill_and(skills, structured_hits, knowledge, embedding_model, candidate_k, similarity, top_k):
    """模式 B 主干：每技能单独双路召回 → RRF → 简历级加权聚合(coverage+semantic) → 分级放宽 → rerank。"""
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
| 模式 B：查询分解（mock LLM 返回 5 技能带重要程度） | 走 Skill-AND、importance 解析正确（required/preferred/nice） |
| 模式 B：覆盖度加权 | required 全命中优先于等权命中、coverage 公式正确 |
| 模式 B：required 未全命中被筛除 | 不进入候选，meta 记录放宽级别 |
| 模式 B：技能命中矩阵聚合 | 全命中排前、部分命中靠后、加权总分正确 |
| 模式 B：渐进放宽 | 全命中不足 top_k → 放宽 k-1，meta.skill_relaxed 记录 |
| 模式 B：技能解析失败 | 退化模式 A 整句检索，meta.mode=phrase |
| 模式 B：结构化路命中 | Candidate.skills 全含 → 权重最高排前 |

### 5.2 真实模型冒烟（installer/resume_search_smoke.py，渐进）

1. 入库 5~10 份数据集简历（复用 resume_pipeline_smoke.py 或直接 SQL 造数）
2. 6 个查询：实体型"有幕墙系统设计经验"、技能型"熟悉 Python 和 Django"、自然语言型"有销售管理经验的候选人"、复合型"3 年以上财务主管经验"、**技能复合型"会 java python fastapi agent rag 的人"（模式 B：5 技能带重要程度 → 各自检索 → 加权聚合）**、**权重对比型"会 java 精通 python 了解 rag 的人"（验证 required/preferred/nice 分级生效）**
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
2. 真实模型冒烟通过（四类查询 rerank 排序生效、meta 完整、降级可触发）
3. 量化对比报告落盘：RRF 融合 ≥ dense-only、rerank 后 recall@3 ≥ RRF、语义检索 Top-K 相关性优于结构化基线（PRD §9.2 C 阶段完成定义）
4. 全量 342 + 新增回归通过；`makemigrations --check` 干净（仅 HrConfig.rerank_model_id 迁移 0016）

> 关联：实施计划 ../plans/2026-08-15-c-stage-resume-rag.md 阶段 3；综合设计 §1.2/§6；HANDOFF §5.3