# PIP-T06: 实现 refine NARROW 分支

## 基本信息
- **对应 Spec**: CONV REQ-009, CONV RULE-006
- **依赖**: PIP-T05
- **预计工时**: 0.5 天
- **优先级**: P1

## 问题
`src/conversation_memory/workflow.py:289` 注释 `# TODO: 实现在上次结果中检索的逻辑`，然后直接全库检索。
`scope_decider` 判出 `NARROW` 后的行为与 `FULL` 完全相同，多轮对话的"缩小范围"是空的。

## 实现要求

### 在 workflow.py:286-294 实现 NARROW 分支
```python
if scope_decision.scope == SearchScope.NARROW:
    logger.info("在上次结果中检索")
    # 从上次候选人列表中提取 resume_id
    candidate_ids = scope_decision.candidate_ids
    if candidate_ids:
        # 在候选集中用查询向量过滤
        retrieval_results = self.hybrid_retriever.retrieve(
            merged_slots,
            raw_query=intent_result.raw_query,
        )
        # 后过滤: 只保留 candidate_ids 中的结果
        retrieval_results = [
            r for r in retrieval_results
            if r.resume_id in candidate_ids
        ]
    else:
        retrieval_results = []
else:
    # 全库检索 (现有逻辑)
    retrieval_results = self.hybrid_retriever.retrieve(merged_slots, raw_query=intent_result.raw_query)
```

### 降级处理
- 若 NARROW 过滤后结果为空（all filtered out），降级为 FULL 并记录日志
- 若 candidate_ids 为空列表，降级为 FULL

## 验收检查点
- [ ] `workflow.py:289` 的 TODO 注释已移除，替换为可工作的 NARROW 逻辑
- [ ] NARROW 模式只在上次结果中检索
- [ ] NARROW 结果为空时降级为 FULL
- [ ] 日志包含 `scope` 和 `scope_reason`

### 通过判定
全部 ✅ → Done | 任一 ❌ 且 retry<3 → 修复 | retry=3 → BLOCKED
