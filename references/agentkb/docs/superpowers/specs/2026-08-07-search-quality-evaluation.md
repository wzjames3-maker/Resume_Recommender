# 搜人质量评测规范

> 版本：v0.4
> 日期：2026-08-07
> 状态：草案，待审查
> 关联：PRD F7、M4；MVP 范围与验收 spec §3.1；简历解析质量评测 spec（数据源）。
> 本 spec 定义「智能搜人质量」的可复现评测方法，是 MVP 核心目标之二（搜人质量）的验收依据。
> v0.4 变更（本轮 review 修复）：①候选搜索、统计查询、拒答负例分开计分，避免非候选响应污染 Precision@10；②补充 `requested_count`、`missing_policy`、机器池枚举与 `assignment_history` 谓词；③明确 end-to-end 解析失败样本的搜索可用性和独立报告；④画像依赖查询在画像标注未就绪时不进入 M4 硬门槛；⑤M4 只验收最小 `pool_scope` ACL，完整池流转归 M5；⑥补充候选结果覆盖、重复 ID、未知 ID 和零相关结果规则；⑦非数量候选查询也冻结最低返回覆盖，避免少返回规避 Precision 门槛。
> v0.3 变更（review 修复）：①Precision@10 补充空结果规则与 Recall@10、数量满足率，杜绝「少返回 / 空返回」绕过门槛；②标准标注升级为结构化条件 AST（字段 / 操作符 / 值 / 逻辑关系 / 默认条件），禁止静默追加隐藏条件；③新增 search-only / end-to-end 双评测模式，隔离解析误差与检索质量；④统计查询新增独立准确率指标；⑤新增排序质量 NDCG@10（观测）；⑥查询集各意图配额预注册；⑦fixture 规模与多轮序列冻结；⑧评测 bundle 扩展（查询集 / fixture / 运行配置哈希）。
> v0.2 变更：Top-N 指标统一为 Precision（§3.2），消除「≥80%」与「全部命中」的矛盾；新增评测上下文 fixture（§2.2），支撑按岗位搜索 / 跨池查询 / 统计查询三类意图。

## 1. 评测目标

验证对话式搜人（F7）能否：

- 正确理解人事部门的自然语言查询，抽取出准确检索条件。
- 检索出真正符合条件的人，且返回结果有效。
- 多轮追问在上一轮条件基础上正确收敛。
- 返回结果带可解释的匹配依据。
- 在服务端按当前用户可访问的池范围执行过滤，不因历史条件泄露不可访问候选人。

## 2. 评测数据

### 2.1 数据来源与评测模式

- 使用简历解析质量评测 spec 冻结的同一份评测简历集（从 AI Studio 数据集构建，含 manifest）。
- 简历集作为搜人检索的语料底库。

**评测模式（正式冻结）**：

| 模式 | 检索语料构建 | 验证对象 |
|------|--------------|----------|
| `search-only` | 使用冻结 Ground Truth 构建的理想结构化索引 + 池归属 + 冻结画像标签 | 意图识别 / 条件抽取 / 检索 / 排序能力 |
| `end-to-end` | 使用冻结版本的真实解析产物（含解析误差传播） | 上传 → 解析 → 检索的完整闭环 |

- 两种模式使用同一查询集、候选人 universe、fixture 和标准标注。
- `end-to-end` 中 `parse_failed` 样本不进入可搜索候选 universe，但保留在 bundle 中并单独报告「解析导致不可搜索的相关候选人数量」；不得根据本次运行结果临时删除样本或修改标签。
- M4 的硬门槛适用于 `core_candidate_search` 与 `pool_history_search` 查询族的两种模式；后者先以冻结 fixture 验收最小 `pool_scope` ACL 与历史条件不可越权。画像依赖查询和诊断指标见 §3.8。完整池流转由 M5 验收。

### 2.2 评测上下文 fixture

部分意图除简历外还依赖业务上下文，需构造冻结的 fixture：

