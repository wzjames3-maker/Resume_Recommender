<!-- Module: resume-parser -->
<!-- Spec Layer: 06 - Acceptance Criteria -->
<!-- Phase: Phase 4 - Spec Writing -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-23 -->

# 验收标准：Resume Parser

## 验收总览

每条验收标准使用 Given-When-Then 格式，覆盖所有 REQ、RULE 和关键 EC。

| AC ID | 覆盖 | 描述 | 优先级 |
|-------|------|------|--------|
| AC-001 | REQ-001 | PDF 文本型简历解析 | P0 |
| AC-002 | REQ-001, RULE-001 | PDF 解析降级到 PyPDF2 | P0 |
| AC-003 | REQ-002 | DOCX 简历解析 | P0 |
| AC-004 | REQ-003, RULE-002 | 图片简历 OCR 解析 | P1 |
| AC-005 | REQ-004 | JSON 简历导入 | P0 |
| AC-006 | REQ-005, RULE-003 | LLM 结构化提取成功 | P0 |
| AC-007 | REQ-006 | 语义段落切分 | P0 |
| AC-008 | REQ-007, RULE-005, RULE-006 | Skill 标准化 | P1 |
| AC-009 | REQ-008, RULE-004 | 解析失败降级 | P0 |
| AC-010 | RULE-007 | PII 字段加密 | P1 |
| AC-011 | EC-001 | 加密 PDF 处理 | P1 |
| AC-012 | EC-002 | 扫描件 PDF 处理 | P1 |
| AC-013 | EC-004 | 非中文简历处理 | P2 |
| AC-014 | EC-005 | 空文件处理 | P0 |
| AC-015 | EC-006 | LLM Schema 验证失败重试 | P0 |
| AC-016 | EC-010 | LLM API 超时 | P1 |
| AC-017 | RULE-008 | Multi-Chunk 生成 | P0 |
| AC-018 | RULE-009 | Small Chunk 长度控制 | P0 |
| AC-019 | EC-013 | 短简历 Chunk 处理 | P1 |
| AC-020 | EC-014 | 单 Section 简历 Chunk 处理 | P1 |
| AC-021 | EC-015 | 文件 MD5 去重 — 相同文件重复上传 | P0 |

---

## AC-001: PDF 文本型简历解析

**覆盖**: REQ-001

**Given** 一份包含文字内容的 PDF 简历文件（如"张三_简历.pdf"，2 页，包含个人信息、教育经历、工作经历、技能等）

**When** 调用 `parse_resume(file)` 传入该 PDF 文件

**Then**
- `status` 为 `ParseStatus.SUCCESS`
- `raw_text` 非空，包含简历中的关键文字（如"张三"、"Java"等）
- `resume_data` 不为 None，包含结构化的 `PersonalInfo`、`EducationSchema`、`ExperienceSchema`、`SkillSchema`
- `metadata.source_file_type` 为 `"pdf"`
- `metadata.parse_tool` 为 `"pdfplumber"` 或 `"PyPDF2"`
- `metadata.page_count` 为 2

---

## AC-002: PDF 解析降级到 PyPDF2

**覆盖**: REQ-001, RULE-001

**Given** 一份 PDF 简历文件，且 pdfplumber 提取该文件时抛出异常（如特定编码不支持）

**When** 调用 `parse_resume(file)` 传入该 PDF 文件

**Then**
- 系统自动降级到 PyPDF2 提取
- `status` 为 `ParseStatus.SUCCESS`（如 PyPDF2 成功提取）
- `metadata.parse_tool` 为 `"PyPDF2"`
- 日志中包含 warning 级别的 pdfplumber 失败记录

---

## AC-003: DOCX 简历解析

**覆盖**: REQ-002

**Given** 一份 .docx 格式简历文件，包含段落文本和表格（如技能表格）

**When** 调用 `parse_resume(file)` 传入该 DOCX 文件

**Then**
- `status` 为 `ParseStatus.SUCCESS`
- `raw_text` 非空，包含段落文本和表格内容
- `resume_data` 包含结构化数据
- `metadata.source_file_type` 为 `"docx"`
- `metadata.parse_tool` 为 `"python-docx"`

---

## AC-004: 图片简历 OCR 解析

