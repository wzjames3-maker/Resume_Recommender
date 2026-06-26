<!-- Module: resume-parser -->
<!-- Spec Layer: 05 - Edge Cases -->
<!-- Phase: Phase 4 - Spec Writing -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-23 -->

# 边界情况与异常处理：Resume Parser

## 边界情况总览

| ID | 边界情况 | 触发条件 | 影响范围 | 处理策略 |
|----|----------|----------|----------|----------|
| EC-001 | PDF 加密/密码保护 | 用户上传加密 PDF | PDF 文本提取 | 提示用户输入密码或跳过 |
| EC-002 | 扫描件型 PDF（图片型 PDF） | PDF 内容为扫描图片而非文字 | PDF 文本提取 | 检测并转 OCR 流程 |
| EC-003 | DOCX 包含图片 | DOCX 内嵌图片简历 | DOCX 文本提取 | 提取图片走 OCR |
| EC-004 | 简历语言非中文 | 英文/日文/混合语言简历 | LLM 提取 | 仍尝试解析，标记语言 |
| EC-005 | 简历内容为空 | 上传空白文件或无文字内容 | 全流程 | 标记 failed |
| EC-006 | LLM 返回格式不符 Schema | LLM 输出 JSON 不符合 Pydantic 定义 | LLM 结构化提取 | 重试 1 次，仍失败降级 |
| EC-007 | 并发上传同名文件 | 多用户同时上传同名文件 | 文件去重 | 按 resume_id 去重 |
| EC-013 | 简历内容过短无法切分 | 简历文本 < 100 字符 | Chunk 生成 | 仅生成 Full Chunk，不切分 |
| EC-014 | Single Section 简历 | 简历无明确分区标题 | Chunk 生成 | 整份简历作为单一 Parent Chunk |
| EC-015 | 文件内容重复上传 | 上传的文件 MD5 与已入库简历相同 | 入库流程 | 返回已有简历 resume_id，标记 status=skipped，不重复解析入库 |

---

## EC-001: PDF 加密/密码保护

**触发条件**: 用户上传的 PDF 文件设置了打开密码或权限密码

**检测方式**:
```python
# pdfplumber 检测
try:
    with pdfplumber.open(file) as pdf:
        _ = pdf.pages[0]  # 尝试读取第一页
except pdfplumber.PasswordNotProvided:
    # 加密 PDF，需要密码
except Exception as e:
    # 其他错误
```

**处理策略**:

```
IF PDF 加密（需要密码）:
    1. 返回 ParseResult(
         status=ParseStatus.FAILED,
         error_message="PDF 文件已加密，请提供密码或上传未加密版本",
         raw_text=""
       )
    2. 记录日志: LOG warning "加密 PDF: {file_name}"
    3. 由 api-layer 返回 422 错误给用户，提示上传未加密版本
```

**不做的事**:
- V1 不实现密码输入/自动破解功能
- V1 不尝试常见密码字典

---

## EC-002: 扫描件型 PDF（图片型 PDF）

**触发条件**: PDF 的内容为扫描图片而非可选择的文字，pdfplumber 和 PyPDF2 均无法提取有效文本

**检测方式**:
```
IF pdfplumber 提取文本长度 <= 50 字符
   AND PyPDF2 提取文本长度 <= 50 字符:
    → 可能是扫描件型 PDF
    尝试提取 PDF 内嵌图片数量
    IF 有内嵌图片:
        → 确认为扫描件型 PDF
```

**处理策略**:

```
IF 确认为扫描件型 PDF:
    1. 提取 PDF 每一页的内嵌图片
       - 使用 PyPDF2 或 pdfplumber 提取图片对象
       - 将图片转为 PIL Image
    
    2. 对每张图片执行 OCR 流程 (RULE-002):
       - 图片预处理（如需要）
       - 调用 DeepSeek-OCR
       - 获取识别文本
    
    3. 合并所有页面的识别文本:
       - 按页码顺序拼接
       - 页与页之间用换行符分隔
    
    4. 后续流程与普通 PDF 一致:
       - 语义切分 → LLM 提取 → Skill 标准化
    
    5. metadata 中标记:
       - parse_tool = "deepseek-ocr"
       - 追加日志 "扫描件型 PDF，已转 OCR 处理"
```

