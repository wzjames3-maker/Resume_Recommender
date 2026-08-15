# 简历语义检索设计（阶段 3：Rerank + Small-to-Big + 量化对比）

> 日期：2026-08-15
> 状态：设计定稿（实施依据）
> 依据：../plans/2026-08-15-c-stage-resume-rag.md 阶段 3；../specs/2026-08-15-end-to-end-pipeline-combined-design.md §1.2/§6（检索流水线选型）
> 现状前提（代码盘点 2026-08-15）：Rerank 模型已注册（OpenAIRerankModel → SiliconFlow /rerank，top_n 默认 3）但零接入；知识库 hit_test（blend 双路召回）为唯一检索入口；HR 侧无简历正文语义检索 API；简历索引链路完备（每工作区"简历语义索引"知识库 + ResumeFile.document_id + 生命周期同步 + 流转日志）。

---

## 1. 检索管线（定稿）

```
用户查询（自然语言/JD 片段）
  → ① 参数校验 + 权限（hr_access_required，VIEWER 可搜但结果脱敏）
  → ② 取工作区简历知识库（无 → 400 "尚未建立简历语义索引"）
  → ③ vector.hit_test(blend, top_number=recall_k=10, similarity=0.2)
       复用知识库向量层：cosine + ts_rank_cd 双路融合召回 top10 段落
  → ④ Rerank 精排：HrConfig.rerank_model_id 实例 → bge-reranker-v2-m3
       rerank(query, [10 段落 content], top_n=top_k=5)
       无 rerank 配置/调用失败 → 自动降级：按 blend comprehensive_score 取 top_k
  → ⑤ Small-to-Big 回溯：段落.document_id → ResumeFile → Candidate
       每份简历保留最高分段落，多段落命中合并
  → ⑥ 输出：候选人 + 简历 + 命中段落 + 分数 + rank
       写检索审计（SEARCH 动作）
```

**为什么 rerank 放在 HR 服务层而不是知识库层**：知识库 hit_test 是通用能力（chat 等场景复用），改它影响面大；HR 简历检索有独立的权限/审计/回溯/脱敏要求，服务层组合（复用 vector 层与模型实例工厂）改动最小、可独立测试。

## 2. API 设计

### 2.1 POST /admin/api/workspace/{workspace_id}/hr/resumes/search

请求：
```json
{
  "query": "有幕墙系统设计经验的候选人",
  "top_k": 5,          // 最终返回条数，默认 5，clamp [1, 20]
  "recall_k": 10,      // 召回段数（blend topN），默认 10，clamp [5, 50]
  "similarity": 0.2    // 召回阈值（comprehensive_score 下限），默认 0.2，clamp [0, 2]
}
```

响应（result.success 包裹）：
```json
{
  "items": [
    {
      "rank": 1,
      "rerank_score": 0.87,
      "recall_score": 1.42,
      "candidate": {
        "id": "…", "name": "李冠光",
        "phone": "138****5678", "email": "ab***@example.com",
        "highest_degree": "硕士", "years_experience": 5,
        "skills": ["幕墙设计", "项目管理"], "status": "ACTIVE"
      },
      "resume": {"id": "…", "file_name": "李冠光.docx", "extension": "docx"},
      "paragraph": {"id": "…", "title": "工作经历-深圳大运置业 后端", "content": "…"},
      "document_id": "…"
    }
  ],
  "meta": {
    "recall_count": 10, "reranked": true,
    "rerank_model": "bge-reranker-v2-m3",
    "elapsed_ms": 342
  }
}
```

- 权限：`@hr_access_required`（VIEWER/OPERATOR/ADMIN 均可检索；VIEWER 输出 phone/email 脱敏——复用 `_masked_phone/_masked_email`）
- 审计：`write_audit_log(ws, user, "SEARCH", "RESUME", detail={query, top_k, recall_k, hit_count})`（新动作名 SEARCH；查询原文不落审计，避免 PII 入审计表——只记长度/命中数）
- 输入校验：query 必填且 ≤ 2000 字符；非法参数 400

### 2.2 配置扩展（AI 设置）

- `HrConfig` 增加 `rerank_model_id`（CharField，可空，迁移 0016）
- `GET/PUT /hr/ai/config` 返回/保存 `{llm_model_id, rerank_model_id}`；rerank 模型校验 `model_type == RERANKER` 且工作区可见（`get_model_by_id` 语义不变）
- 不配 rerank → 检索走纯 blend 降级（可正常使用，只是少精排）

## 3. 服务层（hr/services/resume_search.py）

```python
def search_resumes(workspace_id, query, top_k=5, recall_k=10, similarity=0.2):
    """简历语义检索：blend 召回 → rerank 精排 → Small-to-Big 回溯。
    返回 [{'candidate':..., 'resume':..., 'paragraph':..., 'rank', 'rerank_score', 'recall_score', 'document_id'}]"""
```

