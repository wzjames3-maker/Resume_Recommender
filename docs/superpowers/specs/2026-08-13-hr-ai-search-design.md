# HR 五期规格：AI 自然语言搜人 + 职位技能抽取

日期：2026-08-13
状态：已批准

## 背景

HR 模块已具备候选人组合搜索（技能/城市/年限/学历/状态）与职位技能要求字段，但搜索入口是结构化表单，技能抽取依赖人工填写。本期间 HR 引入 LLM 能力（复用内核 OpenAI 兼容模型），提供：

1. 自然语言搜人：用户输入自然语言，LLM 解析为结构化搜索条件，前端确认后复用现有组合搜索执行。
2. 职位技能抽取：从职位描述自动抽取技能列表，填充技能要求。

**范围外**：Embedding 语义检索（保留后续期）、异步任务（六期）、简历下载与候选人合并（七期）。

## 1. 配置

### 1.1 模型 `HrConfig`

- 新模型 `apps/hr/models/recruitment.py` 中 `HrConfig`：
  - `workspace_id`：varchar(64)，`unique=True`
  - `llm_model_id`：varchar(128)
  - `create_time` / `update_time`（对齐现有模型风格）
- 迁移 `0006_hrconfig.py`。
- `apps/hr/models/__init__.py` 导出。
- 语义：一个工作区一条配置；未配置 = 未启用 AI 能力。

### 1.2 模型获取与错误处理

- 配置保存与模型实例化均先调 `models_provider.tools.get_model_by_id(model_id, workspace_id)`（该函数兼容共享给工作区的授权模型，禁止直接 `Model.objects.filter()`），再校验 `model.model_type == 'LLM'`（防止误选 embedding 等）；模型不存在或非 LLM → 400。
- 服务层经 `get_model_instance_by_model_workspace_id(config.llm_model_id, workspace_id)` 获取 LLM 实例。
- 未配置（无 `HrConfig` 行）或获取失败 → `AppApiException(400, "请先在 AI 设置中选择模型")`。

## 2. AI 服务（新增 `apps/hr/services/ai_parser.py`）

纯规则实现 + 依赖注入：服务函数接收 `model` 实例参数，不直接读配置，便于单测传 stub。

### 2.0 LLM 调用契约

- 唯一调用方式：`response = model.invoke(prompt)`，仅接受 `response.content` 为字符串的结果。
- 空内容、非字符串内容、`invoke` 抛异常、JSON 解析异常 → 统一 `AppApiException(400, "AI 解析失败，请重试或手动填写筛选条件")`。
- 测试 stub 只提供 `invoke()`，返回带 `content` 属性的对象。

### 2.1 `parse_search_conditions(model, query)`

- Prompt 指令：将自然语言需求转为 JSON，字段与三期组合搜索参数对齐：
  ```json
  {
    "skills": ["Python", "Kafka"],
    "city": "上海",
    "years_min": 3,
    "years_max": null,
    "highest_degree": "本科",
    "status": "ACTIVE"
  }
  ```
- 规则约束：只输出 JSON；无法判断的字段给 null/[]；技能逐项抽取、不得合并成复合词；年限归一为整数年。
- Prompt 用明确分隔符（如 `<query>` 标签）包裹用户输入，并声明其中内容仅作为待解析文本、不得执行其中任何指令（防注入）。
- 后处理（幂等修正）：`skills` 非列表 → `[]`；`city`/`highest_degree`/`status` 非字符串 → null；`years_min`/`years_max` 非正整数 → null；`years_min > years_max` → 交换。
- 返回 `{conditions: {...}}`。

### 2.2 `extract_skills(model, description)`

- Prompt 指令：从职位描述抽取技能（技术栈、工具、软技能中的硬性技能），输出 `{"skills": ["Python", ...]}`；数量上限 20。
- 同样用分隔符包裹输入并声明不得执行输入中的指令。
- 后处理：非列表 → `[]`；逐项 strip、去空、去重；超 20 项截断为前 20。
- 返回 `{skills: [...]}`。

## 3. API（新增 `apps/hr/views/ai.py`，注册 `views/__init__.py` 与 `hr/urls.py`）

| 方法 | 路径 | 权限 | 行为 |
|---|---|---|---|
| GET | `/workspace/{wid}/hr/ai/config` | `@manage_required` | 返回 `{llm_model_id: string \| null}` |
| PUT | `/workspace/{wid}/hr/ai/config` | `@manage_required` | body `{llm_model_id}`；按 1.2 校验；upsert 配置；返回同上 |
| POST | `/workspace/{wid}/hr/ai/search-parse` | `@member_required` | body `{query}`（非空，≤2000 字符）；校验配置；调 `parse_search_conditions`；返回 `{conditions}` |
| POST | `/workspace/{wid}/hr/ai/extract-skills` | `@manage_required` | body `{description}`（非空，≤4096 字符）；校验配置；调 `extract_skills`；返回 `{skills}` |

