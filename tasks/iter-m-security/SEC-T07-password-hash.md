# SEC-T07: 密码哈希 + 用户表迁移

## 基本信息
- **对应 Spec**: SEC-REQ-005
- **对应 AC**: AC-SEC-005
- **依赖**: SEC-T06
- **预计工时**: 0.5 天
- **优先级**: P1

## 输入
- `src/api/v1/auth.py`（USERS_DB 硬编码、明文比对）

## 输出
- `src/resume_store/models.py` 或新建 `src/common/user_store.py` — User 模型 + MongoDB users collection
- 修改 `src/api/v1/auth.py` — 改用数据库查询 + bcrypt 校验
- `scripts/init_users.py` — 初始化用户脚本（哈希写入）
- `tests/unit/test_auth.py` — 补充哈希校验测试

## 实现要求
1. User 模型：
   ```python
   class UserSchema(BaseModel):
       user_id: str
       username: str  # unique
       password_hash: str  # bcrypt
       role: Literal["admin", "hr", "viewer"]
       created_at: datetime
   ```
2. `auth.py` login：
   ```python
   from passlib.context import CryptContext
   pwd_context = CryptContext(schemes=["bcrypt"])
   user = user_store.find_by_username(request.username)
   if not user or not pwd_context.verify(request.password, user["password_hash"]):
       raise AuthenticationError(ErrorCode.AUTH_005)
   ```
   删除 USERS_DB 字典
3. `init_users.py`：创建 admin/hr/viewer 三个用户，密码用强随机值或交互输入，哈希后写入 MongoDB
4. pyproject.toml 添加依赖 `passlib[bcrypt]>=1.7`

## 验收检查点
- [ ] MongoDB users collection 存在且 password_hash 以 `$2b$` 开头
- [ ] 代码中无 USERS_DB、无明文密码
- [ ] `admin/admin123` 登录失败（除非 init 时显式设置该弱口令）
- [ ] 合法凭据登录返回 JWT
- [ ] `tests/unit/test_auth.py` 哈希校验测试通过

### 通过判定
全部 ✅ → Done | 任一 ❌ 且 retry<3 → 修复 | retry=3 → BLOCKED