**降级策略**:
- 如果 PDF 内嵌图片提取失败: `status=failed, error="扫描件 PDF 无法提取图片"`
- 如果 OCR 识别失败: `status=failed, error="扫描件 PDF OCR 识别失败"`

---

## EC-003: DOCX 包含图片

**触发条件**: DOCX 文件中包含图片简历（如将简历截图插入 DOCX），纯文本提取结果为空或极少

**检测方式**:
```
1. python-docx 提取所有段落文本
2. IF 段落文本总长度 <= 50 字符:
    → 文本过少，检查是否包含图片
3. 检查 DOCX 内嵌图片:
   - 遍历 doc.inline_shapes
   - IF 有内嵌图片:
       → 可能为图片型 DOCX
```

**处理策略**:

```
IF DOCX 文本过少 且 包含图片:
    1. 提取 DOCX 内嵌图片
       - 遍历 doc.inline_shapes
       - 提取图片二进制数据
       - 保存为临时文件
    
    2. 对每张图片执行 OCR 流程 (RULE-002):
       - 调用 DeepSeek-OCR
       - 获取识别文本
    
    3. 合并图片 OCR 文本 + 原始段落文本（如有）
    
    4. 后续流程一致

ELIF DOCX 包含图片 且 文本足够:
    → 正常文本提取，忽略图片
    → 图片中的附加信息（如证件照中的文字）不处理
```

**注意**: V1 对 DOCX 图片中的简历信息提取为 best-effort，不保证完整。

---

## EC-004: 简历语言非中文

**触发条件**: 简历内容为英文、日文或其他非中文语言

**检测方式**:
```python
# 简单语言检测（基于字符比例）
def detect_language(text: str) -> str:
    total = len(text)
    if total == 0:
        return "unknown"
    
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    chinese_ratio = chinese_chars / total
    
    if chinese_ratio > 0.3:
        return "zh"      # 中文为主
    elif chinese_ratio > 0.1:
        return "mixed"   # 中英混合
    else:
        return "en"      # 英文为主
```

**处理策略**:

```
1. 文本提取后自动检测语言
2. IF language == "en":
   a. LLM Prompt 中注明"该简历为英文，请用中文输出结构化数据"
   b. LLM 仍使用中文输出 Schema
   c. metadata.language = "en"
3. IF language == "mixed":
   a. LLM Prompt 中注明"该简历为中英混合"
   b. metadata.language = "mixed"
4. IF language == "unknown" 或其他:
   a. 仍尝试让 LLM 解析
   b. LLM 可能返回部分字段为空
   c. metadata.language = "other"
   d. LOG warning "不常见的简历语言: {file_name}"
```

**不做**:
- V1 不做日文/韩文等 CJK 语言的专项优化
- V1 不拒绝非中文简历，尽力解析

---

## EC-005: 简历内容为空

**触发条件**: 上传的文件为空文件、或文本提取结果为空

**检测方式**:
```
多个检测点:
1. 文件级别: file_size == 0
2. 文本提取后: raw_text.strip() == ""
3. 文本提取后: raw_text 长度 <= 10 字符（可能是乱码或空白）
```

**处理策略**:

```
IF file_size == 0:
    RETURN ParseResult(
        status=ParseStatus.FAILED,
        error_message="文件为空",
        raw_text=""
    )

IF raw_text.strip() == "" OR len(raw_text.strip()) <= 10:
    RETURN ParseResult(
        status=ParseStatus.FAILED,
        error_message="简历内容为空或过少，无法解析",
        raw_text=raw_text
    )
    LOG warning "空内容简历: {file_name}, 提取文本长度={len(raw_text)}"
```

**不做的事**:
- 不对空文件进行 LLM 提取（浪费 token）
- 不对空文件进行重试

---

## EC-006: LLM 返回格式不符 Schema