| fixture | 内容（规模正式冻结） | 支撑意图 |
|---------|----------------------|----------|
| 职位 fixture | ≥ 3 个职位（含至少 1 组同名 / 近似名职位，验证岗位定位歧义），各含自然语言岗位要求及不可变 `job_id` | 按岗位搜索 |
| 候选人池归属 fixture | 覆盖三池机器值 `active` / `rejected` / `hired`，每池正负样本各 ≥ 5；含多指派边界：同一候选人在两职位不同状态、offer 已拒绝但仍有其他进行中指派、入职后余留进行中指派、重新指派回 `active` | 跨池显式指定、池隔离校验 |
| 指派历史 fixture | 至少覆盖 `offer_rejected` 当前池为 `active` / `rejected` / `hired` 的候选人；记录可访问池与不可访问池组合 | 历史条件查询与 ACL |
| 统计查询标准答案 | 对冻结快照预先计算数量 / 分布（含空桶处理），记录去重键与池范围 | 统计查询 |

- fixture 与简历集一同冻结，记录在评测 manifest 中。
- `pool_scope` 是用户请求的池范围，服务端实际查询范围为 `requested_pool_scope ∩ allowed_pool_scopes`；历史条件只在可访问候选人集合上求值。
- M4 只要求当前池过滤和 ACL 生效；M5 再验收状态流转驱动的池变更、重指派和入职聚合规则。

### 2.3 查询集构建

从简历集中构造一组真实的人事查询语句，覆盖主要意图。**配额预注册（正式冻结）**：

| 查询族 | 意图 | 示例查询 | 最低数量 | 计分指标 |
|--------|------|----------|----------|----------|
| `core_candidate_search` | 技能 + 年限 | 「找 5 年以上 Java 后端，base 杭州」 | ≥ 10 | AST / P@10 / Recall / 覆盖率 |
| `core_candidate_search` | 岗位 + 数量 | 「我需要 20 份匹配前端开发岗位的简历」 | ≥ 10 | AST / P@10 / 数量满足率 |
| `core_candidate_search` | 领域经验 | 「找做过支付系统的人」 | ≥ 10 | AST / P@10 |
| `profile_dependent_search` | 管理能力 / 职级 / 领域画像 | 「找有团队管理经验的高级工程师」 | ≥ 10 | AST / P@10，画像未就绪时仅观测 |
| `core_candidate_search` | 追问收敛 | 「学历高一点」「范围缩小到上海」 | ≥ 10（每条 ≥ 2 轮） | 每轮状态准确率 |
| `statistics` | 统计查询 | 「人才库里有多少 Java 候选人？」 | ≥ 10 | 统计准确率 |
| `pool_history_search` | 跨池 / 历史条件 | 「在已面试未通过的人才库里找电商运营」 | ≥ 10 | ACL / AST / P@10 |
| `no_result` | 预期无结果 | 「找 50 年以上且明确在火星工作的 Java 人」 | ≥ 10 | 无结果准确率 |
| `non_search` | 闲聊 / 超出范围 / 写请求引导 | 「把这些人批量指派到岗位」 | ≥ 30 | 意图准确率 / 无副作用 |

- `statistics`、`non_search` 不进入 Precision@10、Recall@10 或数量满足率分母。
- `profile_dependent_search` 在画像标注子集未就绪时不进入 M4 硬门槛；标注就绪后可升级为独立硬门槛，不得静默改变整体门槛。
- 每类意图分别报告指标，整体通过不豁免单类硬门槛未达标。

### 2.4 每条查询的标准标注（结构化条件 AST）

每条查询配一份结构化标准标注，记录完整条件、相关性、池 ACL 和期望响应类型：

