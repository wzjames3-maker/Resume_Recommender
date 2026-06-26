<!-- Spec: resume-store -->
<!-- 调研决策: ✅ 直接复用 (MongoDB) -->
<!-- Spec 策略: 简化 — 引用 MongoDB + Pydantic Model -->

# 00-overview: Resume Store

## 来源
PRD §4 FR-010, FR-019; Domain Model Resume 实体

## 做什么
- 管理结构化简历数据的 CRUD 操作
- PII 字段加密存储（phone, email）
- 支持按 Metadata 字段查询和过滤

## 不做什么
- 不做简历解析（由 resume-parser 负责）
- 不做向量检索（由 vector-index 负责）
- 不做推荐排序（由 recommendation-engine 负责）

## 技术栈（引用 tech-decision.md）
- 数据库: MongoDB (Docker)
- Python SDK: pymongo>=4.9
- 加密: cryptography (AES-256)
- ODM: 直接使用 pymongo，不用 MongoEngine

---

# 01-requirements: Resume Store

| ID | 对应 PRD | 描述 | 优先级 |
|----|----------|------|--------|
| REQ-001 | FR-010 | 简历写入（单份） | P0 |
| REQ-002 | FR-010 | 批量简历写入 | P1 |
| REQ-003 | FR-010 | 简历查询（by resume_id） | P0 |
| REQ-004 | FR-010 | 简历列表查询（分页+过滤） | P0 |
| REQ-005 | FR-010 | 简历更新 | P1 |
| REQ-006 | FR-010 | 简历删除（软删除） | P1 |
| REQ-007 | FR-019 | PII 字段加密存储 | P1 |
| REQ-008 | FR-019 | PII 字段脱敏返回 | P1 |
| REQ-009 | - | 按 Metadata 聚合统计（供 analytics） | P2 |
| REQ-010 | - | 简历去重检测（by name+phone） | P1 |
| REQ-011 | - | 文件级去重（by file_md5）— 相同文件内容不重复入库 | P0 |

## REQ-011: 文件级去重（file_md5）
- 输入: file_md5 (str, 32位十六进制)
- 输出: ResumeSchema | None
- 前置: file_md5 非空且格式合法
- 后置: 如 MongoDB 中已存在相同 file_md5 且 status=active 的简历，返回该简历；否则返回 None
- 用途: 简历上传时先检查文件是否已入库，避免重复解析和向量化

---

## REQ-001: 简历写入
- 输入: ResumeSchema (Pydantic)
- 输出: resume_id (str)
- 前置: ResumeSchema 验证通过
- 后置: MongoDB 写入成功，返回 resume_id

---

# 02-data-model: Resume Store

直接引用 `docs/requirements/04-domain-model.md` 中的 Resume 实体定义。

## MongoDB Collection: resumes

```python
# Pydantic Schema（与 Domain Model 对齐）
class ResumeSchema(BaseModel):
    resume_id: str = Field(default_factory=lambda: str(uuid4()))
    candidate_name: str
    phone: str | None = None       # PII, 加密存储
    email: str | None = None       # PII, 加密存储
    gender: Literal["男", "女"] | None = None
    age: int | None = None
    city: str | None = None
    source_type: Literal["pdf", "docx", "image", "json", "upload"]
    file_md5: str | None = None       # 文件内容 MD5，用于去重
    raw_file_path: str | None = None
    parsed_content: str | None = None
    embedding_id: str | None = None  # 关联 Milvus
    status: Literal["active", "archived", "deleted"] = "active"
    education: list[EducationSchema] = []
    experience: list[ExperienceSchema] = []
    projects: list[ProjectSchema] = []
    skills: list[SkillSchema] = []
    parsed_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class EducationSchema(BaseModel):
    school: str
    degree: Literal["高中", "专科", "本科", "硕士", "博士"]
    major: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    tier: Literal["985", "211", "双一流", "普通"] | None = None

class ExperienceSchema(BaseModel):
    company: str
    title: str
    description: str | None = None
    start_date: str | None = None
    end_date: str | None = None  # None = 至今
    industry: str | None = None
    is_outsource: bool = False

class ProjectSchema(BaseModel):
    name: str
    role: str | None = None
    description: str | None = None
    skills: list[str] = []
    start_date: str | None = None
    end_date: str | None = None

class SkillSchema(BaseModel):
    name: str
    category: Literal["programming", "framework", "database", "devops", "soft_skill", "other"] = "other"
    proficiency: Literal["了解", "熟悉", "熟练", "精通"] | None = None
    years: int | None = None
    source: Literal["from_resume", "inferred"] = "from_resume"
```

