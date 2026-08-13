# 简历 Schema 与导入模板

> 版本：v0.5
> 日期：2026-08-07
> 状态：草案，待审查
> 关联：PRD F6、F12；本 spec 定义解析输出的统一 Schema 与 CSV/JSON 导入契约。
> v0.5 变更（遗留项冻结）：`referrer` 类型正式冻结——工作区成员邮箱或自由文本姓名（≤64 字符），批次内一致，作为内推归属统计依据（对齐 PRD F12）。
> v0.4 变更（本轮 review 修复）：①JSON 导入统一使用批次 envelope，避免单条对象与来源元数据分叉；②补充 evidence、skills canonical dictionary、CSV 汇总字段与 row_hash 语义；③显式重解析与重复上传使用不同幂等键；④软删除记录仍参与查重，硬删除后以 tombstone 释放身份；⑤未知工作类型不计入正式年限。
> v0.3 变更（review 修复）：①空值语义统一——枚举移除 `unknown`，无法确定一律标 `null`（gender / 学历同步）；②明确数组字段名 `education` / `work` / `project` 为正式契约，`[]` 与 `null` 语义区分；③conflict 结构扩展（type / values / evidence），并明确冲突认定以评测 Ground Truth 冻结为准，预测端不得自行豁免；④years_experience 补充区间端点、employment type 与学历 ordinal；⑤字段优先级引入 revision 与字段级 override/clear 语义；⑥CSV dialect 契约冻结（编码/分隔符/未知列/错误报告）；⑦幂等键从 CSV/JSON 扩展至全部上传格式。
> v0.2 变更：city 拆分为 city（现居地）+ expected_city（期望工作城市）；years_experience 改为区间合并累计月数；定义 conflict 标记结构；明确 CSV 仅支持汇总文本、结构化数组仅 JSON 导入。

## 1. 统一简历 Schema

所有简历（doc/docx/txt/csv/json）解析后统一映射到如下 Schema。字段取值无法确定时标 `null`，禁止编造。

> **Schema 契约性质**：本节的字段名、类型、枚举与数组结构为**正式契约**，字段名不从 `project` / `projects` 等变体取值；变更必须提升 schema 版本并显式兼容或拒绝旧版本。顶层数组字段名正式冻结为 `education` / `work` / `project`（JSON 导入），CSV 不展平数组（见 §3）。
>
> **空值语义（正式冻结）**：
> - `null`、空字符串、字段缺失三者等价，表示「无法确定 / 未提供」，禁止编造。
> - `[]` 仅用于数组字段，表示「确认无该经历」；与 `null`（无法确定）语义不同，不可互换。
> - 枚举类字段不再使用 `unknown` 作为取值；无法确定时一律标 `null`（画像标注的 `unknown` 见画像评测 spec §4.4，属独立口径）。

> **审计元数据（不属于业务字段）**：每个解析 revision 另保存 `evidence` 映射，键为字段路径（如 `work[0].content`），值至少包含 `ir_revision_id`、`block_id`、`start_offset`、`end_offset`、`quote_hash`。结构化输出、画像、岗位条件和匹配理由只能引用同一 revision 中的 evidence；引用不存在或 hash 不匹配时不得发布结果。

### 1.1 基本信息

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 否 | 姓名 |
| gender | string | 否 | 性别，枚举：男 / 女（无法确定标 `null`） |
| birth_month | string | 否 | 出生年月，格式 `YYYY-MM` |
| phone | string | 否 | 手机号，PII 字段 |
| email | string | 否 | 邮箱，PII 字段 |
| highest_degree | string | 否 | 最高学历，枚举见 1.6 |
| hometown | string | 否 | 籍贯 |
| political_status | string | 否 | 政治面貌 |
| expected_position | string | 否 | 期望职位 |
| city | string | 否 | 当前居住/工作城市（简历现居地），可参与搜索 |
| expected_city | string | 否 | 期望工作城市 / base 地，可参与搜索 |
| skills | string[] | 否 | 技能标签 |