**触发条件**: LLM 输出的 JSON 不符合 Pydantic ResumeSchema 定义（字段缺失、类型错误、格式异常等）

**常见不符合场景**:
| 场景 | 示例 | Pydantic 错误 |
|------|------|--------------|
| 字段类型错误 | `years_of_experience: "五年"` | ValidationError: int expected |
| 必填字段缺失 | `experience_list` 中缺少 `company` | ValidationError: field required |
| 枚举值错误 | `degree: "本科在读"`（非标准值） | ValidationError: invalid enum |
| 嵌套结构错误 | `education_list` 为字符串而非列表 | ValidationError: list expected |
| JSON 格式错误 | LLM 输出包含 markdown 标记 | JSONDecodeError |

**处理策略**:

```
1. 第一次 LLM 调用:
   a. 调用 LLM 获取输出
   b. 尝试 JSON 解析
      - IF JSONDecodeError:
          清理输出（去除 markdown 标记 ```json ... ```）
          重新解析
          IF 仍然失败:
              CONTINUE to retry
   c. 尝试 Pydantic 验证
      - IF ValidationError:
          记录具体错误字段和原因
          CONTINUE to retry

2. 重试（最多 1 次）:
   a. 调整 Prompt:
      - 追加上一次的错误信息
      - 强调格式要求
      示例: "上一次输出有以下错误，请修正：{errors}。请严格按 Schema 输出。"
   b. 重新调用 LLM
   c. 重新验证
      - IF 验证成功: RETURN resume_data
      - IF 验证失败: CONTINUE to fallback

3. 降级（retry 后仍失败）:
   a. 尝试部分解析:
      - 对 LLM 输出中合法的字段手动提取
      - 不合法字段设为默认值（None/空列表）
   b. IF 有部分有效字段:
        RETURN (status=ParseStatus.PARTIAL, resume_data=partial_data)
   c. IF 完全无法解析:
        RETURN (status=ParseStatus.PARTIAL, resume_data=None,
                error_message="LLM 输出格式验证失败: {errors}")
```

**日志要求**:
```json
{
  "level": "warning",
  "module": "resume_parser",
  "function": "extract_with_llm",
  "file_name": "resume.pdf",
  "error_type": "schema_validation_error",
  "validation_errors": [
    {"field": "experience_list.0.company", "error": "field required"},
    {"field": "personal_info.years_of_experience", "error": "int expected, got str"}
  ],
  "retry_count": 1,
  "llm_model": "deepseek-chat",
  "llm_tokens_used": 2048
}
```

---

## EC-007: 并发上传同名文件

**触发条件**: 多个用户同时上传文件名相同的简历（或同一用户重复上传）

**处理策略**:

```
1. 文件名去重不是本模块的职责:
   - resume_id 由 resume-store 生成（UUID），与文件名无关
   - 同名文件会被视为不同简历

2. 本模块的处理:
   - 文件名仅用于 metadata.source_file_name 记录
   - 不基于文件名做去重判断
   - 每次调用 parse_resume 都生成独立的解析结果

3. 去重由 resume-store 负责:
   - resume-store 可基于文件内容 hash（MD5/SHA256）做去重
   - 或基于姓名+手机号组合去重
   - 具体策略见 resume-store 模块的 Spec

4. 并发安全:
   - parse_resume 函数本身无状态，天然支持并发调用
   - 同义词词典为只读共享，无并发写入风险
   - LLM API 调用通过 httpx 异步客户端，支持并发
```

---

## 其他边界情况

### EC-008: 文件格式与扩展名不匹配

**触发条件**: 文件扩展名为 .pdf 但实际是 DOCX，或反之

**处理策略**:
```
1. 优先按文件扩展名选择解析器
2. IF 按扩展名解析失败:
   a. 尝试通过文件内容的 magic bytes 检测真实格式
   b. IF 真实格式与扩展名不同:
      LOG warning "文件格式与扩展名不匹配: {file_name}, 实际格式={detected_type}"
      使用真实格式重新解析
   c. IF 无法检测真实格式:
      status=failed
```

### EC-009: 文件过大

**触发条件**: 上传文件超过 20MB

