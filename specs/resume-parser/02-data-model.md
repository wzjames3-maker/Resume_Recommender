<!-- Module: resume-parser -->
<!-- Spec Layer: 02 - Data Model -->
<!-- 变更: Tier L - RAG 全量重构 -->
<!-- Date: 2026-07-03 -->

# 数据模型：Resume Parser

## 1. 概述

Resume Parser 的数据模型定义了简历解析过程中涉及的所有实体和 Schema。最终输出为 Resume 实体，与 Domain Model 中定义的 Resume(1:N Education, Experience, Project, Skill) 一致。

---

## 2. Domain Model 引用

本模块的数据模型直接引用 Domain Model 中的以下实体：

| 实体 | 关系 | 说明 |
|------|------|------|
| Resume | 根实体 | 简历主实体，包含个人信息和关联子实体 |
| Education | Resume 1:N | 教育经历 |
| Experience | Resume 1:N | 工作经历 |
| Project | Resume 1:N | 项目经历 |
| Skill | Resume 1:N | 技能列表 |

### 实体关系图

```
Resume (1)
├── personal_info: PersonalInfo
├── education_list: list[Education]     (1:N)
├── experience_list: list[Experience]   (1:N)
├── project_list: list[Project]         (1:N)
├── skill_list: list[Skill]             (1:N)
└── metadata: ResumeMetadata
```

---

## 3. Pydantic Schema 定义

### 3.1 ParseStatus（解析状态枚举）

```python
from enum import Enum

class ParseStatus(str, Enum):
    """简历解析状态"""
    PENDING = "pending"       # 待解析
    PARSING = "parsing"       # 解析中
    SUCCESS = "success"       # 解析成功
    PARTIAL = "partial"       # 部分解析成功（LLM 提取失败，保留原始文本）
    FAILED = "failed"         # 解析失败
    SKIPPED = "skipped"       # 文件已存在（MD5 去重），跳过解析
```

**状态流转**:
```
PENDING ──> PARSING ──> SUCCESS
                   ──> PARTIAL (LLM 提取失败，有原始文本)
                   ──> FAILED  (文本提取失败，无原始文本)
PARSING ──> SKIPPED (文件 MD5 已存在，跳过解析)
```

### 3.2 PersonalInfo（个人信息）

```python
from pydantic import BaseModel, Field
from typing import Optional

class PersonalInfo(BaseModel):
    """候选人个人信息"""
    full_name: Optional[str] = Field(None, description="姓名")
    phone: Optional[str] = Field(None, description="手机号（加密存储）")
    email: Optional[str] = Field(None, description="邮箱（加密存储）")
    city: Optional[str] = Field(None, description="所在城市")
    birth_year: Optional[int] = Field(None, ge=1950, le=2010, description="出生年份")
    gender: Optional[str] = Field(None, description="性别")
    years_of_experience: Optional[int] = Field(None, ge=0, le=50, description="工作年限")
    current_company: Optional[str] = Field(None, description="当前公司")
    current_title: Optional[str] = Field(None, description="当前职位")
    expected_city: Optional[str] = Field(None, description="期望工作城市")
    expected_salary_range: Optional[str] = Field(None, description="期望薪资范围")
    summary: Optional[str] = Field(None, description="个人简介/自我评价")
```

**PII 字段标注**:
- `phone`: 加密存储（AES-256），展示时脱敏（138****1234）
- `email`: 加密存储（AES-256），展示时脱敏（zhang***@gmail.com）

### 3.3 EducationSchema（教育经历）

```python
class EducationSchema(BaseModel):
    """教育经历"""
    school: str = Field(..., description="学校名称")
    degree: Optional[str] = Field(None, description="学历（本科/硕士/博士/大专）")
    major: Optional[str] = Field(None, description="专业")
    start_date: Optional[str] = Field(None, description="开始日期（YYYY-MM 或 YYYY）")
    end_date: Optional[str] = Field(None, description="结束日期（YYYY-MM 或 YYYY）")
    is_985: Optional[bool] = Field(None, description="是否 985 院校")
    is_211: Optional[bool] = Field(None, description="是否 211 院校")
    is_double_first_class: Optional[bool] = Field(None, description="是否双一流院校")
    gpa: Optional[float] = Field(None, description="GPA")
    description: Optional[str] = Field(None, description="其他描述")
```

### 3.4 ExperienceSchema（工作经历）

```python
class ExperienceSchema(BaseModel):
    """工作经历"""
    company: str = Field(..., description="公司名称")
    title: Optional[str] = Field(None, description="职位名称")
    start_date: Optional[str] = Field(None, description="开始日期（YYYY-MM 或 YYYY）")
    end_date: Optional[str] = Field(None, description="结束日期（YYYY-MM 或 YYYY 或 至今）")
    is_current: Optional[bool] = Field(False, description="是否在职")
    description: Optional[str] = Field(None, description="工作描述")
    achievements: list[str] = Field(default_factory=list, description="工作成果列表")
    industry: Optional[str] = Field(None, description="所属行业")
```

### 3.5 ProjectSchema（项目经历）

