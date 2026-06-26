# T-017: Slot 提取 + 意图路由分发

## 基本信息
- 对应 Spec: specs/intent-router/01-requirements.md REQ-003, REQ-004
- 对应 AC: AC-005~AC-007, AC-010, AC-012
- 依赖: T-016
- 预计工时: 2 天

## 输入
- `specs/intent-router/01-requirements.md` — Slot 提取与路由需求
- `specs/intent-router/02-data-model.md` — Slot 数据模型
- `specs/intent-router/03-api-contract.md` — 路由接口契约
- `src/intent_router/classifier.py` — 意图分类器（T-016 产出）
- `src/intent_router/schemas.py` — Intent Schema（T-016 产出）

## 输出
- `src/intent_router/slot_extractor.py` — Slot 提取模块
- `src/intent_router/router.py` — 意图路由分发器
- `src/intent_router/handlers/` — 各意图处理器接口定义
- `tests/intent_router/test_slot_extractor.py` — Slot 提取测试
- `tests/intent_router/test_router.py` — 路由分发测试

## 实现要求
1. 根据识别的意图类型，提取对应的 Slot（槽位）：搜索类提取 `position`、`experience`、`skills`、`location`；查找类提取 `candidate_name`、`candidate_id`；比较类提取 `candidate_ids`
2. Slot 提取使用 LLM Function Calling，与意图识别合并为单次调用以节省 Token
3. 实现路由分发器 `IntentRouter`，根据 `intent` 字段将请求分发到对应的 Handler
4. Handler 接口统一为 `async def handle(intent_result: IntentResult, context: ConversationContext) -> HandlerResponse`
5. 路由表可配置化：新增意图只需注册新 Handler，无需修改路由逻辑
6. Slot 合并策略：新提取的 Slot 与历史 Slot 合并，同名字段覆盖，新增字段追加
7. 关键设计决策：意图识别和 Slot 提取合并为一次 LLM 调用，减少延迟和 Token 消耗
8. 禁止事项：禁止在路由层硬编码 if-else 分支（必须使用注册表模式）；禁止忽略未知意图的处理

## 验收检查点

### 前置确认
- [ ] T-016（意图识别）已完成
- [ ] 容器环境已启动

### AC 验收
- [ ] AC-005: 输入"找3年Java经验在北京的候选人"，正确提取 Slot: `{position: "Java开发", experience: "3年", location: "北京"}`
- [ ] AC-006: 路由分发正确：`recruitment.search` → SearchHandler，`candidate.lookup` → LookupHandler
- [ ] AC-007: Slot 合并：先问"找Java"再问"3年经验的"，Slot 正确合并为 `{position: "Java开发", experience: "3年"}`

### 代码质量
- [ ] lint pass（ruff + mypy）
- [ ] 路由注册表模式清晰，可扩展
- [ ] Handler 接口统一，便于新增
- [ ] Slot 合并逻辑有完整测试覆盖
- [ ] 类型标注完整


- [ ] AC-010: 排除条件（如"不要外包""排除金融行业"）正确解析为 negative_slots，过滤时排除
- [ ] AC-012: Slots 冲突时（如先说"北京"后说"上海"），按最新值覆盖并记录冲突日志

### Spec 一致性
- [ ] Slot 字段定义与 `specs/intent-router/02-data-model.md` 一致
- [ ] Handler 接口与 `specs/intent-router/03-api-contract.md` 一致
- [ ] 路由分发逻辑与 REQ-004 一致

### 通过判定
全部 ✅ → Done | retry < 3 → 修复 | retry = 3 → BLOCKED
