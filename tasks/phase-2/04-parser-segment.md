# T-012: 语义段落切分 + Skill 标准化

## 基本信息
- 对应 Spec: specs/resume-parser/01-requirements.md REQ-006, REQ-007
- 对应 AC: AC-007, AC-008
- 依赖: T-011
- 预计工时: 2 天

## 输入
- `specs/resume-parser/01-requirements.md` — 段落切分与 Skill 标准化需求
- `specs/resume-parser/02-data-model.md` — ResumeSegment / Skill 数据模型
- `src/resume_parser/llm_extractor.py` — LLM 结构化提取（T-011 产出）
- `src/resume_parser/schemas.py` — Pydantic Schema（T-011 产出）

## 输出
- `src/resume_parser/segmenter.py` — 语义段落切分模块（含 Multi-Level Chunk 构建）
- `src/resume_parser/chunk_builder.py` — Chunk 层级构建器（Small/Parent/Full 三层）
- `src/resume_parser/schemas.py` — 数据 Schema（扩展 T-011，含 ChunkSchema 定义（⚠️ 增量扩展：保留 T-011 全部 Schema，追加 ChunkSchema，禁止全量覆盖））
- `src/resume_parser/skill_normalizer.py` — Skill 标准化模块
- `data/skill_taxonomy.json` — 技能分类标准库
- `tests/resume_parser/test_segmenter.py` — 段落切分单元测试
- `tests/resume_parser/test_chunk_builder.py` — Chunk 构建器单元测试
- `tests/resume_parser/test_skill_normalizer.py` — Skill 标准化单元测试

## 实现要求
1. 按照简历语义结构将文本切分为独立段落（Segment）：教育段、工作段、项目段、技能段等
2. 每个 Segment 包含 `segment_type`、`content`、`start_date`、`end_date`、`organization`、`title` 等字段
3. Skill 标准化：建立技能同义词映射表（如 "JS" → "JavaScript"，"机器学习" → "Machine Learning"）
4. 使用技能分类标准库 `skill_taxonomy.json` 进行匹配，支持模糊匹配和层级分类（大类 → 小类 → 具体技能）
5. 标准化后输出 `NormalizedSkill`：`raw_name`、`normalized_name`、`category`、`confidence`
6. 段落切分支持重叠区间检测：如果两段时间重叠，添加 `overlap_warning`
7. 关键设计决策：段落切分使用规则引擎 + LLM 双层架构，规则引擎处理标准格式，LLM 处理非标格式
8. **Multi-Level Chunk 构建**（对齐 specs/vector-index/00-overview.md Multi-Granularity 设计）：
   - **Small Chunk**：将每个语义段落进一步切分为单句级粒度（50~200 字符），作为向量检索单元
     - 工作经历段：按项目/职责拆分为独立小段
     - 教育经历段：按学历条目拆分
     - 项目经历段：按项目拆分
     - 技能段：按技能分类拆分
   - **Parent Chunk**：Small Chunk 所属的完整语义段落（Section 级），作为 LLM 上下文
   - **Full Resume Chunk**：整份简历全文，用于全局语义匹配和推荐理由生成
   - **parent_chunk_id 映射**：每个 Small Chunk 必须记录其 parent_chunk_id，指向所属 Parent Chunk
   - **chunk_id 格式**：{resume_id}:{level}:{index}（如 R001:small:3、R001:parent:1、R001:full:0）
   - 输出数据结构 ChunkSchema：chunk_id、
esume_id、chunk_level（small/parent/full）、parent_chunk_id、section_type、content、sequence_index
   - 写入量估算：单份简历约 1 个 Full + ~4 个 Parent + ~10 个 Small = ~15 个 Chunk
9. 禁止事项：禁止丢弃无法识别的技能（必须保留原始名称 + 标记为 unrecognized）；禁止修改段落原始文本内容；禁止生成的 Chunk 缺少 chunk_level 或 parent_chunk_id 字段（Small Chunk 必须有 parent_chunk_id）

## 验收检查点

### 前置确认
- [ ] T-011（LLM 结构化提取）已完成
- [ ] 容器环境已启动
- [ ] `skill_taxonomy.json` 已编写并验证格式

### AC 验收
- [ ] AC-007: 简历文本能正确切分为语义段落，段落类型标注准确（教育/工作/项目/技能），边界清晰不重叠
- [ ] AC-008: 技能名称标准化后与标准库匹配，同义词正确映射，分类准确，未识别技能保留原始名称
- [ ] **AC-NEW-01**: Multi-Level Chunk 输出包含 Small/Parent/Full 三层，单份简历生成约 15 个 Chunk
- [ ] **AC-NEW-02**: 每个 Small Chunk 的 parent_chunk_id 正确指向其所属 Parent Chunk
- [ ] **AC-NEW-03**: chunk_id 格式为 {resume_id}:{level}:{index}，全局唯一
- [ ] **AC-NEW-04**: ChunkSchema 包含全部必填字段（chunk_id, resume_id, chunk_level, parent_chunk_id, section_type, content）

### 代码质量
- [ ] lint pass（ruff + mypy）
- [ ] `skill_taxonomy.json` 格式规范，可扩展
- [ ] 无硬编码的技能映射，全部通过 JSON 配置
- [ ] 模糊匹配有可配置的阈值
- [ ] 类型标注和 docstring 完整

### Spec 一致性
- [ ] Segment 输出结构与 `specs/resume-parser/02-data-model.md` 一致
- [ ] NormalizedSkill 输出结构与 spec 一致
- [ ] 段落类型枚举与 spec 定义一致

- [ ] Chunk 三层结构（Small/Parent/Full）与 `specs/vector-index/00-overview.md` Multi-Granularity 设计一致
- [ ] chunk_level、parent_chunk_id、chunk_id 格式与 vector-index Spec Schema 定义一致
- [ ] 单份简历 Chunk 数量符合估算（~15 个：1 Full + ~4 Parent + ~10 Small）

### 通过判定
全部 ✅ → Done | retry < 3 → 修复 | retry = 3 → BLOCKED
