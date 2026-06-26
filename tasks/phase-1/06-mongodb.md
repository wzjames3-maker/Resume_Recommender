# T-007: MongoDB 连接 + ResumeStore 基础 CRUD

## 基本信息
- 对应 Spec: tech-decision.md 决策项（MongoDB）、specs/resume-parser/02-data-model.md
- 对应 AC: PRD 中简历管理相关用例
- 依赖: T-001, T-002
- 预计工时: 1 天

## 输入
- docs/tech-decision.md
- docker-compose.yml（来自 T-001，确认 MongoDB 服务配置）
- src/common/config.py（来自 T-003，MongoDB 连接配置）
- specs/resume-parser/02-data-model.md（简历数据模型定义）

## 输出
- src/resume_store/connection.py
- src/resume_store/models.py
- src/resume_store/store.py
- src/resume_store/encryption.py
- tests/unit/test_resume_store.py

## 实现要求
1. 创建 `src/resume_store/connection.py`：
   - MongoDB 连接管理（使用 `motor` 异步驱动或 `pymongo` 同步驱动，对齐 tech-decision.md）
   - 连接池配置
   - 连接健康检查方法
   - 支持环境切换（dev 使用 docker-compose 中的 MongoDB）
2. 创建 `src/resume_store/models.py`：
   - `ResumeSchema` Pydantic Model，对齐 specs/resume-parser/02-data-model.md：
     - `id: str` (UUID)
     - `user_id: str` — 所属用户
     - `name: str` — 姓名
     - `phone: str` — 电话（PII，需加密存储）
     - `email: str` — 邮箱（PII，需加密存储）
     - `education: list[EducationEntry]`
     - `experience: list[ExperienceEntry]`
     - `skills: list[str]`
     - `raw_text: Optional[str]` — 原始解析文本
     - `vector_id: Optional[str]` — Milvus 中的向量 ID
     - `status: ResumeStatus` — active / archived / deleted
     - `created_at: datetime`
     - `updated_at: datetime`
   - 嵌套模型：`EducationEntry`, `ExperienceEntry`
3. 创建 `src/resume_store/store.py` — `ResumeStore` 类：
   - `create(resume: ResumeSchema) -> str` — 创建简历，返回 ID
   - `get(resume_id: str, user_id: str) -> Optional[ResumeSchema]` — 获取单条
   - `list(user_id: str, status: str = "active", page: int = 1, size: int = 20) -> tuple[list, int]` — 分页列表
   - `update(resume_id: str, user_id: str, data: dict) -> bool` — 更新简历
   - `soft_delete(resume_id: str, user_id: str) -> bool` — 软删除（status → deleted）
4. 创建 `src/resume_store/encryption.py`：
   - PII 字段加密/解密（phone, email）
   - 使用对称加密（AES-GCM 或 Fernet，对齐 tech-decision.md）
   - 加密密钥从配置读取
   - 查询时支持密文检索或明文索引方案
5. 所有操作需添加 Audit Log（调用 T-005 的 logger）
6. 编写单元测试：
   - CRUD 全流程测试（使用 mongomock 或测试数据库）
   - PII 加密/解密往返测试
   - 软删除后不可查询测试
   - 分页测试

## 验收检查点

### 前置确认
- [ ] T-001 已完成（docker-compose.yml 存在，MongoDB 服务定义正确）
- [ ] T-002 已完成（项目骨架存在）
- [ ] docs/tech-decision.md 已读取
- [ ] specs/resume-parser/02-data-model.md 已读取

### AC 验收
- [ ] 连接 docker-compose 中的 MongoDB 成功
- [ ] create → get → update → soft_delete 全流程通过
- [ ] PII 字段（phone, email）存储为密文
- [ ] 分页查询返回正确数量和总数
- [ ] 软删除后 get 返回 None

### 代码质量
- [ ] 异常使用统一错误码体系（T-004）
- [ ] 所有操作有 Audit Log
- [ ] 单元测试全部通过

### Spec 一致性
- [ ] ResumeSchema 字段与 specs/resume-parser/02-data-model.md 完全一致
- [ ] MongoDB 连接配置与 docker-compose 服务名对齐
- [ ] 加密方案与 tech-decision.md 一致

### 通过判定
全部 ✅ → Done | 任一 ❌ 且 retry < 3 → 修复 | retry = 3 → BLOCKED
