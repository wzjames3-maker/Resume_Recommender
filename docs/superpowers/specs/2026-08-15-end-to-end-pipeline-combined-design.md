# 端到端综合方案：简历 RAG 入库 + 检索流水线（选型定稿）

> 日期：2026-08-15
> 状态：**定稿（C 阶段唯一权威设计）**
> 依据：GitHub 调研端到端流程（入库 11 步 + 检索 8 步，参考 smart-ats / hr-rag-assistant / MewAgent / ResumeScreening / HireFlow / Hungreeee 等） + 本项目已有能力盘点
> 选型原则：**复用优先**——MaxKB 已具备向量化/混合检索/异步/chat 等 80% 能力，开发与模型调用预算只投在缺口上。
> 关联：实施计划 ../plans/2026-08-15-c-stage-resume-rag.md；链路流程图 2026-08-15-resume-upload-split-embed-flow.md（辅助）；调研 ../audits/2026-08-15-chunking-landscape.md；审查 ../audits/2026-08-15-design-reality-check.md

---

## 1. 选型总览（映射决策表）

### 1.1 入库流水线（11 步 → 8 项决策）

| 环节 | 调研方案 | 本项目决策 | 动作 |
|---|---|---|---|
| 1 上传校验 | 白名单 + 魔数 + MD5 | **已有**：docx/txt + sha256 去重 + 20MB（PRD 锁定，无 pdf/doc） | 可选补魔数校验 |
| 2 解析 | python-docx 段落+表格；doc 用 POI/antiword；Tika 兜底 | **已有**：python-docx 段落 + txt utf-8/gbk；表格已排除（产品决策）；doc 不在 PRD 白名单 | 无 |
| 3 清洗 | 空字节/换行/空格/空行/长度检查 | **缺** | 新增 `sanitize_resume_text()`（小函数，采纳 hr-rag-assistant 要点） |
| 4 结构化提取 | LLM 20+ 字段 → 画像表 | **已有**：规则解析建 Candidate；LLM 画像增强可选 | 后置（1 次调用/份，画像用于检索补全） |
| 5 切分 | A 整段摘要向量 / B 语义块、滑动窗口、递归、三级 Auto-merging | **B 为主（定稿）：LLM 边界标注 → 条目级 chunk（见 §6 切片协议）**；**A 画像向量为阶段 3 增强**（候选人级筛选） | 核心实现 |
| 6 元数据 | resume_id/section/index/parent | 已有结构映射：Document=简历、Paragraph.title=区块、meta 可扩 | 打通时补 `ResumeFile.document_id` |
| 7 向量化 | bge-m3/large-zh + pgvector hnsw | **已有**：bge-large-zh-v1.5 + `embedding_by_document` + hnsw | 零开发 |
| 8 BM25 | rank_bm25 + jieba | **已有**：Postgres tsvector（`KeywordsSearch`） | 零开发，不引入 jieba |
| 9 画像落库 | profile 表 | **已有**：`hr_candidate` 表 | 零开发 |
| 10 质量抽检 | RAGAS / adaptive 5 指标 | 评测集计划已定（格式变体） | 评测阶段 |
| 11 异步 | Celery/RabbitMQ | **已有**：Celery（parse + embedding 任务） | 零开发 |

### 1.2 检索流水线（8 步 → 6 项决策）

| 环节 | 调研方案 | 本项目决策 | 动作 |
|---|---|---|---|
| 1 查询输入 | 自然语言 / JD | 已有 | 无 |
| 2 查询理解 | RAG Fusion 子查询 / 重写 | 可选后置（成本敏感） | 阶段 3 评估 |
| 3 双路检索 | 向量 + BM25 并行 | **已有**：`BlendSearch`（cosine + ts_rank_cd 融合，blend_search.sql） | 零开发 |
| 4 融合排序 | RRF（k=60，向量 0.7+BM25 0.3） | **现有 blend 为分数加和**（1-dist + ts_rank，尺度未归一） | 小改进：RRF 或归一化加权（实施时评测对比） |
| 5 重排 | bge-reranker / LLM 画像重排 | **reranker 已注册（bge-reranker-v2-m3）但零接入** | 核心实现：召回 top10 → rerank top3~5 |
| 6 Small-to-Big | 父块合并 / 整简历回溯 | **天然支持**：document_id = 简历；段落命中 → 回溯条目/整份简历 | 打通时实现回溯 |
| 7 LLM 生成 | prompt + 文档块 | **已有**：chat 链路（引用输出） | 零开发 |
| 8 溯源 | 引用 + 反馈 | **已有**：ChatRecord 引用；HR 反馈后置 | 复用 |

## 2. 综合架构（定稿）

