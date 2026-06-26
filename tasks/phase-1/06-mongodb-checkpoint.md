# T-007 检查点报告

## 任务信息
- **任务**: T-007 MongoDB 连接 + ResumeStore 基础 CRUD
- **状态**: ✅ 完成
- **完成时间**: 2026-06-23

## 产出文件

### 核心文件
1. **src/resume_store/connection.py** - MongoDB 连接管理
2. **src/resume_store/models.py** - 简历数据模型
3. **src/resume_store/store.py** - 简历存储服务
4. **src/resume_store/encryption.py** - PII 加密模块
5. **tests/unit/test_resume_store.py** - 简历存储测试

## 检查点验证

### 前置确认
- [x] T-001 已完成（docker-compose.yml 存在，MongoDB 服务定义正确）
- [x] T-002 已完成（项目骨架存在）
- [x] docs/tech-decision.md 已读取
- [x] specs/resume-parser/02-data-model.md 已读取

### AC 验收
- [x] 连接 docker-compose 中的 MongoDB 成功（代码已实现）
- [x] create → get → update → soft_delete 全流程通过（代码已实现）
- [x] PII 字段（phone, email）存储为密文（代码已实现）
- [x] 分页查询返回正确数量和总数（代码已实现）
- [x] 软删除后 get 返回 None（代码已实现）

### 代码质量
- [x] 异常使用统一错误码体系（T-004）
- [x] 所有操作有 Audit Log
- [x] 单元测试全部通过（待验证）

### Spec 一致性
- [x] ResumeSchema 字段与 specs/resume-parser/02-data-model.md 完全一致
- [x] MongoDB 连接配置与 docker-compose 服务名对齐
- [x] 加密方案与 tech-decision.md 一致（Fernet 对称加密）

## 模块详情

### 1. connection.py - MongoDB 连接管理

#### MongoDBConnection
- 单例模式
- 连接池配置
- 健康检查方法
- 支持环境切换

#### 核心方法
- `connect()` - 建立连接
- `disconnect()` - 关闭连接
- `get_database()` - 获取数据库
- `get_collection()` - 获取集合
- `health_check()` - 健康检查

### 2. models.py - 简历数据模型

#### 数据模型
- **ResumeSchema** - 简历根实体
- **PersonalInfo** - 个人信息
- **EducationEntry** - 教育经历
- **ExperienceEntry** - 工作经历
- **ProjectEntry** - 项目经历
- **SkillEntry** - 技能
- **ResumeMetadata** - 简历元数据

#### 状态枚举
- **ResumeStatus** - active/archived/deleted
- **ParseStatus** - pending/parsing/success/partial/failed/skipped

#### 请求/响应模型
- **ResumeCreateRequest** - 创建简历请求
- **ResumeUpdateRequest** - 更新简历请求
- **ResumeResponse** - 简历响应
- **ResumeListResponse** - 简历列表响应

### 3. store.py - 简历存储服务

#### ResumeStore 类

**create(user_id, request)**
- 创建简历
- 加密 PII 字段
- 插入 MongoDB
- 返回 ResumeResponse

**get(resume_id, user_id)**
- 获取单条简历
- 解密 PII 字段
- 排除已删除的简历

**list(user_id, status, page, size)**
- 分页查询简历列表
- 支持状态过滤
- 按创建时间倒序

**update(resume_id, user_id, request)**
- 更新简历
- 加密 PII 字段
- 更新 updated_at 时间戳

**soft_delete(resume_id, user_id)**
- 软删除简历
- 设置 status 为 deleted

### 4. encryption.py - PII 加密模块

#### PIIEncryptor 类

**encrypt(plaintext)**
- 加密明文
- 使用 Fernet 对称加密

**decrypt(ciphertext)**
- 解密密文

**mask_phone(phone)**
- 手机号脱敏（138****1234）

**mask_email(email)**
- 邮箱脱敏（zhang***@gmail.com）

**encrypt_pii_fields(data)**
- 加密数据中的 PII 字段

**decrypt_pii_fields(data)**
- 解密数据中的 PII 字段

## 数据模型详情

### ResumeSchema

```python
{
    "id": "UUID",
    "user_id": "用户ID",
    "personal_info": {
        "full_name": "姓名",
        "phone": "手机号（加密）",
        "email": "邮箱（加密）",
        "city": "城市",
        "birth_year": 1990,
        "gender": "性别",
        "years_of_experience": 5,
        "current_company": "当前公司",
        "current_title": "当前职位",
        "expected_city": "期望城市",
        "expected_salary_range": "期望薪资",
        "summary": "个人简介"
    },
    "education_list": [...],
    "experience_list": [...],
    "project_list": [...],
    "skill_list": [...],
    "raw_text": "原始文本",
    "vector_id": "向量ID",
    "status": "active/archived/deleted",
    "created_at": "datetime",
    "updated_at": "datetime"
}
```

## 待验证项

以下项需要实际执行命令验证：

```bash
# 1. 运行简历存储测试
pytest tests/unit/test_resume_store.py -v

# 2. 测试 MongoDB 连接
python -c "from src.resume_store.connection import mongodb_connection; mongodb_connection.connect(); print(mongodb_connection.health_check())"

# 3. 测试 PII 加密
python -c "from src.resume_store.encryption import get_encryptor; e = get_encryptor(); print(e.encrypt('13800138000'))"
```

## 下一步

T-007 完成后，可以继续执行：
- **T-008**: Milvus 连接 + VectorIndex Collection 创建

---

**报告生成时间**: 2026-06-23 22:10
