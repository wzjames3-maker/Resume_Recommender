# RAG v2 完成结果审查修复计划

> 状态：**实施完成（F2/F1/F4-F7/F3 提交 7c11df7..ffcbd75；F8/F9 提交 3211036/2cee880）；复审修复（P2-A/B/C + P3-1~5）已提交；后续修复计划已执行（P1 超阈值后置过滤/P2 PII 日志顺序/P2 评测除零/P3 sparse 6/P3 Termbase Job 聚合），实测基线 418/418，评测脚本假 key 端到端跑通无崩溃**
> 依据：v2 完成结果审查（本会话逐项锚点复核）+ `installer/eval_v2_report.txt` 逐格比对 + git 考古（对照 `be6e659` 实施前基线）
> 基线（本次实测，非采信声明）：HANDOFF §1.1 命令口径 393/393 PASS；`common.tests` 10/10 PASS（合计 403）；`ruff check apps/hr` 干净；`makemigrations --check` 无漂移
> 纪律：每任务独立提交（中文 Conventional Commits）；不运行真实模型脚本（SENSENOVA/SILICONFLOW key 步骤一律项目方执行）；不 DROP DATABASE test_maxkb；--keepdb

---

## 1. 已确认问题清单

> 编号以本文档为准。相对上轮审查报告的变化：原「P2-2 文档三处」经 git 对照 **be6e659** 后升级拆分为 P2-2（行为变更，新发现）/ P2-3（措辞失实）/ P2-4（基线口径）。

### P2-1 模式 B（Skill-AND）不接结构化预筛，硬条件丢失

- **位置**：`apps/hr/services/resume_search.py:391`（`if mode in ("phrase", "hybrid") and hard:`）；`:213`（`_search_skill_and` 签名无 `document_ids`）；`:371-376`（auto 模式 LLM 解析出 ≥2 技能即转 skills 模式）
- **现象**：查询「会 python 和 java 的 5 年以上北京候选人」-> auto 判定 skills 模式 -> 预筛块不执行，年限/学历/城市槽只进 `meta.slots` 不参与过滤，不满足条件的候选人照常返回。
- **判定**：与 v2 设计 §3 路由图「conditional -> L1 结构化层（保证 G1）」意图不符；模式 A（phrase/hybrid）已接、模式 B 未接，实现不对称。
- **影响**：复合查询（技能 + 硬条件）精确度；G1「条件精确率 = 1.0」在 skills 模式下无法成立。

### P2-2 模式 A 聚合基准漂移：λ=0 并不回退旧行为（相对初审的升级发现）

- **位置**：当前 `resume_search.py:199`（`score = max(_para_score(p) for p in ps) + _EVIDENCE_LAMBDA * math.log2(1 + len(ps))`）；实施前 `be6e659:apps/hr/services/resume_search.py:30-31,184`（`_RESUME_SCORE_MAX_WEIGHT=0.7 / _AVG_WEIGHT=0.3`，`score = 0.7*max + 0.3*avg`）
- **现象**：v2 将模式 A 聚合基准从 `0.7*max+0.3*avg` 换成了纯 `max`。λ=0 时得分 = 纯 max ≠ 旧行为。
- **后果链**（均已逐项核实）：
  1. README-hr「λ=0.15（置 0 回退旧行为）」「λ 默认置 0（机制保留）」的**回退承诺落空**；
  2. `tests.py:3925` T3 测试注释「λ=0 恢复旧排序」语义错误（测试数据 0.90 vs 0.89/0.88 在两种公式下恰好同序，断言碰巧通过）；
  3. spec §9.4 偏差表（`2026-08-15-hr-resume-search-design.md:335`）「置 0 回退 0.7*max+0.3*avg」与实现矛盾——该行写的是**意图**，代码没兑现；
  4. λ 消融（eval_v2_report PASS B）的对照臂是纯 max，**不是** C 阶段审计基线的 0.7max+0.3avg；「λ=0 与审计基线持平 0.92」是两公式在此锚点集上的巧合相等，不是机制等价的证据。
