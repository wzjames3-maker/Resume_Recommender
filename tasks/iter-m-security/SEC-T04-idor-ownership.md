# SEC-T04: IDOR 资源归属校验

## 基本信息
- **对应 Spec**: SEC-REQ-002, SEC-RULE-002
- **对应 AC**: AC-SEC-002
- **依赖**: SEC-T03
- **预计工时**: 0.5 天
- **优先级**: P0

## 输入
- `src/api/v1/conversations.py`（get/delete 取 user_id 未校验归属；用裸 HTTPException）
- `src/conversation_memory/session_manager.py`（get_session/delete_session）
- `src/resume_store/repository.py`（get 的 user_id 可选；list 已强制 user_id）

## 输出
- 修改 `src/api/v1/conversations.py` — get/delete 校验 session.user_id；改用 ResourceNotFoundError
- 修改 `src/resume_store/repository.py` — get 的 user_id=None 仅限 admin（docstring 标注）
- `tests/security/test_idor.py` — 新增

## 实现要求
1. `conversations.py` get_conversation：
   ```python
   from src.common.errors import ResourceNotFoundError, ErrorCode
   session = session_manager.get_session(conversation_id)
   if not session:
       raise ResourceNotFoundError(error_code=ErrorCode.CONV_001, detail="对话不存在")
   if session.user_id != user_id and current_user.get("role") != "admin":
       raise ResourceNotFoundError(error_code=ErrorCode.CONV_001, detail="对话不存在")  # 404 防枚举
   ```
2. `conversations.py` delete_conversation 同样校验归属后再调用 delete_session
3. 删除现有的裸 `HTTPException(status_code=404, detail="对话不存在")`，统一用 `ResourceNotFoundError(CONV_001)`
4. `repository.get()` docstring 标注：`user_id=None` 仅 admin 内部调用；API 层必须传当前 user_id

## 验收检查点
- [ ] 用户 A token GET `/conversations/{B的id}` 返回 404 + CONV_001
- [ ] 用户 A token DELETE `/conversations/{B的id}` 返回 404 + CONV_001
- [ ] admin token GET `/conversations/{B的id}` 返回 200
- [ ] 用户 A token GET 自己的 conversation 返回 200
- [ ] 不存在 id 返回 404 + CONV_001
- [ ] conversations 路由无裸 HTTPException，统一用 ResourceNotFoundError
- [ ] `tests/security/test_idor.py` 覆盖以上场景通过
- [ ] 无 403 泄露资源存在性

### 通过判定
全部 ✅ → Done | 任一 ❌ 且 retry<3 → 修复 | retry=3 → BLOCKED
