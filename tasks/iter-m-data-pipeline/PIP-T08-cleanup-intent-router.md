# PIP-T08: 清理 IntentRouter 死代码 + chat.py 显式路由

## 基本信息
- **对应 Spec**: INTENT REQ-007 (新增)
- **依赖**: 无
- **预计工时**: 0.5 天
- **优先级**: P1

## 问题

### 问题 1: IntentRouter 全套体系是死代码
`src/intent_router/router.py` 的 dependents: "no other indexed file depends on it"。
`SearchHandler/RefineHandler/LookupHandler/ChatHandler/FallbackHandler` 的 `handle()` 方法只返回固定字符串，不做任何业务逻辑。router.py 的 module docstring 自己承认 Handler 是桩实现。

### 问题 2: chat.py 硬编码 if/elif
`src/api/v1/chat.py:86-99` 用六个 if/elif 分支直接调 `workflow.search()/refine()/lookup()`。五个意图（RESUME_UPLOAD/RESUME_MANAGE/KNOWLEDGE_QA/ANALYTICS/CHAT）全部返回固定回复 "您好！我是智能招聘助手"。

## 实现要求

### 方案: 承认现状，清理死代码，显式化路由

1. **删除** `router.py` 中的 Handler 体系（或整个文件改为文档注释说明现状）
2. **chat.py** 显式化意图→处理函数的映射表:
```python
INTENT_HANDLERS = {
    IntentEnum.RECRUITMENT_SEARCH: workflow.search,
    IntentEnum.RECRUITMENT_REFINE: workflow.refine,
    IntentEnum.CANDIDATE_LOOKUP: workflow.lookup,
}

async def generate_sse_stream(...):
    ...
    handler = INTENT_HANDLERS.get(intent_result.intent)
    if handler:
        result = handler(intent_result, conversation_id, user_id)
        # ... 发送响应
    else:
        # 未实现的意图统一返回引导消息
        yield ...
```

3. **chat.py** 的 else 分支改为返回更有用的引导消息（而非统一回复）:
```python
FALLBACK_MESSAGES = {
    IntentEnum.RESUME_UPLOAD: "请使用简历上传功能上传简历文件",
    IntentEnum.RESUME_MANAGE: "您可以在简历管理页面查看和编辑简历",
    IntentEnum.KNOWLEDGE_QA: "关于招聘知识，您可以问...",
    ...
}
```

### 保留
- `classifier.py` (Intent 分类 + _keyword_fallback) 保持不变
- `schemas.py` (IntentEnum/CandidateSlot/QuerySlot) 保持不变
- `fallback_handler.py` (置信度门控) 保持不变

## 验收检查点
- [ ] `router.py` 的 Handler 类已删除或标记为 deprecated
- [ ] `chat.py` 使用映射表而非 if/elif
- [ ] card.py 的 else 分支返回意图相关的引导消息
- [ ] 无新增 ImportError
- [ ] 现有 chat endpoint 测试通过

### 通过判定
全部 ✅ → Done | 任一 ❌ 且 retry<3 → 修复 | retry=3 → BLOCKED