> 敏感字段（gender、birth_month、hometown、political_status）**不参与搜索、排序与推荐**，仅作展示。PII 字段（phone、email）加密存储。city / expected_city 为可搜索字段。
>
> **城市匹配口径**：搜人条件「城市 / base」命中 `city` 或 `expected_city` 任一即视为匹配。简历未区分现居地与期望地时，仅填能确定的字段，另一字段标 `null`，不互相猜测填充。

### 1.2 教育经历（数组，字段名 `education`）

| 字段 | 类型 | 说明 |
|------|------|------|
| school | string | 毕业院校 |
| degree | string | 学位 / 学历 |
| major | string | 专业 |
| start | string | 开始时间 `YYYY-MM` |
| end | string | 结束时间 `YYYY-MM` |

### 1.3 工作经历（数组，字段名 `work`）

| 字段 | 类型 | 说明 |
|------|------|------|
| company | string | 工作单位 |
| title | string | 职务 |
| content | string | 工作内容（长文本） |
| start | string | 开始时间 `YYYY-MM` |
| end | string | 结束时间 `YYYY-MM`；在职为 `null` |
| type | string | 工作类型，枚举：full_time / intern / part_time / project；用于 `years_experience` 计算，无法确定标 `null`，不得默认为 full_time |

### 1.4 项目经历（数组，字段名 `project`）

| 字段 | 类型 | 说明 |
|------|------|------|
| name | string | 项目名称 |
| responsibility | string | 项目责任（长文本） |
| start | string | 开始时间 `YYYY-MM` |
| end | string | 结束时间 `YYYY-MM` |

### 1.5 画像字段

画像字段为解析后由 LLM 生成的衍生结果，不来源于简历原始字段，单独存放。**第一层固定画像为八维枚举**（与 PRD F6 一致）：

| 字段 | 类型 | 说明 |
|------|------|------|
| level | string | 职级层级，枚举：Junior / Mid / Senior / Staff / Principal |
| professional_depth | string | 专业深度，枚举：Low / Medium / High / Expert |
| domain | string | 领域经验，枚举：金融科技 / 电商 / AI / 医疗 / 供应链等（开放枚举，见 PRD F6；画像评测时由标注子集冻结标签集合，未命中允许追加但须在标注指南登记） |
| influence_scope | string | 影响范围，枚举：个人贡献者 / 小组 / 团队负责 / 跨团队 / 组织级 |
| management | string | 管理能力，枚举：无 / 导师 / 技术负责 / 团队管理 / 总监级 |
| stability | string | 职业稳定性，枚举：稳定 / 正常 / 频繁变动 / 风险 |
| growth_trend | string | 成长趋势，枚举：上升 / 平稳 / 平台期 / 下滑 |
| communication | string | 沟通协作，枚举：低 / 中 / 高 |

**第二层开放洞察**（自由文本，不参与检索）：

| 字段 | 类型 | 说明 |
|------|------|------|
| strengths / risks / career_pattern | string | 优势 / 风险 / 职业模式，仅供 HR 阅读参考 |

### 1.6 学历枚举与 ordinal

```
初中 / 高中 / 中专 / 大专 / 本科 / 硕士 / 博士
```

- 枚举不做 `unknown` 取值；无法确定标 `null`。
- **ordinal 映射（正式冻结，用于「学历高一点」「本科及以上」等比较条件）**：初中=1、高中=2、中专=3、大专=4、本科=5、硕士=6、博士=7。
- 比较规则：「≥ X」命中 ordinal(X) 及以上；`null` 学历在比较条件中**不参与排序**（不命中也不反命中，由条件 AST 显式规定是否排除）。

### 1.7 校验规则

