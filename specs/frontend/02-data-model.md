<!-- Module: frontend -->
<!-- Spec Layer: 02 - Data Model -->
<!-- Date: 2026-06-25 -->

# 02-data-model: Frontend v2.0 数据模型

## 2.1 session_state 完整结构

```python
st.session_state = {
    # --- 认证 ---
    'token': str | None,
    'user_id': str | None,
    'role': str | None,

    # --- 对话 ---
    'conversation_id': str | None,
    'messages': list,
    'last_candidates': list,

    # --- v2.0 NEW ---
    'compare_candidates': list[str],  # 最多5个候选人ID
    'search_filters': {
        'city': list[str],
        'education': str | None,
        'min_experience': int,
        'max_experience': int | None,
        'skills': list[str],
        'is_985': bool,
        'is_211': bool,
        'sort_by': str,
    },
    'resume_page': int,
    'conv_page': int,
}
```

## 2.2 候选人数据结构（API 返回）

```python
candidate = {
    'resume_id': str,
    'chunk_id': str,
    'content': str,
    'score': float,  # 0-1 匹配度
    'rank': int,
    'reason': {
        'reason': str,
        'matched_skills': list[str],
        'missing_skills': list[str],
        'score_breakdown': {
            'semantic_score': float,
            'filter_score': float,
            'final_score': float,
            'skill_match_score': float,
            'industry_match_score': float,
        },
    },
    'metadata': {'name': str},
}
```

## 2.3 简历详情结构（MongoDB）

```python
resume = {
    'id': str,
    'personal_info': {
        'name': str,
        'highest_education': str  # e.g. 本科/硕士/博士,
        'total_experience': str | None  # e.g. '5年',
        'expected_cities': list[str]  # list of city names,
        'expected_salary': str | None,
        'current_status': str | None  # e.g. 在职/离职,
        'name': str  # duplicate removed - already above,
    },
    'education_list': [{'school': str, 'degree': str, 'major': str, 'is_985': bool}],
    'experience_list': [{'company': str, 'title': str, 'duration': str, 'description': str}],
    'project_list': [{'name': str, 'role': str, 'description': str, 'tech_stack': list}],
    'skill_list': list[str],
    'status': str,
    'created_at': str,
}
```

## 2.4 导出 Excel 数据结构

| 列名 | 字段 |
|------|------|
| 排名 | rank |
| 姓名 | name |
| 匹配度 | score |
| 匹配技能 | matched_skills (comma joined) |
| 缺失技能 | missing_skills (comma joined) |
| 学历 | degree |
| 毕业院校 | school |
| 工作年限 | years_of_experience |
| 当前公司 | current_company |
| 期望城市 | expected_city |
| 期望薪资 | expected_salary_range |