```
┌─ 入库（离线）──────────────────────────────────────────────┐
│ 上传(docx/txt, sha256去重, 已有)                            │
│   → 解析(python-docx/txt, 已有)                            │
│   → 清洗 sanitize_resume_text()【新增】                    │
│   → LLM 边界标注切片(行号JSON, 条目级, PII过滤)【核心】      │
│   → Document/Paragraph 落库(复用 DocumentSerializers.Create)│
│   → embedding_by_document 向量化(已有)                     │
│   → tsvector 关键词索引(已有)                              │
│   → Candidate 规则解析画像(已有)                           │
│   → 评测抽检(格式变体评测集, 阶段2)                        │
└────────────────────────────────────────────────────────────┘
┌─ 检索（在线）──────────────────────────────────────────────┐
│ 查询/JD → BlendSearch 双路召回 top10 (已有)                 │
│   → rerank 精排 top3~5【核心】                             │
│   → Small-to-Big: 段落 → 条目/整简历回溯 (document_id)      │
│   → chat 生成 + 引用溯源(已有)                             │
│   (可选后置: RRF融合优化 / 画像向量路A / RAG Fusion子查询)   │
└────────────────────────────────────────────────────────────┘
```

## 3. 开发缺口清单（全部工作项，按阶段）

| 阶段 | 工作项 | 参考实现 | 预估 |
|---|---|---|---|
| 1 | `sanitize_resume_text()` 清洗 | hr-rag-assistant sanitizeTextContent | 小 |
| 1 | ResumeSplitter：LLM 行号边界标注 + 校验层 + 规则降级 + PII 过滤 | zChunk / Chroma LLMChunker / 前设计文档 | 中 |
| 1 | 格式变体评测集 + 边界 F1/保真度评测 | Chroma chunking_evaluation / adaptive 5 指标 | 中 |
| 2 | 打通：parse_resume_task → 切片 → Document 创建 → 向量化 | smart-ats 流水线 + MaxKB 已有链路 | 中 |
| 2 | `ResumeFile.document_id` 关联 + 生命周期同步（删除/归档/合并） | MewAgent parent store | 中 |
| 3 | rerank 接入检索管线（top10 → top3~5） | MewAgent rerank 用法 | 小 |
| 3 | Small-to-Big 回溯（段落 → 条目/简历） | MewAgent auto-merge / Hungreeee | 小 |
| 3 | （可选）blend 融合改 RRF / 画像向量路 A / RAG Fusion 子查询 | ResumeScreening RRF k=60 / Hungreeee | 小~中 |

## 4. 裁剪说明（为什么不要）

| 调研方案 | 裁剪理由 |
|---|---|
| .pdf / .doc 支持 | PRD 锁定 docx/txt；pdf 需解析器、doc 需 antiword/libreoffice，超出范围 |
| OCR/图片输入 | 业务无图片简历（PRD 无此输入） |
| rank_bm25 + jieba | Postgres tsvector 已实现同等能力，避免双套关键词引擎 |
| Milvus/Chroma 向量库 | pgvector + hnsw 已上线（S2 验证），不引入第二套存储 |
| 三级 Auto-merging 分块 | 简历条目本身 < 1024 字，两级（条目→简历）足够；三级复杂度不值 |
| LLM 画像重排（Stage B） | 画像表可支持，但初期 reranker 已够用；后置评估 |

## 5. 实施顺序

1. 阶段 1：清洗 + ResumeSplitter + 评测 → 通过后再进入
2. 阶段 2：打通入库链路（含生命周期同步）
3. 阶段 3：rerank 接入 + Small-to-Big + 可选增强

> 关联文档：实施计划 ../plans/2026-08-15-c-stage-resume-rag.md；链路流程图 2026-08-15-resume-upload-split-embed-flow.md（辅助）；调研 ../audits/2026-08-15-chunking-landscape.md；审查 ../audits/2026-08-15-design-reality-check.md


---

## 6. 切片协议（ResumeSplitter，v4 定稿）

> 本节为切片子方案的唯一规范来源（原独立切片设计文档已并入本节，git 历史可追溯）。

### 6.1 为什么通用切分对简历失效

通用链路（`TextSplitHandle` → `SplitModel` → `smart_split_paragraph`）按"长度窗口 + 标点兜底"切分，两个硬伤（代码实测）：
1. **默认 `limit=4096` 等于不切**：简历文本极短（语料 549~2205 字符），4096 窗口下 30/30 整篇单段；
2. **切点质量差**：切点字符表 `('!',0),('!',0),('?',0),('?',0)` 半角写重、全角 `！？` 缺失，实际有效切点只有 `。` `.`；实测把 "毕业时间：2005.06" 从小数点切断。

**规则切分同样不能做主干**：30 份语料是同构生成数据（"100% 命中"是测试集假象），真实简历异质（docx 排版/无标题/中英混排/乱换行），规则覆盖率低。**规则只能做降级保底。**

### 6.2 架构（LLM 主干 + 三层保障）

```
简历文件
  ├─ L0 文本提取（已有）：docx→python-docx 段落拼接（按 PRD 无表格/无 OCR）；txt→utf-8/gbk
  ├─ L1 LLM 边界标注（主干，每份 1 次调用）
  │     输入：清洗后全文（带行号）
  │     输出：JSON [{title, start_line, end_line}]
  │     硬约束：只标边界、生成 title，禁止改写正文一个字
  ├─ L2 校验修复层：行号越界/重叠/漏段 → 修正或重试一次；
  │     拼接校验：按行号区间切出的原文拼接 == 输入原文（保真性硬校验）
  └─ L3 规则降级（ResumeSplitter 规则版）：LLM 失败/配额耗尽/超短文本(<300字) 时兜底
```

