# PIP-T03: 修复 llm_extractor.py regex: s*→\s*

## 基本信息
- **对应 Spec**: RES-PARSER REQ-003
- **依赖**: 无
- **预计工时**: 0.25 天
- **优先级**: P0

## 问题
`src/resume_parser/llm_extractor.py:85`:
```python
match = re.search(r"`{3}(?:json)?s*({.*?})s*`{3}", text, re.DOTALL)
```
`\s` 被误写为 `s`（缺反斜杠），`s*` 只匹配字面字母 s。当 LLM 返回带换行的正常 JSON 块时提取失败。

对比 `src/intent_router/classifier.py:30` 写的是正确的 `\s*`。

## 实现要求

### 修改 `src/resume_parser/llm_extractor.py:85`
```python
# 旧:
match = re.search(r"`{3}(?:json)?s*({.*?})s*`{3}", text, re.DOTALL)
# 新:
match = re.search(r"`{3}(?:json)?\s*(\{.*?\})\s*`{3}", text, re.DOTALL)
```

### 验证
手工构造测试用例验证 JSON 块前后有换行的场景能正确提取:
```python
text = "```json\n{\"name\": \"test\"}\n```"
result = _extract_json_from_text(text)
assert result == {"name": "test"}
```

## 验收检查点
- [ ] `llm_extractor.py:85` 中 `s*` 改为 `\s*`
- [ ] 新增或更新 `tests/resume_parser/test_llm_extractor.py` 包含带换行 JSON 块的测试
- [ ] `rg "s\*\(\{" src/resume_parser/` 返回零结果（确认修复）

### 通过判定
全部 ✅ → Done | 任一 ❌ 且 retry<3 → 修复 | retry=3 → BLOCKED
