# 简历多库与总库设计

> 状态：已交付
> 更新日期：2026-08-18
> 适用范围：HR 简历上传、候选人列表、简历语义检索和库管理

## 1. 产品决策

HR 简历库采用“一个总库 + 多个业务库”的模型：

- 每个 workspace 有且只有一个系统总库，名称为“总库”。
- 总库代表 workspace 内的全部简历，上传时自动加入，前端默认选中且不可取消。
- HR 管理员可以创建多个业务库，例如“技术岗位库”“校招库”或“上海候选人库”。
- 一份物理简历文件只保存一次，但可以同时归属总库和多个业务库。
- 业务库用于组织、筛选和检索，不复制原文件、不重复解析、不重复创建语义索引。
- 业务库归档只禁止后续上传和检索，不删除已有简历，也不删除成员关系。

总库是全集，业务库是集合。查询业务库时应进入对应库的详情页，或在 RAG 页面取消总库后手动选择业务库。

## 2. 数据模型

### 2.1 ResumeDatabase

表：hr_resume_database

| 字段 | 说明 |
|---|---|
| workspace_id | workspace 隔离边界 |
| name | 库名称；同一 workspace 内唯一 |
| description | 库说明 |
| status | ACTIVE 或 ARCHIVED |
| is_default | 兼容旧默认库语义 |
| is_system | 系统总库标识 |
| user_id | 创建人 |

系统总库的约束：

- is_system=true、is_default=true、名称为“总库”。
- 不能归档、删除或被业务库替代。
- 若旧 workspace 只有默认库，服务层会将其修复为系统总库。

### 2.2 ResumeDatabaseMembership

表：hr_resume_database_membership

| 字段 | 说明 |
|---|---|
| resume_file | ResumeFile |
| resume_database | ResumeDatabase |
| create_time | 加入库的时间 |

(resume_file, resume_database) 有唯一约束。

ResumeFile.resume_database 保留为主归属/兼容字段，供旧代码和已有接口读取；实际的多库归属以 ResumeDatabaseMembership 为准。文件、解析结果和 document_id 仍然以 workspace + SHA-256 全局去重，一份文件不因加入多个库而产生副本。

## 3. 归属规则

### 3.1 上传

上传接口接收 resume_database_ids，支持 multipart 中重复提交同名字段，也兼容旧的单值 resume_database_id：

- 未传库或传空值：服务端自动使用总库。
- 传入业务库：服务端验证 workspace、库状态和权限。
- 服务端始终将总库加入上传目标，客户端不能绕过总库。
- 同一 SHA-256 已存在时，不新建 ResumeFile，只补充缺少的成员关系。
- 归档库不能作为上传目标。

### 3.2 列表与统计

候选人列表、简历库统计和库内简历列表均通过成员关系过滤：

- 简历数：按成员关系去重统计。
- 候选人数：按成员关系关联的候选人去重统计。
- 待解析数：按成员关系统计 PENDING 简历。
- 同一候选人可以因为多份简历或多个库归属被关联查询，但列表结果必须去重。

### 3.3 归档

业务库归档后：

- 不出现在上传和 RAG 的有效库选择器中。
- 不能作为候选人列表的有效筛选范围。
- 已有成员关系保留，历史数据不被删除。
- 总库不允许归档。

## 4. 前端信息架构

简历数据库采用两层页面：

| 页面 | 路由 | 作用 |
|---|---|---|
| 多库总览 | /hr/candidates | 展示总库和业务库卡片、数量和待解析统计 |
| 库内详情 | /hr/resumes/databases/:databaseId | 展示当前库内候选人和简历 |
| 库管理 | /hr/resumes/databases | ADMIN 创建和归档业务库 |
| 批量上传 | /hr/resumes/upload | 选择多个目标库并上传 |
| 库内上传 | /hr/resumes/upload?database_id=<id> | 从库内进入时预选当前库和总库 |
| 全部候选人兼容入口 | /hr/candidates/list | 跨库候选人列表，保留仪表盘等旧入口 |

库内详情页的上下文行为：

