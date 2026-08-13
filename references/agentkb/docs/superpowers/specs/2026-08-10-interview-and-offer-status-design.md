# 面试与 Offer 状态设计

## 目标

建立 HR 可执行的候选人招聘闭环，区分：

- 面试反馈结果：这次面试是否通过、是否履约。
- 招聘流程结果：是否发 Offer、是否接受并入职、是否拒绝 Offer。
- 人才池和自然语言搜人范围：候选人是否默认可被再次检索。

本设计只覆盖候选人与职位的 `Assignment` 关系，不改变候选人基础资料和职位生命周期。

## 状态模型

### 招聘流程状态

继续使用现有 `Assignment.status`：

```text
pending_screen -> screen_passed -> interviewing -> offer -> hired
       |                |               |            |
       +-------------- rejected <-------+            +-> offer_rejected
```

现有终态继续保留：`rejected`、`offer_rejected`、`hired`、`closed_after_hire`、`closed_by_job`。

- `offer`：已向候选人发出 Offer，尚未记录最终结果。
- `hired`：候选人接受 Offer 并已入职。
- `offer_rejected`：候选人明确拒绝 Offer。
- `rejected`：HR 在初筛或面试环节淘汰候选人。

因此“发 Offer 后是否入职”和“拒绝 Offer”由现有状态真实表达，不通过前端标签推导。

### 面试结果状态

新增 `Assignment.interview_result`，可为空或为以下值：

```text
passed    面试通过
failed    面试不通过
no_show   未履行面试
cancelled 取消面试
```

该字段表示最近一次已处理的面试结果，不覆盖 `Assignment.status`。

- 新建指派和已安排但尚未反馈的面试：`null`。
- 面试官提交通过：`passed`。
- 面试官提交不通过：`failed`。
- HR 确认候选人未参加：`no_show`。
- HR 或面试官取消面试：`cancelled`。
- 候选人重新安排新一轮面试时，保留历史轮次，但将当前面试结果清空为 `null`。

### 多轮面试规则

- `advance`：本轮通过但需要下一轮，面试结果保持 `null`，Assignment 保持 `interviewing`。
- `recommend`：本轮最终通过，写入 `passed`；Assignment 仍保持 `interviewing`，由 HR 再执行“发 Offer”。
- `reject`：写入 `failed`，Assignment 流转为 `rejected`，淘汰原因必填。
- `hold`：不写入最终面试结果，Assignment 保持 `interviewing`。
- 只有最终通过后才允许进入 `offer`；已有的评分、评语完整性闸门继续保留。
- `no_show` 和 `cancelled` 是面试履约结果，不自动将候选人标记为 `rejected`，便于重新安排面试或保留人才记录。

## 面试管理

面试页仍为四个 Tab，筛选依据为面试结果与招聘流程的组合：

| Tab | 进入条件 | 展示重点 |
| --- | --- | --- |
| 待面试 | Assignment 为 `pending_screen`/`screen_passed`，或存在尚未反馈的已安排轮次 | 面试安排、面试官、反馈动作 |
| 已经面试 | 已完成至少一轮面试，结果为 `null`，且没有待反馈轮次 | 面试轮次、反馈和后续 HR 动作 |
| 面试通过 | `interview_result = passed` | 当前招聘状态：面试通过、已发 Offer、已入职 |
| 面试不通过 | `interview_result in (failed, no_show, cancelled)`，或流程状态为 `rejected` | 结果原因和是否可重新安排 |

待面试行提供四个结果动作：

- 面试通过：写入 `passed`。
- 面试不通过：写入 `failed`，需要淘汰原因时同时执行合法流程流转。
- 未履行面试：写入 `no_show`。
- 取消面试：写入 `cancelled`。

面试通过 Tab 的招聘流程动作：

- 发 Offer：`interviewing -> offer`，继续使用现有完整反馈校验和 HC 校验。
- 标记已入职：`offer -> hired`，继续使用现有入职聚合逻辑。
- 标记拒绝 Offer：`offer -> offer_rejected`，记录 Offer 拒绝结果并释放 HC reservation。

所有动作必须经过后端校验并记录候选人事件和审计事件，前端不能直接改变展示分类作为状态变更。

## 简历列表筛选

候选人列表新增“面试状态”筛选，允许：

