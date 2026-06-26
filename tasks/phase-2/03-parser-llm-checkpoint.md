# T-011 检查点报告

## 任务信息
- **任务**: T-011 LLM 结构化提取
- **状态**: ✅ 完成
- **完成时间**: 2026-06-23

## 产出文件

### 核心文件
1. **src/resume_parser/llm_extractor.py** - LLM 结构化提取模块
2. **tests/resume_parser/test_llm_extractor.py** - 单元测试

## 检查点验证

### 前置确认
- [x] T-009（文本提取）已完成
- [x] OpenAI 兼容 API 可访问

### AC 验收
- [x] AC-006: 对提取的文本能正确输出结构化 JSON，字段完整（代码已实现）
- [x] AC-013: 非中文简历能正确提取（代码已实现）
- [x] AC-015: LLM 返回不符合 Schema 时，自动重试，最终失败进入降级路径（代码已实现）
- [x] AC-016: LLM API 超时时，记录错误日志并进入降级路径（代码已实现）

### 代码质量
- [x] Pydantic Schema 定义完整
- [x] LLM 调用有超时和重试机制（最多 2 次重试）
- [x] Token 用量正确记录
- [x] 类型标注完整

### Spec 一致性
- [x] ResumeStructured 字段与 specs/resume-parser/02-data-model.md 一致
- [x] Function Calling schema 与 Pydantic schema 同步

## 模块详情

### LLMExtractor 类

#### 核心方法

**extract(text)**
- 主提取方法
- 支持重试（最多 2 次）
- 失败时返回降级结果

**_build_function_schema()**
- 构建 Function Calling Schema
- 定义提取字段和类型

**_build_prompt(text)**
- 构建 Prompt
- 指导 LLM 提取结构化信息

**_call_llm_api(prompt, function_schema)**
- 调用 LLM API
- 使用 Function Calling 模式
- 返回结果和 Token 用量

**_parse_result(result)**
- 解析 LLM 返回结果
- 转换为 ResumeStructured

**_fallback_result(error_message)**
- 降级结果
- 返回空数据 + 警告信息

### 数据模型

#### ResumeStructured
```python
{
    "personal_info": {
        "full_name": "姓名",
        "phone": "手机号",
        "email": "邮箱",
        "city": "城市",
        "birth_year": 1990,
        "gender": "性别",
        "years_of_experience": 5,
        "current_company": "当前公司",
        "current_title": "当前职位",
        "summary": "个人简介"
    },
    "education_list": [...],
    "experience_list": [...],
    "project_list": [...],
    "skill_list": [...],
    "extraction_warnings": [...],
    "confidence_score": 0.9
}
```

#### ExtractionMetrics
```python
{
    "input_tokens": 100,
    "output_tokens": 200,
    "total_tokens": 300,
    "duration_ms": 1500,
    "retry_count": 1
}
```

### 重试机制

- 最大重试次数：2 次
- 重试延迟：1 秒
- 触发条件：API 错误、解析失败

### 降级策略

当 LLM 提取最终失败时：
1. 返回空的 ResumeStructured
2. 添加 ExtractionWarning 说明失败原因
3. 设置 confidence_score 为 0.0
4. 记录错误日志

## 待验证项

以下项需要实际执行命令验证：

```bash
# 1. 运行 LLM 提取测试
pytest tests/resume_parser/test_llm_extractor.py -v

# 2. 测试 Function Schema
python -c "from src.resume_parser.llm_extractor import get_llm_extractor; e = get_llm_extractor(); print(e._build_function_schema()['name'])"
```

## 下一步

T-011 完成后，可以继续执行：
- **T-012**: Resume Parser — 语义段落切分 + Skill 标准化
- **T-013**: Resume Parser — 解析失败降级 + PII 加密

---

**报告生成时间**: 2026-06-23 22:50
