<!-- Module: resume-parser -->
<!-- Spec Layer: 04 - Business Rules -->
<!-- 变更: Tier L - RAG 全量重构 -->
<!-- Date: 2026-07-03 -->

# 业务规则：Resume Parser

## 规则总览

| ID | 规则名称 | 关联 REQ | 优先级 |
|----|----------|----------|--------|
| RULE-001 | PDF 提取优先级与降级 | REQ-001 | P0 |
| RULE-002 | 图片格式走 OCR 流程 | REQ-003 | P1 |
| RULE-003 | LLM 提取使用 Pydantic Schema 约束 | REQ-005 | P0 |
| RULE-004 | 解析失败保留原文并标记状态 | REQ-008 | P0 |
| RULE-005 | Skill 标准化大小写规则 | REQ-007 | P1 |
| RULE-006 | 同义词映射维护静态词典 | REQ-007 | P1 |
| RULE-007 | PII 字段加密存储 | NFR-013 | P1 |
| RULE-008 | Multi-Chunk 多粒度切分 | REQ-006 | P0 |
| RULE-009 | Small Chunk 长度控制 | REQ-006 | P0 |
| RULE-010 | 文件 MD5 去重 | - | P0 |

---

## RULE-001: PDF 提取优先级与降级

**规则描述**: PDF 简历文本提取优先使用 pdfplumber，当 pdfplumber 提取失败时自动降级到 PyPDF2。

**适用场景**: 所有 PDF 文件的文本提取

**规则逻辑**:

```
IF file_type == "pdf":
    1. TRY pdfplumber.extract_text(file)
       - IF raw_text 非空且长度 > 50 字符:
           RETURN (text=raw_text, tool="pdfplumber", status=success)
       - IF raw_text 为空或长度 <= 50 字符:
           LOG warning "pdfplumber 提取文本过短，可能为扫描件"
           CONTINUE to step 2
       - IF exception:
           LOG warning "pdfplumber 提取失败: {error}"
           CONTINUE to step 2
    
    2. TRY PyPDF2.extract_text(file)
       - IF raw_text 非空且长度 > 50 字符:
           RETURN (text=raw_text, tool="PyPDF2", status=success)
       - IF raw_text 为空或长度 <= 50 字符:
           LOG warning "PyPDF2 提取文本过短，可能为扫描件"
           CONTINUE to step 3
       - IF exception:
           LOG warning "PyPDF2 提取失败: {error}"
           CONTINUE to step 3
    
    3. 判断是否为扫描件型 PDF（图片型）:
       - TRY 提取 PDF 内嵌图片
       - IF 有内嵌图片:
           LOG info "检测到扫描件 PDF，转 OCR 流程"
           REDIRECT to OCR 流程 (RULE-002)
       - ELSE:
           RETURN (text="", tool="none", status=failed, error="无法提取 PDF 文本")
```

**判定阈值**: 原始文本长度 <= 50 字符视为提取失败（可能是空白页或乱码）

**优先级理由**: pdfplumber 对表格和布局的支持优于 PyPDF2，但 PyPDF2 对某些加密/特殊编码的 PDF 兼容性更好，因此作为降级方案。

---

## RULE-002: 图片格式走 OCR 流程

**规则描述**: 图片格式简历（jpg/jpeg/png）和扫描件型 PDF 使用 DeepSeek-OCR 进行文字识别。

**适用场景**: 所有图片格式简历和扫描件型 PDF

**规则逻辑**:

```
IF file_type IN ("jpg", "jpeg", "png"):
    1. 图片预处理:
       a. 检查图片大小
          - IF file_size > 10MB:
              使用 Pillow 缩放图片（保持宽高比，最大边 4096px）
              LOG info "图片过大，已缩放至 {new_size}"
       b. 检查图片格式
          - 转换为 RGB 模式（如为 RGBA/CMYK）
    
    2. 调用 DeepSeek-OCR:
       a. 将图片编码为 base64
       b. 调用 DeepSeek-OCR API
       c. 获取识别文本
    
    3. 结果处理:
       - IF raw_text 非空:
           RETURN (text=raw_text, tool="deepseek-ocr", status=success)
       - IF raw_text 为空:
           RETURN (text="", tool="deepseek-ocr", status=failed, error="OCR 未识别到文字")

ELIF file_type == "pdf" AND RULE-001 判定为扫描件:
    1. 从 PDF 提取内嵌图片
    2. 对每张图片执行上述 OCR 流程
    3. 合并所有图片的识别文本
```

