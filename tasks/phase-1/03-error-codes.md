# T-004: 统一错误码体系

## 基本信息
- 对应 Spec: PRD 附录B（错误码定义）
- 对应 AC: 无（基础设施）
- 依赖: T-002
- 预计工时: 0.5 天

## 输入
- docs/PRD.md（附录B 错误码表）
- src/common/ 包结构（来自 T-002）
- src/api/ FastAPI 应用入口（来自 T-002）

## 输出
- src/common/errors.py
- tests/unit/test_errors.py

## 实现要求
1. 创建 `src/common/errors.py`，定义错误码体系：
   - `ErrorCode` 枚举类，对齐 PRD 附录B 所有错误码
   - 错误码格式：`模块前缀_数字`（如 `AUTH_001`, `RESUME_001`, `VEC_001`）
   - 模块前缀：AUTH, RESUME, VEC, RECOMMEND, CONV, SYS
   - 每个错误码包含：code, message（中文）, http_status
2. 定义 `ErrorResponse` Pydantic Model：
   - `code: str` — 错误码
   - `message: str` — 错误描述
   - `detail: Optional[Any]` — 调试详情（仅 dev 环境返回）
   - `request_id: Optional[str]` — 请求追踪 ID
   - `timestamp: datetime`
3. 定义自定义异常基类 `AppException`：
   - 继承 `Exception`
   - 包含 `ErrorCode` 和可选 `detail`
   - 提供 `to_response()` 方法
4. 定义具体异常子类：
   - `AuthenticationError` (AUTH_xxx)
   - `AuthorizationError` (AUTH_xxx)
   - `ResourceNotFoundError` (RESUME_xxx / SYS_xxx)
   - `ValidationError` (SYS_xxx)
   - `ExternalServiceError` (VEC_xxx / SYS_xxx)
5. 注册 FastAPI 全局异常处理器：
   - `AppException` → 对应 HTTP 状态码 + ErrorResponse
   - `RequestValidationError` → 400 + 统一格式
   - 通用 `Exception` → 500 + 统一格式
6. 编写单元测试：
   - 每个异常子类能正确转换为 ErrorResponse
   - HTTP 状态码正确映射
   - detail 仅在 dev 模式下返回

## 验收检查点

### 前置确认
- [ ] T-002 已完成（项目骨架存在）
- [ ] docs/PRD.md 已读取（附录B 错误码表）

### AC 验收
- [ ] 抛出 AppException 后返回正确的 HTTP 状态码
- [ ] 所有错误响应格式统一（ErrorResponse 结构）
- [ ] PRD 附录B 中所有错误码均已定义

### 代码质量
- [ ] ErrorCode 枚举覆盖所有模块
- [ ] 异常处理器已注册到 FastAPI app
- [ ] 单元测试全部通过

### Spec 一致性
- [ ] 错误码命名与 PRD 附录B 一致
- [ ] HTTP 状态码映射与 PRD 一致
- [ ] 中文错误消息与 PRD 一致

### 通过判定
全部 ✅ → Done | 任一 ❌ 且 retry < 3 → 修复 | retry = 3 → BLOCKED
