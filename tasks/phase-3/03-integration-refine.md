# T-038: recruitment.refine 多轮对话集成测试

## 基本信息
- **对应 Spec**: integration-testing（多轮对话状态管理）
- **对应 AC**: 多轮对话状态合并验证
- **依赖任务**: T-028（recruitment.refine 模块）
- **预计工时**: 1 天
- **优先级**: P0

## 输入
- T-028 产出的 `recruitment.refine` 模块（多轮对话 refine 逻辑）
- 预置的测试候选人数据（复用 T-037 的数据集）
- 多轮对话场景测试用例（`tests/fixtures/refine_scenarios.json`）

## 输出
- `tests/integration/test_refine_multiturn.py` — 集成测试文件
- `tests/fixtures/refine_scenarios.json` — 多轮对话场景
- 集成测试运行报告

## 实现要求

### 测试链路
```
第 1 轮: "找一个Python开发" → search → 返回候选人列表
第 2 轮: "要有3年以上经验" → refine → 基于上轮结果 + 新条件过滤
第 3 轮: "只要上海的" → refine → 继续叠加条件
第 4 轮: "看看第一个候选人的详情" → verify state merge
```

### 测试用例设计
1. **基础 Refine**: search → refine，验证结果列表缩小（条件叠加过滤）
2. **条件叠加**: 多轮 refine 后，所有条件均生效（验证 state merge 正确）
3. **条件替换**: 第 2 轮说"经验改为 5 年"（覆盖而非叠加）
4. **条件移除**: 第 3 轮说"不限地点了"（移除已有筛选条件）
5. **状态一致性**: 验证对话状态中的 `filters` 字段正确反映所有轮次的条件变更
6. **结果继承**: refine 后的结果是上轮结果的子集（不会出现上轮没有的候选人）
7. **空结果回退**: refine 导致无结果时，给出提示并保持上轮结果

### 状态合并验证
- 每轮 refine 后检查对话状态对象：
  - `conversation_id` 保持一致
  - `filters` 正确合并（新条件叠加/替换/移除）
  - `turn_count` 递增
  - `results` 是最新轮次的过滤结果

## 验收检查点

### 前置确认
- [ ] T-028 已完成并通过验收
- [ ] MongoDB + Milvus 中已有测试候选人数据
- [ ] 多轮对话场景用例已准备

### 测试通过标准
- [ ] 所有 7 个测试用例通过
- [ ] 多轮 refine 延迟 < 3 秒/轮
- [ ] 状态合并无数据丢失或错乱

### 代码质量
- [ ] 每个多轮场景独立运行，不共享状态
- [ ] 使用 mock 对话 ID 隔离不同测试场景
- [ ] 测试覆盖正向路径和边界情况

### Spec 一致性
- [ ] 状态合并规则与 `04-business-rules.md` 中对话状态机一致
- [ ] refine 响应格式与 `03-api-contract.md` 一致

### 通过判定
- [ ] 所有测试用例通过
- [ ] 状态合并逻辑人工验证正确（打印 state diff）
- [ ] 无内存泄漏或状态污染（多次运行结果一致）