- **根因**：v2 实施计划 T3 把旧行为误描述为「最高段分」（纯 max），实现照计划落地，旧公式的 0.3*avg 项被静默丢弃；T8 文档同步时从 v1 spec 抄回了 0.7max+0.3avg 字样，反而暴露矛盾。
- **判定**：未声明的确定性排序行为变更 + 回滚语义（λ=0）失效。属 P2（无功能故障：12 锚点上两公式 recall@5 均 0.92，风险低），但必须二选一收敛：恢复基准（推荐，F2）或全面改口并记偏差（备选）。

### P2-3 λ 消融结论措辞与报告数据不符（「全面下降/全面劣于」失实）

- **位置**：`resume_search.py:35-37` 注释；`README-hr.md:191`；`HANDOFF.md:154`
- **判定依据**（eval_v2_report.txt PASS A vs PASS B 逐格比对，12 个指标格中 **3 格 λ=0.15 更优**）：
  - RRF（无 rerank）recall@5：**0.75 > 0.67**（λ=0.15 更优）
  - RRF+rerank Top-1：**0.67 > 0.58**（λ=0.15 更优）
  - RRF+rerank MRR：**0.705 > 0.680**（λ=0.15 更优）
  - 其余 9 格 λ=0 更优（含主指标：dense recall@5 0.75→0.67、RRF+rerank recall@5 0.92→0.83）
- **结论本身仍成立**（综合劣于、主指标下降、样本仅 12 锚点不足显著判定），但「全面」二字与留档证据矛盾，损害证据链精度；G4（规模验证）正是为此保留裁决。

### P2-4 基线口径 403 不可复现 + HANDOFF 两处滞后

- **位置**：`HANDOFF.md:31`（§1.1 测试命令不含 `common.tests`）；`:60`（§3 标题仍写「383/383，HR 349」）；`:183`（基线演进止于 383）
- **事实**：`apps/common/tests.py` 为本轮内核修复**新增文件**（提交 8638956/29222d2，10 个测试方法）；照 HANDOFF §1.1 命令实测 = 393/393，补 `common.tests` 后 = 403。各处声称「四 app + ops 403/403」口径漏列 common，按文档复现会以为少 10 个测试。
- **补充构成**（实测）：393 = 383（T8 时点）+ 内核修复在四 app+ops 内净增 10 例；403 = 393 + common 10 例。

### P3-1 预筛候选人计数可能重复

- **位置**：`resume_search.py:405-410`（`values_list("id")` 前置技能 `skill_rows__skill_norm__in` 联表查询无 `.distinct()`）
- **影响**：候选人命中多个查询技能时重复计数，仅污染 `meta.prefilter.candidate_count` 展示；下游 `ResumeFile` 查询与 `document_id__in` 自然去重，结果集正确。

### P3-2 姓名通道置顶项缺 rank / 后续 rank 不重排

- **位置**：`resume_search.py:524-530`（name_hits 构造无 rank）；`:555`（structured 路 prepend）；`:629-634`（混合路 prepend）；对照 `:570`（name_match 路有 rank）
- **影响**：API 项 rank 字段缺失或与最终位置不符；纯展示层。

### P3-3 λ / 预筛阈值为模块常量，不满足「可配」要求

- **位置**：`resume_search.py:38`（`_EVIDENCE_LAMBDA = 0`）、`:40`（`_PREFILTER_MAX = 2000`）
- **判定**：实施计划明文「阈值可配」「置 0 即回退（不改代码）」；现状调参需改代码发版。λ 当前默认已是目标值，影响小，但 G4 若裁决重开 λ=0.15，需要不改代码的开关。

### P3-4 计划点名的两项测试缺失

