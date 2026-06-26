<!-- Module: resume-parser -->
<!-- Spec Layer: 01 - Requirements -->
<!-- Phase: Phase 4 - Spec Writing -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-23 -->

# 功能需求：Resume Parser

## 需求总览

| ID | 需求名称 | PRD 来源 | 优先级 | 状态 |
|----|----------|----------|--------|------|
| REQ-001 | PDF 简历解析 | FR-010, FR-011 | P0 | 待实现 |
| REQ-002 | DOCX 简历解析 | FR-010, FR-011 | P0 | 待实现 |
| REQ-003 | 图片简历 OCR 解析 | FR-010, FR-011 | P1 | 待实现 |
| REQ-004 | JSON 简历导入 | FR-010 | P0 | 待实现 |
| REQ-005 | LLM 结构化提取 | FR-011 | P0 | 待实现 |
| REQ-006 | 语义段落切分 | FR-012 | P0 | 待实现 |
| REQ-007 | Skill 标准化 | FR-013 | P1 | 待实现 |
| REQ-008 | 解析失败降级 | - | P0 | 待实现 |

---

## REQ-001: PDF 简历解析

**PRD 来源**: FR-010（支持简历上传 PDF）、FR-011（Resume Parser）

**描述**: 支持上传 PDF 格式简历，提取纯文本内容。优先使用 pdfplumber 提取，失败时降级到 PyPDF2。

**输入**:
- `file`: PDF 文件（二进制流）
- `file_name`: 文件名（用于日志和去重）

**输出**:
- `raw_text`: 提取的纯文本内容
- `metadata`: 元数据（页数、文件大小、提取工具、提取时间）
- `status`: 解析状态（success / failed）

**验收标准**:
- 能解析文本型 PDF（非扫描件），提取全部文字内容
- 能解析包含表格的 PDF，保留表格结构信息
- pdfplumber 提取失败时自动降级到 PyPDF2
- 两种方式均失败时标记 `status=failed`，保留空文本

**依赖**: pdfplumber >= 0.11, PyPDF2 >= 3.0

---

## REQ-002: DOCX 简历解析

**PRD 来源**: FR-010（支持简历上传 DOCX）、FR-011（Resume Parser）

**描述**: 支持上传 .docx 格式简历，提取纯文本内容，包括段落文本和表格内容。

**输入**:
- `file`: DOCX 文件（二进制流）
- `file_name`: 文件名

**输出**:
- `raw_text`: 提取的纯文本内容
- `metadata`: 元数据（段落数、表格数、文件大小、提取时间）
- `status`: 解析状态

**验收标准**:
- 能解析 .docx 文件，提取所有段落文本
- 能解析 .docx 中的表格内容，转为结构化文本
- 不支持旧版 .doc 格式，遇到时返回明确错误提示
- 提取失败时标记 `status=failed`

**依赖**: python-docx >= 1.1

---

## REQ-003: 图片简历 OCR 解析

**PRD 来源**: FR-010（支持简历上传图片）、FR-011（Resume Parser + OCR）

**描述**: 支持上传图片格式简历（jpg/jpeg/png），使用 DeepSeek-OCR 进行文字识别，提取纯文本内容。

**输入**:
- `file`: 图片文件（二进制流）
- `file_name`: 文件名

**输出**:
- `raw_text`: OCR 识别的纯文本内容
- `metadata`: 元数据（图片尺寸、文件大小、OCR 耗时、识别语言）
- `status`: 解析状态

**验收标准**:
- 支持 jpg/jpeg/png 格式图片
- 使用 DeepSeek-OCR（deepseek-ai/DeepSeek-OCR）进行文字识别
- 图片过大时（> 10MB）先进行缩放预处理
- OCR 识别失败时标记 `status=failed`
- 识别后文本会包含一定错误率，依赖 LLM 结构化提取修正

**依赖**: Pillow >= 10.0, DeepSeek-OCR API

---

## REQ-004: JSON 简历导入

**PRD 来源**: FR-010（支持简历上传 JSON）

**描述**: 支持上传已结构化的 JSON 格式简历，直接映射为 Resume 实体，跳过文本提取和 LLM 结构化提取步骤。

**输入**:
- `file`: JSON 文件（二进制流）或 JSON 字符串
- `file_name`: 文件名

**输出**:
- `resume`: 直接映射的 ResumeSchema 对象
- `status`: 解析状态

**验收标准**:
- JSON 格式符合 ResumeSchema 结构时，直接映射为 Resume 实体
- JSON 格式不符合时，尝试字段名模糊匹配（如 "name" → "full_name"）
- 字段缺失时填充默认值（空列表 / null），不报错
- 类型不匹配时（如 experience_years 传入字符串），尝试类型转换
- 完全无法映射时标记 `status=failed`，保留原始 JSON

---

## REQ-005: LLM 结构化提取

**PRD 来源**: FR-011（LLM 结构化提取）

**描述**: 将非结构化简历文本通过 LLM（DeepSeek）提取为结构化 Resume 实体，包括姓名、联系方式、技能、教育经历、工作经历、项目经历等字段。

**输入**:
- `raw_text`: 简历纯文本内容
- `language`: 识别的语言（中文/英文/混合）

