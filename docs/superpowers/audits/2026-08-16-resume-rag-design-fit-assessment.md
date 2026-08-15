# 简历 RAG 链路设计适配性评判（架构级）

> 日期：2026-08-16
> 触发：项目方提问「整个 RAG 链路设计是否合理、有什么缺陷--简历是复杂文本」
> 结论：**骨架方向正确、工程质量高于典型自研 RAG，但对"简历=结构化载体"的利用只走到一半**：切片层结构感知（LLM 行号边界+章节标题），检索层不消费结构（标题不入向量、字段不过滤、跨段不聚合）。缺陷不在"没做结构化"，而在"结构信息在入库后断流"。

---

## 1. 设计做对了什么

1. **保真切片协议**：LLM 只标行号边界、content 永远取原文（`resume_splitter.py _resolve`，实测 dataset30 30/30 无改写）--对"LLM 改写简历内容"这一最大风险的正确防御。
2. **三级降级**：LLM 标注 -> L2 校验（`_validate`）-> `_SECTION_RE` 规则切分（`split_resume_rules`）-> `smart_split_paragraph` 兜底；LLM 不可用时链路不断（实测 29/30 走 LLM 路径）。
3. **500 字上限**（`_MAX_CHUNK_LENGTH`）精确贴合 bge-large-zh 512 token 限制；内核反而靠 256 字 MarkChunkHandle 隐式兜底，HR 侧是显式设防。
4. **检索链形态正确**：模式 A（整句 dense+sparse 双路 -> RRF -> rerank -> 简历聚合）；模式 B（Skill-AND：LLM 分解 -> 逐技能召回 -> 命中向量 -> 结构化 `Candidate.skills` OR 合并 -> 顺位放宽）；降级链 rerank -> RRF -> dense -> 空结果+meta。
5. **PII 门控**：掩码（`mask_pii`）+ 残留扫描拒绝入库（`resume_index.py:88` `scan_residual_pii`），把简历当 PII 载体对待。

## 2. 核心缺陷（按简历文本特性）

### A. 检索原子与判定单元错配（最根本）

检索原子是 500 字段落，招聘查询的判定单元是**整份简历**："3 年 Java"需跨多段经历求和，"有金融背景"任一段命中即可。`_aggregate` 取简历最高分段代表整份，无跨段证据合成。`years_experience`/`highest_degree`/`current_city` 已建模（`hr/models/recruitment.py:92-120`）但**只用于展示回显（`_mask_for_role`），不参与召回过滤**--查询"5 年以上"只能靠向量语义近似，精确条件在 RAG 层不可保证。模式 B 只接入了 skills 一个维度的结构化路。

### B. 章节标题的语义价值在入库后断流

切片协议产出的 title（"工作经历-某某公司 工程师"）存进 `Paragraph.title` 后**既不进 embedding 也不进 search_vector**：`listener_manage.py` dense 输入=content/chunks，`tokenize_by_paragraph` 的 tsvector 同样只用 chunks。查询"教育背景 985"对教育段无先验加成；无法做"只在工作经历段检索"的 section 过滤。结构感知半途而废的典型断点。

### C. PII 掩码与找人路径的张力未产品化

手机/邮箱掩成 `[已脱敏]` 后，按姓名/电话找候选人这条 ATS 高频路径在语义检索里被**设计性排除**。`Candidate.name` 有 db_index 可走 SQL，但系统没有显式分层路由（"按联系方式找"->SQL；"按条件+语义"->RAG），用户会困惑"搜手机号搜不到"。

### D. 稀疏路的词汇现实

sparse = jieba `cut_all` + PG `simple` 配置 + query 截 4 词（`_sparse_query max_terms=4`）。简历技术栈词汇同义词/变体泛滥（Java/JAVA/Java8、K8s/Kubernetes、"前端"/"Web 前端"），无归一字典。内核有 Termbase 机制（用户词表进分词器，`ts_vecto_util._build_tokenizer`），HR 知识库**没有使用**。模式 B 的 LLM 查询分解部分缓解，模式 A 整句检索直接伤召回。

### E. 合规缺口

LLM 切片调用发送**未脱敏全文**（掩码发生在 LLM 返回边界之后；检索设计文档 §9.3 已知限制）--对简历这种文本，这是链路里最大的合规敞口，比检索质量问题严重。

### F. 更新粒度与评测盲区

简历修订=整份重切重嵌（当前量级可接受，无段落级增量）。评测锚定 dataset30 + recall@3/MRR，但**缺分查询类型的错误分析**（年限类/背景类/技能组合类各自失败率），无法指导 A/B 类补强优先级。

## 3. 改进建议（ROI 排序）

1. **结构化过滤前置**：查询理解抽取 `{skills, years>=, degree, city}` -> `Candidate` SQL 预筛 -> RAG 只在预筛集内召回。模式 B 已有 skills 骨架，扩展成统一入口是自然演进，改动集中在 `resume_search.py`。
2. **title 并入向量文本**：embedding/分词输入改为 `"{title}\n{content}"`（行级改动），让"工作经历/教育背景"先验进 dense+sparse。
3. **技能同义词典**：复用内核 Termbase（入库+查询双向归一），或 HR 侧维护技能字典。
4. **简历级证据合成**：聚合时对 top-k 段落 multi-hit 加权（模式 B 的 hit_skills 向量是雏形，推广到模式 A）。
5. **分层检索路由产品化**（按姓名/电话->SQL；按条件+语义->RAG）+ 分查询类型评测集。

## 4. 一句话结论

这套链路把简历当"复杂非结构化文本"处理得不错，但还没把简历当"结构化文档"处理到位--**字段过滤前置（建议 1）+ 标题入向量（建议 2）** 两步补上，结构感知才真正闭环。

## 5. 与第三轮内核审查的关系

本文聚焦 HR 简历链路的**设计适配性**；内核链路的实现级问题（SSRF/异常文本/解压上限等 3 P1+6 P2+6 P3）见 `2026-08-16-kernel-rag-fullflow-review.md`。两者互补、零重叠。

## 6. 证据锚点索引

- 切片协议：`apps/hr/services/resume_splitter.py`（L53 边界协议示例、L195 `split_resume_text`、L238 掩码输出）
- 结构化字段：`apps/hr/models/recruitment.py` Candidate（L92-120：years_experience/skills/highest_degree/current_city）
- 检索模式：`apps/hr/services/resume_search.py`（L7-9 模式注释、L200 `_search_skill_and`、L127 `_rrf_fuse`、L169 `_aggregate`）
- 标题断流：`apps/common/event/listener_manage.py`（embedding 输入与 `tokenize_by_paragraph` 均只取 content/chunks）
- 实测数据：`README-hr.md` 验收记录（30/30 保真、29/30 LLM 路径、PII 26/30 掩码）；`docs/superpowers/audits/2026-08-15-c-stage-rerank-eval.md`（rerank 量化收益）
