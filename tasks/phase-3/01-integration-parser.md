# T-036: Resume Parser → Store → Vector 全链路集成测试【M1 验收门控】

## 基本信息
- **对应 Spec**: integration-testing（全链路数据流）
- **对应 AC**: 全链路数据完整性验证
- **依赖任务**: T-015（Embedding + Milvus 写入）, T-014（Resume Store CRUD）
- **执行位置**: M1 结束时立即执行（第 1 周末），作为 M1 验收门控
- **🔴 左移策略**: 本任务原定 Phase 3（第 4 周），现左移到 M1 节点。RAG 系统的数据流断裂越晚发现修复成本越高——若 Parser 输出的 Chunk Schema 与 Milvus 接收的 Metadata 不匹配，必须在 M1 阶段立即修复，否则 T-016~T-035 全部建立在错误地基上
- **预计工时**: 1 天
- **优先级**: P0（M1 验收门控 — 不通过则阻断 M2/M3/M4 全部后续任务）

## 输入
- T-014 产出的 Resume Parser 模块
- T-015 产出的 Embedding 生成 + Milvus 写入模块
- 测试用 PDF 简历文件（`tests/fixtures/resumes/` 目录下，至少 3 份不同格式）

## 输出
- `tests/integration/test_parser_store_vector.py` — 集成测试文件
- `tests/fixtures/resumes/` — 测试用简历文件（如尚未创建）
- 集成测试运行报告

## 实现要求

### 测试链路
```
PDF 文件上传
  → Resume Parser 解析（提取姓名、技能、经历等）
  → 写入 MongoDB resumes collection
  → 生成 Embedding（调用 Embedding API）
  → 写入 Milvus resume_chunks collection
  → 验证：Milvus 中可检索到对应向量
```

### 测试用例设计
1. **正常路径**: 上传标准 PDF → 解析成功 → MongoDB 有记录 → Milvus 有向量
2. **字段完整性**: 验证 MongoDB 中存储的字段与 Parser 输出完全一致
3. **向量维度**: 验证 Milvus 中向量维度与 Embedding 模型一致
4. **ID 关联**: 验证 MongoDB resume_id 与 Milvus 向量 ID 可关联
5. **幂等性**: 同一文件上传两次，验证不产生重复记录（或正确标记为更新）
6. **异常路径**: 损坏的 PDF 文件 → Parser 应返回明确错误，不写入脏数据

### 环境要求
1. 测试在 Docker Compose 容器内运行
2. 使用独立的测试数据库（不污染开发数据）
3. Milvus 使用测试 collection，测试后清理
4. 测试前后使用 `setup` / `teardown` 确保数据隔离

## 验收检查点

### 前置确认
- [ ] T-014 已完成并通过验收
- [ ] T-015 已完成并通过验收
- [ ] Docker Compose 测试环境就绪（MongoDB + Milvus）
- [ ] 测试用 PDF 文件已准备

### 测试通过标准
- [ ] 所有 6 个测试用例通过
- [ ] 正常路径端到端延迟 < 30 秒（含 Embedding 生成）
- [ ] 测试数据在 teardown 后完全清理

### 代码质量
- [ ] 每个测试用例有独立的 `setup` / `teardown`
- [ ] 测试数据使用 factory 或 fixture 生成，不依赖外部状态
- [ ] Mock 外部 Embedding API 调用（或使用本地轻量模型）

### Spec 一致性
- [ ] MongoDB 字段结构与 `02-data-model.md` 一致
- [ ] Milvus collection schema 与 Spec 定义一致

### 通过判定
- [ ] 所有测试用例通过
- [ ] 无脏数据残留
- [ ] 测试可重复运行（幂等）