**输出**:
- `resume_data`: ResumeSchema 结构化数据
- `extraction_metadata`: 提取元数据（LLM 模型、token 用量、提取耗时、重试次数）
- `status`: 解析状态

**验收标准**:
- 使用 DeepSeek LLM（OpenAI Compatible API）进行结构化提取
- Prompt 明确指定输出 JSON Schema（与 Pydantic ResumeSchema 一致）
- LLM 输出必须通过 Pydantic ResumeSchema 验证
- 验证失败时重试 1 次（调整 Prompt 提示格式错误）
- 重试仍失败时降级：返回部分提取结果 + 标记 `status=partial`
- 提取字段包括：full_name, phone, email, city, education_list, experience_list, project_list, skill_list, summary

**依赖**: openai SDK, pydantic >= 2.0, DeepSeek API Key

---

## REQ-006: 语义段落切分

**PRD 来源**: FR-012（语义段落切分）

**描述**: 将简历纯文本按语义维度切分为教育经历、工作经历、项目经历、技能等段落，保留每个段落的元数据（起止位置、段落类型、原始文本）。

**输入**:
- `raw_text`: 简历纯文本内容

**输出**:
- `sections`: 段落列表，每个段落包含：
  - `section_type`: 段落类型（education / experience / project / skill / personal_info / other）
  - `raw_content`: 原始文本
  - `start_pos`: 起始位置
  - `end_pos`: 结束位置

**验收标准**:
- 能识别简历中的标准分区标题（如"教育经历"、"工作经历"、"项目经历"、"技能特长"等）
- 支持中英文分区标题识别
- 未识别到分区标题时，将全文作为单一段落传递给 LLM 处理
- 切分结果包含每个段落的起止位置信息

**实现说明**: 语义切分可以有两种策略：
1. **规则优先**：基于标题关键词匹配进行切分，速度快
2. **LLM 辅助**：由 LLM 在结构化提取过程中同时完成切分
- 推荐策略 1 作为首选，策略 2 作为 LLM 提取的补充

---

## REQ-007: Skill 标准化

**PRD 来源**: FR-013（Skill 标准化）

**描述**: 对提取出的技能列表进行标准化处理，包括大小写统一、同义词映射、去重等。

**输入**:
- `skills`: 原始技能列表（list[str]）

**输出**:
- `standardized_skills`: 标准化后的技能列表（list[SkillSchema]）

**验收标准**:
- 大小写统一：首字母大写，其余小写（如 "JAVA" → "Java", "python" → "Python"）
- 同义词映射：维护静态词典，将同义词映射到标准名称（如 "JS" → "JavaScript", "SpringBoot" → "Spring Boot"）
- 去重：相同技能（标准化后）只保留一条
- 未知技能保留原名（标准化大小写后），不做臆造映射
- 同义词词典为静态配置文件（YAML/JSON），支持后续扩展

**依赖**: 静态同义词词典文件

---

## REQ-008: 解析失败降级

**PRD 来源**: 通用错误处理需求

**描述**: 任何解析环节失败时，系统必须保证不丢数据，保留原始文件和已提取的部分内容，并标记解析状态。

**输入**:
- 失败发生在任意解析环节

**输出**:
- `status`: 最终解析状态（success / partial / failed）
- `raw_text`: 保留的原始文本（即使结构化提取失败）
- `error_message`: 错误信息
- `partial_data`: 部分提取的数据（如有）

**验收标准**:
- 文本提取失败：标记 `status=failed`，`raw_text` 为空，记录错误信息
- LLM 结构化提取失败：标记 `status=partial`，保留 `raw_text`，`resume_data` 为空或部分填充
- Skill 标准化失败：标记 `status=partial`，使用原始技能列表
- 所有失败场景都记录错误日志（结构化 JSON 日志）
- 失败状态不影响后续重试（可重新触发解析）

---

## 需求间依赖关系

```
REQ-001 (PDF)  ──┐
REQ-002 (DOCX) ──┤──> REQ-006 (语义切分) ──> REQ-005 (LLM 提取) ──> REQ-007 (Skill 标准化)
REQ-003 (OCR)  ──┤
REQ-004 (JSON) ──┘ (跳过上述流程，直接映射)

REQ-008 (降级) ──> 贯穿所有环节的错误处理
```

## NFR 关联

| NFR | 与本模块的关联 |
|-----|---------------|
| NFR-007 | 简历入库 QPS >= 10（直接影响解析吞吐量） |
| NFR-013 | PII 加密存储（AES-256）— 影响 phone/email 字段 |
| NFR-014 | PII 脱敏展示 — 解析阶段加密，展示阶段脱敏 |
| NFR-020 | LLM 降级 — LLM 不可用时的降级策略 |

---
## v1.2-data-pipeline 新增 (2026-06-26)
| ID | 对应 PRD | 描述 | 优先级 |
|----|----------|------|--------|
| REQ-012 | FR-002 | API 上传简历后自动触发 语义分段→Chunk构建→向量索引写入（索引失败不阻塞上传响应） | P0 |
| REQ-013 | FR-011 | JSON 提取 regex 使用正确的 \s* 而非 s* | P0 |
| REQ-014 | FR-011 | ResumeCreateRequest 必须包含 project_list 字段 | P1 |
| REQ-015 | FR-011 | 存储时使用 fallback_handler 处理后的 structured（而非原始 LLM 输出） | P1 |