- 预筛 > 阈值跳过路径（`prefilter_skipped`）无测试；
- 城市「北京/北京市」归一无端到端测试（`resume_search.py:399` 三形态 Q 无覆盖；单元级 `test_extract_slots_degree_and_city` 不覆盖 SQL 匹配层）。

### P3-5 评测脚本结构化基线不过滤条件 + typed 指标缺 conditional 精确率

- **位置**：`installer/resume_search_eval.py:150-174`（结构化基线只处理 `cond["skills"]`，years/degree/city 读都没读）；`:84-85`（city 锚点 `structured` 字典无 city 键）；汇总只有 recall/MRR 无 precision
- **影响**：typed conditional 锚点的结构化基线恒为 0（无意义）；规模验证计划 G3「conditional 条件精确率 = 1.0」**当前 runner 产不出该指标**，验收依赖落空。

### P3-6 `installer/_demo_pipeline.py` ruff 2 错（存量）

- **位置**：`:10` F401（`mask_pii` 导入未用）、`:61` E402（`import urllib.request` 不在顶部）
- **判定**：本轮未触碰该文件（`git log be6e659..HEAD` 为空），系存量；与「installer 干净」的历史口径不符，顺手修。

---

## 2. 修复任务（F1-F9）

> 提交顺序 = 依赖顺序：F2 先定聚合语义 -> F1 -> 小修（F4/F5/F6/F7）-> F3 文档汇总（引用最终行为）-> F8 评测脚本 -> F9 清理。

### F2 `fix(hr): 模式 A 聚合恢复 0.7*max+0.3*avg 基准，兑现 λ=0 回退旧行为承诺`（P2-2，先做）

**文件**：`apps/hr/services/resume_search.py`、`apps/hr/tests.py`
**改动**：
1. 恢复常量 `_RESUME_SCORE_MAX_WEIGHT = 0.7`、`_RESUME_SCORE_AVG_WEIGHT = 0.3`（对齐 be6e659:30-31）；
2. `_aggregate` 得分改为：
   ```
   base = 0.7 * max(段分) + 0.3 * (段分均值)
   score = base + _EVIDENCE_LAMBDA * math.log2(1 + 命中段数)
   ```
   λ=0 时严格等价实施前行为（0.7max+0.3avg）；λ 语义（多段证据加分）不变；
3. 修正 `tests.py:3925` 注释，并**新增公式锁定断言**：λ=0 时 `score == 0.7*max+0.3*avg`（精确到常数，防止再次漂移）；既有双 patch 用例（0.15/0）复核通过（0.9 单段 vs 0.89/0.88 双段在两种 λ 下胜负关系不变，已手算验证）；
4. `meta.aggregation` 补 `base_formula: "0.7max+0.3avg"`，便于线上核对。
**风险与依据**：C 阶段审计基线（0.7max+0.3avg）与本轮 PASS B（纯 max）在 12 锚点上 recall@5 同为 0.92，恢复基准行为风险低；规模验证 G4 复测兜底。
**备选（不推荐）**：保持纯 max，则须改 README 承诺、代码注释、T3 测试注释、§9.4 行，并在偏差表新增「聚合基准由 0.7max+0.3avg 改为纯 max」条目——回退语义永久丢失，λ 消融历史结论的解释链也要重写。

### F1 `fix(hr): 模式 B 接入结构化预筛（年限/学历/城市硬条件不丢失）`（P2-1）

**文件**：`apps/hr/services/resume_search.py`、`apps/hr/tests.py`
**改动**：
1. 预筛块门条件 `mode in ("phrase", "hybrid")` 扩为 `mode in ("phrase", "hybrid", "skills")`；
2. **skills 模式下技能维度不进预筛**（只保留年限/学历/城市）：技能命中判定交给模式 B 自身的结构化路 + 语义路 OR 合并，避免与 `candidate_skill` EXISTS 双重收窄、回填稀疏期误杀（表空 guard 已有，稀疏表风险不同）；
3. `_search_skill_and(...)` 新增 `document_ids=None` 参数：
   - 逐技能 `_recall_dual(skill, ..., document_ids=document_ids)`（语义路限定预筛集）；
   - 结构化路 `ResumeFile` 查询追加 `document_id__in=document_ids`（候选人与预筛集求交）；
   - `structured_only` 补位继承同一限定（由 doc 池天然限定）；
