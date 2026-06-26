# T-005: 日志规范

## 基本信息
- 对应 Spec: tech-decision.md 决策项（日志方案）
- 对应 AC: 无（基础设施）
- 依赖: T-002
- 预计工时: 0.5 天

## 输入
- docs/tech-decision.md
- docs/PRD.md（审计日志需求）
- src/common/ 包结构（来自 T-002）

## 输出
- src/common/logger.py
- src/common/middleware/audit_log.py
- tests/unit/test_logger.py

## 实现要求
1. 创建 `src/common/logger.py`：
   - 使用 `python-json-logger` 实现结构化 JSON 日志
   - 统一日志字段：timestamp, level, message, module, request_id, user_id
   - 日志级别通过配置控制（DEBUG / INFO / WARNING / ERROR / CRITICAL）
   - 提供 `get_logger(name: str)` 工厂函数
   - 日志输出到 stdout（容器化场景下由 Docker 收集）
2. 创建 `src/common/middleware/audit_log.py`：
   - Audit Log FastAPI 中间件基础框架
   - 记录：请求方法、路径、状态码、耗时、用户ID、请求ID
   - 请求ID 自动生成（UUID4），通过 `X-Request-ID` header 传递
   - 敏感路径（如 `/auth/login`）不记录请求体
3. 集成到 FastAPI app：
   - 中间件注册
   - 请求ID 注入到日志上下文
4. 编写单元测试：
   - 验证 JSON 格式输出
   - 验证 Audit Log 中间件记录请求信息
   - 验证 Request ID 生成与传递

## 验收检查点

### 前置确认
- [ ] T-002 已完成（项目骨架存在）
- [ ] docs/tech-decision.md 已读取
- [ ] docs/PRD.md 已读取（审计日志需求部分）

### AC 验收
- [ ] 日志输出为有效 JSON 格式
- [ ] 每条日志包含 timestamp, level, message 字段
- [ ] HTTP 请求自动记录到审计日志
- [ ] X-Request-ID 在响应头中返回

### 代码质量
- [ ] `get_logger()` 工厂函数可用
- [ ] 敏感路径不记录请求体
- [ ] 单元测试全部通过

### Spec 一致性
- [ ] 日志格式与 tech-decision.md 一致
- [ ] 审计日志字段与 PRD 需求一致
- [ ] 容器内 stdout 输出（不写文件）

### 通过判定
全部 ✅ → Done | 任一 ❌ 且 retry < 3 → 修复 | retry = 3 → BLOCKED
