# SEC-T03: RBAC 权限强制挂载

## 基本信息
- **对应 Spec**: SEC-REQ-001, SEC-RULE-001
- **对应 AC**: AC-SEC-001
- **依赖**: SEC-T02
- **预计工时**: 0.5 天
- **优先级**: P0

## 输入
- `src/common/middleware/rbac.py`（`require_permission(*required_permissions)` 已实现，ROLE_PERMISSIONS 已定义，0 端点使用）
- `src/api/v1/upload.py`、`chat.py`、`conversations.py`（仅 `Depends(get_current_user)`）

## 输出
- 修改 `src/api/v1/upload.py` — 追加 `Depends(require_permission("resume:create"))`
- 修改 `src/api/v1/chat.py` — 追加 `Depends(require_permission("conversation:create"))`
- 修改 `src/api/v1/conversations.py` — list/get 追加 `conversation:read`；delete 追加 `conversation:delete`
- `tests/security/test_rbac_enforcement.py` — 新增

## 实现要求
1. `require_permission` 签名是可变参数 `(*required_permissions: str)`，返回 `permission_checker`（已含 `Depends(get_current_user)`）。端点签名追加一个参数即可：
   ```python
   async def upload_resume(
       file: UploadFile = File(...),
       current_user: dict = Depends(get_current_user),
       _=Depends(require_permission("resume:create")),
   ):
   ```
   或直接用 `current_user: dict = Depends(require_permission("resume:create"))` 替换 get_current_user（require_permission 内部已调用 get_current_user）
2. 权限映射（对齐 rbac.py ROLE_PERMISSIONS，不改矩阵）：
   | 端点 | permission | admin | hr | viewer |
   |------|-----------|-------|----|--------|
   | POST /resumes/upload | resume:create | ✅ | ✅ | ❌ |
   | POST /chat | conversation:create | ✅ | ✅ | ❌ |
   | GET /conversations | conversation:read | ✅ | ✅ | ✅ |
   | GET /conversations/{id} | conversation:read | ✅ | ✅ | ✅ |
   | DELETE /conversations/{id} | conversation:delete | ✅ | ✅ | ❌ |
3. 权限不足由 rbac.py 抛 `AuthorizationError(AUTH_002, 403)`，走全局处理器

## 验收检查点
- [ ] viewer token 调用 upload 返回 403 + AUTH_002
- [ ] hr token 调用 upload 返回 200
- [ ] viewer token 调用 /chat 返回 403（无 conversation:create）
- [ ] viewer token 调用 GET /conversations 返回 200
- [ ] viewer token 调用 DELETE /conversations/{id} 返回 403
- [ ] admin token 调用 DELETE /conversations/{id} 返回 200（需配合 T04 归属校验）
- [ ] `tests/security/test_rbac_enforcement.py` 覆盖以上场景通过
- [ ] 现有 `tests/unit/test_rbac.py` 仍通过

### 通过判定
全部 ✅ → Done | 任一 ❌ 且 retry<3 → 修复 | retry=3 → BLOCKED
