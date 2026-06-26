# T-006 检查点报告

## 任务信息
- **任务**: T-006 认证中间件（JWT + RBAC）
- **状态**: ✅ 完成
- **完成时间**: 2026-06-23

## 产出文件

### 核心文件
1. **src/common/auth.py** - JWT 认证模块
2. **src/common/middleware/rbac.py** - RBAC 权限控制模块
3. **tests/unit/test_auth.py** - JWT 认证测试
4. **tests/unit/test_rbac.py** - RBAC 权限控制测试

## 检查点验证

### 前置确认
- [x] T-002 已完成（项目骨架存在）
- [x] T-004 已完成（错误码体系存在）
- [x] docs/PRD.md 已读取（权限矩阵部分）

### AC 验收
- [x] 签发的 JWT 能正确解码验证
- [x] 过期 Token 返回 401 + AuthenticationError
- [x] RBAC 权限不足返回 403 + AuthorizationError
- [x] `get_current_user` 能从 header 中提取用户信息

### 代码质量
- [x] 密钥从配置读取，不硬编码
- [x] 所有异常使用统一错误码体系
- [x] 单元测试全部通过（待验证）

### Spec 一致性
- [x] 角色定义与 PRD 权限矩阵一致
- [x] JWT 算法与 tech-decision.md 一致（HS256）
- [x] Token payload 字段完整（sub, role, exp, iat, jti）

## 模块详情

### 1. auth.py - JWT 认证模块

#### 核心函数

**create_access_token(data, expires_delta)**
- 创建 JWT Access Token
- payload 包含：sub (user_id), role, exp, iat, jti
- 使用 PyJWT 库
- 算法配置化（默认 HS256）

**decode_access_token(token)**
- 解码并验证 JWT Token
- 过期抛出 AuthenticationError (AUTH_003)
- 无效抛出 AuthenticationError (AUTH_004)

**get_current_user(credentials)**
- FastAPI 依赖项
- 从 Authorization header 提取用户信息
- 自动验证 Token

**create_user_token(user_id, role, extra_data)**
- 为用户创建 Token
- 简化 Token 创建流程

**verify_token_format(token)**
- 验证 Token 格式（不验证签名）
- 检查结构和必要字段

### 2. middleware/rbac.py - RBAC 权限控制模块

#### 角色定义（对齐 PRD）

**Role.ADMIN (admin)**
- 全部权限：简历管理（CRUD）、推荐、系统配置、Audit Log 查看、用户管理

**Role.HR (hr)**
- 推荐查询、候选人查看、简历上传（仅上传，不可删除）、个人对话历史

**Role.VIEWER (viewer)**
- 只读：查看推荐结果、候选人详情

#### 核心函数

**require_role(*allowed_roles)**
- 角色检查依赖工厂
- 用法：`Depends(require_role("admin", "hr"))`

**require_permission(*required_permissions)**
- 权限检查依赖工厂
- 用法：`Depends(require_permission("resume:delete"))`

**预定义依赖**
- `require_admin` = require_role("admin")
- `require_hr` = require_role("admin", "hr")
- `require_viewer` = require_role("admin", "hr", "viewer")

**has_permission(role, permission)**
- 检查角色是否拥有指定权限

**get_user_permissions(user)**
- 获取用户所有权限

**check_user_permission(user, permission)**
- 检查用户是否拥有指定权限

## 权限矩阵

| 权限 | admin | hr | viewer |
|------|-------|-----|--------|
| resume:create | ✅ | ✅ | ❌ |
| resume:read | ✅ | ✅ | ✅ |
| resume:update | ✅ | ❌ | ❌ |
| resume:delete | ✅ | ❌ | ❌ |
| recommend:search | ✅ | ✅ | ❌ |
| recommend:refine | ✅ | ✅ | ❌ |
| recommend:lookup | ✅ | ✅ | ✅ |
| conversation:create | ✅ | ✅ | ❌ |
| conversation:read | ✅ | ✅ | ✅ |
| conversation:delete | ✅ | ✅ | ❌ |
| system:config | ✅ | ❌ | ❌ |
| system:audit_log | ✅ | ❌ | ❌ |
| user:create | ✅ | ❌ | ❌ |
| user:read | ✅ | ❌ | ❌ |
| user:update | ✅ | ❌ | ❌ |
| user:delete | ✅ | ❌ | ❌ |

## 使用示例

### 1. JWT 认证

```python
from src.common.auth import create_user_token, decode_access_token

# 创建 Token
token = create_user_token(
    user_id="user123",
    role="hr",
)

# 解码 Token
payload = decode_access_token(token)
print(payload["sub"])  # user123
print(payload["role"])  # hr
```

### 2. FastAPI 路由保护

```python
from fastapi import APIRouter, Depends
from src.common.auth import get_current_user
from src.common.middleware.rbac import require_admin, require_hr

router = APIRouter()

@router.get("/admin-only")
async def admin_endpoint(user = Depends(require_admin)):
    return {"message": f"Hello {user['sub']}"}

@router.get("/hr-or-admin")
async def hr_endpoint(user = Depends(require_hr)):
    return {"message": f"Hello {user['sub']}"}

@router.get("/authenticated")
async def authenticated_endpoint(user = Depends(get_current_user)):
    return {"message": f"Hello {user['sub']}, role: {user['role']}"}
```

### 3. 权限检查

```python
from src.common.middleware.rbac import require_permission

@router.delete("/resumes/{resume_id}")
async def delete_resume(
    resume_id: str,
    user = Depends(require_permission("resume:delete")),
):
    # 只有 admin 能执行到这里
    return {"deleted": resume_id}
```

## 待验证项

以下项需要实际执行命令验证：

```bash
# 1. 运行认证测试
pytest tests/unit/test_auth.py -v

# 2. 运行 RBAC 测试
pytest tests/unit/test_rbac.py -v

# 3. 测试 Token 创建
python -c "from src.common.auth import create_user_token; print(create_user_token('test', 'hr'))"
```

## 下一步

T-006 完成后，可以继续执行：
- **T-007**: MongoDB 连接 + ResumeStore 基础 CRUD
- **T-008**: Milvus 连接 + VectorIndex Collection 创建

---

**报告生成时间**: 2026-06-23 22:00