**OCR 参数**:
- 模型: `deepseek-ai/DeepSeek-OCR`
- 最大图片尺寸: 4096px（长边）
- 支持语言: 中文、英文、中英混合

---

## RULE-003: LLM 提取使用 Pydantic Schema 约束

**规则描述**: LLM 结构化提取时，使用 Pydantic Schema 定义输出格式约束，确保 LLM 输出可被程序解析。

**适用场景**: 所有非 JSON 格式简历的结构化提取

**规则逻辑**:

```
1. 构建 LLM Prompt:
   a. System Prompt: 定义角色（简历解析专家）和输出要求
   b. User Prompt: 包含简历原始文本
   c. 输出格式要求: 明确指定 JSON Schema（与 ResumeSchema 对齐）

2. LLM 调用:
   a. 使用 OpenAI Compatible API 的 structured output 功能
   b. 传入 response_format = ResumeSchema 的 JSON Schema
   c. temperature = 0.1（保证输出稳定性）

3. 输出验证:
   a. 解析 LLM 返回的 JSON
   b. 使用 ResumeSchema.model_validate(json_data) 验证
   c. IF 验证成功:
        RETURN resume_data
   d. IF 验证失败:
        LOG warning "LLM 输出格式不符 Schema: {errors}"
        RETRY 1 次（在 Prompt 中追加格式错误提示）
        IF 重试仍失败:
            RETURN (status=partial, error="LLM 输出格式验证失败")
```

**Prompt 模板**:
```
System: 你是一个专业的简历解析专家。请将以下简历文本提取为结构化 JSON 数据。
       严格按照指定的 Schema 输出，不要添加额外字段。
       如果某个字段在简历中找不到对应信息，设置为 null。
       日期统一为 YYYY-MM 或 YYYY 格式。

User: {resume_text}

Output Schema: {ResumeSchema.model_json_schema()}
```

**重试策略**:
- 最大重试次数: 1 次
- 重试时在 Prompt 中追加上一次的错误信息
- 重试仍失败时标记 `status=partial`，返回部分结果

---

## RULE-004: 解析失败保留原文并标记状态

**规则描述**: 任何解析环节失败时，必须保留已提取的原始文本，标记解析状态，确保不丢数据。

**适用场景**: 所有解析失败场景

**规则逻辑**:

```
状态标记规则:

1. 文本提取环节失败:
   - raw_text = ""
   - status = ParseStatus.FAILED
   - error_message = "{具体错误}"
   - resume_data = None

2. LLM 结构化提取环节失败:
   - raw_text = "{已提取的文本}"（保留）
   - status = ParseStatus.PARTIAL
   - error_message = "LLM 结构化提取失败: {具体错误}"
   - resume_data = None 或部分填充的 ResumeSchema

3. Skill 标准化环节失败:
   - raw_text = "{已提取的文本}"
   - status = ParseStatus.PARTIAL（如 LLM 提取成功）
   - error_message = "Skill 标准化失败: {具体错误}"
   - resume_data = {LLM 提取的原始数据，skill_list 未标准化}

4. 部分字段提取失败:
   - 失败字段设为 None 或空列表
   - 成功字段正常填充
   - status = ParseStatus.PARTIAL
```

**数据保留原则**:
- `raw_text` 永远保留，即使 `resume_data` 为空
- 失败的解析结果仍然传递给 resume-store（存储原文 + 失败状态）
- 支持后续重新触发解析（用 `raw_text` 重新走 LLM 提取）

**日志要求**:
- 所有失败场景记录结构化 JSON 日志
- 日志包含: module, function, file_name, file_type, error_type, error_message, duration_ms

---

## RULE-005: Skill 标准化大小写规则

**规则描述**: 技能名称标准化时，统一为首字母大写、其余小写的格式，特殊名称按同义词词典处理。

