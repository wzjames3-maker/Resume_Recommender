<!-- Module: frontend -->
<!-- Spec Layer: 04 - Business Rules -->
<!-- Date: 2026-06-25 -->

# 04-business-rules: Frontend 业务规则

## 4.1 认证与权限

| ID | 规则 |
|----|------|
| RULE-001 | 未登录时所有页面显示登录页，无法跳过 |
| RULE-002 | JWT 存储在 session_state，每次 API 请求携带 Authorization header |
| RULE-003 | 简历管理页、用户管理页仅 role==admin 可访问 |
| RULE-004 | 登录过期/401 时自动跳转登录页并清除 session_state |

## 4.2 搜索与推荐

| ID | 规则 |
|----|------|
| RULE-005 | 搜索结果按 final_score 降序排列 |
| RULE-006 | 筛选器在搜索请求发送前附加到 ChatRequest.filters 字段 |
| RULE-007 | 候选人卡片默认展开前3个，其余折叠 |
| RULE-008 | 对比候选人最多5个，超出提示 |
| RULE-009 | 导出 Excel 时按当前排序顺序导出 |

## 4.3 简历上传

| ID | 规则 |
|----|------|
| RULE-010 | 仅支持 PDF / DOCX / JSON 格式 |
| RULE-011 | 文件大小限制 20MB |
| RULE-012 | 批量上传逐个处理，单次最多 50 个文件 |
| RULE-013 | 上传后展示解析结果预览 |

## 4.4 简历管理

| ID | 规则 |
|----|------|
| RULE-014 | 简历删除为软删除（status=deleted） |
| RULE-015 | 简历编辑仅修改 personal_info、skill_list、education_list、experience_list |
| RULE-016 | 分页每页 10 条 |
| RULE-017 | 筛选条件在 MongoDB 查询层执行 |

## 4.5 仪表盘

| ID | 规则 |
|----|------|
| RULE-018 | 仪表盘数据从 MongoDB 聚合查询实时获取 |
| RULE-019 | 图表在每次页面加载时重新渲染 |
| RULE-020 | Docker 状态检测为可选（fallback 显示 N/A） |

## 4.6 UI 通用规则

| ID | 规则 |
|----|------|
| RULE-021 | 所有页面使用 layout=wide |
| RULE-022 | 所有页面顶部显示当前用户和角色 |
| RULE-023 | 所有操作按钮需防重复点击 |
| RULE-024 | 数据加载中显示 st.spinner |
