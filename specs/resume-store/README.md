# resume-store Spec

> 简化模块：含 00-overview.md + README.md

## 为什么没有 8 层文件？

resume-store 的完整需求（REQ、Data Model、API Contract、Business Rules、Edge Cases、AC）全部整合在 00-overview.md 中。
这是因为 resume-store 是相对简单的 CRUD 模块，不需要拆分为 8 个文件。

## 引用关系
- T-007: MongoDB 连接 + 基础 CRUD
- T-014: Resume Store CRUD + 脱敏（引用 00-overview 全部章节）
