# C 阶段实施计划：简历语义索引（入库打通 + 检索增强）

> 日期：2026-08-15
> 状态：执行中——阶段 1/2 已完成 + 数据集 30 份压力测试（2026-08-15，见 HANDOFF §5.3），阶段 3 待执行
> 依据：../specs/2026-08-15-end-to-end-pipeline-combined-design.md（权威设计）；本文档为实施顺序与验收的唯一来源
> 输入约束：PRD 锁定 docx/txt（无 OCR/表格/图片）；外部模型：SenseNova 6.8-flash-lite（LLM）、SiliconFlow bge-large-zh-v1.5（Embedding）+ bge-reranker-v2-m3（Rerank）

---

## 阶段 1：切片器与评测（先立标杆，后接通路）【已完成 2026-08-15】

| 任务 | 内容 | 验收 |
|---|---|---|
| 1.1 | `sanitize_resume_text()` 清洗函数（hr/services 或 common） | 单测：空字节/换行/空格/空行/过短异常 |
| 1.2 | ResumeSplitter：LLM 行号边界标注（prompt + JSON 协议）+ L2 校验层（越界/重叠/拼接==原文 + 重试 1 次）+ L3 规则降级 + PII 正则过滤 | 离线单测（stub 模型）全绿；真实模型冒烟 10 份 |
| 1.3 | docx 格式变体评测集（样式标题/无标题/软换行/空段/超长单行/中英混排 × 数据集内容）+ 分号流压力样本 | 边界 F1、保真度 100%、PII 检出率 100% 报告落盘。**已完成分号流压力测试（2026-08-15）**：数据集 192080 抽取 30 份 OCR 分号流，30/30 成功、29/30 LLM 路径、30/30 内容无改写、PII 26/30 掩码；并修复两处生产问题（SenseNova reasoning 流、分号流转行，提交 af4c52a）。docx 变体集并入阶段 3 检索评测 |
| 1.4 | （可选）zChunk 式置信度：LLM 输出含 confidence，低置信走人工复核队列 | 设计评审后决定 |

**出口标准**：评测报告通过（边界 F1 ≥ 0.9、保真度 100%、PII 零泄漏）→ 进入阶段 2。

## 阶段 2：打通入库链路【已完成 2026-08-15】

| 任务 | 内容 | 验收 |
|---|---|---|
| 2.1 | 简历知识库：每个 workspace 内部 Knowledge 行（embedding_model_id=bge），按需延迟创建 | 服务函数 + 单测 |
| 2.2 | `parse_resume_task` 扩展：解析成功后 → 清洗 → 切片 → DocumentSerializers.Create → `embedding_by_document.delay` | 端到端冒烟（真实模型，10~30 份） |
| 2.3 | `ResumeFile.document_id` 新字段（迁移）+ 状态扩展（索引状态入 meta） | 迁移 + 单测 |
| 2.4 | 生命周期同步：候选人删除/合并 → 删 Document+Embedding；归档 → is_active=False；恢复 → 重向量化 | 单测全绿 |
| 2.5 | 失败可观测：error_message 记录、refresh 重试入口 | 单测 |

**出口标准**：上传→索引→检索全链路通（真实模型），生命周期同步单测全绿。

## 阶段 3：检索增强

| 任务 | 内容 | 验收 |
|---|---|---|
| 3.1 | Rerank 接入检索管线：BlendSearch 召回 top10 → bge-reranker-v2-m3 精排 top3~5 | 真实模型评测：rerank 后 recall@3 |
| 3.2 | Small-to-Big：段落命中 → document_id 回溯条目/整份简历供 LLM 上下文 | 引用展示含上下文 |
| 3.3 | （可选）blend 融合改 RRF（k=60）/ 画像向量路 A / RAG Fusion 子查询 / LLM title 摘要 | 各按评测收益决策 |

**出口标准**：PRD §9.2 C 阶段完成定义——语义索引与候选人生命周期同步 + 试点标注集 Top-K 相关性优于结构化检索基线（量化对比报告落盘）。

## 里程碑与模型调用预算

| 阶段 | LLM 调用 | Embedding 调用 | 说明 |
|---|---|---|---|
| 1 | ~20 次 | ~100 次 | 评测集（10~20 变体 × 5~7 段） |
| 2 | ~30 次 | ~300 次 | 端到端冒烟 30 份 |
| 1/2 实测 | ~65 次 | 0 次 | 分号流 30 份压力测试（LLM 32 次 + 诊断/对照实验 ~30 次；本次按需求不向量化，embedding 0 次） |
| 3 | ~10 次 | ~100 次 | 检索评测（查询×候选） |
| 合计 | ~125 次 | ~500 次 | 远低于配额（SenseNova 3000 / SiliconFlow 3000） |

> 关联：../../../HANDOFF.md §5.3（状态跟踪）；综合方案 §6（切片协议）
