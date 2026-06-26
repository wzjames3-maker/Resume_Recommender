<!-- Task: T-038 -->
<!-- Phase: Phase 3 - Frontend v2.0 增强 -->
<!-- Module: frontend -->
<!-- Priority: P0 -->
<!-- Depends: T-036, T-037 -->

# T-038: 智能搜索页增强 + 简历上传页增强

## 任务目标

增强搜索页（筛选器、排序、对比勾选、导出）和上传页（预览、拖拽、进度）。

## 前置条件

- T-036 (公共组件 + api_client 增强) ✅
- T-037 (详情页 + 对比页) ✅

## 输出清单

| 文件 | 操作 | 内容 |
|------|------|------|
| `src/frontend/pages/1_智能搜索.py` | 修改 | 增加筛选器、排序、对比勾选、导出（增量扩展） |
| `src/frontend/pages/2_简历上传.py` | 修改 | 增加解析预览、进度条（增量扩展） |

## ⚠️ 增量扩展警告

`1_智能搜索.py` 和 `2_简历上传.py` 已有 v1.0 完整实现，**禁止全量覆盖**。仅追加功能，不改动现有逻辑。

## 详细规格

### 1_智能搜索.py 增强

1. **侧边栏筛选器**（新增在现有侧边栏下方）
   - 使用 `render_filter_sidebar(cities, skills)`
   - 筛选条件存入 `st.session_state.search_filters`
   - 发送搜索时附加到 ChatRequest

2. **候选人卡片增强**（在现有 render_candidate_card 基础上）
   - 每张卡片增加 st.checkbox("加入对比", key=f"compare_{resume_id}")
   - compare 状态存入 `st.session_state.compare_candidates`
   - 最大5人限制

3. **排序选项**（搜索结果显示区域上方）
   - st.radio: 按匹配度 / 按经验 / 按学历

4. **导出按钮**（搜索结果有数据时显示）
   - st.download_button("导出搜索结果")
   - 调用 `export_to_excel(last_candidates)`

5. **搜索结果行**（在专家卡片显示区域上方）
   - st.page_link 跳转到详情页
   - st.page_link 跳转到对比页（若已选候选人）

6. **排序/过滤**（在搜索结果显示区域上方）
   - 增加排序单选按钮

### 2_简历上传.py 增强

1. **解析结果预览**（上传成功后展示）
   - 调用 `get_resume(resume_id)` 获取数据
   - 使用 `render_resume_full()` 展示

2. **拖拽上传**（Streamlit 原生支持，添说明文字）

3. **批次进度条增强**（现有基础上增强样式）

## 验收标准

| ID | Given | When | Then |
|----|-------|------|------|
| AC-038-01 | 已登录 | 打开搜索页 | 侧边栏显示筛选器 |
| AC-038-02 | 筛选为北京+硕士 | 搜索 | 结果匹配筛选条件 |
| AC-038-03 | 勾选3个对比 | 点击进入对比 | 跳转对比页 |
| AC-038-04 | 上传PDF | 完成后 | 显示解析预览 |
