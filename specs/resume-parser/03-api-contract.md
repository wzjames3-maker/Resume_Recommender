<!-- Module: resume-parser -->
<!-- Spec Layer: 03 - API Contract -->
<!-- 变更: Tier L - RAG 全量重构 -->
<!-- Date: 2026-07-03 -->

# 内部接口契约：Resume Parser

## 1. 接口概述

Resume Parser 模块提供**内部函数接口**，不对外暴露 HTTP 端点。其他模块（如 API 层的简历上传接口）通过 Python 函数调用方式使用本模块。

**调用方式**: 直接 Python 函数调用（`from src.resume_parser import ...`）

**注意**: 本模块不直接暴露 REST API。简历上传的 HTTP 端点由 `api-layer` 模块提供，该模块调用本模块的函数接口。

---

## 2. 接口清单

| 函数名 | 输入 | 输出 | 说明 |
|--------|------|------|------|
| `parse_resume` | `UploadFile` | `ParseResult` | 主入口：解析上传文件为结构化 Resume |
| `parse_resume_text` | `str` (纯文本) | `ResumeSchema` | 纯文本结构化提取（跳过文本提取步骤） |
| `standardize_skills` | `list[str]` | `list[SkillSchema]` | Skill 标准化 |
| `generate_chunks` | `str, ResumeStructured, str` | `list[ChunkSchema]` | 从结构化数据构建多粒度 Chunk |

---

## 3. 接口详情

### 3.1 parse_resume

**用途**: 主入口函数，接收上传文件，完成从文件到结构化 Resume 的完整解析流程。

**签名**:
```python
async def parse_resume(file: UploadFile) -> ParseResult:
```

**输入参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | `UploadFile` | 是 | FastAPI UploadFile 对象，包含文件名、内容类型、文件流 |

**输出**: `ParseResult`

| 字段 | 类型 | 说明 |
|------|------|------|
| `resume_id` | `Optional[str]` | 简历 ID（本阶段为 None，由 resume-store 生成） |
| `raw_text` | `str` | 提取的原始文本 |
| `sections` | `list[SectionSchema]` | 语义段落列表 |
| `chunks` | `list[ChunkSchema]` | 多粒度 Chunk 列表（Small + Parent + Full） |
| `resume_data` | `Optional[ResumeSchema]` | 结构化简历数据 |
| `status` | `ParseStatus` | 解析状态 |
| `error_message` | `Optional[str]` | 错误信息（失败时） |

**处理流程**:
```
1. 读取文件内容和元信息（文件名、大小、类型）
1.1 计算文件内容 MD5（file_md5 = hashlib.md5(file_bytes).hexdigest()）
1.2 调用 resume-store find_by_md5(file_md5) 检查重复：若已存在则返回 ParseResult(status=skipped)，否则继续
2. 根据文件类型分发：
   - .pdf  → _extract_pdf()
   - .docx → _extract_docx()
   - .jpg/.jpeg/.png → _extract_image_ocr()
   - .json → _import_json()
   - 其他  → status=failed, error="不支持的文件格式"
3. 文本提取成功后：
   a. 语义段落切分 → sections
   b. LLM 结构化提取 → resume_data
   c. Skill 标准化 → resume_data.skill_list
4. 返回 ParseResult
```

**异常处理**:

| 异常场景 | 处理方式 | status |
|----------|----------|--------|
| 文件为空 | 返回 `ParseResult(status=failed, error_message="文件为空")` | `failed` |
| 不支持的格式 | 返回 `ParseResult(status=failed, error_message="不支持的文件格式: {ext}")` | `failed` |
| 文本提取失败 | 返回 `ParseResult(status=failed, error_message="{具体错误}")` | `failed` |
| LLM 提取失败 | 返回 `ParseResult(status=partial, raw_text=..., error_message="LLM 结构化提取失败")` | `partial` |
| Skill 标准化失败 | 返回原始 skill_list，标记 `status=partial` | `partial` |
| 文件 MD5 重复 | 返回 ParseResult(status=skipped, file_md5=..., error_message=文件已存在) | `skipped` |

**性能要求**:
- P95 延迟 <= 5s（PDF/DOCX），<= 10s（图片 OCR）
- 依赖 LLM 调用延迟

---

### 3.2 parse_resume_text

**用途**: 接收纯文本内容，跳过文本提取步骤，直接进行语义切分和 LLM 结构化提取。适用于已有纯文本的场景。

**签名**:
```python
async def parse_resume_text(text: str) -> ResumeSchema:
```

**输入参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `text` | `str` | 是 | 简历纯文本内容，最大 100,000 字符 |

**输出**: `ResumeSchema`

完整的结构化简历数据，metadata 中 `source_file_type` 为 `"text"`，`parse_tool` 为 `None`。

**处理流程**:
```
1. 输入校验（非空、长度限制）
2. 语义段落切分 → sections
3. LLM 结构化提取 → resume_data
4. Skill 标准化 → resume_data.skill_list
5. 返回 ResumeSchema
```

**异常处理**:

| 异常场景 | 处理方式 |
|----------|----------|
| text 为空 | 抛出 `ValueError("简历文本不能为空")` |
| text 超长 | 截断到 100,000 字符，记录警告日志 |
| LLM 提取失败 | 抛出 `ResumeParseError("LLM 结构化提取失败: {detail}")` |
| Pydantic 验证失败 | 重试 1 次，仍失败则抛出 `ResumeParseError` |

---

### 3.3 standardize_skills

**用途**: 对技能列表进行标准化处理（大小写统一、同义词映射、去重）。

**签名**:
```python
def standardize_skills(skills: list[str]) -> list[SkillSchema]:
```

**输入参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `skills` | `list[str]` | 是 | 原始技能名称列表 |

**输出**: `list[SkillSchema]`

标准化后的技能列表，每个元素包含标准化后的 `name`、`category`（如可推断）和 `original_names`。

**处理流程**:
```
1. 遍历 skills 列表
2. 对每个 skill：
   a. 去除首尾空白
   b. 查找同义词词典 → 映射到标准名称
   c. 大小写标准化（首字母大写，特殊名称按词典）
   d. 分类（如可从词典中查到）
3. 按标准化后的 name 去重
4. 合并同义词的 original_names
5. 返回标准化列表
```

**示例**:

```python
# 输入
["java", "JAVA", "SpringBoot", "JS", "python", "mysql", "MySQL"]

# 输出
[
    SkillSchema(name="Java", category="programming", original_names=["java", "JAVA"]),
    SkillSchema(name="Spring Boot", category="framework", original_names=["SpringBoot"]),
    SkillSchema(name="JavaScript", category="programming", original_names=["JS"]),
    SkillSchema(name="Python", category="programming", original_names=["python"]),
    SkillSchema(name="MySQL", category="database", original_names=["mysql", "MySQL"]),
]
```

---

### 3.4 generate_chunks

**用途**: 从 LLM 提取的结构化数据（ResumeStructured）构建多粒度 Chunk 列表。

> **变更说明 (Tier L)**: 输入从 `(resume_id, sections, full_text)` 改为 `(resume_id, resume_structured, raw_text)`。
> Chunk 不再从 raw_text 按字符数切割，而是从结构化数据中每条记录生成一个 Small Chunk。
> 每个 Chunk 携带完整 metadata（候选人级 + Chunk 级），支持 Milvus 标量预过滤。

**签名**:
```python
def generate_chunks(
    resume_id: str,
    resume_structured: ResumeStructured,
    raw_text: str,
) -> list[ChunkSchema]:
```

**输入参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `resume_id` | `str` | 是 | 简历 ID |
| `resume_structured` | `ResumeStructured` | 是 | LLM 提取的结构化简历数据 |
| `raw_text` | `str` | 是 | 简历原始文本（Full Chunk 降级用） |

**输出**: `list[ChunkSchema]`

包含所有粒度的 Chunk 列表。

**处理流程**:
```
1. 提取候选人级 metadata（从 resume_structured.personal_info）:
   - candidate_name, years_of_experience, city, gender
   - current_title, current_company
   - skills_normalized (skill_list[].name 小写), skills_original
   - highest_education_level (从 education_list 推导), highest_education
   - is_985, is_211, industry

2. 构建 Full Resume Chunk (1 个):
   - content = LLM 生成的简历摘要（如有 summary 则用 summary，否则用 raw_text）
   - chunk_level = FULL
   - metadata = 候选人级 metadata

3. 构建 Parent + Small Chunks:

   3a. 教育经历 (education_list):
   - Parent: content = 所有教育条目拼接
   - Small: 每条 EducationEntry → "学校 | 专业 | 学历 | 日期"
     metadata = 候选人级 + {section_type=education, organization=学校, start_date, end_date}

   3b. 工作经历 (experience_list):
   - Parent: content = 所有工作条目拼接
   - Small: 每条 ExperienceEntry → "公司 | 职位 | 日期\n描述\n成就"
     metadata = 候选人级 + {section_type=experience, organization=公司, title=职位, start_date, end_date}

   3c. 项目经历 (project_list):
   - Parent: content = 所有项目条目拼接
   - Small: 每条 ProjectEntry → "项目名 | 角色 | 日期\n描述\ntech_stack"
     metadata = 候选人级 + {section_type=project, organization=项目名, title=角色, tech_stack, start_date, end_date}

   3d. 技能清单 (skill_list):
   - Parent: content = 所有技能拼接
   - Small: 按类别分组，每组一条 → "Java(精通,8年), Python(熟练,5年)..."
     metadata = 候选人级 + {section_type=skill}

4. 每个 Small Chunk 设置 parent_chunk_id 指向对应 Parent Chunk

5. 返回所有 Chunk 列表（Full + Parent + Small）
```

**降级处理**:
- `resume_structured` 为 None 或 confidence_score < 0.3:
  - 降级为旧策略（从 raw_text 按 SectionType 关键词切分 + 字符数 50-200 合并）
  - metadata 仅包含 section_type，不包含候选人级字段
  - 记录警告日志

