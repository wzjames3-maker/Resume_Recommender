# PIP-T04: Upload 传递 project_list + 使用 fallback_result.structured

## 基本信息
- **对应 Spec**: RES-PARSER REQ-003, REQ-005
- **依赖**: PIP-T03
- **预计工时**: 0.5 天
- **优先级**: P1

## 问题
1. `upload.py:96-102` 构建 `ResumeCreateRequest` 时未传递 `project_list`，LLM 提取的项目经历被静默丢弃
2. `upload.py:96-102` 使用原始的 `structured` 而非 fallback_handler 处理后的 `fallback_result.structured`，降级结果被忽略

## 实现要求

### 1. 补传 project_list
```python
# upload.py line 96-102, 新增 project_list 参数:
request = ResumeCreateRequest(
    personal_info=structured.personal_info if structured else None,
    education_list=structured.education_list if structured else [],
    experience_list=structured.experience_list if structured else [],
    skill_list=structured.skill_list if structured else [],
    project_list=structured.project_list if structured else [],  # 新增
    raw_text=extracted_doc.raw_text,
)
```

### 2. 使用 fallback 处理后的结果
```python
# 第 9 步"降级处理"之后，优先使用 fallback_result:
effective = fallback_result.structured if fallback_result.structured else structured

request = ResumeCreateRequest(
    personal_info=effective.personal_info if effective else None,
    education_list=effective.education_list if effective else [],
    experience_list=effective.experience_list if effective else [],
    skill_list=effective.skill_list if effective else [],
    project_list=effective.project_list if effective else [],
    raw_text=extracted_doc.raw_text,
)
```

## 验收检查点
- [ ] `ResumeCreateRequest` 包含 `project_list` 参数
- [ ] 使用 `fallback_result.structured` 优先于原始 `structured`
- [ ] `rg -n "project_list" src/api/v1/upload.py` 返回至少 1 个结果

### 通过判定
全部 ✅ → Done | 任一 ❌ 且 retry<3 → 修复 | retry=3 → BLOCKED
