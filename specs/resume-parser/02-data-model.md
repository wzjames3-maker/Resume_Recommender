<!-- Module: resume-parser -->
<!-- Spec Layer: 02 - Data Model -->
<!-- Phase: Phase 4 - Spec Writing -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-23 -->

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

```python
class ChunkLevel(str, Enum):
    """Chunk 粒度级别"""
    SMALL = "small"        # Small Chunk: 单句或小段落 (50~200 字符)
    PARENT = "parent"      # Parent Chunk: 完整 Section (教育/工作/项目等)
    FULL = "full"          # Full Resume: 整份简历

class ChunkSchema(BaseModel):
    """多粒度 Chunk"""
    chunk_id: str = Field(..., description="Chunk 唯一 ID (resume_id + level + index)")
    resume_id: str = Field(..., description="所属简历 ID")
    chunk_level: ChunkLevel = Field(..., description="Chunk 粒度级别")
    section_type: Optional[SectionType] = Field(None, description="所属 Section 类型 (small/parent 级别必填)")
    parent_chunk_id: Optional[str] = Field(None, description="父 Chunk ID (small 级别必填)")
    content: str = Field(..., description="Chunk 文本内容")
    char_count: int = Field(..., description="字符数")
    sequence_index: int = Field(..., description="在简历中的顺序索引 (0-based)")
    metadata: dict = Field(default_factory=dict, description="附加 Metadata (如 page_num, section_title)")
```

**Chunk 层级关系**:
```
Full Resume (chunk_level=full)
├── Parent Chunk: 教育经历 (chunk_level=parent, section_type=education)
│   ├── Small Chunk: "2018-2022 浙江大学 计算机科学与技术 本科" (chunk_level=small)
│   └── Small Chunk: "GPA 3.8/4.0 校级优秀毕业生" (chunk_level=small)
├── Parent Chunk: 工作经历 (chunk_level=parent, section_type=experience)
│   ├── Small Chunk: "2022.07-至今 阿里巴巴 高级Java工程师" (chunk_level=small)
│   ├── Small Chunk: "负责订单系统核心模块开发，日均处理订单量 500 万+" (chunk_level=small)
│   └── Small Chunk: "主导微服务架构改造，系统可用性从 99.5% 提升至 99.99%" (chunk_level=small)
├── Parent Chunk: 项目经历 (chunk_level=parent, section_type=project)
│   ├── Small Chunk: "电商平台重构项目 技术负责人" (chunk_level=small)
│   └── Small Chunk: "使用 Spring Cloud + Kafka + Redis 实现分布式架构" (chunk_level=small)
└── Parent Chunk: 技能清单 (chunk_level=parent, section_type=skill)
    └── Small Chunk: "Java, Spring Boot, MySQL, Redis, Kafka, Docker, K8s" (chunk_level=small)
```

**chunk_id 生成规则**:
```python
def generate_chunk_id(resume_id: str, level: ChunkLevel, index: int) -> str:
    """生成 Chunk ID"""
    return f"{resume_id}:{level.value}:{index:04d}"
# 示例: "r_abc123:parent:0000", "r_abc123:small:0003"
```