**适用场景**: 所有技能名称的标准化

**规则逻辑**:

```
标准化流程:

1. 去除首尾空白字符

2. 查找同义词词典:
   - IF 原始名称在词典中:
       使用词典中的标准名称（词典中的名称已预设正确大小写）
   - IF 原始名称不在词典中:
       CONTINUE to step 3

3. 大小写标准化:
   a. 单词: 首字母大写，其余小写
      - "java" → "Java"
      - "PYTHON" → "Python"
      - "c++" → "C++"（特殊规则）
   
   b. 多词短语: 每个单词首字母大写
      - "machine learning" → "Machine Learning"
      - "spring boot" → "Spring Boot"
   
   c. 特殊大小写保留（词典外的手工规则）:
      - 包含大写字母缩写的保留: "iOS" → "iOS", "macOS" → "macOS"
      - 编程语言特殊规则: "JavaScript" → "JavaScript"（非 "Javascript"）
      - 保留 "+" 等特殊字符: "C++" → "C++", "C#" → "C#"

4. 去重:
   - 标准化后名称相同 → 合并，保留所有 original_names
```

**特殊名称规则表**（不在同义词词典中，但需要特殊大小写）:

| 原始输入 | 标准化输出 | 规则 |
|----------|-----------|------|
| c++, C++, cpp | C++ | 特殊字符保留 |
| c#, C#, csharp | C# | 特殊字符保留 |
| ios, IOS | iOS | 苹果命名规范 |
| macos, MACOS | macOS | 苹果命名规范 |
| ai, AI | AI | 两字母全大写保留 |
| ml, ML | ML | 两字母全大写保留 |
| nlp, NLP | NLP | 三字母全大写保留 |
| sql, SQL | SQL | 三字母全大写保留 |
| css, CSS | CSS | 三字母全大写保留 |
| html, HTML | HTML | 四字母全大写保留 |

---

## RULE-006: 同义词映射维护静态词典

**规则描述**: 技能同义词映射使用静态词典文件（JSON 格式），支持后续扩展。词典在模块启动时加载，运行时不动态修改。

**适用场景**: 所有技能名称的同义词查找

**词典格式**:
```json
{
  "version": "1.0.0",
  "updated_at": "2026-06-23",
  "mappings": [
    {
      "standard_name": "JavaScript",
      "category": "programming",
      "aliases": ["js", "JS", "javascript", "ecmascript", "ECMAScript", "ES6", "ES2015"]
    },
    {
      "standard_name": "Spring Boot",
      "category": "framework",
      "aliases": ["springboot", "SpringBoot", "spring-boot", "spring boot"]
    },
    {
      "standard_name": "Python",
      "category": "programming",
      "aliases": ["python", "PYTHON", "py", "Python3", "python3"]
    }
  ]
}
```

**规则逻辑**:
```
1. 模块启动时加载词典到内存:
   - 读取 config/skill_synonyms.json
   - 构建反向索引: alias → (standard_name, category)
   - 缓存到模块级变量

2. 查询时:
   - 将原始名称转小写
   - 在反向索引中查找
   - IF found: 返回 (standard_name, category)
   - IF not found: 返回 None（使用默认大小写规则）
```

**词典维护规则**:
- 词典文件存储在 `config/skill_synonyms.json`
- 版本号遵循 semver
- 新增同义词需人工审核
- 未知技能不做臆造映射，保留原名

**初始词典覆盖范围**（V1 必须包含）:
- 常见编程语言（20+）
- 常见框架（20+）
- 常见数据库（10+）
- 常见工具（10+）
- 常见云平台（5+）

---

## RULE-007: PII 字段加密存储

**规则描述**: 简历中的 PII（个人可识别信息）字段在解析阶段进行加密存储，使用 AES-256 对称加密。

**适用场景**: 所有包含 PII 字段的简历

**PII 字段清单**:

| 字段 | 类型 | 加密 | 脱敏展示 |
|------|------|------|----------|
| `phone` | 手机号 | ✅ AES-256 | `138****1234` |
| `email` | 邮箱 | ✅ AES-256 | `zhang***@gmail.com` |
| `full_name` | 姓名 | ❌ | 明文 |
| `birth_year` | 出生年份 | ❌ | 明文 |

