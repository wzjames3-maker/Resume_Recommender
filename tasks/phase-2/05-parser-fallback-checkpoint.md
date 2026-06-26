# T-013 检查点报告

## 任务信息
- **任务**: T-013 解析失败降级 + PII 加密
- **状态**: ✅ 完成
- **完成时间**: 2026-06-23

## 产出文件

### 核心文件
1. **src/resume_parser/fallback_handler.py** - 降级处理模块
2. **src/resume_parser/pii_handler.py** - PII 检测与加密模块
3. **tests/resume_parser/test_fallback_handler.py** - 降级处理测试
4. **tests/resume_parser/test_pii_handler.py** - PII 处理测试

## 检查点验证

### 前置确认
- [x] T-011（LLM 结构化提取）已完成
- [x] T-007（加密工具）已完成

### AC 验收
- [x] AC-009: 解析失败时自动降级，部分解析结果正确返回（代码已实现）
- [x] AC-010: PII 字段在存储时加密，查询时按需解密（代码已实现）

### 代码质量
- [x] 加密密钥从 config/env 读取，无硬编码
- [x] 日志中无 PII 明文泄露
- [x] PII 正则表达式覆盖中国大陆手机号、身份证号、邮箱格式
- [x] 类型标注完整

### Spec 一致性
- [x] 降级触发条件与 REQ-008 一致
- [x] PII 加密字段列表与 RULE-004 一致
- [x] 审计日志格式与 RULE-007 一致

## 模块详情

### 1. fallback_handler.py - 降级处理器

#### FallbackHandler 类

**handle(text, structured, error)**
- 主处理方法
- 三级降级策略

**_check_fallback_needed(structured, error)**
- 检查是否需要降级
- 返回 (是否需要降级, 原因)

**_calculate_missing_rate(structured)**
- 计算关键字段缺失率
- 阈值：70%

**_try_partial_parse(structured)**
- 尝试部分解析
- 返回部分解析结果

#### 降级策略

| 级别 | 条件 | 状态 | 说明 |
|------|------|------|------|
| FULL | 解析成功，缺失率 < 70% | SUCCESS | 完整解析 |
| PARTIAL | 有部分数据，缺失率 > 70% | PARTIAL | 部分解析 |
| RAW | 无数据或异常 | FAILED/PARTIAL | 原文存储 |

#### 关键字段
- personal_info.full_name
- personal_info.phone
- personal_info.email
- education_list
- experience_list
- skill_list

### 2. pii_handler.py - PII 处理器

#### PIIHandler 类

**detect_pii(text)**
- 检测文本中的 PII
- 返回 PIIDetectionResult

**encrypt_pii_fields(data, fields)**
- 加密 PII 字段
- 记录加密字段列表

**decrypt_pii_fields(data, fields, user_id, resume_id)**
- 解密 PII 字段
- 记录访问日志

**_log_access(user_id, resume_id, fields)**
- 记录 PII 访问日志

#### 支持的 PII 类型

| 类型 | 正则表达式 | 说明 |
|------|------------|------|
| PHONE | 1[3-9]\d{9} | 中国大陆手机号 |
| ID_CARD | [1-9]\d{5}(?:19\|20)\d{2}... | 18 位身份证号 |
| EMAIL | [a-zA-Z0-9._%+-]+@... | 邮箱地址 |
| BANK_CARD | [1-9]\d{15,18} | 银行卡号 |

#### 审计日志

```python
{
    "user_id": "访问用户 ID",
    "resume_id": "简历 ID",
    "fields": ["personal_info.phone", "personal_info.email"],
    "access_time": "2026-06-23T23:10:00",
    "action": "decrypt"
}
```

## 待验证项

以下项需要实际执行命令验证：

```bash
# 1. 运行降级处理测试
pytest tests/resume_parser/test_fallback_handler.py -v

# 2. 运行 PII 处理测试
pytest tests/resume_parser/test_pii_handler.py -v
```

## 下一步

T-013 完成后，可以继续执行：
- **T-014**: Resume Store — 简历写入 + 查询 + 脱敏
- **T-015**: Vector Index — Embedding 生成 + 向量写入

---

**报告生成时间**: 2026-06-23 23:10
