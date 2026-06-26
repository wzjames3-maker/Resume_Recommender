<!-- Module: frontend -->
<!-- Spec Layer: 08 - Dependencies -->
<!-- Date: 2026-06-25 -->

# 08-dependencies: Frontend 模块依赖

## 8.1 上游依赖

| 模块 | 依赖方式 | 说明 |
|------|----------|------|
| api-layer | HTTP (requests) | POST /chat, /upload, /auth, /conversations |
| resume-store | MongoDB 直连 (pymongo) | 简历管理、详情、统计查询 |

## 8.2 下游依赖

Frontend 是终端模块，无下游依赖。

## 8.3 数据依赖

| 数据 | 来源 |
|------|------|
| 候选人搜索结果 | POST /api/v1/chat SSE |
| 简历详情 | MongoDB resumes 集合 |
| 统计数据 | MongoDB 聚合 pipeline |
| 对话历史 | GET /api/v1/conversations |
| 用户认证 | POST /api/v1/auth/login |

## 8.4 文件依赖关系

```
src/frontend/
├── app.py              (主入口，引用 api_client)
├── api_client.py       (无内部依赖)
├── components.py       (无内部依赖，被所有页面引用)
└── pages/
    ├── 1_智能搜索.py    → api_client, components
    ├── 2_简历上传.py    → api_client
    ├── 3_简历管理.py    → api_client, components
    ├── 4_对话历史.py    → api_client
    ├── 5_系统仪表盘.py  → api_client, components
    ├── 6_简历详情.py    → api_client, components  [NEW]
    ├── 7_候选人对比.py  → api_client, components  [NEW]
    └── 8_用户管理.py    → api_client               [NEW]
```