4. 显式 `dense` 模式**维持不接预筛**（消融纯净性，评测口径依赖），代码注释 + README/spec 声明该契约；
5. 预筛空 + skills 模式 -> 走既有 `prefilter_empty` 提前返回（不做语义兜底），meta 如实记录。
**测试**（新增 3 例）：
- 复合查询（mode="skills"，LLM stub 返回 2 技能 + 年限槽）：年限不满足的候选人即使技能命中也不返回；
- skills 模式 + 无满足条件候选人 -> `search_type == "prefilter_empty"`；
- 语义路召回集被限定（mock EmbeddingSearch 断言传入 query_set 含 document_id 过滤）。
**风险**：模式 B 召回池收窄 -> recall 可能下降（预期内：精确条件本就应过滤）；规模验证 typed/语义锚点复测覆盖。

### F4 `fix(hr): 预筛候选人计数去重`（P3-1）

**文件**：`resume_search.py`（`:405-410` 加 `.distinct()`）+ 测试 1 例（同一候选人命中 2 个查询技能 -> `candidate_count == 1`）。

### F5 `fix(hr): 姓名通道置顶后统一重排 rank`（P3-2）

**文件**：`resume_search.py`（`:555`、`:629-634` 两处 prepend 后 `for i, it in enumerate(items, 1): it["rank"] = i`；`:570` name_match 路保持）+ 测试 1 例（置顶后 rank 连续 1..n 且首项为 name 命中）。

### F6 `feat(hr): λ 与预筛阈值支持环境变量覆盖`（P3-3）

**文件**：`resume_search.py`、`README-hr.md`
**改动**：模块加载时读取 `MAXKB_HR_EVIDENCE_LAMBDA`（float）与 `MAXKB_HR_MAX_PREFILTER`（int），解析失败回退默认并 `maxkb_logger.warning`；不改 DB 配置（避免迁移与后台界面联动，配置面留 P3 合并调用轮）。README「运行要点」记录两个变量。G4 若裁决重开 λ=0.15：改 env 重启即可，无需发版。
**测试** 1 例：patch 模块常量仍生效（兼容现状测试写法），env 解析函数单测（合法/非法值）。

### F7 `test(hr): 补预筛超阈值与城市归一端到端`（P3-4）

1. `patch _PREFILTER_MAX=1` + 2 份简历带硬条件 -> `prefilter_skipped=True`、`applied=False`、走全量语义（search_type 为 hybrid_rrf*）；
2. 候选人 `current_city="北京市"`，查询「北京 5年以上」命中；反向（存「北京」查「北京市」）亦命中。

### F3 `docs(hr): 修正 λ 消融措辞、回退语义与基线口径`（P2-3/P2-4 + F1/F2/F6 文档同步）

**文件**：`README-hr.md`、`HANDOFF.md`、`docs/superpowers/specs/2026-08-15-hr-resume-search-design.md`
**改动**：
1. **措辞**（3 处）：`resume_search.py:35-37` 注释、`README:191`、`HANDOFF:154` ——「全面下降/全面劣于」改为「综合劣于：recall@5 主指标全面下降（dense 0.75→0.67、RRF+rerank 0.92→0.83），但 RRF 无 rerank 的 recall@5（0.67→0.75）与 RRF+rerank 的 Top-1/MRR（0.58→0.67 / 0.680→0.705）三格回升；样本 12 锚点不足显著判定，默认保守 0，待规模验证 G4 裁决」；
2. **README:182**：λ 描述改为「默认 0（F2 后 λ=0 = 旧行为 0.7max+0.3avg）；`MAXKB_HR_EVIDENCE_LAMBDA` 可调」；
3. **spec §9.4:335**：证据合成行备注改为「λ=0 严格回退 0.7*max+0.3*avg（F2 恢复基准）」并补偏差表两行：模式 B 预筛接入（F1）、dense 模式不接预筛契约；
4. **HANDOFF:31**：命令补 `common.tests`（附注释「403 口径 = 四 app+ops 393 + common 10」）；**:60** §3 标题更新为「403/403（HR 349 + 内核 44 + common 10）」；**:183** 基线演进货尾追加 393/403 构成说明。