```python
class ProjectSchema(BaseModel):
    """项目经历"""
    name: str = Field(..., description="项目名称")
    role: Optional[str] = Field(None, description="担任角色")
    start_date: Optional[str] = Field(None, description="开始日期")
    end_date: Optional[str] = Field(None, description="结束日期")
    description: Optional[str] = Field(None, description="项目描述")
    tech_stack: list[str] = Field(default_factory=list, description="技术栈")
    achievements: list[str] = Field(default_factory=list, description="项目成果")
    url: Optional[str] = Field(None, description="项目链接")
```

### 3.6 SkillSchema（技能）

```python
class SkillSchema(BaseModel):
    """技能"""
    name: str = Field(..., description="技能名称（标准化后）")
    category: Optional[str] = Field(None, description="技能分类（programming/database/framework/tool/soft_skill）")
    proficiency: Optional[str] = Field(None, description="熟练度（了解/熟悉/熟练/精通）")
    years_of_experience: Optional[int] = Field(None, ge=0, le=30, description="使用年限")
    original_names: list[str] = Field(default_factory=list, description="原始名称列表（标准化前的同义词）")
```

**字段说明**:
- `name`: 标准化后的技能名称（首字母大写，如 "Java", "Python"）
- `original_names`: 标准化前的原始名称列表（如 ["java", "JAVA", "jdk"]），用于回溯

### 3.7 ResumeMetadata（简历元数据）

```python
class ResumeMetadata(BaseModel):
    """简历解析元数据"""
    source_file_name: str = Field(..., description="原始文件名")
    source_file_type: str = Field(..., description="文件类型（pdf/docx/jpg/png/json）")
    source_file_size: int = Field(..., description="文件大小（字节）")
    parse_status: ParseStatus = Field(ParseStatus.PENDING, description="解析状态")
    parse_tool: Optional[str] = Field(None, description="文本提取工具（pdfplumber/PyPDF2/python-docx/deepseek-ocr）")
    llm_model: Optional[str] = Field(None, description="LLM 模型名称")
    llm_tokens_used: Optional[int] = Field(None, description="LLM token 用量")
    parse_duration_ms: Optional[int] = Field(None, description="解析耗时（毫秒）")
    language: Optional[str] = Field(None, description="识别的语言（zh/en/mixed）")
    error_message: Optional[str] = Field(None, description="错误信息")
    created_at: Optional[str] = Field(None, description="解析时间（ISO 8601）")
    retry_count: int = Field(0, description="重试次数")
    file_md5: Optional[str] = Field(None, description="文件内容 MD5 哈希值（用于去重）")
```

### 3.7a ResumeStructured（LLM 提取的结构化数据）

> **注意**: `ResumeStructured` 是 LLM 从 raw_text 提取的结构化数据，**不含** chunks/metadata。
> `ResumeSchema` = `ResumeStructured` + chunks + metadata，是 complete pipeline 的最终输出。

```python
class ResumeStructured(BaseModel):
    """LLM 结构化提取的简历数据（生成 Chunk 的输入）"""
    personal_info: PersonalInfo = Field(default_factory=PersonalInfo)
    education_list: list[EducationSchema] = Field(default_factory=list)
    experience_list: list[ExperienceSchema] = Field(default_factory=list)
    project_list: list[ProjectSchema] = Field(default_factory=list)
    skill_list: list[SkillSchema] = Field(default_factory=list)
    confidence_score: float = Field(0.0, ge=0, le=1, description="LLM 提取置信度")
```

### 3.8 ResumeSchema（简历根 Schema）

```python
class ResumeSchema(BaseModel):
    """简历完整结构化数据"""
    personal_info: PersonalInfo = Field(default_factory=PersonalInfo, description="个人信息")
    education_list: list[EducationSchema] = Field(default_factory=list, description="教育经历列表")
    experience_list: list[ExperienceSchema] = Field(default_factory=list, description="工作经历列表")
    project_list: list[ProjectSchema] = Field(default_factory=list, description="项目经历列表")
    skill_list: list[SkillSchema] = Field(default_factory=list, description="技能列表")
    chunks: list[ChunkSchema] = Field(default_factory=list, description="多粒度 Chunk 列表")
    metadata: ResumeMetadata = Field(..., description="解析元数据")
```

### 3.9 SectionSchema（语义段落）

```python
from enum import Enum

class SectionType(str, Enum):
    """段落类型"""
    PERSONAL_INFO = "personal_info"
    EDUCATION = "education"
    EXPERIENCE = "experience"
    PROJECT = "project"
    SKILL = "skill"
    OTHER = "other"

class SectionSchema(BaseModel):
    """语义段落切分结果"""
    section_type: SectionType = Field(..., description="段落类型")
    raw_content: str = Field(..., description="原始文本内容")
    start_pos: int = Field(..., description="起始字符位置")
    end_pos: int = Field(..., description="结束字符位置")
    confidence: Optional[float] = Field(None, ge=0, le=1, description="切分置信度")
```

---


### 3.10 ChunkSchema（多粒度 Chunk）