- 必填字段缺失且无法从简历推断 → `null`，不编造。
- 时间字段解析失败 → `null`，不猜测。
- 生产 JSON Schema 校验：`birth_month` / 经历 `start` / `end` 只能为 `YYYY-MM` 或 `null`；`phone` 归一化后为 7–15 位数字；`email` 通过基础邮箱格式校验；字符串字段 ≤2,000 字符，数组元素 ≤100；未知字段、非法枚举、非法类型一律拒绝入库。
- 字段间矛盾（如同单位两个时间线冲突）→ 保留原始值并标记 `conflict`，进入人工确认。

**conflict 标记结构**：矛盾字段保留原始值，候选人记录附加 `conflicts` 列表：

```json
{
  "field": "work[0].start",
  "type": "timeline_overlap",
  "values": ["2020-01", "2019-06"],
  "evidence": "work[0].start=2020-01 与 work[1].start=2019-06 重叠",
  "reason": "与 work[1] 时间段重叠"
}
```

- `type` 枚举：`timeline_overlap`（时间线重叠）/ `value_conflict`（同一字段多值矛盾）/ `other`。
- `values`：双方原始值；`evidence`：冲突发生的字段定位与原文依据。
- > **冲突认定口径（正式冻结）**：`conflict` 是否成立由评测样本的 Ground Truth 预先冻结判定（见解析评测 spec §2.4、§3.6），**预测端不得自行声明字段为 conflict 以豁免评分**；生产环境由解析流水线标记后进入「待人工确认」，最终由 HR 处理。
- > 标记 `conflict` 的字段在评测时不计入结构化字段 F1（不算错误），单独统计为「待人工确认」数量，并单独评估 conflict 检测准确率。

### 1.8 派生字段

| 字段 | 类型 | 说明 |
|------|------|------|
| years_experience | int | 工作年限（整年，向下取整）= 工作时间段合并后的累计月数 / 12 |

**计算规则**：

- **区间端点**：时间段 `[start, end]` 为**闭区间**，两端月份各计 1 个月；同一月份内的经历计 1 个月（如 `2020-01` 至 `2020-01` 计 1 个月）。
- **区间合并**：对全部工作经历的 `[start, end]` 区间求并集，重叠区间合并，区间之间的空档不计入；累计月数 = 并集覆盖的月份总数。
- `start` 为空、格式非法或 `end` 早于 `start` 的经历不计入年限，并进入 `conflict` /「待人工确认」；仅有 `end=null`（在职）时可按基准日闭合区间。
- **计入范围**：仅计 `type = full_time` 的正式经历；`intern` / `part_time` / `project` / `null` 不计入。`type = null` 的经历保留在结构化结果中，并计入「待人工确认」，不得影响正式工作年限，避免把不确定经历直接用于「5 年以上」等筛选。
- **在职经历**：`end` 为 `null` 或「至今」时，计算至基准日。
- **基准日**：评测固定为数据集快照日期（保证结果可复现）；生产环境取当前日期。
- 无工作经历时标 `null`；`years_experience` 为整年向下取整（累计月数 / 12）。

> 派生字段由系统计算，不参与「禁止编造」判定；搜索条件中的「年限」基于此字段。

## 2. 字段优先级与版本（revision）

简历数据存在三层来源，取值优先级从高到低：

1. **人工修正值（override）**（HR 手工修正，最高优先，永不自动覆盖）。
2. **最新解析值**（最新一次解析 run 产出的结构化字段）。
3. **历史解析值**（供回溯，不参与当前展示）。

> 人工修正值在后续重新解析时保留；重新解析只更新「最新解析值」，不覆盖人工修正值。

**revision 与字段级 override/clear 语义（正式冻结）**：

