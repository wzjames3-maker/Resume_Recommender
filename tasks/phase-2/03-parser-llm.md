# T-011: LLM 结构化提取

## 基本信息
- 对应 Spec: specs/resume-parser/01-requirements.md REQ-005
- 对应 AC: AC-006, AC-013, AC-015, AC-016
- 依赖: T-009, T-003
- 预计工时: 2 天

## 输入
- `specs/resume-parser/01-requirements.md` — 结构化提取需求
- `specs/resume-parser/02-data-model.md` — Resume 结构化数据模型
- `src/resume_parser/text_extractor.py` — 文本提取模块（T-009 产出）
- `src/common/exceptions.py` — 自定义异常（T-003 产出）

## 输出
- `src/resume_parser/llm_extractor.py` — LLM 结构化提取模块
- `src/resume_parser/schemas.py` — Pydantic Schema 定义
- `tests/resume_parser/test_llm_extractor.py` — 单元测试

## 实现要求
1. 使用 LLM（OpenAI 兼容接口）对原始简历文本进行结构化信息提取
2. 定义 `ResumeStructured` Pydantic Schema，包含：基本信息（姓名、电话、邮箱、地址）、教育经历、工作经历、项目经历、技能列表、证书列表
3. 使用 Function Calling / Structured Output 模式强制 LLM 返回符合 Schema 的 JSON
4. 实现 `LLMExtractor` 类，暴露 `extract(text: str) -> ResumeStructured` 方法
5. LLM 提取失败时，返回部分提取结果 + `extraction_warnings: list[str]`，不抛异常
6. 支持通过 prompt 模板可配置化，prompt 模板存放在 `src/resume_parser/prompts/` 目录
7. Token 用量监控：记录每次提取的 input/output tokens，写入 `extraction_metrics` 表
8. 关键设计决策：使用 Function Calling 而非正则，因为简历格式多样，LLM 的泛化能力更强
9. 禁止事项：禁止在 prompt 中硬编码示例简历；禁止忽略 LLM 返回的 confidence score

## 验收检查点

### 前置确认
- [ ] T-009（文本提取）已完成
- [ ] T-003（异常体系）已完成
- [ ] 容器环境已启动
- [ ] OpenAI 兼容 API 可访问

### AC 验收
- [ ] AC-006: 对提取的文本能正确输出结构化 JSON，字段完整（姓名、电话、邮箱、教育经历、工作经历、技能列表均非空），返回符合 ResumeStructured Schema

### 代码质量
- [ ] lint pass（ruff + mypy）
- [ ] Pydantic Schema 定义完整，有 Field 描述和校验规则
- [ ] LLM 调用有超时和重试机制
- [ ] Token 用量正确记录
- [ ] Prompt 模板外置，无硬编码


- [ ] AC-013: 非中文简历（英文/中英混合）能正确提取，字段名统一为中文 Schema
- [ ] AC-015: LLM 返回的 JSON 不符合 Schema 时，自动重试（最多 2 次），最终失败则进入降级路径
- [ ] AC-016: LLM API 超时（>30s）时，记录错误日志并进入降级路径，不阻塞整体流程

### Spec 一致性
- [ ] `ResumeStructured` 字段与 `specs/resume-parser/02-data-model.md` 完全一致
- [ ] Function Calling schema 与 Pydantic schema 同步

### 通过判定
全部 ✅ → Done | retry < 3 → 修复 | retry = 3 → BLOCKED