**加密流程**:
```
1. LLM 提取出 PersonalInfo 中的 phone 和 email
2. 使用 PII_ENCRYPT_KEY 对字段值进行 AES-256-GCM 加密
3. 加密后的值格式: "encrypted:{base64_encoded_ciphertext}"
4. 存入 ResumeSchema 的对应字段
5. ResumeSchema 传递给 resume-store 时，resume-store 直接存储加密值
```

**密钥管理**:
- 密钥来源: 环境变量 `PII_ENCRYPT_KEY`
- 密钥长度: 32 字节（256 位）
- 密钥格式: base64 编码
- 密钥轮换: V1 不支持（V2 实现密钥版本管理）

**脱敏规则**:
- 手机号: 保留前 3 位和后 4 位，中间用 `****` 替代 → `138****1234`
- 邮箱: 用户名保留前 3 位，其余用 `***` 替代，域名保留 → `zhang***@gmail.com`
- 脱敏在展示阶段执行（由 api-layer 负责），不在解析阶段

---

## RULE-008: Multi-Chunk 基于结构化数据切分

> **变更说明 (Tier L)**: 不再从 raw_text 按关键词+字符数切割，改为从 LLM 提取的 ResumeStructured 结构化数据构建 Chunk。

**规则描述**: 简历解析后从 ResumeStructured 构建三个粒度的 Chunk：Full Resume（LLM 摘要）、Parent Chunk（Section 级）、Small Chunk（单条结构化记录），每个 Chunk 携带完整 metadata 支持向量库预过滤。

**适用场景**: 所有成功解析的简历（ResumeStructured.confidence_score >= 0.3）

**Chunk 构建规则**:

```
1. Full Resume Chunk (1 个):
   - content = resume_structured.personal_info.summary（如有）或 raw_text
   - chunk_level = "full"
   - metadata = 候选人级 metadata 全量字段
   - 用途: 全局语义匹配 + LLM 推荐理由的完整上下文

2. Parent Chunks (N 个, N = 非空 section 数量):
   - 每个 Section 对应一个 Parent Chunk
   - content = 该 section 下所有条目的拼接文本
   - chunk_level = "parent"
   - section_type = education/experience/project/skill
   - metadata = 候选人级 metadata + section_type
   - 用途: Small→Big 召回的 "Big"（LLM 上下文提供）

3. Small Chunks (M 个):
   - 每条结构化记录 → 一个 Small Chunk
   - education_list 每条 → "学校 | 专业 | 学历 | 日期"
   - experience_list 每条 → "公司 | 职位 | 日期\n描述\n成就"
   - project_list 每条 → "项目名 | 角色 | 日期\n描述\ntech_stack"
   - skill_list 按类别分组 → "技能名(熟练度,年限), ..."
   - chunk_level = "small"
   - parent_chunk_id = 对应 Parent Chunk 的 chunk_id
   - metadata = 候选人级 metadata + chunk 级 metadata（organization, title, dates, tech_stack 等）
   - 用途: 向量检索的最小单元（Small→Big 中的 "Small"）
```

**Metadata 填充规则**:
- 候选人级字段（years_of_experience, city, gender, highest_education_level, skills_normalized 等）从 ResumeStructured.personal_info 提取
- 所有 chunk 共享同一份候选人级 metadata
- 这使得 vector-index 可以在 Milvus expr 中做硬约束预过滤（如 `years_of_experience >= 5`）

**降级策略**:
- ResumeStructured 为 None 或 confidence_score < 0.3:
  - 降级为旧策略：从 raw_text 按 SectionType 关键词切分 + 字符数合并
  - metadata 仅含 section_type（不包含候选人级字段）
  - 记录警告日志 "Chunk 降级为 raw_text 切分模式"

**预计 Chunk 数量** (2 页简历):
- 1 Full + ~4 Parent + ~10 Small = ~15 个

---

## RULE-009: Small Chunk 基于结构化记录构建

> **变更说明 (Tier L)**: 不再按句号/字符数切割，改为每条结构化记录（一条工作经历/一个项目/一条教育）作为一个 Small Chunk。