> **变更说明 (Tier L)**: Chunk 不再从 raw_text 按字符数切割，而是从 ResumeStructured 结构化数据构建。
> 每个 Small Chunk 对应一条结构化记录（如一条工作经历、一个项目），携带完整 metadata。

```python
class ChunkLevel(str, Enum):
    """Chunk 粒度级别"""
    SMALL = "small"        # Small Chunk: 单条结构化记录（工作经历/项目/教育/技能组）
    PARENT = "parent"      # Parent Chunk: 完整 Section（所有教育/所有工作/所有项目...）
    FULL = "full"          # Full Resume: LLM 生成摘要（非 raw_text 拼接）

class ChunkSchema(BaseModel):
    """多粒度 Chunk"""
    chunk_id: str = Field(..., description="Chunk 唯一 ID (resume_id + level + index)")
    resume_id: str = Field(..., description="所属简历 ID")
    chunk_level: ChunkLevel = Field(..., description="Chunk 粒度级别")
    section_type: Optional[SectionType] = Field(None, description="所属 Section 类型")
    parent_chunk_id: Optional[str] = Field(None, description="父 Chunk ID (small 级别必填)")
    content: str = Field(..., description="Chunk 文本内容")
    char_count: int = Field(..., description="字符数")
    sequence_index: int = Field(..., description="在简历中的顺序索引 (0-based)")
    metadata: dict = Field(default_factory=dict, description="完整 Metadata（见 §3.10.1）")
```

#### 3.10.1 Chunk Metadata Schema

**候选人级（所有 chunk 共享，从 ResumeStructured.personal_info 继承）**:

| 字段 | 类型 | 来源 | Milvus 标量列 |
|------|------|------|---------------|
| candidate_name | str | personal_info.full_name | — (仅 JSON) |
| years_of_experience | int | personal_info.years_of_experience | ✅ INT64 |
| city | str | personal_info.city | ✅ VARCHAR(64) |
| gender | str | personal_info.gender | ✅ VARCHAR(8) |
| current_title | str | personal_info.current_title | — |
| current_company | str | personal_info.current_company | — |
| highest_education_level | int | 从 education_list 推导最高学历 | ✅ INT8 |
| highest_education | str | 从 education_list 推导最高学历名称 | — |
| is_985 | bool | education_list 任一 is_985=true | — |
| is_211 | bool | education_list 任一 is_211=true | — |
| skills_normalized | list[str] | skill_list[].name 小写 | — |
| skills_original | list[str] | skill_list[].name 原始 | — |
| industry | str | experience_list 最近一条 industry | — |

**Chunk 级（每个 chunk 独有）**:

| 字段 | 类型 | 适用 level | 说明 |
|------|------|-----------|------|
| section_type | str | small/parent | "education"/"experience"/"project"/"skill" |
| organization | str | small/parent | 学校名/公司名 |
| title | str | small/parent | 职位/角色 |
| start_date | str | small/parent | YYYY-MM |
| end_date | str | small/parent | YYYY-MM 或 "至今" |
| tech_stack | list[str] | small/parent (project) | 技术栈 |
| sequence_index | int | all | 顺序索引 |

#### 3.10.2 Chunk 构建层级（2 页简历典型示例）

```
Full Resume (1 个, chunk_level=full)
  content = LLM 生成的简历摘要（非 raw_text）
  metadata = 全部候选人级字段
│
├── Parent: 教育经历 (chunk_level=parent, section_type=education)
│   content = 所有 education_list 条目拼接
│   metadata = 候选人级 + section_type=education
│   ├── Small: "浙江大学 | 计算机科学 | 硕士 | 2012-09 ~ 2015-06" (chunk_level=small)
│   │   metadata = 候选人级 + {organization=浙江大学, section_type=education, start_date=2012-09, ...}
│   └── Small: "清华大学 | 软件工程 | 本科 | 2008-09 ~ 2012-06"
│
├── Parent: 工作经历 (chunk_level=parent, section_type=experience)
│   ├── Small: "阿里巴巴 | 高级Java工程师 | 2019-07 ~ 2024-03\n负责电商交易系统..."
│   │   metadata = 候选人级 + {organization=阿里巴巴, title=高级Java工程师, ...}
│   ├── Small: "字节跳动 | 后端开发 | 2015-07 ~ 2019-06\n负责推荐系统后端..."
│   └── Small: "腾讯 | 实习生 | 2014-10 ~ 2015-04\n参与微信支付模块开发..."
│
├── Parent: 项目经历 (chunk_level=parent, section_type=project)
│   ├── Small: "电商交易平台重构 | 技术负责人 | Spring Cloud + Kafka + Redis..."
│   └── Small: "推荐系统实时计算 | 核心开发 | Flink + ClickHouse..."
│
└── Parent: 技能清单 (chunk_level=parent, section_type=skill)
    └── Small: "Java(精通,8年), Spring Cloud(熟练,5年), MySQL(熟练,8年), Kafka(熟悉,3年)..."
```

**预计 Chunk 数量** (2 页简历):
- 1 Full + 4 Parent + 8-12 Small = 13-17 个 Chunk