```json
{
  "query_id": "q-001",
  "query_family": "core_candidate_search",
  "utterance": "找 5 年以上 Java 后端，base 杭州",
  "intent": "search",
  "expected_result_type": "candidate_list",
  "conditions": [
    {"field": "skills", "op": "contains", "value": ["Java"], "logic": "AND", "missing_policy": "exclude"},
    {"field": "years_experience", "op": ">=", "value": 5, "logic": "AND", "missing_policy": "exclude"},
    {"fields": ["city", "expected_city"], "op": "any_match", "value": "杭州", "logic": "AND", "missing_policy": "exclude"}
  ],
  "default_conditions": [],
  "requested_count": null,
  "job_id": null,
  "actor_role": "member",
  "pool_scope": "active",
  "allowed_pool_scopes": ["active"],
  "access_decision": "allow",
  "assignment_history": [],
  "candidate_labels": {
    "c-001": "relevant",
    "c-002": "relevant",
    "c-004": "irrelevant",
    "c-010": "not_in_pool"
  },
  "available_relevant_count": 2,
  "evidence": {"c-001": ["work[0].content", "skills"]}
}
```

- `conditions` 中每项必须二选一提供 `field` 或 `fields`；`fields` 用于多字段匹配。每项必须包含 `missing_policy`：`exclude`（缺失不命中）或 `include`（仅适用于显式缺失查询）。
- `default_conditions` 仅允许来自冻结上下文的隐含条件，必须显式记录；禁止把查询中未出现且未冻结的条件静默加入标准标注。
- `requested_count` 是数量意图的正式字段；无数量意图必须为 `null`。`available_relevant_count` 是冻结 universe 中满足条件且在该模式可搜索的相关候选数。
- 当 `available_relevant_count=0` 时，`expected_result_type` 必须为 `no_result`；若仍标为 `candidate_list`，视为标准标注格式错误，不得利用零分母绕过候选搜索门槛。
- `actor_role`、`pool_scope` 与 `allowed_pool_scopes` 使用冻结的机器枚举；角色为 `owner` / `admin` / `member`，池为 `active` / `rejected` / `hired`，中文仅为展示文案。`allowed_pool_scopes` 必须由服务端根据 actor/workspace fixture 派生，不能由查询文本或模型自行声明。
- `access_decision` 为 `allow` / `refuse`；当请求的 `pool_scope` 不在 `allowed_pool_scopes` 时，标准标注固定为 `refuse`，`expected_result_type=refusal`，服务端返回统一无权限响应，不返回候选人、池名、数量或可枚举的错误差异；该查询只计 ACL/无副作用，不进入候选搜索指标。
- `assignment_history` 是独立于当前池的历史谓词数组，例如 `{"event":"offer_rejected"}`。服务端先执行 ACL，再在可见候选人上执行历史谓词；不可访问候选人不得通过数量、是否命中、池名或错误信息泄露。
- `candidate_labels` 必须覆盖候选人 universe 中的每个 ID，值为 `relevant` / `irrelevant` / `not_in_pool`；未知 ID、重复 ID、标签缺失均为评测格式错误。
- 上述 JSON 仅为结构示例；正式 bundle 不允许省略候选人 ID，`candidate_labels` 的键集合必须与对应模式的 `candidate_universe` 完全一致。
- `evidence` 为相关候选人匹配依据字段定位，供可解释性核对；证据必须引用冻结的 IR / candidate revision。
- `expected_result_type` 枚举：`candidate_list` / `statistics_card` / `refusal` / `no_result`。只有 `candidate_list` 进入候选搜索指标。

### 2.5 评测 manifest 扩展

评测 bundle 在简历解析评测 manifest 基础上扩展以下字段（一并冻结）：

```
query_set: {path, sha256, version}
job_fixture: {path, sha256}
pool_fixture: {path, sha256}
assignment_history_fixture: {path, sha256}
stat_oracle: {path, sha256, snapshot_date}
candidate_universe: {path, sha256}
index_runtime: {embedding_model, rerank_model, top_k, rrf_params, index_snapshot_sha256}
```