### F8 `feat(installer): 评测脚本结构化基线支持条件过滤 + conditional 精确率指标`（P3-5）

**文件**：`installer/resume_search_eval.py`
**改动**：
1. 结构化基线按 `cond` 全字段过滤：years（`>=`，NULL 视为不匹配，与预筛「纳入」口径的差异在输出注明）、degree（词表层级）、city（归一匹配），skills 维持现状；
2. `build_typed_anchors` city 锚点 `structured` 补 `"city"` 键；
3. typed 汇总新增 **conditional 精确率**：对返回 `items` 逐项核对候选人 years/degree/city 是否满足锚点条件，输出 precision（G3 验收指标 =1.0 的直接产出）；
4. 仅改脚本，服务代码零改动；真实运行由项目方执行（含 key）。

### F9 `chore(installer): 清理 _demo_pipeline ruff 告警`（P3-6）

`uv run ruff check installer/_demo_pipeline.py --fix`（F401 自动删 `mask_pii` 导入）+ `import urllib.request` 上移文件顶部；人工跑一遍脚本 `--help`/dry 路径确认不破坏（该脚本无测试，改动仅限 import 位置）。

---

## 3. 执行顺序与依赖

```
F2（聚合语义定调） -> F1（模式 B 预筛） -> F4 -> F5 -> F6 -> F7（测试批）
-> F3（文档汇总，引用 F1/F2/F6 最终行为） -> F8（评测脚本） -> F9（清理）
```

F1 依赖 F2 之后提交仅为评审顺序（两者无代码冲突）；F3 必须最后（引用最终行为）。

## 4. 验收标准

- 全量测试（**修正后命令**：`hr.tests application.tests knowledge.tests models_provider.tests ops.tests common.tests`）403 + 新增（预计 +7~10 例）全绿；
- `uv run ruff check apps/hr installer` 干净（F9 后 installer 归零）；
- `makemigrations --check --dry-run` 无漂移（本轮全部无模型变更，0018 之后无新迁移）；
- P2-1/P2-2 的真实效果复测并入规模验证计划（G4 λ 裁决 + typed conditional 精确率），不在本轮单测内伪造结论；
- 文档三处失实（P2-2 §9.4 行 / P2-3 措辞 / P2-4 口径）修后与代码事实逐字对得上。

## 5. 需 owner 拍板的 2 个决策点

1. **F2 方案**：推荐 a（恢复 0.7max+0.3avg 基准，兑现回退承诺）；备选 b（保持纯 max，全面改口 + 偏差记录）。
2. **F1 范围**：skills 模式预筛只接年限/学历/城市（推荐，理由见 F1.2）；备选为全量接入（含技能 EXISTS，收窄更激进，回填稀疏期有误杀风险）。

## 6. 不修项与理由

- **dense 显式模式不接预筛**：消融纯净性（评测口径依赖），以注释 + 文档声明契约（并入 F1.4/F3.3）；
- **typed 锚点 targets 单目标性**（conditional 锚点 recall 只对单一目标）：评测口径已知限制，规模验证 §3 已有锚点体系设计，不在本轮修；
- **HRConfig 化的运行时配置面板**：需要迁移 + 后台界面，并入 P3 合并调用轮，本轮 env 变量够用（F6）；
- **内核 214 处 ruff 历史告警**：维持最小 diff 纪律不动（P3-15 立项决策留给 owner）。
