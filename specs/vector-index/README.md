# vector-index Spec

> 简化模块：仅含 00-overview.md

## 为什么没有 8 层文件？

vector-index 的完整需求（REQ-001~010、Data Model、Business Rules、Edge Cases、AC）全部整合在 00-overview.md 中。
这是因为向量索引层与 Milvus SDK 紧密耦合，拆分为 8 层反而增加维护成本。

## 引用关系
- T-008: Milvus 连接 + Collection 创建（引用 00-overview 02-data-model + REQ）
- T-015: Embedding 生成 + 向量写入（引用 00-overview REQ-001~010）