### 6.3 输出协议与清洗

- **清洗**（前置）：`sanitize_resume_text()`——删空字节/控制字符、\r\n→\n、压缩连续空格、\n{3,}→\n\n、长度 <20 字判解析失败。
- **PII 过滤**（切片后）：正则（电话含 +86/空格/横线变体、邮箱、身份证）命中字段段整段丢弃或 [已脱敏]；入库前二次扫描，仍有 PII → 拒绝入库 + 告警（PRD §6）。

### 6.4 粒度与检索质量实验（真实模型实测）

- **粒度实验**（bge-large-zh-v1.5，2 简历 × 3 锚点查询）：事实级细切 vs 条目级——稀释效应存在但幅度小（±0.03），细切**噪声同升**（通用动词短语近义），排序无改善甚至变差。**结论：条目级（150~300 字，语义完整、引用保真），不做事实级细切。**
- **rerank 补偿实验**（bge-reranker-v2-m3）：最差案例（embedding 排名 4/13）重排后目标第 1，区分度 **≈100 倍**（0.345 vs 噪声 0.003）；3/3 查询目标全部第 1。**结论：embedding 只负责召回（top_k=10），reranker 负责精排（top_n=3~5），tsvector 兜底专有名词。**

### 6.5 成本

- LLM 边界标注：每份 1 次（flash-lite 级 ~1.5K token）；3 万份 ≈ 4500 万 token（几元~几十元量级），Celery 异步批处理；
- embedding：条目级每份 ~7 段；rerank 仅检索时触发；
- 超短文本（<300 字）走规则降级省调用。

### 6.6 评测计划（格式变体，不再用同构数据自证）

1. docx **格式变体**样本集（样式标题/无标题/软换行/空段/超长单行/中英混排，内容用数据集内容填充）+ 数据集合成分号流作为**压力测试**（验证降级路径）；
2. 指标：边界 F1（对照人工标注）、**原文保真度（切段拼接==原文，必须 100%）**、段落长度分布、每份调用次数；
3. 检索端：实体锚点查询 recall@5（embedding）、rerank 后 recall@3、混合检索覆盖率。

### 6.8 实现协议（ResumeSplitter v1.0，阶段 1 直接编码依据）

**输入**：清洗后文本，自动编号（1..N 行）。

**System Prompt 硬约束**：
1. 只输出 JSON，不输出任何其他内容；
2. 只标行号边界 + title，**禁止改写/重组/翻译原文一个字**；
3. 行号必须覆盖全部文本行（空行归并相邻段）；
4. title ≤ 20 字，格式 `区块-关键词`（如"工作经历-深圳大运置业 后端"）；
5. 单段 50~500 字（**实测上限**：SiliconFlow bge-large-zh-v1.5 中文输入 ~500-600 字符、600 报 400，normalize_for_embedding 不截断——切片层必须保证 ≤500 否则向量化失败）；超长条目允许拆子条目，但元数据行（时间/单位/职务）不得与内容拆开。

**输出 JSON**：
```json
{"chunks": [{"title": "...", "start_line": 3, "end_line": 5, "confidence": 0.9}]}
```

**L2 校验（程序化，不信任 LLM）**：
1. 行号合法：1 ≤ start ≤ end ≤ N；
2. 区间不重叠，拼接后覆盖 1..N（空行归并相邻段）；
3. 保真硬校验：按区间切出的文本拼接 == 原文（逐字符）；
4. 单段 50~500 字（行数 + 字符数双重校验；2026-08-15 实测修复：无换行超长文本的 LLM 单段输出、规则/smart 降级均按 500 上限兜底）。
→ 失败：附错误信息重试 1 次 → 仍失败：走 L3。

**L3 降级链**：规则切分（【区块】+条目）→ smart_split(1024) → 整篇单段（兜底）。

**PII 过滤（切片后、入库前）**：正则电话（1[3-9]\d{9} 及 +86/空格/横线变体）/邮箱/身份证（\d{17}[\dXx]）；命中段整段丢弃或 [已脱敏]；入库前二次扫描，仍有 PII → 拒绝入库 + 告警。

**演进路径（评测驱动）**：行号失败率高 → 字符偏移/原文子串锚定；LLM 输出不稳定 → Chroma 式直接输出 chunk；成本敏感 → 微调小模型替换（chonky 路线）。

### 6.7 遗留问题（实现时决策）

1. title 增强：LLM 生成条目主题摘要（如"幕墙设计·深圳大运置业 1992-2017"）是否值得 1 次额外调用——待检索评测收益量化后决定；
2. 多条目简历 title 层级（区块→条目）映射 knowledge_paragraph.title（单字段）；
3. ResumeFile → Document 生命周期同步细节（见 flow 文档 §8 与实施计划）。
