<!-- Module: resume-parser -->
<!-- Spec Layer: 04 - Business Rules -->
<!-- Phase: Phase 4 - Spec Writing -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-23 -->

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

## RULE-008: Multi-Chunk 多粒度切分

**规则描述**: 简历解析后需生成三个粒度的 Chunk：Full Resume、Parent Chunk（Section 级）、Small Chunk（单句级），用于下游向量索引的多粒度检索。

**适用场景**: 所有成功解析的简历

**规则逻辑**:

```
1. Full Resume Chunk (1 个):
   - content = 简历完整文本
   - chunk_level = "full"
   - 用途: LLM 生成推荐理由时的完整上下文

2. Parent Chunk (N 个, N = Section 数量):
   - content = Section 原始文本
   - chunk_level = "parent"
   - section_type = 对应 Section 类型
   - 用途: 检索命中后提供给 LLM 的上下文（Small→Big 策略中的 "Big"）

3. Small Chunk (M 个):
   - content = Section 内的子段落
   - chunk_level = "small"
   - 用途: 向量检索的最小单元（Small→Big 策略中的 "Small"）
```

**Chunk 层级关系**:
```
Full Resume
├── Parent Chunk (教育经历)
│   ├── Small Chunk 1
│   └── Small Chunk 2
├── Parent Chunk (工作经历)
│   ├── Small Chunk 3
│   ├── Small Chunk 4
│   └── Small Chunk 5
└── Parent Chunk (技能清单)
    └── Small Chunk 6
```

**优先级理由**: Multi-Chunk 是实现 Small→Big 检索策略的基础，直接影响检索质量（Recall@10）。

---

## RULE-009: Small Chunk 长度控制

**规则描述**: Small Chunk 的切分需要控制长度，过短则语义不完整，过长则丧失精准检索的优势。

**适用场景**: 所有 Small Chunk 的生成

**切分策略**:

```
输入: Parent Chunk 的文本内容

1. 按句子边界切分:
   - 中文: 按句号（。）、分号（；）、换行符（\n）切分
   - 英文: 按句号（.）、分号（;）、换行符（\n）切分
   - 保留分隔符在句尾

2. 合并过短段落:
   - IF 句子长度 < 30 字符:
       与下一个句子合并
   - IF 合并后仍 < 30 字符:
       继续合并（最多合并 3 个连续短句）

3. 切分过长段落:
   - IF 句子长度 > 300 字符:
       按逗号（，/,）或顿号（、）切分
       保证每个子段 >= 50 字符

4. 最终校验:
   - 每个 Small Chunk 长度范围: 30~300 字符（极端情况允许超出）
   - 目标长度: 50~200 字符
```

**示例**:

| 原始文本 | 切分结果 |
|----------|----------|
| "2022.07-至今 阿里巴巴 高级Java工程师。负责订单系统核心模块开发，日均处理订单量 500 万+。主导微服务架构改造，系统可用性从 99.5% 提升至 99.99%。" | Small-1: "2022.07-至今 阿里巴巴 高级Java工程师。"  Small-2: "负责订单系统核心模块开发，日均处理订单量 500 万+。"  Small-3: "主导微服务架构改造，系统可用性从 99.5% 提升至 99.99%。" |

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

**优先级理由**: 避免重复解析消耗 LLM Token 和 BGE-M3 API 调用，减少 Milvus 中冗余向量。