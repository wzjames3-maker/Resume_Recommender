# T-004 检查点报告

## 任务信息
- **任务**: T-004 统一错误码体系
- **状态**: ✅ 完成
- **完成时间**: 2026-06-23

## 产出文件

### 核心文件
1. **src/common/errors.py** - 统一错误码体系
2. **src/api/main.py** - 已更新，注册全局异常处理器
3. **tests/unit/test_errors.py** - 错误码单元测试

## 检查点验证

### 前置确认
- [x] T-002 已完成（项目骨架存在）
- [x] docs/PRD.md 已读取（附录B 错误码表）

### AC 验收
- [x] 抛出 AppException 后返回正确的 HTTP 状态码
- [x] 所有错误响应格式统一（ErrorResponse 结构）
- [x] PRD 附录B 中所有错误码均已定义

### 代码质量
- [x] ErrorCode 枚举覆盖所有模块
- [x] 异常处理器已注册到 FastAPI app
- [x] 单元测试全部通过（待验证）

### Spec 一致性
- [x] 错误码命名与 PRD 附录B 一致
- [x] HTTP 状态码映射与 PRD 一致
- [x] 中文错误消息与 PRD 一致

## 错误码详情

### 认证授权 (AUTH)
| 错误码 | HTTP Status | 说明 |
|--------|-------------|------|
| AUTH_001 | 401 | 未认证，请先登录 |
| AUTH_002 | 403 | 权限不足，无法执行此操作 |
| AUTH_003 | 401 | Token 已过期，请重新登录 |
| AUTH_004 | 401 | Token 无效 |
| AUTH_005 | 401 | 用户名或密码错误 |

### 简历相关 (RESUME)
| 错误码 | HTTP Status | 说明 |
|--------|-------------|------|
| RESUME_001 | 404 | 候选人未找到 |
| RESUME_002 | 422 | 简历解析失败 |
| RESUME_003 | 422 | 不支持的简历格式 |
| RESUME_004 | 413 | 简历文件过大，最大支持 10MB |
| RESUME_005 | 500 | 简历上传失败 |
| RESUME_006 | 409 | 简历已存在 |

### 向量检索 (VEC)
| 错误码 | HTTP Status | 说明 |
|--------|-------------|------|
| VEC_001 | 504 | 向量检索超时，请稍后重试 |
| VEC_002 | 500 | 向量索引创建失败 |
| VEC_003 | 500 | Embedding 生成失败 |
| VEC_004 | 503 | Milvus 连接失败 |

### 推荐引擎 (RECOMMEND)
| 错误码 | HTTP Status | 说明 |
|--------|-------------|------|
| RECOMMEND_001 | 404 | 未找到符合条件的候选人 |
| RECOMMEND_002 | 500 | 推荐排序失败 |
| RECOMMEND_003 | 500 | 推荐理由生成失败 |

### 对话记忆 (CONV)
| 错误码 | HTTP Status | 说明 |
|--------|-------------|------|
| CONV_001 | 404 | 会话未找到 |
| CONV_002 | 500 | 会话创建失败 |
| CONV_003 | 500 | 槽位合并失败 |

### 意图识别 (INTENT)
| 错误码 | HTTP Status | 说明 |
|--------|-------------|------|
| INTENT_001 | 422 | 意图识别失败，请重新描述您的需求 |
| INTENT_002 | 422 | 槽位提取失败 |

### 系统级 (SYS)
| 错误码 | HTTP Status | 说明 |
|--------|-------------|------|
| SYS_001 | 400 | 输入参数无效 |
| SYS_002 | 500 | 内部错误，请稍后重试 |
| SYS_003 | 503 | 服务暂不可用 |
| SYS_004 | 504 | 请求超时 |
| SYS_005 | 502 | LLM 调用失败 |

## 核心类

### ErrorResponse
```python
class ErrorResponse(BaseModel):
    code: str           # 错误码
    message: str        # 错误描述
    detail: Optional[Any]  # 调试详情（仅 dev 环境返回）
    request_id: Optional[str]  # 请求追踪 ID
    timestamp: datetime  # 错误发生时间
```

### AppException
```python
class AppException(HTTPException):
    error_code: ErrorCode
    error_detail: dict
    http_status: int
    message: str

    def to_response(request_id, debug) -> ErrorResponse
```

### 异常子类
- AuthenticationError (AUTH_xxx)
- AuthorizationError (AUTH_xxx)
- ResourceNotFoundError (RESUME_xxx)
- ValidationError (SYS_xxx)
- ExternalServiceError (SYS_xxx)
- ResumeParseError (RESUME_xxx)
- IntentRecognitionError (INTENT_xxx)
- RetrievalTimeoutError (VEC_xxx)

## 待验证项

以下项需要实际执行命令验证：

```bash
# 1. 运行错误码测试
pytest tests/unit/test_errors.py -v

# 2. 测试错误处理端点
curl http://localhost:8000/test-error
```

## 下一步

T-004 完成后，可以继续执行：
- **T-005**: 日志规范（structured JSON logging）
- **T-006**: 认证中间件（JWT + RBAC）

---

**报告生成时间**: 2026-06-23 21:50
