# T-013: 解析失败降级 + PII 加密

## 基本信息
- 对应 Spec: specs/resume-parser/01-requirements.md REQ-008, specs/resume-parser/04-business-rules.md RULE-004, RULE-007
- 对应 AC: AC-009, AC-010
- 依赖: T-011, T-007
- 预计工时: 1.5 天

## 输入
- `specs/resume-parser/01-requirements.md` — 降级策略需求
- `specs/resume-parser/04-business-rules.md` — 业务规则（RULE-004 PII加密, RULE-007 降级策略）
- `src/resume_parser/llm_extractor.py` — LLM 提取模块（T-011 产出）
- `src/common/crypto.py` — 加密工具（T-007 产出）

## 输出
- `src/resume_parser/fallback_handler.py` — 降级处理模块
- `src/resume_parser/pii_handler.py` — PII 检测与加密模块
- `tests/resume_parser/test_fallback_handler.py` — 降级处理测试
- `tests/resume_parser/test_pii_handler.py` — PII 处理测试

## 实现要求
1. 降级策略三级流水线：完整解析 → 部分解析（仅提取可识别字段）→ 原文存储（标记 `parse_status=partial`）
2. 降级触发条件：LLM 超时 / 返回格式异常 / 关键字段缺失率 > 70%
3. 部分解析结果必须包含 `extraction_warnings` 列表，说明哪些字段提取失败
4. PII 检测：使用正则 + NER 模型识别手机号、身份证号、邮箱、地址等 PII 字段
5. PII 加密：使用 T-007 的加密模块对 PII 字段进行 AES-256 加密，存储时保存 `encrypted_fields` 列表
6. PII 解密：查询时按需解密，支持字段级解密（只解密需要的字段）
7. 审计日志：所有 PII 解密操作记录到 `pii_access_log` 表（who/when/which_fields）
8. 关键设计决策：PII 检测使用"宁可多标不可漏标"策略，误报优于漏报
9. 禁止事项：禁止在日志中打印 PII 明文；禁止将加密密钥与加密数据存储在同一张表

## 验收检查点

### 前置确认
- [ ] T-011（LLM 结构化提取）已完成
- [ ] T-007（加密工具）已完成
- [ ] 容器环境已启动
- [ ] AES-256 加密密钥已配置

### AC 验收
- [ ] AC-009: 解析失败时自动降级，部分解析结果正确返回，`parse_status` 和 `extraction_warnings` 字段完整
- [ ] AC-010: PII 字段（手机号、身份证、邮箱）在存储时加密，查询时按需解密，`pii_access_log` 记录完整

### 代码质量
- [ ] lint pass（ruff + mypy）
- [ ] 加密密钥从 config/env 读取，无硬编码
- [ ] 日志中无 PII 明文泄露
- [ ] PII 正则表达式覆盖中国大陆手机号、身份证号、邮箱格式
- [ ] 类型标注完整

### Spec 一致性
- [ ] 降级触发条件与 REQ-008 一致
- [ ] PII 加密字段列表与 RULE-004 一致
- [ ] 审计日志格式与 RULE-007 一致

### 通过判定
全部 ✅ → Done | retry < 3 → 修复 | retry = 3 → BLOCKED