- `candidate_universe` 为每个模式的候选人 ID、当前池、解析状态、是否可搜索的冻结映射；`end-to-end` 不得运行后修改。
- 检索运行配置（embedding / rerank 模型、召回 Top-K、RRF 参数、索引快照哈希）随 bundle 冻结，保证结果可复跑。
- 查询集冻结后不允许修改标准标注「凑指标」；确需调整时生成新 bundle 版本并重新跑基线。

## 3. 评测指标

### 3.1 检索条件理解准确率

```
条件理解准确率 = 条件 AST 与标准条件完全一致的查询数 / 该查询族查询总数
```

- 对 `core_candidate_search`、`profile_dependent_search`、`pool_history_search` 分别计算；`statistics` 和 `non_search` 使用各自指标。
- 对比字段 / 操作符 / 值 / 逻辑关系 / `missing_policy` / `requested_count` / `job_id` / `pool_scope` / `assignment_history`，且不得引入标准标注之外的额外条件。
- 意图识别错误直接计该查询族失败。

### 3.2 Precision@10（候选列表查询）

```
Precision@10 = 返回结果前 10 条中唯一 relevant ID 数量 / min(10, 实际返回的唯一候选 ID 数量)
```

- 仅对 `expected_result_type=candidate_list` 的查询计算；统计卡片、拒答和预期无结果查询不进入分母。
- N 固定为 10；结果中的 `irrelevant` 为不相关；`not_in_pool`、未知 ID、重复 ID、跨 ACL 的 ID 或其他越权返回直接判定该查询失败，不能从分母中排除无效结果。
- 返回 0 条时 P@10 计 0；若标准 `available_relevant_count=0` 且 `expected_result_type=no_result`，改用 §3.5 的无结果准确率，不以 P@10 评价。
- **最低返回覆盖（正式冻结）**：`expected_result_type=candidate_list` 且 `available_relevant_count > 0` 时，唯一候选 ID 返回数必须至少为 `min(10, available_relevant_count)`；否则该查询判为失败，即使现有返回结果的 Precision 为 1.0。该规则与数量意图无关，数量意图另按 §3.4 验证请求 N。
- 候选搜索目标：**P@10 ≥ 0.80**。

### 3.3 Recall@10（候选列表查询，观测）

```
Recall@10 = 返回结果前 10 条命中的唯一 relevant ID 数量 / available_relevant_count
```

- `available_relevant_count=0` 时记为 `N/A`，不进入平均值。
- `end-to-end` 使用当前模式冻结的 `available_relevant_count`；解析失败的相关样本进入单独的 availability 报告，不被 scorer 临时从 universe 删除。

### 3.4 数量满足率

```
数量满足率 = 满足「返回唯一有效候选数 ≥ min(requested_count, available_relevant_count)」的数量查询数 / 数量查询总数
```

- 仅对 `requested_count != null` 且 `expected_result_type=candidate_list` 的查询计算。
- 目标：**≥ 0.90**；不足时必须显式说明「仅找到 X 个」，不允许用分页未加载、重复 ID 或越权 ID 凑数。

### 3.5 无结果准确率

```
无结果准确率 = 正确返回空候选列表且明确说明无命中的 no_result 查询数 / no_result 查询总数
```

- 预期存在相关候选人却返回空列表计失败；预期无结果查询返回任意候选人也计失败。
- 该指标只用于 `expected_result_type=no_result`，目标 ≥ 0.90。

### 3.6 多轮追问收敛准确率

- 每条多轮序列冻结完整 transcript（初始查询、每轮 assistant 输出、会话 ID）与每轮期望条件 AST。
- 判定：按全部追问轮次计算——每轮仅更新变化字段、保留上一轮条件并遵守 `missing_policy` 为正确；分母 = 追问轮次总数。
- 目标：观测基线，MVP 不设硬性目标；变更语义（如「学历高一点」= 提高学历 ordinal 阈值）在 AST 中显式规定。

### 3.7 统计查询准确率

```
统计查询准确率 = 统计结果与标准答案一致的查询数 / statistics 查询总数
```