- 每次解析（含重新解析）产生一个解析 run / revision，记录 `run_id`、输入文件 hash、解析器版本、模型与 schema 版本、产物 hash（见 PRD 解析审计链）。历史 revision 全部保留。
- 人工修正按字段记录为 `override`（含修正前值、修正人、时间、基于的 revision_id）；人工「清空字段」记录为 `clear`。
- 展示与检索使用「最新 revision 的解析值 + 人工 override/clear 覆盖」的合并视图。
- **数组字段合并**：按数组元素的关键字段（教育→school、工作→company、项目→name）配对后逐字段应用 override；新增元素追加，删除的元素由人工在 UI 操作并记录。
- **并发保护**：人工修正与重新解析均带乐观锁（基于 revision_id），冲突时提示 HR 选择，禁止静默覆盖。
- **派生值联动**：重新解析后，`years_experience`、画像、五段向量、全文索引与惰性岗位匹配缓存按依赖关系重新生成；人工 override 的字段不参与覆盖。
- **与查重合并的关系**：候选人合并后，整体以「最新解析 revision + 人工 override」为准，历史简历文件与 revision 全部保留（见 PRD F12）。

## 3. CSV / JSON 导入模板

CSV/JSON 用于从旧系统结构化批量导入。导入数据已是结构化数据，**跳过 LLM 结构化步骤**，直接映射到统一 Schema。

> **表达能力差异**：CSV 为轻量导入，仅支持基本字段 + 教育/工作经历汇总文本；JSON 为完整导入，支持教育/工作/项目结构化数组。CSV 导入的候选人经历数组为 `null`（仅保留汇总文本供向量检索），**不纳入结构化字段 F1 评测**。

### 3.1 必填 / 可选

| 字段 | CSV 必填 | JSON 必填 | 说明 |
|------|----------|-----------|------|
| name | 是 | 是 | 姓名 |
| phone | 推荐 | 推荐 | 用于查重；缺失时用 email 查重 |
| email | 推荐 | 推荐 | 用于查重 |
| gender | 否 | 否 | 枚举：男 / 女（无法确定留空，标 `null`） |
| birth_month | 否 | 否 | `YYYY-MM` |
| highest_degree | 否 | 否 | 学历枚举 |
| city | 否 | 否 | 当前居住/工作城市 |
| expected_city | 否 | 否 | 期望工作城市 / base 地 |
| expected_position | 否 | 否 | 期望职位 |
| skills | 否 | 否 | CSV 用 `;` 分隔 |
| 教育 / 工作 / 项目经历 | 否 | 否 | 不支持时留空 |

### 3.2 CSV 列顺序与 dialect（导入模板，正式冻结）

```
name,gender,birth_month,phone,email,highest_degree,city,expected_city,expected_position,skills,max_education_desc,max_work_desc
```

- `skills`：多个技能用 `;` 分隔。
- `max_education_desc`：教育经历汇总文本（可选）。
- `max_work_desc`：工作经历汇总文本（可选）。
- 行内字段缺失：允许，标 `null`。
- **CSV dialect（正式冻结）**：编码 UTF-8（兼容 BOM）；分隔符英文逗号；引号双引号并支持转义；表头固定为上述列顺序。
- **未知列 / 重复列**：拒收并报错（不静默忽略）。
- **错误报告**：单行错误不影响整批，逐行报告（行号 + 字段 + 原因）；错误行不产生候选人记录。
- **字段长度上限**：单字段 ≤ 2,000 字符，超长拒收该行。

### 3.3 JSON 导入结构

```json
{
  "schema_version": "resume-import/v1",
  "template_version": "2026-08-07.1",
  "source_channel": "referral",
  "referrer": "李四",
  "records": [
    {
      "name": "张三",
      "gender": "男",
      "birth_month": "1995-03",
      "phone": "13800000000",
      "email": "zhangsan@example.com",
      "highest_degree": "本科",
      "city": "杭州",
      "expected_city": "杭州",
      "expected_position": "Java 后端",
      "skills": ["Java", "Spring"],
      "education": [
        {"school": "H 大学", "degree": "本科", "major": "计算机", "start": "2013-09", "end": "2017-06"}
      ],
      "work": [
        {"company": "A 公司", "title": "后端工程师", "content": "负责支付系统", "start": "2017-07", "end": "2021-06", "type": "full_time"}
      ],
      "project": []
    }
  ]
}
```

