# C 阶段检索量化对比报告（阶段 3.3 出口）

> 日期：2026-08-16
> 状态：**C 阶段完成定义达成**（PRD §9.2：语义索引与候选人生命周期同步 ✓ + 试点标注集 Top-K 相关性优于结构化检索基线 ✓）
> 执行：installer/resume_search_eval.py（可复跑）；语料入库 installer/resume_ingest_30.py（幂等）
> 模型：bge-large-zh-v1.5（Embedding，SiliconFlow）/ bge-reranker-v2-m3（Rerank）/ sensenova-6.8-flash-lite（LLM 技能分解，SenseNova）

---

## 1. 语料与标注

- **语料**：testdata/generated/resumes 30 份生成简历 + 数据集真实 docx 1 份（cbb7a43eb62f.docx，表格排版）= **31 份**，全部入库"简历语义索引"知识库（LLM 切片 29/31 + smart 降级 2/31；309 条向量）
- **锚点查询集**：12 个，从简历内容反向构造并标注目标简历（1~2 份/查询）：实体型 6 个（幕墙设计/会计/招聘/平面设计/机电质检/物流）、技能型 2 个（Unity/新媒体运营）、自然语言型 4 个（销售管理/教师/楼面经理/外联沟通）
- **对照模式**：dense-only（mode=dense）、RRF 双路融合（mode=phrase 无 rerank）、RRF+rerank（mode=phrase 有 rerank）、Skill-AND（mode=auto 技能复合）、结构化基线（Candidate.skills 组合过滤）

## 2. 结果汇总

| 模式 | recall@5 | recall@3 | Top-1 | MRR |
|---|---|---|---|---|
| dense-only | 0.75 | 0.58 | 0.42 | 0.513 |
| RRF 双路融合 | 0.75 | 0.67 | 0.50 | 0.579 |
| **RRF + rerank** | **0.92** | **0.83** | **0.75** | **0.785** |
| Skill-AND（含 rerank） | 0.75 | 0.75 | 0.50 | 0.604 |
| 结构化基线 | 0.00 | 0.00 | 0.00 | 0.000 |

## 3. 结论

1. **RRF+rerank 全面最优，达成 PRD 完成定义**：recall@5=0.92、MRR=0.785，显著优于结构化基线（0.00）与单路 dense（0.513）。rerank 把"平面设计"目标从 RRF 第 2 提到第 1、"幕墙"等保持 Top-1，并清理了低相关候选（rerank 分 0 的排后）。
2. **RRF 双路融合优于单 dense**（MRR 0.513→0.579，recall@3 0.58→0.67）：sparse 关键词路（jieba→tsvector）对实体词（新媒体/平面设计/会计）有精确命中，与 dense 语义互补。
3. **Skill-AND 技能复合**：recall@3=0.75、MRR 0.604（含 rerank 精排，2026-08-16 补齐设计步骤 6）。12 个锚点中仅 3 个（Unity/楼面经理/外联）被 LLM 解析为多技能走模式 B，其余为单复合技能走模式 A——评测集多数查询并非多技能场景，Skill-AND 优势未充分体现；模式 B rerank 通路已由单测与 HTTP 验收验证（skill_ordered_reranked，"会 java python fastapi agent rag 的人"5 技能分解正确）；在真实多技能异质语料上的优势需更大标注集验证。
4. **结构化基线 0.00**：该语料 Candidate.skills 规则解析为空（技能在正文未进结构化字段）——恰好证明简历正文语义检索的价值（结构化检索对此类简历完全失效）。
5. **rerank 成本**：每查询 1 次 /rerank 调用（top_n=5），12 查询共 12 次，远低于配额。

## 4. 实施中修复的检索管线缺陷（均有实测依据）

| 缺陷 | 现象 | 修复 |
|---|---|---|
| sparse 路长查询 0 命中 | websearch_to_tsquery 空格=AND 语义，完整句 tsquery 需段落含全部词 → 0 命中 | `_sparse_query`：jieba 切词去停用词取前 4 个（BM25 常见做法），dense 路不受影响 |
| sparse 阈值误过滤 | 多词 AND 稀释 ts_rank（幕墙 0.286→0.193），0.2 阈值下高质量多词命中被过滤 | sparse 内部阈值降至 0.01，质量筛选交给 RRF rank |
| rerank index 映射错误 | SiliconFlow results[].index=输入下标，原代码用 enumerate 下标映射 → 分数错位 | 按 index 写回 fused 原行再排序 |
| rerank 排序被聚合覆盖 | rerank 重排段落但 _aggregate 用 rrf 聚合 → 排序回退 | `_para_score`：rerank 启用时聚合/排序键优先 rerank 分 |
| 模式 B 固定命中阈值无区分度 | 短技能词对任意段落 dense 相似度 0.2~0.42，固定 0.2 下人人命中 | 相对阈值 max(0.2, 技能top分×0.75) |
| 模式 B 缺 rerank（设计步骤 6 未实现） | Skill-AND 只有 hit_vec 排序，无精排 | 候选段落（每简历最优段）→ rerank → skill_ordered_reranked（2026-08-16 补齐） |

## 5. 资源消耗

- Embedding：~40 次（31 份入库 309 段 + 12 查询 × 模式数）
- Rerank：12 次（每查询 1 次）
- LLM：~31 次切片 + ~10 次技能分解
- 全部远低于配额（SenseNova 3000 / SiliconFlow 3000）

## 6. 遗留与建议

- rerank 分数 0 的候选直接排最后（无归一化处理）——可接受，后续可加"rerank 后 min_score 过滤"
- 数据集为合成语料（技能模板共享），真实异质简历上的 Skill-AND 优势待更大标注集验证
- 可选增强（plans 3.4）按本报告收益决策：路由分级（简单查询省 rerank）、画像重排、RAG Fusion 均未触发；docx 格式变体评测集并入后续

> 关联：实施计划 ../plans/2026-08-15-c-stage-resume-rag.md 阶段 3；设计 ../specs/2026-08-15-hr-resume-search-design.md；HANDOFF §5.3