**边界处理**:
- education_list 为空 → 不生成 education 的 Parent/Small Chunk
- experience_list 为空 → 不生成 experience 的 Parent/Small Chunk
- 单条经历描述过长（> 500 字符） → 按。；;切分为多个 Small Chunk


## 4. 自定义异常

```python
class ResumeParseError(Exception):
    """简历解析异常"""
    def __init__(self, message: str, status: ParseStatus = ParseStatus.FAILED, detail: Optional[str] = None):
        self.message = message
        self.status = status
        self.detail = detail
        super().__init__(message)
```

---

## 5. 调用示例

### 5.1 API 层调用 parse_resume

```python
from fastapi import APIRouter, UploadFile, HTTPException
from src.resume_parser import parse_resume, ResumeParseError

router = APIRouter()

@router.post("/api/v1/resumes/upload")
async def upload_resume(file: UploadFile):
    """简历上传入口（由 api-layer 模块实现）"""
    try:
        result = await parse_resume(file)
        
        if result.status == ParseStatus.FAILED:
            raise HTTPException(status_code=422, detail=f"简历解析失败: {result.error_message}")
        
        # 传递给 resume-store 存储
        # resume_id = await resume_store.save(result.resume_data)
        # 传递给 vector-index 生成 Embedding
        # await vector_index.index(resume_id, result.resume_data)
        
        return {
            "status": result.status,
            "resume_data": result.resume_data.model_dump() if result.resume_data else None,
            "message": "解析成功" if result.status == ParseStatus.SUCCESS else "部分解析成功"
        }
    except ResumeParseError as e:
        raise HTTPException(status_code=422, detail=str(e))
```

### 5.2 内部调用 parse_resume_text

```python
from src.resume_parser import parse_resume_text

# 已有纯文本的场景
text = "张三\n电话：13800138000\n邮箱：zhangsan@example.com\n..."
resume = await parse_resume_text(text)
```

### 5.3 内部调用 standardize_skills

```python
from src.resume_parser import standardize_skills

raw_skills = ["java", "SpringBoot", "JS", "python"]
standardized = standardize_skills(raw_skills)
```

---

## 6. 与其他模块的接口约定

### 6.1 resume-parser → resume-store

**数据**: `ResumeSchema` 对象

**resume-store 职责**:
- 为简历生成 `resume_id`（UUID）
- 将 `ResumeSchema` 写入 MongoDB
- 对 PII 字段加密（phone/email）
- 返回 `resume_id`

### 6.2 resume-parser → vector-index

**数据**: `resume_id` + `list[ChunkSchema]`

**vector-index 职责**:
- 接收 `resume_id` 和 ChunkSchema 列表（已从 ResumeStructured 构建）
- 调用 FlagEmbedding BGEM3FlagModel 本地推理生成 Dense + Sparse Embedding
- 提取 metadata 中的标量字段（years_of_experience, highest_education_level, city, gender）
- 写入 Milvus

### 6.3 api-layer → resume-parser

**数据**: `UploadFile`（来自 HTTP 请求）

**api-layer 职责**:
- 文件大小校验（<= 20MB）
- 文件类型白名单校验
- 调用 `parse_resume(file)`
- 调用 resume-store 和 vector-index 完成入库

---

## 7. 模块配置

```python
class ResumeParserConfig(BaseModel):
    """Resume Parser 配置"""
    # LLM 配置
    llm_base_url: str = Field("https://api.deepseek.com/v1", description="LLM API Base URL")
    llm_api_key: str = Field(..., description="LLM API Key（从环境变量读取）")
    llm_model: str = Field("deepseek-chat", description="LLM 模型名称")
    llm_max_tokens: int = Field(4096, description="LLM 最大输出 token")
    llm_temperature: float = Field(0.1, description="LLM 温度（低温度保证输出稳定）")
    
    # OCR 配置
    ocr_api_url: str = Field(..., description="DeepSeek-OCR API URL")
    ocr_api_key: str = Field(..., description="DeepSeek-OCR API Key")
    
    # 解析配置
    max_file_size_mb: int = Field(20, description="最大文件大小（MB）")
    max_text_length: int = Field(100000, description="最大文本长度（字符）")
    llm_retry_count: int = Field(1, description="LLM 提取失败重试次数")
    
    # Skill 标准化配置
    synonym_dict_path: str = Field("config/skill_synonyms.json", description="同义词词典路径")
    
    # PII 配置
    pii_encrypt_key: str = Field(..., description="PII 加密密钥（从环境变量读取）")
```

**环境变量**:
| 变量名 | 说明 | 必填 |
|--------|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek LLM API Key | 是 |
| `DEEPSEEK_OCR_API_KEY` | DeepSeek-OCR API Key | 是 |
| `PII_ENCRYPT_KEY` | PII 加密密钥（AES-256，32 字节） | 是 |
| `LLM_BASE_URL` | LLM API Base URL | 否（默认 DeepSeek） |
| `LLM_MODEL` | LLM 模型名称 | 否（默认 deepseek-chat） |
