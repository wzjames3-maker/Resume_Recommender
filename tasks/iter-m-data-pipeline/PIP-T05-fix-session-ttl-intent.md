# PIP-T05: Session TTL 检查 + last_intent 持久化

## 基本信息
- **对应 Spec**: CONV REQ-008 (新增), CONV RULE-003
- **依赖**: 无
- **预计工时**: 0.5 天
- **优先级**: P1

## 问题
1. `session_manager.py:58` 接受 `ttl_seconds=1800`，但 `get_session()` (line 94-115) 从不检查 `last_active_at`，TTL 形同虚设
2. `SessionState` 缺少 `last_intent` 字段，`get_conversation_context()` 返回的 dict 不含 `last_intent`，导致 classifier 的上下文信息始终为空

## 实现要求

### 1. TTL 检查
在 `get_session()` 中增加过期检查:
```python
def get_session(self, session_id: str) -> Optional[SessionState]:
    session = self._sessions.get(session_id)
    if not session:
        return None
    if session.status != SessionStatus.ACTIVE:
        return None
    # 新增: TTL 检查
    elapsed = (datetime.now(timezone.utc) - session.last_active_at).total_seconds()
    if elapsed > self.ttl_seconds:
        session.status = SessionStatus.EXPIRED
        logger.warning(f"会话已过期: session_id={session_id}, elapsed={elapsed:.0f}s")
        return None
    return session
```

### 2. last_intent 持久化
在 `SessionState` 中新增 `last_intent: Optional[str] = Field(None)` 字段。
在 `update_session_state()` 中增加 `last_intent` 参数。
在 `get_conversation_context()` 返回的 dict 中增加 `last_intent`。
在工作流 `search()` / `refine()` 更新会话状态时传入当前 intent。

### 3. 清理过期的后台任务（可选, P2）
添加 `_cleanup_expired()` 方法定时清理过期会话，避免内存泄漏。

## 验收检查点
- [ ] `get_session()` 检查 TTL 超时返回 None
- [ ] `SessionState` 有 `last_intent` 字段
- [ ] `get_conversation_context()` 返回 `last_intent`
- [ ] 工作流更新状态时传入 `last_intent`
- [ ] 新增测试 `test_session_ttl_expiry`

### 通过判定
全部 ✅ → Done | 任一 ❌ 且 retry<3 → 修复 | retry=3 → BLOCKED