```text
passed  面试通过
failed  面试不通过
no_show 未履行面试
```

筛选基于当前工作区 Assignment 的 `interview_result`，使用 `EXISTS` 语义避免候选人存在多职位指派时重复显示。

“取消面试”不作为简历列表筛选项，但取消面试仍会在面试管理和候选人详情时间线中保留。

候选人基础状态筛选继续保留：在职库、待确认、已面试未通过、入职员工、已删除，并继续按角色限制 `hired` 与 `deleted` 的可见性。

## 自然语言查询口径

### 默认查询范围

没有明确历史状态条件时，智能人事助手默认返回“人才池中可继续招聘或激活”的候选人：

- `active`、`pending_review` 候选人。
- 有进行中 Assignment：`pending_screen`、`screen_passed`、`interviewing`、`offer`。
- 面试结果为 `passed`、`no_show`、`cancelled` 的候选人，只要其没有已入职或其他终止关系，也可以作为人才结果返回。

“面试通过”不等于“已入职”；已通过面试但尚未发 Offer 的候选人默认可查。

### 只有明确提及时查询

以下状态必须由用户明确提到，或使用明确的历史筛选条件，才可返回：

- 面试不通过：`interview_result = failed` 或流程状态 `rejected`。
- 拒绝 Offer：`Assignment.status = offer_rejected`。
- 已入职：`Assignment.status = hired`，且仅 admin/owner 可查询员工池。
- 已关闭流程：`closed_after_hire`、`closed_by_job`。

示例：

- “找 Java 后端”不返回已淘汰、拒绝 Offer、已入职候选人。
- “找面试通过但还没发 Offer 的 Java 后端”返回 `interview_result=passed` 且 Assignment 不是 `offer/hired` 的候选人。
- “查拒绝过 Offer 的候选人”允许查询 `offer_rejected` 历史。
- “查已入职的后端员工”仅管理员/所有者允许，普通成员按现有 ACL 不返回。

### 取消面试和未履行面试

- “找未履行面试的人”明确命中 `no_show`。
- “找取消面试的人”明确命中 `cancelled`，但自然语言搜人默认不返回该类历史记录，除非用户明确提出。
- 重新安排面试会将当前面试结果清空；历史事件不丢失，查询“曾经取消/未履行”需要基于历史事件能力，当前 MVP 只支持当前结果字段。

### 意图解析契约

搜索意图解析器增加 `interview_result` 和 `assignment_status` 条件，历史 `offer_rejected` 条件继续保留并扩展为统一状态谓词。解析器不得从“面试通过”推导 `offer` 或 `hired`，也不得从“已入职”推导面试通过。

## API 与数据流

- 反馈接口写入 `InterviewRound` 并同步当前 Assignment 的 `interview_result`。
- 新增 Assignment 面试结果更新接口，供“未履行面试”和“取消面试”使用。
- Assignment 看板返回 `interview_result`、`offer`/`hired`/`offer_rejected` 等招聘状态。
- 候选人列表接口接收 `interview_result` 参数，并在服务层通过 Assignment 关联筛选。
- 面试结果更新和 Offer 流转都写入候选人事件，前端刷新后以 API 返回结果重新分组。

## 错误处理与权限

- 不属于当前工作区、不可见候选人或不存在的指派统一返回 404。
- 终态指派不能再次发 Offer、入职或拒绝 Offer。
- 只有 `offer` 状态可以标记入职或拒绝 Offer。
- 只有候选人可见范围内的成员可以提交反馈；关闭职位后的关闭操作继续限制 admin/owner。
- 非 admin/owner 查询 `hired` 时按现有 ACL 返回 404/空结果，不泄露员工信息。

## 验收与测试

- 迁移后 Assignment 默认 `interview_result` 为空，既有状态和 HC 数值不变。
- 四种面试结果均可持久化、在看板返回并正确进入对应 Tab。
- 反馈 `recommend` 不自动发 Offer；发 Offer、入职、拒绝 Offer 的状态和 HC 变化符合现有规则。
- 候选人面试状态筛选返回去重结果，且排除 `cancelled` 筛选项。
- 自然语言查询覆盖默认排除和显式查询的状态边界，并验证普通成员不能查询已入职人员。
- 运行后端相关测试、前端类型检查和前端测试，并通过 Playwright 验证四个 Tab、反馈操作和筛选控件。