**处理策略**:
```
1. 在 api-layer 层进行文件大小校验（parse_resume 调用前）
2. IF file_size > 20MB:
   直接返回 413 Payload Too Large
3. 本模块内不做文件大小校验（由调用方保证）
```

### EC-010: LLM API 超时

**触发条件**: DeepSeek API 调用超时（默认 60s）

**处理策略**:
```
1. 设置 LLM 调用超时时间为 60s
2. IF 超时:
   a. LOG error "LLM 调用超时: {timeout}s"
   b. 不重试（超时通常意味着服务端问题，重试无效）
   c. RETURN (status=ParseStatus.PARTIAL, raw_text=raw_text,
              error_message="LLM 调用超时")
3. raw_text 保留，支持后续手动重试
```

### EC-011: OCR API 不可用

**触发条件**: DeepSeek-OCR 服务不可用或返回错误

**处理策略**:
```
1. IF OCR API 调用失败:
   a. LOG error "OCR API 调用失败: {error}"
   b. RETURN (status=ParseStatus.FAILED,
              error_message="图片 OCR 识别失败，请稍后重试或上传 PDF/DOCX 格式")
2. 不自动降级到其他 OCR 引擎（V1 仅支持 DeepSeek-OCR）
3. 建议用户转换格式（图片 → PDF/DOCX）
```

### EC-012: 简历格式极端非标

**触发条件**: 简历使用极端非标准格式（如纯图片无文字、艺术字体、手写简历等）

**处理策略**:
```
1. LLM 提取后字段大面积为空:
   - IF 关键字段（name, experience_list, skill_list）全部为空:
       status = ParseStatus.PARTIAL
       error_message = "简历格式非标，仅提取到部分信息"
2. 建议在日志中标记 "low_quality_parse"
```


### EC-013: 简历内容过短无法切分

**触发条件**: 简历原始文本长度 < 100 字符

**处理策略**:
```
1. 仅生成 Full Resume Chunk (chunk_level=full)
2. 不生成 Parent Chunk 和 Small Chunk
3. metadata 中标记 "short_resume": true
4. 不影响后续入库流程（向量索引仅使用 Full Chunk）
```

### EC-014: Single Section 简历

**触发条件**: 简历文本无法识别出多个 Section（如一段纯文本、无标题分隔）

**处理策略**:
```
1. 语义切分返回 1 个 Section (section_type=OTHER)
2. 生成 1 个 Parent Chunk (section_type=other)
3. 正常生成 Small Chunk（按句子切分）
4. metadata 中标记 "single_section": true
```

### EC-015: 文件内容重复上传

**触发条件**: 上传文件的 MD5 哈希值与 MongoDB 中已存在的某份简历（status=active）的 file_md5 相同

**检测方式**:
`
1. 文件读取后立即计算 MD5: file_md5 = hashlib.md5(file_bytes).hexdigest()
2. 调用 resume-store find_by_md5(file_md5)
3. IF 返回非空（已有简历）:
     → 文件已存在
`

**处理策略**:
`
IF 文件 MD5 已存在:
    1. 返回 ParseResult(
         status=ParseStatus.SKIPPED,
         file_md5=file_md5,
         resume_data=None,
         error_message="文件已存在，已有 resume_id={existing_resume_id}"
       )
    2. 记录日志: LOG info "文件去重: file_md5={file_md5}, existing_resume_id={existing_id}"
    3. 由 api-layer 返回给用户:
       {
         "resume_id": existing_resume_id,
         "status": "skipped",
         "message": "该文件已存在于人才库中"
       }
    4. 不重新解析、不重新生成向量、不重复写入 MongoDB
`

**边界情况**:
- 同一文件更换文件名后上传 → MD5 相同，仍去重（内容去重，非文件名去重）
- 不同文件但 MD5 碰撞 → 概率极低（2^128），V1 不处理，V2 可增加 SHA-256 双重校验
- file_md5 为 None（旧数据迁移）→ 不触发去重，正常解析入库
- 已有简历被软删除（status=deleted）→ 视为不存在，允许重新上传