- JSON 顶层必须是导入 envelope；`records` 内元素的数组字段名固定为 `education` / `work` / `project`，不使用 `projects` 变体。
- `phone`、`email` 为明文输入接口，入库前按统一 Schema 加密存储（示例中的 `13800000000` 为明文占位，非掩码）。
- `source_channel` 批次级必填；`source_channel=referral` 时 `referrer` 可选但必须按 envelope 传递。
- **`referrer` 类型（正式冻结）**：推荐人标识，允许两种形态——工作区成员邮箱（优先匹配成员）或自由文本姓名（内部推荐人/员工姓名，STRING 类型，≤ 64 字符）；两者均作为内推归属统计依据（PRD F12）。同一批次内 `referrer` 必须一致（批次级），不允许混用。
- 记录字段无法确定时省略或标 `null`；数组无该经历用 `[]`。
- 未知字段：拒收并报错（不静默忽略）。

### 3.4 导入处理规则

- **查重**：导入前按姓名 + 手机/邮箱精确匹配（见 §3.5 归一化）。命中则提示合并，不自动覆盖。
- **幂等（扩展至全部上传格式）**：所有上传（doc/docx/txt/csv/json）统一使用 `workspace_id + upload_id` 识别同一次提交，使用 `workspace_id + 文件内容 hash + 导入模板版本 + source_channel` 识别同一业务输入。显式重新解析必须生成新的 `run_id` / revision，不得被内容 hash 去重；Celery 任务以 `run_id` 幂等执行，重复投递 / worker 重启 / 重试不产生重复候选人、简历、解析产物或索引写入。
- **错误处理**：单行错误不影响整批导入，逐行报告错误（行号 + 字段 + 原因）。
- **来源渠道**：导入时必须按 §3.3 envelope / multipart 元数据提供机器枚举 `referral` / `job_site` / `headhunter` / `campus` / `other`。
- **批量部分成功**：批内部分成功 / 部分失败时，成功行正常入库，失败行逐行报告，返回 `batch_id` 供前端展示进度与 retry。CSV/JSON 每行生成稳定的 `row_hash`；重试只处理失败 `row_hash`，已成功行不得重新创建候选人或 revision。

### 3.5 查重字段归一化

- `phone`：去除空格、`+86` 前缀、全角数字转半角后取哈希比对。
- `email`：去除首尾空白、小写化后取哈希比对。
- 查重逻辑：**姓名 +（phone 或 email）任一命中**即视为重复候选；多条命中时全部列出，由 HR 选择合并目标。
- 软删除记录仍参与精确查重，但只返回「已删除记录，可恢复或合并」提示，不出现在搜索与普通列表；只有完成硬删除 / 加密擦除并保留 tombstone 后才释放唯一身份。跨池（已面试未通过 / 入职员工库）命中时提示池归属与历史面试记录（见 PRD F15 查重联动）。

### 3.6 skills 数组归一化

- `skills` 是无序集合，不按数组顺序评分；去除重复项后按固定 canonical dictionary 做别名归一化（例如 `Spring Boot` → `SpringBoot`）。dictionary 版本记录在评测 bundle 与 schema 版本中。
- 预测集合与标准集合的交集为 TP，预测独有项为 FP，标准独有项为 FN；集合为空时按 §1 的 `null` / `[]` 语义处理。

## 4. 待确认项

- 已定：CSV 仅用汇总文本（`max_education_desc` / `max_work_desc`），不展平结构化数组；教育/工作/项目结构化数组仅 JSON 导入支持（见 §3 表达能力差异注）。
- `max_education_desc` / `max_work_desc` 是 CSV 导入专用汇总字段，不属于候选人结构化 Schema；入库到 `import_summary.education` / `import_summary.work`，同时生成 IR / 检索文本，但不计入结构化字段 F1。
- 列名与枚举值已在本版冻结；若后续需变更，必须提升 schema 版本并显式兼容或拒绝旧版本。