**覆盖**: REQ-003, RULE-002

**Given** 一份 jpg 格式的简历图片，图片中包含中文简历内容

**When** 调用 `parse_resume(file)` 传入该图片文件

**Then**
- `status` 为 `ParseStatus.SUCCESS` 或 `ParseStatus.PARTIAL`（OCR 识别率可能不完美）
- `raw_text` 非空，包含 OCR 识别的文字
- `metadata.source_file_type` 为 `"jpg"`
- `metadata.parse_tool` 为 `"deepseek-ocr"`
- `resume_data` 包含可提取的结构化数据（至少 name 和部分 skill）

---

## AC-005: JSON 简历导入

**覆盖**: REQ-004

**Given** 一份符合 ResumeSchema 结构的 JSON 简历文件

**When** 调用 `parse_resume(file)` 传入该 JSON 文件

**Then**
- `status` 为 `ParseStatus.SUCCESS`
- `resume_data` 直接映射为 JSON 中的数据，无 LLM 调用
- `metadata.source_file_type` 为 `"json"`
- `metadata.llm_tokens_used` 为 None 或 0（未调用 LLM）
- 所有字段值与 JSON 文件内容一致

---

## AC-006: LLM 结构化提取成功

**覆盖**: REQ-005, RULE-003

**Given** 一段包含完整简历信息的纯文本（含姓名、手机号、邮箱、教育经历、工作经历、项目经历、技能列表）

**When** 调用 `parse_resume_text(text)` 传入该文本

**Then**
- `status` 为 `ParseStatus.SUCCESS`
- `personal_info.full_name` 不为空
- `personal_info.phone` 不为空（加密格式）
- `personal_info.email` 不为空（加密格式）
- `education_list` 非空，至少包含 1 条记录，每条包含 `school` 和 `degree`
- `experience_list` 非空，至少包含 1 条记录，每条包含 `company` 和 `title`
- `skill_list` 非空，至少包含 3 个技能
- `metadata.llm_model` 包含 "deepseek"
- `metadata.llm_tokens_used` > 0
- 所有输出字段符合 Pydantic Schema 约束

---

## AC-007: 语义段落切分

**覆盖**: REQ-006

**Given** 一段包含标准分区标题的简历文本（如"个人信息"、"教育经历"、"工作经历"、"项目经历"、"技能"）

**When** 对该文本执行语义段落切分

**Then**
- 切分结果包含至少 4 个段落
- 段落类型覆盖 `personal_info`、`education`、`experience`、`skill` 中的至少 3 种
- 每个段落的 `start_pos` 和 `end_pos` 正确（不重叠、不遗漏）
- `confidence` 字段有值

---

## AC-008: Skill 标准化

**覆盖**: REQ-007, RULE-005, RULE-006

**Given** 原始技能列表：`["java", "JAVA", "SpringBoot", "JS", "python", "mysql", "MySQL", "c++"]`

**When** 调用 `standardize_skills(skills)`

**Then**
- 返回列表长度为 5（去重后：Java, Spring Boot, JavaScript, Python, MySQL, C++）
- 包含 `SkillSchema(name="Java")` 且 `original_names` 包含 `["java", "JAVA"]`
- 包含 `SkillSchema(name="Spring Boot")` 且 `original_names` 包含 `["SpringBoot"]`
- 包含 `SkillSchema(name="JavaScript")` 且 `original_names` 包含 `["JS"]`
- 包含 `SkillSchema(name="Python")`
- 包含 `SkillSchema(name="MySQL")` 且 `original_names` 包含 `["mysql", "MySQL"]`
- 包含 `SkillSchema(name="C++")` 且 `original_names` 包含 `["c++"]`
- 所有技能的 `category` 有值

---

## AC-009: 解析失败降级

**覆盖**: REQ-008, RULE-004

**Given** 一份 PDF 文件，且 pdfplumber 和 PyPDF2 均无法提取文本（非扫描件）

**When** 调用 `parse_resume(file)` 传入该文件

**Then**
- `status` 为 `ParseStatus.FAILED`
- `raw_text` 为空字符串
- `resume_data` 为 None
- `error_message` 不为空，包含具体错误描述
- 日志中记录了错误信息

---