- 页面标题显示当前库名称。
- 候选人筛选固定在当前库，不再显示跨库选择器。
- 批量上传会自动预选当前库，同时保留总库。
- “库内检索”会将当前库传入 RAG 页面，默认只检索当前库。
- 返回操作回到多库总览，而不是直接回到旧的候选人列表。

## 5. RAG 范围

RAG API 支持 resume_database_ids 多选范围：

- 前端从多库总览进入库内检索时，使用当前库范围。
- 独立打开 RAG 页面时，默认选择总库，即查询全部简历。
- 在独立 RAG 页面可以取消总库，再选择一个或多个业务库。
- 总库和业务库同时选择时，结果等价于总库全集。
- 缺少或为空的范围参数按全部有效简历处理，服务端仍验证显式传入的库必须属于当前 workspace 且为 ACTIVE。
- 范围最多 50 个库，重复 ID 会去重。

库范围必须贯穿完整检索链路：

1. 结构化候选人预筛；
2. dense 向量召回；
3. sparse/tsvector 召回；
4. RRF 合并；
5. rerank；
6. 简历级聚合和姓名精确匹配。

不能只在前端隐藏结果，也不能只过滤最终结果，否则会造成跨库召回和统计污染。

## 6. API

以下路径均位于 /admin/api 下，<workspace_id> 受 token 和 HR 权限校验：

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | /workspace/<workspace_id>/hr/resume-databases | HR Access | 返回总库和业务库统计 |
| POST | /workspace/<workspace_id>/hr/resume-databases | HR ADMIN | 创建业务库 |
| PUT | /workspace/<workspace_id>/hr/resume-databases/<database_id>/archive | HR ADMIN | 归档业务库；总库拒绝 |
| POST | /workspace/<workspace_id>/hr/candidates/resumes | HR Access | 多文件上传；接收 resume_database_ids |
| POST | /workspace/<workspace_id>/hr/resumes/search | HR Access | 接收 resume_database_ids 作为 RAG 范围 |

候选人分页接口仍使用 resume_database_id 兼容参数；服务层将其转换为成员关系过滤。

## 7. 迁移和验收

迁移：

- 0027_resumedatabase：建立旧的简历库和主归属字段。
- 0028_resumedatabasemembership：增加 is_system、创建成员关系表，并将存量简历加入总库和原主库。

迁移必须在生产环境执行并检查：

- 每个 workspace 存在有效总库。
- 每份存量简历至少有一条总库成员关系。
- 总库成员数与 workspace 的 ResumeFile 数量一致。
- 业务库统计使用成员关系去重。
- 归档库不能出现在上传和检索选择器中。

本次开发库验收结果：总库 261 份简历、261 位候选人、261 条总库成员关系。该数字仅是开发数据快照，不是生产固定值。

## 8. 关键实现位置

- 模型和成员关系：apps/hr/models/recruitment.py
- 数据迁移：apps/hr/migrations/0028_resumedatabasemembership.py、0030_remove_candidate_legacy_fields.py（Candidate 13列删除 + CandidateSkill DROP）
- 库、上传和统计服务：apps/hr/serializers/recruitment.py（0030 后 Candidate 仅 name/phone/email，库筛选仅以 Membership + name/phone/email 模糊为准）
- RAG 库范围：apps/hr/services/resume_search.py
- 库接口和上传接口：apps/hr/views/recruitment.py、apps/hr/urls.py
- 多库总览：ui/src/views/hr/resumes/index.vue
- 库内候选人：ui/src/views/hr/candidates/index.vue（0030 后仅三字段表/单框筛选/480px 弹窗，见 HR-FRONTEND-GUIDE:4.4）
- 库管理：ui/src/views/hr/resumes/databases.vue
- 上传页：ui/src/views/hr/resumes/upload.vue
- RAG 页面：ui/src/views/hr/search/index.vue

## 9. 已完成验证

- Django migration 状态确认 0028_resumedatabasemembership 已应用。
- 总库成员关系、候选人筛选和 RAG 库范围已使用真实开发数据验证。
- Python compileall 和 git diff --check 通过。
- 前端 vue-tsc、目标文件 ESLint 和 Vite production build 通过。
- 现有开发 GUI http://127.0.0.1:3000/admin 返回 HTTP 200。
