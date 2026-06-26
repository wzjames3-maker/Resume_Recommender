# 迭代任务看板：iter/m-data-pipeline

## 基本信息
- **迭代类型**: Tier M（模块增强）
- **分支**: `iter/m-data-pipeline`
- **触发**: CodeGraph 全项目 Review（2026-06-26）
- **Spec 基线**: v1.2-data-pipeline（基于现有 specs/ 目录）
- **预计工时**: 3 天
- **串行门控**: 一次只执行一个任务，过检查点才进下一个；同一任务修复 ≤3 次

## 背景

CodeGraph Review 发现 6 个 P0/P1 问题和 10+ 个 P2 问题，涉及四大模块：
1. **数据加载链路断裂**：API 上传后不触发分段→分块→向量化，向量索引永远为空
2. **Intent Router 空壳**：Handler 体系无人调用，chat.py 硬编码 if/elif
3. **上下文管理形同虚设**：Session TTL 不生效、last_intent 不持久化、refine NARROW 是 TODO
4. **Small→Big 聚合是假的**：_aggregate_with_parent 不查询 parent chunk

## 变更范围（Spec 层）

| 模块 | 变更类型 | 影响文件 |
|------|----------|----------|
| resume-parser | 新增需求: upload 后触发索引链路 | 01-requirements, 03-api-contract, 04-business-rules |
| vector-index | 修复: full_pipeline 方法名 | 03-api-contract |
| intent-router | 简化: 移除死代码, 修 regex, 对齐实际实现 | 00-overview, 01-requirements, 03-api-contract |
| conversation-memory | 新增需求: TTL 检查, last_intent 持久化, refine NARROW 实现 | 01-requirements, 04-business-rules |
| recommendation-engine | 修复: Small→Big 聚合, 去重逻辑 | 01-requirements, 04-business-rules |

## 任务列表

| # | 任务 | 对应 Spec | 优先级 | 依赖 | 状态 |
|---|------|-----------|--------|------|------|
| PIP-T01 | Upload 接入分段→分块→向量化链路 | RES-PARSER REQ-012, VEC REQ-002 | P0 | 无 | ⬜ pending |
| PIP-T02 | 修复 full_pipeline.py 方法名 + 清理离线脚本 | VEC REQ-002 | P0 | PIP-T01 | ⬜ pending |
| PIP-T03 | 修复 llm_extractor.py regex: s*→\s* | RES-PARSER REQ-003 | P0 | 无 | ⬜ pending |
| PIP-T04 | Upload 传递 project_list + 使用 fallback_result.structured | RES-PARSER REQ-003/005 | P1 | PIP-T03 | ⬜ pending |
| PIP-T05 | Session TTL 检查 + last_intent 持久化 | CONV REQ-008, CONV RULE-003 | P1 | 无 | ⬜ pending |
| PIP-T06 | 实现 refine NARROW 分支（在 last_candidates 内过滤） | CONV REQ-009, CONV RULE-006 | P1 | PIP-T05 | ⬜ pending |
| PIP-T07 | Small→Big 聚合: 切换为 retrieve_with_parent + 修去重 | REC REQ-010, REC RULE-007/008 | P0 | PIP-T01 | ⬜ pending |
| PIP-T08 | 清理 IntentRouter 死代码 + chat.py 显式路由 | INTENT REQ-007 | P1 | 无 | ⬜ pending |
| PIP-T09 | 代码卫生: import re 位置/remove_header_footer/去重键/classifier.py.orig | 跨模块 | P2 | 无 | ⬜ pending |
| PIP-T10 | 集成验收 + spec 基线冻结 | 全模块 06-acceptance | P0 | PIP-T01~T09 | ⬜ pending |

## 状态图例
- ⬜ pending — 未开始
- 🔄 in_progress — 执行中
- ✅ done — 检查点通过
- ⛔ blocked — 修复超限，需人介入

## 通过判定
每个任务附检查点（checkpoint）。全部 ✅ → Done | 任一 ❌ 且 retry<3 → 修复 | retry=3 → BLOCKED