**Given** 一份文本内容正常的简历，但 LLM API 返回的 JSON 格式不符合 ResumeSchema，且重试 1 次仍失败

**When** 调用 `parse_resume_text(text)`

**Then**
- `status` 为 `ParseStatus.PARTIAL`
- `raw_text` 保留原始文本
- `resume_data` 为 None 或包含部分填充的数据
- `error_message` 包含 "LLM 输出格式验证失败" 或类似描述
- 日志中记录了 Pydantic 验证错误详情

---

## AC-010: PII 字段加密

**覆盖**: RULE-007

**Given** 一段包含手机号 "13800138000" 和邮箱 "zhangsan@example.com" 的简历文本

**When** 调用 `parse_resume_text(text)` 完成解析

**Then**
- `resume_data.personal_info.phone` 以 `"encrypted:"` 开头（为加密后的 base64 字符串）
- `resume_data.personal_info.phone` 不等于明文 "13800138000"
- `resume_data.personal_info.email` 以 `"encrypted:"` 开头
- `resume_data.personal_info.email` 不等于明文 "zhangsan@example.com"
- `resume_data.personal_info.full_name` 为明文（未加密）

---

## AC-011: 加密 PDF 处理

**覆盖**: EC-001

**Given** 一份设置了打开密码的 PDF 文件

**When** 调用 `parse_resume(file)` 传入该文件

**Then**
- `status` 为 `ParseStatus.FAILED`
- `error_message` 包含 "加密" 或 "密码" 相关提示
- `raw_text` 为空
- 不会抛出未捕获异常

---

## AC-012: 扫描件 PDF 处理

**覆盖**: EC-002

**Given** 一份扫描件型 PDF（内容为图片，无文字层），且 PDF 包含内嵌图片

**When** 调用 `parse_resume(file)` 传入该文件

**Then**
- 系统检测到 pdfplumber 和 PyPDF2 提取结果为空
- 自动提取内嵌图片并调用 OCR
- `metadata.parse_tool` 为 `"deepseek-ocr"`
- `status` 为 `ParseStatus.SUCCESS` 或 `ParseStatus.PARTIAL`
- `raw_text` 非空（OCR 识别结果）

---

## AC-013: 非中文简历处理

**覆盖**: EC-004

**Given** 一份英文简历的纯文本

**When** 调用 `parse_resume_text(text)` 传入该文本

**Then**
- `status` 为 `ParseStatus.SUCCESS` 或 `ParseStatus.PARTIAL`
- `metadata.language` 为 `"en"` 或 `"mixed"`
- `resume_data` 中的字段以中文输出（LLM 统一用中文）
- 至少 `personal_info.full_name` 和 `skill_list` 有值

---

## AC-014: 空文件处理

**覆盖**: EC-005

**Given** 一个 0 字节的 PDF 文件

**When** 调用 `parse_resume(file)` 传入该文件

**Then**
- `status` 为 `ParseStatus.FAILED`
- `error_message` 包含 "文件为空" 或类似描述
- 不调用 LLM
- 不抛出未捕获异常

---

**Given** 一份 PDF 文件，提取后文本长度为 5 个字符（如乱码 "????"）

**When** 调用 `parse_resume(file)` 传入该文件

**Then**
- `status` 为 `ParseStatus.FAILED`
- `error_message` 包含 "内容为空或过少"
- 不调用 LLM

---

## AC-015: LLM Schema 验证失败重试

**覆盖**: EC-006

**Given** LLM 第一次返回的 JSON 中 `experience_list` 的元素缺少必填字段 `company`

**When** 系统检测到 Pydantic 验证失败

**Then**
- 系统自动重试 1 次（Prompt 中追加错误提示）
- 如重试成功：`status` 为 `ParseStatus.SUCCESS`
- 如重试失败：`status` 为 `ParseStatus.PARTIAL`，`error_message` 包含验证错误详情
- 日志中记录了重试前后的验证错误
- 总 LLM 调用次数 <= 2

---

## AC-016: LLM API 超时

**覆盖**: EC-010

**Given** DeepSeek API 在 60 秒内未返回响应

**When** 系统检测到 LLM 调用超时

**Then**
- `status` 为 `ParseStatus.PARTIAL`
- `raw_text` 保留已提取的文本
- `resume_data` 为 None
- `error_message` 包含 "超时" 相关描述
- 不进行重试（超时不做盲目重试）
- 日志中记录超时信息

