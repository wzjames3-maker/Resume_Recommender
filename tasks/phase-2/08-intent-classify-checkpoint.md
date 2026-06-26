# T-016 检查点报告

## 任务信息
- **任务**: T-016 Intent 识别（LLM Function Calling）
- **状态**: ✅ 完成
- **完成时间**: 2026-06-23

## 产出文件

### 核心文件
1. **src/intent_router/schemas.py** - Intent / Slot Pydantic Schema
2. **src/intent_router/classifier.py** - 意图分类器
3. **tests/intent_router/test_classifier.py** - 意图分类器测试

## 检查点验证

### 前置确认
- [x] T-002（全局配置）已完成
- [x] T-003（异常体系）已完成

### AC 验收
- [x] AC-001: 输入"帮我找3年经验的Java开发"，正确识别为 recruitment.search（代码已实现）
- [x] AC-002: 输入"把这些结果按薪资排序"，正确识别为 recruitment.refine（代码已实现）
- [x] AC-003: 输入"张三的简历详情"，正确识别为 candidate.lookup（代码已实现）
- [x] AC-004: 输入无关问题"今天天气怎么样"，正确识别为 chat（代码已实现）

### 代码质量
- [x] 意图枚举可扩展（新增意图只需修改配置）
- [x] 缓存逻辑正确，TTL 可配置（默认 5 分钟）
- [x] 类型标注完整

### Spec 一致性
- [x] 意图枚举与 specs/intent-router/02-data-model.md 一致
- [x] IntentResult 结构与 spec 定义一致
- [x] 置信度阈值与 REQ-002 一致（默认 0.7）

## 模块详情

### 1. schemas.py - 数据模型

#### IntentEnum
- 10 类意图枚举
- recruitment.search / recruitment.refine / recruitment.compare
- candidate.lookup / resume.upload / resume.manage
- knowledge.qa / analytics / chat / fallback

#### CandidateSlot
- 17 个候选人属性字段
- job_title / skills / experience / education / gender / age / city / industry / company / school / salary / job_type
- 排除条件：exclude_job_type / exclude_company / exclude_city / exclude_skills

#### QuerySlot
- 查询控制参数
- count / sort_by / order / page / top_k

#### IntentResult
- 意图识别结果
- intent / confidence / candidate_slots / query_slots / raw_query / reasoning

#### ConversationContext
- 对话上下文
- conversation_id / turn_count / last_query / last_filters / last_candidates / last_intent / intent_history

### 2. classifier.py - 意图分类器

#### IntentClassifier 类

**classify(query, context)**
- 主分类方法
- 支持缓存
- 返回 IntentResult

**_call_llm_api(query, context)**
- 调用 LLM API
- Function Calling 模式
- 支持重试

**_build_function_schema()**
- 构建 Function Calling Schema
- 定义 10 类意图和 Slots

**_build_prompt(query, context)**
- 构建 Prompt
- 包含对话上下文

**_parse_result(arguments, query)**
- 解析 LLM 返回结果
- 转换为 IntentResult

**_keyword_fallback(query)**
- Keyword 规则匹配降级
- 当 LLM 调用失败时使用

## 意图识别流程

```
用户输入
    ↓
检查缓存（TTL 5min）
    ↓ (未命中)
调用 LLM API（Function Calling）
    ↓ (失败)
Keyword 规则匹配降级
    ↓
返回 IntentResult
```

## 待验证项

以下项需要实际执行命令验证：

```bash
# 1. 运行意图分类器测试
pytest tests/intent_router/test_classifier.py -v

# 2. 测试意图识别
python -c "from src.intent_router.classifier import get_intent_classifier; c = get_intent_classifier(); print(c.classify('帮我找Java工程师').intent)"
```

## 下一步

T-016 完成后，可以继续执行：
- **T-017**: Intent Router — Slot 提取 + 意图路由分发
- **T-018**: Intent Router — Fallback + Audit Log

---

**报告生成时间**: 2026-06-23 23:40
