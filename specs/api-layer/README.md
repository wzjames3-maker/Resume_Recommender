# api-layer Spec

> 简化模块：仅含 00-overview.md

## 为什么没有 8 层文件？

api-layer 是路由聚合层，不含独立业务逻辑。其需求分散在各业务模块的 Spec 中：
- 认证规则 → 由各业务模块的 auth 依赖注入定义
- API 契约 → 由各业务模块的 03-api-contract.md 定义
- 路由实现 → T-030~T-033 根据各模块 Spec 统一实现

## 引用关系
- T-006: 认证中间件（引用 00-overview RULE-001~004）
- T-030~T-033: API 路由实现（引用各业务模块的 03-api-contract.md）