---


---

## AC-017: Multi-Chunk 生成

**覆盖**: RULE-008

**Given** 一份包含教育经历、工作经历、项目经历、技能清单的标准简历文本

**When** 调用 `generate_chunks(resume_id, sections, full_text)`

**Then**
- 返回的 Chunk 列表包含 1 个 Full Resume Chunk（`chunk_level="full"`）
- 包含 4 个 Parent Chunk（对应 4 个 Section，`chunk_level="parent"`）
- 包含 N 个 Small Chunk（`chunk_level="small"`，N >= 4，取决于每个 Section 的内容长度）
- 每个 Small Chunk 的 `parent_chunk_id` 指向对应的 Parent Chunk
- 所有 Chunk 的 `resume_id` 一致
- 所有 Chunk 的 `chunk_id` 符合 `{resume_id}:{level}:{index}` 格式
- Chunk 列表按 `sequence_index` 排序

---

## AC-018: Small Chunk 长度控制

**覆盖**: RULE-009

**Given** 一段包含 3 个工作成果描述的工作经历文本（每条约 50~100 字符）

**When** 生成该 Section 的 Small Chunk

**Then**
- 每个 Small Chunk 的 `char_count` 在 30~300 范围内
- 没有丢失任何原始文本内容（所有 Small Chunk 的 content 拼接 ≈ Parent Chunk 的 content）
- 每个 Small Chunk 是完整的句子或语义单元（不在句子中间截断）

---

## AC-019: 短简历 Chunk 处理

**覆盖**: EC-013

**Given** 一份极短的简历文本（仅 50 字符，如"张三 Java 3年经验"）

**When** 调用 `generate_chunks(resume_id, sections, full_text)`

**Then**
- 仅返回 1 个 Full Resume Chunk
- `metadata` 中包含 `"short_resume": true`
- 不报错，不抛异常

---

## AC-020: 单 Section 简历 Chunk 处理

**覆盖**: EC-014

**Given** 一份无明确分区标题的纯文本简历（无法识别出教育/工作/项目等 Section）

**When** 对该简历执行语义切分和 Chunk 生成

**Then**
- 语义切分返回 1 个 Section（`section_type=OTHER`）
- 生成 1 个 Parent Chunk（`section_type="other"`）
- 正常生成 Small Chunk（按句子切分）
- `metadata` 中包含 `"single_section": true`


## AC-021: 文件 MD5 去重 — 相同文件重复上传

**覆盖**: EC-015

**Given** 一份 PDF 简历文件"张三_简历.pdf"已成功入库（resume_id=r_001, file_md5=abc123...）

**When** 再次上传同一份文件（文件名可改为"张三_最新简历.pdf"，但内容完全相同）

**Then**
- status 为 ParseStatus.SKIPPED
- ile_md5 与第一次上传时一致
- rror_message 包含"文件已存在"和已有 resume_id
- 不调用 LLM
- 不写入 MongoDB 新记录
- 不生成新的 Embedding
- 日志中记录"文件去重"事件

## AC-022: 文件 MD5 去重 — 不同文件正常入库

**覆盖**: EC-015

**Given** 一份 PDF 简历文件已入库，另一份内容不同的 PDF 文件

**When** 上传第二份文件

**Then**
- status 为 ParseStatus.SUCCESS（正常解析）
- ile_md5 与第一份不同
- 正常完成解析、入库、向量化全流程

## 验收执行方式

### 手动验收（Phase 8）

1. 准备测试简历文件集：
   - `test_pdf_text.pdf`（文本型 PDF）
   - `test_docx.docx`（DOCX 格式）
   - `test_image.jpg`（图片格式）
   - `test_resume.json`（JSON 格式）
   - `test_encrypted.pdf`（加密 PDF）
   - `test_scan.pdf`（扫描件 PDF）
   - `test_empty.pdf`（空文件）
   - `test_english.pdf`（英文简历）

2. 逐条执行 AC，记录通过/失败

### 自动化验收（Phase 7）

- 每条 AC 对应一个 pytest 测试用例
- LLM 调用在测试中使用 mock 或录制回放
- 测试在 Docker 容器内运行