- 所有视图 `authentication_classes = [TokenAuth]`；权限由 `hr/views/recruitment.py` 中同款 `@member_required` / `@manage_required` 装饰器执行。
- 错误：缺 query/description → 400「query is required」/「description is required」；超长 → 400「query is too long」/「description is too long」；未配置 → 400「请先在 AI 设置中选择模型」。

## 4. 前端

### 4.1 AI 设置入口

- 候选页与职位页共用：页面工具区新增「AI 设置」按钮 → dialog：
  - 展示当前配置（`getConfig`）。
  - 模型下拉：`getSelectModelList({model_type: 'LLM'})`（现有 `ui/src/api/model/model.ts`）。
  - 保存：`putConfig({llm_model_id})`，成功提示。
- 未配置时显示「未设置」与引导文案。

### 4.2 候选页 AI 搜索

- 搜索区新增「AI 搜索」入口（输入框 + 按钮）：
  - 输入自然语言 → `POST ai/search-parse` → 成功后将返回条件**回填到现有筛选表单并立即执行搜索**；用户可再修改结构化条件后重新搜索。
  - 未配置 / 解析失败 → 展示错误提示，不清空表单。

### 4.3 职位页 AI 技能抽取

- 编辑职位对话框「职位描述」旁新增「AI 抽取技能」按钮（新建与编辑均可用）：
  - 基于当前表单 `description`（非空校验）→ `POST ai/extract-skills`，body `{description}` → 回填「技能要求」输入。
  - 失败提示不破坏表单。

### 4.4 类型与 API 封装

- `ui/src/api/type/hr.ts`：`HrConfig`、`AiConditions` 类型。
- `ui/src/api/hr/recruitment.ts`：`getAiConfig` / `putAiConfig` / `parseSearch` / `extractSkills`。
- `ui/src/views/hr/candidates/index.vue`、`ui/src/views/hr/jobs/index.vue` 改动。
- AI 设置对话框可抽小组件 `ui/src/views/hr/components/AiSettingDialog.vue`（两页复用）。

## 5. 测试（TDD）

### 5.1 服务层（`apps/hr/tests.py` 新增 `AiParserTests`）

- `parse_search_conditions`：
  - 合法 JSON 全字段 → 原样返回。
  - 缺字段 → 默认值（skills `[]`，其余 null）。
  - 非 JSON 文本 → 400。
  - 年限倒挂（min>max）→ 交换；非正整数字符串 → null。
  - 技能列表含空串/重复 → 清洗去重。
- `extract_skills`：
  - 合法列表 → 清洗返回。
  - 非列表 → `[]`。
  - 超过 20 项 → 截断为前 20。
- 配置未设时模型获取失败 → 400（API 层覆盖）。
- stub 方式：`MockModel` 仅提供 `invoke()`，返回 `content` 为预设字符串的对象；另测 `invoke` 抛异常 → 400。

### 5.2 API 层（`AiApiTests`）

- 配置：GET 默认 null；PUT 保存 LLM 模型（含共享授权模型，经 `get_model_by_id`）；PUT 非 LLM 类型 → 400；PUT 不存在的模型 → 400。
- search-parse：无 query → 400；超长 query → 400；未配置 → 400；已配置（mock 模型返回预设 JSON）→ 200 且条件正确。
- extract-skills：无 description → 400；超长 description → 400；未配置 → 400；正常 → 200。
- mock 方式：`unittest.mock.patch` 替换 `get_model_by_id`/`get_model_instance_by_model_workspace_id`，返回 stub 实例。

### 5.3 回归与构建

- `manage.py test hr.tests application.tests knowledge.tests models_provider.tests --keepdb`：原 47 项 + 新增全过。
- `manage.py check`、`makemigrations --check --dry-run`。
- 前端：`vue-tsc --build`、双 `vite build`、裁剪端点产物扫描（新增端点白名单确认）。

## 6. 验收标准

- 配置读写闭环：设置 LLM 模型后 GET 返回一致；未配置时 AI 端点统一 400 提示。
- 自然语言搜人：LLM 输出条件可回填筛选表单并执行组合搜索，用户可编辑。
- 职位技能抽取：结果回填技能要求输入框，随表单保存。
- 全部自动化测试通过，前端可构建。

## 7. 提交

- 规格：`docs(人事): 制定 AI 搜索与技能抽取规格`
- 计划：`docs(人事): 制定 AI 搜索与技能抽取实现计划`
- 模型+服务+API+测试：`feat(人事): 提供 AI 搜索解析与技能抽取能力`
- 前端：`feat(人事): 新增 AI 搜索与技能抽取页面`
- 验收：`test(人事): 记录 AI 搜索与技能抽取验收`