实现要点：
1. **知识库**：`get_resume_knowledge(workspace_id)`，None → `AppApiException(400, "简历语义索引尚未建立")`
2. **召回**：`vector = VectorStore.get_embedding_vector()`；`get_embedding_model_by_knowledge_id(knowledge.id)`；`vector.hit_test(query, [knowledge.id], exclude_document_id_list=[is_active=False 的 document], recall_k, similarity, SearchMode.blend, embedding)` → [{paragraph_id, similarity(=comprehensive_score)}]（blend SQL 仅返回段落 id + 分数，**不含 content**）；随后 `list_paragraph([paragraph_id…])`（knowledge/serializers/common.py）补全 content/title/document_id——rerank 输入与 Small-to-Big 回溯都依赖这一步
3. **Rerank**：`HrConfig.rerank_model_id` → `get_model_instance_by_model_workspace_id(rerank_model_id, workspace_id)` → `model.rerank(query, [p.content for p in paragraphs], top_n=top_k)` → [{index, relevance_score}]；按 index 映射回段落。异常（模型缺失/调用失败）→ 降级 blend 排序，meta.reranked=false
4. **回溯**：段落.document_id → `ResumeFile.objects.filter(workspace_id, document_id__in=...)` → candidate（select_related）；同简历多段落命中取最高分段落；简历无关联候选人（孤儿）仍可返回 resume 级结果
5. **脱敏**：VIEWER 角色对 candidate.phone/email 脱敏（服务层接收 hr_role 参数）
6. **审计**：命中数/耗时入 HrAuditLog（动作 SEARCH）；查询原文不入库

边界：
- 简历知识库为空（无文档）→ 返回空 items（200 非 400）
- 召回 0 段 → 空 items
- rerank 结果含 index 越界 → 忽略该条
- top_k > recall_k 时 clamp top_k ≤ recall_k

## 4. 测试计划

### 4.1 单测（hr/tests.py，新增 ResumeSearchTests，mock 不调真实模型）

| 用例 | 验证 |
|---|---|
| 检索成功（mock hit_test 返回 10 段 + mock rerank 返回排序） | 输出含 candidate/resume/paragraph/rank，top_k=5 截断 |
| 无 rerank 配置 → 降级 blend | meta.reranked=false，按 recall_score 排序 |
| rerank 调用失败 → 降级 | 不抛异常，仍返回 blend 排序结果 |
| 多段落命中同一简历 | 合并为一条，取最高分段落 |
| 简历知识库不存在 | 400 AppApiException |
| 知识库无文档 | 200 空 items |
| VIEWER 脱敏 | phone/email 掩码 |
| 审计写入 | SEARCH 动作记录，query 原文不在 detail 中 |
| 参数校验 | query 缺失/超长/top_k 越界 400 |

### 4.2 真实模型冒烟（installer/resume_search_smoke.py，渐进）

1. 复用已有入库数据（或 `resume_pipeline_smoke.py` 上传 3~5 份数据集简历）
2. 自然语言查询 3 个（如"有幕墙系统设计经验"、"有销售管理经验"、"财务主管"）
3. 输出每查询：blend top10 前 5 vs rerank 后 top5 排序对比 + 命中候选人姓名
4. 验收：rerank 后目标简历进入 top5、rerank_score 与 recall_score 排序差异可见

### 4.3 量化对比报告（阶段 3.3，落盘 audits/2026-08-15-c-stage-rerank-eval.md）

- 语料：数据集 30 份简历入库（向量化）
- 锚点查询集 10~15 个（实体型 5~7 + 自然语言型 5~8，从简历内容反向构造，标注目标简历）
- 三路对比：结构化基线（组合搜索：skills/degree/years 过滤 recall@5）vs blend top10 vs rerank top5
- 指标：recall@5（命中=目标简历在结果内）、rerank 后 recall@3、Top-1 准确率、平均排序位置
- 结论：rerank 是否优于纯 blend、语义是否优于结构化基线（PRD 完成定义）

## 5. 可选增强（阶段 3.4，按评测收益决策）

| 增强 | 内容 | 触发条件 |
|---|---|---|
| RRF 融合 | blend 分数加和 → RRF(k=60) 归一化 | 若 blend 分数尺度问题影响召回排序 |
| 画像向量路 A | 候选人级画像（skills/经历摘要）embedding 粗筛 | 若段落级检索对"候选人整体匹配"噪声大 |
| RAG Fusion 子查询 | 查询拆分子句分别召回再融合 | 长复合查询表现差时 |
| LLM title 摘要 | 检索时对 top 段落生成一句话摘要（+LLM 调用） | 需要可解释展示时 |

## 6. 预算（阶段 3 增量）

| 项 | 量 |
|---|---|
| Embedding（查询向量） | ~40 次（10~15 查询 × 1 + 冒烟/重复） |
| Rerank（/rerank 端点） | ~15 次（每查询 1 次） |
| LLM | 0（可选增强时才用） |

## 7. 验收（出口标准）

1. `hr.tests` 新增 ResumeSearchTests 全绿（mock 离线）
2. 真实模型冒烟通过（rerank 排序生效可见）
3. 量化对比报告落盘：rerank 后 recall@3 ≥ blend 前 3 命中率、语义检索 Top-K 相关性优于结构化基线（PRD §9.2 C 阶段完成定义）
4. 全量 342 + 新增回归通过；`makemigrations --check` 干净（HrConfig.rerank_model_id 迁移 0016）

> 关联：实施计划 ../plans/2026-08-15-c-stage-resume-rag.md 阶段 3；综合设计 §1.2/§6；HANDOFF §5.3
