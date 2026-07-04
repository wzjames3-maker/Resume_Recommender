<!-- Module: vector-index -->
<!-- Spec Layer: 05 - Edge Cases -->
<!-- 变更: Tier L - RAG 全量重构 -->
<!-- Date: 2026-07-03 -->

# 05-edge-cases: Vector Index

| ID | 场景 | 处理 |
|----|------|------|
| EC-001 | FlagEmbedding 模型首次加载超时 | 等待 120s（模型下载 + 加载），仍失败抛 ExternalServiceError |
| EC-002 | FlagEmbedding 无 GPU 环境 | 自动降级 use_fp16=False（CPU 推理），延迟约 2-3x |
| EC-003 | Milvus 连接失败 | 重试 3 次（间隔 2s），仍失败返回错误码 RETRIEVAL_TIMEOUT |
| EC-004 | Dense 向量维度不匹配（非 1024） | 拒绝写入，记录错误日志 |
| EC-005 | Sparse 向量为空 dict | 拒绝写入，记录错误日志（必须是非空的真实 sparse） |
| EC-006 | chunk_id 不存在于 Milvus | delete_chunks_by_resume 静默成功 |
| EC-007 | 缓存命中率低 | cachetools TTL 设为 1 小时，监控缓存命中率 |
| EC-008 | Small Chunk 数量过多（>100/简历） | 截断到 100 个 Small Chunk，记录警告 |
| EC-009 | parent_chunk_id 指向不存在的 Parent Chunk | 降级使用 Full Resume Chunk 作为上下文 |
| EC-010 | Full Resume Chunk 也不存在 | 返回 Small Chunk 自身内容作为上下文 |
| EC-011 | 标量字段值为 None（简历未提取到该字段） | 使用默认值（years_of_experience=0, highest_education_level=0, city="", gender=""） |
| EC-012 | Milvus 标量过滤后结果为空 | 返回空列表，由 recommendation-engine 触发降级策略 |
| EC-013 | 同一 resume_id 被重复写入 | 先删除旧向量再插入新向量（update_chunks 流程） |
| EC-014 | FlagEmbedding batch 输入超过 32 条 | 自动分批，每批最多 32 条 |
| EC-015 | Redis 不可用（L2 缓存） | 降级为仅 L1 缓存，记录警告，不阻断流程 |
| EC-016 | 输入文本为空字符串 | FlagEmbedding 生成全零向量，记录警告但不抛异常 |
