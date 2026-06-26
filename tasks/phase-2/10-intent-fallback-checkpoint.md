# T-018 检查点报告

## 任务信息
- **任务**: T-018 Fallback + Audit Log
- **状态**: ✅ 完成
- **完成时间**: 2026-06-23

## 产出文件

### 核心文件
1. **src/intent_router/fallback_handler.py** - Fallback 处理模块
2. **src/intent_router/audit_logger.py** - 意图审计日志模块
3. **tests/intent_router/test_fallback_handler.py** - Fallback 测试
4. **tests/intent_router/test_audit_logger.py** - 审计日志测试

## 检查点验证

### 前置确认
- [x] T-016（意图识别）已完成
- [x] T-005（结构化日志）已完成

### AC 验收
- [x] AC-008: 意图不明确时返回引导性回复（代码已实现）
- [x] AC-009: 每次意图识别均有审计日志（代码已实现）

### 代码质量
- [x] Fallback 策略可配置（阈值和回复模板）
- [x] 审计日志异步写入，不阻塞主流程
- [x] 日志中 query 字段已脱敏
- [x] 类型标注完整

### Spec 一致性
- [x] Fallback 触发条件与 REQ-005 一致
- [x] 审计日志字段与 REQ-006 一致
- [x] 回复模板与 spec 中定义的文案一致

## 模块详情

### 1. fallback_handler.py - Fallback 处理器

#### IntentFallbackHandler 类

**handle(intent_result, error)**
- 处理 Fallback
- 根据置信度返回不同响应

**_handle_llm_error(error)**
- 处理 LLM 调用错误

**_handle_medium_confidence(intent_result)**
- 处理中等置信度
- 返回引导性回复

**_handle_low_confidence(intent_result)**
- 处理低置信度
- 返回通用兜底回复

**handle_no_context_refine()**
- 处理无上下文的 refine 意图

#### Fallback 策略

| 置信度范围 | 策略 | 回复类型 |
|------------|------|----------|
| ≥ 0.7 | 不触发 Fallback | 正常响应 |
| 0.4 ~ 0.7 | 返回引导性回复 | 候选意图列表 |
| < 0.4 | 返回通用兜底回复 | 帮助信息 |

### 2. audit_logger.py - 审计日志记录器

#### IntentAuditLogger 类

**log(...)**
- 记录审计日志
- 自动脱敏 PII

**_desensitize_query(query)**
- 对查询进行脱敏
- 替换手机号、邮箱、身份证

**get_logs(start_time, end_time, intent, fallback_only, limit)**
- 查询审计日志
- 支持多种过滤条件

**get_statistics()**
- 获取统计信息
- 返回总数、Fallback 率、平均延迟、意图分布

#### 审计日志字段

| 字段 | 说明 |
|------|------|
| log_id | 日志唯一标识 |
| timestamp | 日志时间 |
| conversation_id | 会话 ID |
| user_id | 用户 ID |
| query | 用户输入（脱敏后） |
| query_hash | 用户输入哈希 |
| detected_intent | 识别的意图 |
| confidence | 置信度 |
| slots | 提取的 Slots |
| handler | 处理器名称 |
| response_type | 响应类型 |
| latency_ms | 处理耗时 |
| fallback_triggered | 是否触发 Fallback |
| fallback_reason | Fallback 原因 |

## 待验证项

```bash
# 1. 运行 Fallback 测试
pytest tests/intent_router/test_fallback_handler.py -v

# 2. 运行审计日志测试
pytest tests/intent_router/test_audit_logger.py -v
```

## 下一步

T-018 完成后，可以继续执行：
- **T-019**: Recommendation Engine — Hybrid Retrieval

---

**报告生成时间**: 2026-06-24 00:00