**规则描述**: Small Chunk 从 ResumeStructured 的结构化列表构建，每条记录为一个完整语义单元，携带该记录的 metadata。

**适用场景**: ResumeStructured.confidence_score >= 0.3 的简历

**Small Chunk 构建规则**:

```
1. 工作经历 Small Chunk (每条 ExperienceEntry 一个):
   - content 格式: "{company} | {title} | {start_date} ~ {end_date}\n{description}\n成就: {achievements}"
   - metadata: section_type=experience, organization=company, title=title, start_date, end_date
   - 示例: "阿里巴巴 | 高级Java工程师 | 2019-07 ~ 2024-03\n负责电商交易系统后端架构设计..."

2. 项目经历 Small Chunk (每条 ProjectEntry 一个):
   - content 格式: "{name} | {role} | {start_date} ~ {end_date}\n{description}\n技术栈: {tech_stack}"
   - metadata: section_type=project, organization=name, title=role, tech_stack, start_date, end_date

3. 教育经历 Small Chunk (每条 EducationEntry 一个):
   - content 格式: "{school} | {major} | {degree} | {start_date} ~ {end_date}"
   - metadata: section_type=education, organization=school, start_date, end_date

4. 技能 Small Chunk (按 category 分组):
   - content 格式: "{skill_name}({proficiency},{years}年), ..."
   - metadata: section_type=skill
```

**长内容处理**:
- 单条记录描述过长（> 500 字符）→ 按句号（。/./；/;）切分为多个 Small Chunk，共享同一 parent_chunk_id
- 切分后的 Small Chunk 继承完整 metadata

**降级策略** (ResumeStructured 不可用时):
- 从 raw_text 按 SectionType 关键词识别 section 边界
- 在每个 section 内按句号+换行切分
- 合并到 50-200 字符
- metadata 仅含 section_type（无候选人级字段）

**与旧策略对比**:

| 维度 | 旧策略（关键词+字符数） | 新策略（结构化数据） |
|------|----------------------|---------------------|
| 边界识别 | 关键词 in 匹配（误判率高） | LLM 提取的结构化列表（精确） |
| 语义完整性 | 按字符数 50-200 切断 | 每条记录完整语义单元 |
| Metadata | 仅 section_type | 候选人级 + chunk 级完整字段 |
| 标量预过滤 | 不支持（metadata 为空） | 支持（years, education, city, gender 在 Milvus 标量列） |
| Overlap | 无 | 无需（语义单元天然不重叠） |

---

## RULE-010: 文件 MD5 去重

**规则描述**: 简历解析前，先计算文件内容的 MD5 哈希值，检查是否已有相同文件入库。若已存在则跳过解析，直接返回已有简历信息。

**适用场景**: 所有通过文件上传的简历（PDF/DOCX/图片）

**规则逻辑**:

`
1. 读取文件全部内容到内存
2. 计算 MD5: file_md5 = hashlib.md5(file_bytes).hexdigest()
3. 调用 resume-store.find_by_md5(file_md5):
   a. IF 返回已有简历 (status=active):
        RETURN ParseResult(status=SKIPPED, file_md5=file_md5,
                           error_message="文件已存在，resume_id={existing_id}")
        LOG info "文件去重命中: file_md5={file_md5}, existing={existing_id}"
   b. IF 返回 None (不存在):
        CONTINUE 正常解析流程
   c. IF 已有简历但 status=deleted:
        CONTINUE 正常解析流程（允许重新上传已删除的简历）
4. 解析完成后，在 ResumeMetadata 中记录 file_md5
5. 传递给 resume-store 入库时，file_md5 作为字段写入 MongoDB
`

**去重维度**:
- 基于**文件内容**（MD5），不基于文件名
- 同一文件更换文件名 → MD5 相同 → 去重
- 不同文件内容完全一致 → MD5 相同 → 去重（预期行为）

**性能要求**:
- MD5 计算耗时 < 50ms（20MB 文件）
- find_by_md5 查询走 MongoDB UNIQUE 索引，P95 < 10ms

**优先级理由**: 避免重复解析消耗 LLM Token 和 FlagEmbedding 推理资源，减少 Milvus 中冗余向量。