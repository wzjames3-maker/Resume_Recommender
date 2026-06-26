<!-- Module: frontend -->
<!-- Spec Layer: 00 - Overview -->
<!-- Phase: Phase 4 - Spec Writing (迭代 v2.0) -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-25 -->

# 模块概览：Frontend（前端用户界面）v2.0

## 1. 变更记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2026-06-23 | 初始版本：登录页 + 聊天界面 + 候选人卡片 |
| v2.0 | 2026-06-25 | 全面增强：新增3个页面、增强4个现有页面、公共组件提取、导出功能 |

## 2. 模块定位

Frontend 是用户与智能招聘 RAG 推荐系统交互的唯一界面入口，基于 Streamlit 构建。

## 3. 来源追溯

| 来源 | 内容 |
|------|------|
| PRD FR-015 | 智能搜索界面（聊天式交互） |
| PRD FR-016 | 简历上传与管理界面 |
| PRD FR-017 | 候选人详情与对比界面 |
| PRD FR-018 | 系统仪表盘与数据统计 |
| PRD UC-001 | HR 搜索候选人 |
| PRD UC-005 | 简历上传入库 |
| PRD UC-008 | 候选人详情查看与对比 |

## 4. 做什么（In Scope）v2.0

### 4.1 已有页面（v1.0 保留并增强）

| 页面 | 文件 | v2.0 变更 |
|------|------|-----------|
| 智能搜索 | 1_智能搜索.py | 增加高级筛选器、排序选项、导出Excel、对比勾选、跳转详情 |
| 简历上传 | 2_简历上传.py | 增加解析结果预览、拖拽上传、实时进度条 |
| 简历管理 | 3_简历管理.py | 增加高级筛选器、简历编辑弹窗、批量操作、跳转详情 |
| 对话历史 | 4_对话历史.py | 保持现有功能 |
| 系统仪表盘 | 5_系统仪表盘.py | 增加6+种图表、系统性能指标 |

### 4.2 新增页面（v2.0）

| 页面 | 文件 | 说明 |
|------|------|------|
| 简历详情 | 6_简历详情.py | 完整简历信息展示、教育/工作/项目时间线、技能标签云 |
| 候选人对比 | 7_候选人对比.py | 多候选人并排对比表格、差异高亮、技能匹配/缺失对比 |
| 用户管理 | 8_用户管理.py | 用户列表、角色权限说明、系统配置展示（admin only） |

### 4.3 公共组件增强

| 组件 | 说明 |
|------|------|
| render_resume_full() | 完整简历渲染（个人信息、教育、工作、项目、技能） |
| render_filter_sidebar() | 通用筛选器侧边栏（城市/学历/经验/技能） |
| render_stats_card() | 统计卡片组件 |
| export_to_excel() | Excel 导出工具函数 |

### 4.4 API 客户端扩展（api_client.py）

新增方法：
- get_resume() — 获取简历详情
- list_resumes_api() — 带筛选的简历列表
- update_resume() — 更新简历
- delete_resume_api() — 删除简历
- get_resume_stats() — 获取统计数据
- export_candidates_excel() — 导出候选人Excel

## 5. 不做什么（Out of Scope）

| 不做 | 说明 |
|------|------|
| 移动端适配 | 桌面优先，不做响应式设计 |
| 复杂动画/拖拽 | 保持 Streamlit 原生交互 |
| JavaScript 框架 | 纯 Python + Streamlit |
| 修改后端 API | 不新增后端路由，通过 MongoDB 直连或现有 API 实现 |
| 简历编辑器 | 不做富文本编辑器，仅提供基础字段修改 |

## 6. 技术栈

| 组件 | 技术选型 | 版本 | 用途 |
|------|----------|------|------|
| 框架 | Streamlit | >=1.40 | 多页面路由 |
| HTTP客户端 | requests | >=2.31 | API 调用 |
| Excel导出 | openpyxl | >=3.1 | 候选人数据导出 |
| 数据库直连 | pymongo | >=4.0 | 简历管理页 MongoDB 查询 |
| 图表 | Streamlit 原生 | — | st.bar_chart, st.metric, st.dataframe |

## 7. 页面路由

```
主入口 app.py (登录/认证)
├── 智能搜索    → pages/1_智能搜索.py
├── 简历上传    → pages/2_简历上传.py
├── 简历管理    → pages/3_简历管理.py (admin only)
├── 对话历史    → pages/4_对话历史.py
├── 系统仪表盘  → pages/5_系统仪表盘.py
├── 简历详情    → pages/6_简历详情.py [NEW]
├── 候选人对比  → pages/7_候选人对比.py [NEW]
└── 用户管理    → pages/8_用户管理.py [NEW, admin only]
```

## 8. session_state 结构

- token, user_id, role — 认证状态
- conversation_id, messages, last_candidates — 对话状态
- compare_candidates — [NEW] 候选人ID列表，最多5个
- search_filters — [NEW] 搜索筛选条件

## 9. 数据流

- 搜索: 用户输入 → POST /api/v1/chat (SSE) → 流式渲染卡片
- 上传: 文件选择 → POST /api/v1/resumes/upload → 结果预览
- 管理: MongoDB 直连查询 → 列表/详情渲染
- 导出: 数据聚合 → openpyxl 生成 Excel → 下载

## 10. 文件索引

| 文件 | 内容 |
|------|------|
| 00-overview.md | 模块概览（本文件） |
| 01-requirements.md | 功能需求列表 |
| 02-data-model.md | 数据模型与状态定义 |
| 03-api-contract.md | 前端调用接口契约 |
| 04-business-rules.md | 业务规则与交互逻辑 |
| 05-edge-cases.md | 边界情况与异常处理 |
| 06-acceptance.md | 验收标准（Given-When-Then） |
| 07-tech-constraints.md | 技术约束与依赖版本 |
| 08-dependencies.md | 模块依赖关系 |
