<!-- Module: frontend -->
<!-- Spec Layer: 01 - Requirements -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-25 -->

# 01-requirements: Frontend v2.0 功能需求

## 已有需求（v1.0 保留）

| ID | 描述 | 优先级 | 状态 |
|----|------|--------|------|
| REQ-001 | 聊天输入框 + 发送 + Streaming 输出 | P0 | DONE |
| REQ-002 | 候选人卡片展示（ScoreBar + SkillTags + ReasonList） | P0 | DONE |
| REQ-003 | 多轮对话自动维护 conversation_id | P0 | DONE |
| REQ-004 | 文件上传（单个 + 批量 PDF/DOCX/JSON） | P0 | DONE |
| REQ-005 | 侧边栏对话历史列表 | P1 | DONE |
| REQ-006 | 登录页面 + JWT 认证 | P1 | DONE |
| REQ-007 | 错误提示 + 重试按钮 | P0 | DONE |
| REQ-008 | 简历管理页（admin 查看/搜索/删除） | P1 | DONE |
| REQ-009 | 系统仪表盘（健康检查 + 基础统计） | P1 | DONE |

## 新增需求（v2.0）

### 页面级需求

| ID | 描述 | 优先级 | 对应文件 |
|----|------|--------|----------|
| REQ-010 | 简历详情页：展示完整个人信息、教育/工作/项目经历、技能标签云 | P0 | 6_简历详情.py |
| REQ-011 | 候选人对比：多选候选人并排对比表格，差异高亮 | P0 | 7_候选人对比.py |
| REQ-012 | 用户管理页：admin 查看用户列表、角色权限说明 | P1 | 8_用户管理.py |
| REQ-013 | 搜索筛选器：城市多选、学历下拉、经验滑块、技能多选、985/211勾选 | P0 | 1_智能搜索.py |
| REQ-014 | 搜索结果排序：按匹配度/经验/学历排序 | P1 | 1_智能搜索.py |
| REQ-015 | 候选人对比勾选：搜索结果每张卡片增加 checkbox | P0 | 1_智能搜索.py |
| REQ-016 | 搜索结果导出 Excel：一键导出当前搜索结果 | P0 | 1_智能搜索.py + api_client.py |
| REQ-017 | 简历详情跳转：从搜索结果/管理页点击跳转到详情页 | P0 | 1_智能搜索.py, 3_简历管理.py |
| REQ-018 | 上传解析预览：上传完成后展示提取的结构化数据 | P0 | 2_简历上传.py |
| REQ-019 | 简历管理高级筛选：城市/学历/技能/状态过滤 | P0 | 3_简历管理.py |
| REQ-020 | 简历编辑弹窗：修改个人信息/技能/经历 | P1 | 3_简历管理.py |
| REQ-021 | 简历管理批量操作：批量删除、批量导出 | P1 | 3_简历管理.py |
| REQ-022 | 仪表盘增强：工作年限分布、城市分布、公司Top20、学历分布图 | P0 | 5_系统仪表盘.py |
| REQ-023 | 仪表盘系统指标：平均响应时间、搜索次数、活跃用户 | P1 | 5_系统仪表盘.py |
| REQ-024 | 新增对话按钮：搜索页侧边栏保留 | P0 | 1_智能搜索.py |

### 公共组件需求

| ID | 描述 | 优先级 |
|----|------|--------|
| REQ-025 | render_resume_full() — 可复用的完整简历渲染组件 | P0 |
| REQ-026 | render_filter_sidebar() — 可复用的筛选器侧边栏组件 | P0 |
| REQ-027 | render_stats_card() — 可复用的统计卡片组件 | P1 |
| REQ-028 | export_to_excel() — Excel 导出工具函数 | P0 |

### API 客户端需求

| ID | 描述 | 优先级 |
|----|------|--------|
| REQ-029 | get_resume(resume_id) — 获取单个简历详情 | P0 |
| REQ-030 | list_resumes_api(filters) — 带筛选的简历列表查询 | P0 |
| REQ-031 | update_resume(resume_id, data) — 更新简历 | P1 |
| REQ-032 | delete_resume_api(resume_id) — 删除简历 | P0 |
| REQ-033 | get_resume_stats() — 获取系统统计数据 | P0 |
| REQ-034 | export_candidates_excel(candidates) — 生成 Excel 字节流 | P0 |
