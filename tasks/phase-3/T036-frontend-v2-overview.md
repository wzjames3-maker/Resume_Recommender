<!-- Task: T-036 -->
<!-- Phase: Phase 3 - Frontend v2.0 增强 -->
<!-- Module: frontend -->
<!-- Priority: P0 -->
<!-- Depends: T-034, T-035 (v1.0 frontend baseline) -->

# T-036: Frontend v2.0 — 公共组件与 api_client 增强

## 任务目标

增强 `components.py` 和 `api_client.py`，为后续页面增强提供公共基础。

## 前置条件

- T-034 (app.py + login) ✅
- T-035 (chat + cards) ✅
- pyproject.toml 添加 `openpyxl` 依赖

## 输出清单

| 文件 | 操作 | 内容 |
|------|------|------|
| `src/frontend/components.py` | 修改 | 新增 4 个函数（增量扩展，保留现有 render_candidate_card / render_candidate_list） |
| `src/frontend/api_client.py` | 修改 | 新增 6 个函数（增量扩展，保留现有方法） |
| `pyproject.toml` | 修改 | 添加 openpyxl >= 3.1 依赖 |

## ⚠️ 增量扩展警告

`components.py` 和 `api_client.py` 已有 v1.0 实现，**禁止全量覆盖**。采用尾部追加方式：
- `components.py`：保留现有 `render_candidate_card()` / `render_candidate_list()` / `render_sidebar_stats()`，在文件末尾追加新函数
- `api_client.py`：保留现有 `login()` / `logout()` / `health_check()` / `upload_resume()` / `send_chat_message()` / `list_conversations()` / `get_conversation()` / `delete_conversation()`，在文件末尾追加新方法

## 详细规格

### components.py 新增

1. `render_resume_full(doc, show_id=True)` — 完整简历渲染
   - PersonalInfo: 姓名、城市、年限、公司、职位、薪资期望
   - EducationList: 时间倒序、学校 + 学历 + 专业 + 985/211标签
   - ExperienceList: 时间倒序、公司 + 职位 + 时间 + 描述
   - ProjectList: 项目名 + 角色 + 技术栈标签 + 描述
   - SkillCloud: 技能标签 st.markdown tags

2. `render_filter_sidebar(cities, skills)` — 筛选器侧边栏
   - st.multiselect: 城市
   - st.selectbox: 学历（不限/大专/本科/硕士/博士）
   - st.slider: 工作经验范围
   - st.multiselect: 技能
   - st.checkbox: 985院校 / 211院校

3. `render_stats_card(label, value, delta=None)` — 统计卡片
   - st.metric 封装

4. `export_to_excel(data, filename="export.xlsx")` — Excel 导出
   - 使用 openpyxl 创建工作簿
   - 返回 bytes 供 st.download_button 使用

### api_client.py 新增

5. `get_resume(resume_id)` — MongoDB 直连查询简历详情

6. `list_resumes_api(keyword, skill, city, education, min_exp, is_985, is_211, page, size)` — 带筛选的列表

7. `update_resume(resume_id, data)` — 更新简历

8. `delete_resume_api(resume_id)` — 软删除

9. `get_resume_stats()` — 聚合统计数据

10. `export_candidates_excel(candidates)` — 候选人数据转 Excel bytes

## 验收标准

| ID | Given | When | Then |
|----|-------|------|------|
| AC-036-01 | 传入简历doc | 调用 render_resume_full | 渲染全部字段 |
| AC-036-02 | 传入城市/技能选项 | 调用 render_filter_sidebar | 渲染多选+滑块+checkbox |
| AC-036-03 | 传入候选人列表 | 调用 export_to_excel | 返回 .xlsx bytes |
| AC-036-04 | MongoDB 有数据 | 调用 get_resume_stats | 返回统计dict |