## 索引
| 名称 | 字段 | 类型 | 说明 |
|------|------|------|------|
| _id | resume_id | UNIQUE | 主键 |
| idx_status | status | BTREE | 过滤有效简历 |
| idx_city | city | BTREE | 按城市过滤 |
| idx_created | created_at | BTREE | 按时间排序 |
| idx_name_phone | candidate_name + phone | COMPOSITE | 去重检测 |
| idx_file_md5 | file_md5 | UNIQUE (sparse) | 文件级去重（仅非空时唯一） |

---

# 03-api-contract: Resume Store

内部接口（供其他模块调用）：

```
create_resume(data: ResumeSchema) -> str                    # 返回 resume_id
get_resume(resume_id: str) -> ResumeSchema | None
list_resumes(filters: dict, page: int, size: int) -> dict   # {items, total, page, size}
update_resume(resume_id: str, data: dict) -> bool
soft_delete_resume(resume_id: str) -> bool
find_duplicate(name: str, phone: str) -> ResumeSchema | None
find_by_md5(file_md5: str) -> ResumeSchema | None   # 文件级去重查询
aggregate_stats(dimension: str, filters: dict) -> dict       # 供 analytics
```

---

# 04-business-rules: Resume Store

| ID | 规则 |
|----|------|
| RULE-001 | 删除使用软删除（status=deleted），不物理删除 |
| RULE-002 | phone/email 使用 AES-256 加密后存储 |
| RULE-003 | 查询返回时 phone 脱敏为 138****1234，email 脱敏为 zhang***@gmail.com |
| RULE-004 | 去重检测：同名+同手机号视为同一人，提示是否覆盖 |
| RULE-005 | updated_at 在每次更新时自动刷新 |
| RULE-006 | embedding_id 在向量入库后回写 |
| RULE-007 | file_md5 去重：上传前检查 file_md5 是否已存在，已存在则跳过解析直接返回已有 resume_id |

---

# 05-edge-cases: Resume Store

| ID | 场景 | 处理 |
|----|------|------|
| EC-001 | resume_id 不存在 | 返回 None，调用方处理 404 |
| EC-002 | 加密密钥丢失 | 数据不可恢复，需备份密钥 |
| EC-003 | 并发更新同一简历 | MongoDB find_one_and_update 原子操作 |
| EC-004 | 简历数据量极大(>100万) | 使用 MongoDB 分片（V2） |
| EC-005 | PII 字段为空 | 跳过加密/脱敏，直接返回 None |
| EC-006 | 相同文件重复上传（file_md5 已存在） | 返回已有简历的 resume_id，标记 status=skipped，不重复入库 |

---

# 06-acceptance: Resume Store

| ID | Given | When | Then |
|----|-------|------|------|
| AC-001 | 有效 ResumeSchema | create_resume | MongoDB 写入成功，返回 resume_id |
| AC-002 | resume_id 存在 | get_resume | 返回完整简历数据，phone/email 已脱敏 |
| AC-003 | resume_id 不存在 | get_resume | 返回 None |
| AC-004 | 简历已存在 | soft_delete_resume | status 变为 deleted，数据不物理删除 |
| AC-005 | phone="13812341234" | get_resume | 返回 phone="138****1234" |
| AC-006 | 同名+同手机号 | find_duplicate | 返回已有简历 |
| AC-007 | 无匹配 | find_duplicate | 返回 None |
| AC-008 | file_md5 已存在于 MongoDB（status=active） | find_by_md5 | 返回已有简历 |
| AC-009 | file_md5 不存在 | find_by_md5 | 返回 None |

---

# 07-tech-constraints: Resume Store

## 架构级（引用 tech-decision.md）
- 数据库: MongoDB (Docker)
- 部署: Docker Compose

## 实现级
| 类别 | 选择 | 版本 | 理由 |
|------|------|------|------|
| Python SDK | pymongo | >=4.9 | 官方 SDK |
| 加密 | cryptography | >=42.0 | AES-256 |
| Schema | pydantic | >=2.0 | 与全局一致 |

## 禁止
- 不用 MongoEngine（增加复杂度）
- 不用明文存储 PII

---

# 08-dependencies: Resume Store

## 前置依赖
- 无（基础模块）

## 后置依赖
- resume-parser: 解析完成后调用 create_resume 写入
- recommendation-engine: 通过 get_resume 查询候选人详情
- vector-index: 入库后回写 embedding_id
- api-layer: 封装为 HTTP API
- conversation-memory: 存储 last_candidates 引用

## 对外接口
- 其他模块通过 `from src.resume_store import ResumeStoreClient` 调用
