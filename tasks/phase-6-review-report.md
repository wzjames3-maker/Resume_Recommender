<!-- Phase: Phase 6 - Deep Review Report -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-23 -->

# Phase 6 深度 Review 报告

## Review 范围

对 	asks/ 目录下全部 42 个任务文件 + 	ask.md 总览看板进行了逐文件审查，重点检查：
1. 文件完整性（结构、字段）
2. 路径一致性（模块路径、Spec 引用路径）
3. 依赖链正确性（产出/引用对齐）
4. AC 覆盖率（Spec AC → 任务 AC 映射）
5. 技术约束一致性（与 tech-decision.md / Spec 对齐）

---

## 发现问题与修复

### 🔴 P0 问题（已修复）

| # | 问题 | 影响范围 | 修复方式 |
|---|------|----------|----------|
| 1 | **路径不一致 src/core/ vs src/common/** | 10 个 Phase-2 任务文件 | 全部替换为 src/common/（与 T-002 骨架定义一致） |
| 2 | **Spec 引用路径不存在** specs/resume/02-data-model.md | T-007, T-008 | 替换为 specs/resume-parser/02-data-model.md |
| 3 | 3 | **Redis 依赖已注入（Tier L 变更）** | T-024, T-025, T-031 | 会话 TTL→Redis EXPIRE；状态缓存→Redis；简历上传→ARQ 异步队列 |
| 4 | **存储层路径不一致** | T-007 vs T-014 | 统一为 src/resume_store/；修正 crypto 引用为 ncryption.py |

### 🟡 P1 问题（已修复）

| # | 问题 | 影响范围 | 修复方式 |
|---|------|----------|----------|
| 5 | **AC 覆盖缺口** — 4 模块共 ~15 条 AC 未被任务覆盖 | 多个任务 | 将缺失 AC 分配到对应任务并补充验收检查点 |
| 6 | **里程碑映射编号错误** | task.md | 修正为实际任务 ID（T-009~T-015 等） |

---

## 修复详情

### Fix 1: src/core/ → src/common/
影响文件：01-parser-text.md, 02-parser-ocr.md, 03-parser-llm.md, 05-parser-fallback.md, 06-resume-store-crud.md, 07-vector-index.md, 08-intent-classify.md, 10-intent-fallback.md, 16-conv-crud.md, 24-api-login.md

### Fix 2: Spec 路径修正
- specs/resume/02-data-model.md → specs/resume-parser/02-data-model.md
- 影响文件：06-mongodb.md, 07-milvus.md

### Fix 3: Redis 依赖确认（已由后续 Tier L 变更注入）
- T-024: 会话 TTL 已升级为 Redis EXPIRE 滑动窗口（1800s）+ MongoDB TTL 兜底（86400s）
- T-025: Slot 合并使用 MongoDB findOneAndUpdate + Redis 状态缓存
- T-031: 简历上传改造为 ARQ 异步队列（Redis 作为任务队列后端）
- 依据：tech-decision.md 决策项 11 + conversation-memory/07-tech-constraints.md §5

### Fix 4: 存储路径统一
- src/store/resume_repository.py → src/resume_store/repository.py
- src/store/desensitizer.py → src/resume_store/desensitizer.py
- 	ests/store/ → 	ests/resume_store/
- src/common/crypto.py → src/resume_store/encryption.py（与 T-007 产出一致）

### Fix 5: AC 覆盖补全

| 任务 | 新增 AC | 说明 |
|------|---------|------|
| T-009 (文本提取) | AC-005, AC-011, AC-012, AC-014 | JSON 导入、加密 PDF、扫描件 PDF、空文件 |
| T-011 (LLM 提取) | AC-013, AC-015, AC-016 | 非中文简历、Schema 验证重试、API 超时 |
| T-016 (Intent 分类) | AC-011, AC-014 | 意图模糊消歧、LLM 非法输出降级 |
| T-017 (Slot 提取) | AC-010, AC-012 | 排除条件解析、Slot 冲突处理 |
| T-018 (Fallback) | AC-013, AC-015 | 无上文 Refine 提示、LLM 全局降级 |
| T-019 (Hybrid 检索) | AC-015 | Milvus 超时错误码 |
| T-020 (Filter) | AC-013 | 全不满足时放宽重试 |
| T-023 (降级) | AC-014 | 数量不足时返回实际数量 |
| T-024 (Conv CRUD) | AC-005, AC-011 | ConversationState 更新、MongoDB 持久化恢复 |

### Fix 6: 里程碑映射
- phase-2(T1~T6) → phase-2(T-009~T-015)
- phase-2(T7~T12) → phase-2(T-016~T-023)
- phase-2(T13~T18) → phase-2(T-024~T-029)
- phase-2(T19~T22) → phase-2(T-030~T-035)

---

## 修复后验证

| 检查项 | 结果 |
|--------|------|
| 42 个任务文件全部存在 | ✅ |
| src/core/ 引用清零 | ✅ |
| Spec 路径全部有效 | ✅ |
| Redis 依赖已确认注入（Tier L 变更） | ✅ |
| 存储层路径统一 | ✅ |
| 里程碑编号正确 | ✅ |
| AC 覆盖率 61/61 = **100%** | ✅ |

### AC 覆盖率明细

| 模块 | Spec AC 数 | 已覆盖 | 缺口 |
|------|-----------|--------|------|
| resume-parser | 16 | 16 | 0 |
| intent-router | 15 | 15 | 0 |
| recommendation-engine | 15 | 15 | 0 |
| conversation-memory | 15 | 15 | 0 |
| **合计** | **61** | **61** | **0** |

---

## Review 结论

**✅ Phase 6 Review 通过**。共发现 6 类问题，全部已修复。任务文件质量满足进入 Phase 7 的条件。