- 数量类 exact match；分布类按类别 macro accuracy ≥ 0.90，空桶按 0 参与计算。
- 统计快照、池范围、去重键随 bundle 冻结；统计结果中不得返回不可访问池的数量或分布。
- 目标：**≥ 0.90**。

### 3.8 意图 / 无副作用 / 画像依赖指标

- `non_search`：意图识别准确率 ≥ 0.90；写请求不得产生任何业务数据变更、任务或外部模型副作用；允许并要求追加一条脱敏的只读审计事件，不计为业务副作用。
- `profile_dependent_search`：画像标签冻结且标注子集就绪时，按 P@10 / AST 单独设 ≥ 0.70 / ≥ 0.85；未就绪时只报告，不进入 M4 硬门槛。
- `end-to-end` 另报告 `parse_unavailable_relevant_count` 与「因解析失败不可搜索的相关候选比例」，该指标不能用删除样本修饰。

### 3.9 排序质量与匹配依据可解释性（观测）

- **排序质量**：`NDCG@10`（以 relevant=1 / irrelevant=0 为 rel 值）为观测指标，MVP 不设硬性目标；结果按相关度降序展示是产品要求，观测值用于回归对比。
- **匹配依据可解释性**：抽检候选人卡片的匹配依据，判定依据是否命中 `evidence` 记录的字段定位。抽检量 ≥ 30 条 / 查询族；目标为观测基线。

### 3.10 分类别门槛

- `core_candidate_search`、`pool_history_search` 分别报告 AST、P@10、最低返回覆盖、数量满足率；每个硬门槛查询族的 P@10 ≥ 0.70，整体 P@10 ≥ 0.80。
- `statistics`、`non_search`、`no_result` 使用各自 §3.5 / §3.7 / §3.8 指标，不混入候选搜索平均值。

## 4. 评测流程

```
1. 冻结简历集 + fixture + 查询集 + candidate universe + 标准标注 + 检索运行配置为评测 bundle
2. 分别运行 search-only / end-to-end 两条搜人链路（意图识别 → 条件抽取 → ACL/池过滤 → 检索 → rerank → 输出）
3. 按 query_family 分别运行对应 scorer，输出硬门槛、观测指标和 parse availability 报告
4. 分别归因意图/条件抽取错误、ACL/池过滤错误、召回/排序错误、解析传播错误；两模式差值仅作辅助定位
5. 指标达标 → 冻结该版本，作为回归基线
```

- 查询集冻结后不允许修改标准标注「凑指标」。
- 每次搜人代码、解析代码、模型配置或索引参数变更后跑回归，相关 query family 指标回退视为回归缺陷。

## 5. 失败分类与处置

| 失败类别 | 处置 |
|----------|------|
| 意图误判 | 记录误判类型，进入对应 query family 的意图失败计数 |
| 条件抽取错误 | 记录漏抽 / 错抽的 AST 字段，包括 `missing_policy`、数量和历史谓词 |
| ACL / 跨池错误 | 阻断缺陷：不得返回不可访问候选人、池归属、数量或错误侧信道 |
| 检索召回不足 | 按 §3.3 / §3.4 记录不足原因，验证「不凑数、不编造」规则 |
| 空结果错误 | 按 §3.5 判定，记录预期结果类型与实际响应类型 |
| 统计答案错误 | 记录统计查询的数量 / 分布偏差，不污染 P@10 |
| 写请求副作用 | 阻断缺陷：不得产生业务数据、任务或出站调用；只允许追加脱敏的只读审计事件 |
| 排序质量回退 | 记录 NDCG@10 观测值，出现显著回退视为回归缺陷 |

## 6. 待确认项

- 各类别查询最低数量已在本版冻结（§2.3）；最终查询清单、候选人 universe 与 fixture 在构建 bundle 时冻结。
- 多轮序列的边案例（条件删除 / 澄清 / 回滚）在构建 bundle 时定稿。
- 画像标注子集就绪后是否将 `profile_dependent_search` 升级为 M4 独立硬门槛；在此之前不得把它混入核心 P@10 门槛。
