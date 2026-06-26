# T-014: Resume Store CRUD + 脱敏

## 基本信息
- 对应 Spec: specs/resume-store/00-overview.md (REQ 章节) REQ-001~REQ-008
- 对应 AC: AC-001~AC-007
- 依赖: T-007, T-013
- 预计工时: 2 天

## 输入
- `specs/resume-store/00-overview.md (REQ 章节)` — Resume Store 完整需求
- `specs/resume-store/00-overview.md (02-data-model 章节)` — Resume 数据表模型
- `specs/resume-store/00-overview.md (03-api-contract 章节)` — CRUD API 契约
- `src/common/crypto.py` — 加密工具（T-007 产出）
- `src/resume_parser/pii_handler.py` — PII 处理模块（T-013 产出）

## 输出
- `src/resume_store/repository.py` — Resume 数据仓库层
- `src/resume_store/desensitizer.py` — 数据脱敏模块
- `tests/resume_store/test_resume_repository.py` — 仓库层测试
- `tests/resume_store/test_desensitizer.py` — 脱敏模块测试

## 实现要求
1. 实现 Resume CRUD：创建、读取、更新、删除、列表查询（分页 + 筛选）
2. 列表查询支持按 `parse_status`、`upload_time`、`source` 等字段筛选和排序
3. 数据脱敏：`list` 接口返回脱敏数据（手机号中间4位替换为 `****`，邮箱用户名部分掩码）
4. `detail` 接口返回完整数据（需鉴权 + 记录审计日志）
5. 软删除：`delete` 接口标记 `is_deleted=True`，不物理删除
6. 批量操作：支持批量上传和批量删除
7. 使用 Repository 模式隔离数据访问层，支持后续切换数据库
8. 关键设计决策：脱敏在 API 层而非 Repository 层执行，保持 Repository 返回完整数据
9. 禁止事项：禁止列表接口返回完整 PII 数据；禁止硬编码脱敏规则（规则需可配置）

## 验收检查点

### 前置确认
- [ ] T-007（加密工具）已完成
- [ ] T-013（PII 处理）已完成
- [ ] 容器环境已启动
- [ ] 数据库 Migration 已执行

### AC 验收
- [ ] AC-001: 创建 Resume 记录成功，返回包含 `resume_id` 的响应
- [ ] AC-002: 根据 `resume_id` 查询完整简历信息（含解密 PII）
- [ ] AC-003: 更新简历字段成功，`updated_at` 自动更新
- [ ] AC-004: 软删除简历，列表查询不再返回该记录
- [ ] AC-005: 列表查询支持分页、筛选、排序，返回脱敏数据
- [ ] AC-006: 批量上传和批量删除功能正常
- [ ] AC-007: 脱敏规则正确
- [ ] AC-008: find_by_md5(file_md5) 返回已有简历（file_md5 已存在且 status=active）
- [ ] AC-009: find_by_md5(file_md5) 返回 None（file_md5 不存在）
- [ ] AC-010: create_resume 时 file_md5 正确写入 MongoDB：手机号 `138****1234`，邮箱 `z***@example.com`

### 代码质量
- [ ] lint pass（ruff + mypy）
- [ ] Repository 模式清晰，数据访问与业务逻辑分离
- [ ] 脱敏规则可配置
- [ ] API 响应时间 < 500ms（单条查询）
- [ ] 类型标注和 docstring 完整

### Spec 一致性
- [ ] API 接口与 `specs/resume-store/00-overview.md (03-api-contract 章节)` 完全一致
- [ ] 数据模型与 `specs/resume-store/00-overview.md (02-data-model 章节)` 一致
- [ ] 脱敏规则与 REQ-005 一致
- [ ] file_md5 去重逻辑与 resume-store REQ-011 一致
- [ ] file_md5 UNIQUE sparse 索引与 02-data-model 一致

### 通过判定
全部 ✅ → Done | retry < 3 → 修复 | retry = 3 → BLOCKED
