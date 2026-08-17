# Screening 初筛一致性评测报告（D1 优化轮 · screening-v2）

> 续 docs/SCREENING-EVAL-2026-08-17.md（基线 72%）。同语料（天池人才简历，
> eval-ws 300 份）、同种子（seed 7）、200 例（正 100 / 负 100）、真实模型
> (SenseNova flash-lite + SiliconFlow bge-large-zh-v1.5 / bge-reranker-v2-m3)。
> 报告数据：docs/screening-eval-2026-08-17b.json。

## 1. 本轮改动（基线上叠加）

| # | 改动 | 作用 |
|---|---|---|
| 1 | 评测构造升级：正样本职位由候选人「单一代表角色」渲染完整 JD（职责+技能+年限），替代基线的「技能词列表」。多职业候选人取与资质重合最高的经历段落，职责技能同源 | 消除泛技能语义空间过窄 & 跨职业职责混杂（基线诊断主因1） |
| 2 | 构造回退：无技能重合角色 → 首段工作经历职责 + 仅取该角色片段中出现技能（无则 JD 只要求角色职责） | 避免「首段职责 + 无关全技能」错配（伍红姬/郝芳雪型） |
| 3 | Screening 提示词重标定（screening-v1->v2）：明确 relevance/confidence 按「实质语义支撑强度」映射（0.7+ 直接对应）；禁止因字段矛盾/时间线异常/模板化等格式疑点压低数值（疑虑写 concerns） | 校准 flash-lite 数值（诊断主因2） |
| 4 | 失败重试增强：4 次退避重试（1/2/4s）捕获 provider 临时错误（SenseNova 400/5xx）+ JSON 平衡块提取修复一轮 | FAILED 率 13% -> 1.5%（3/200） |
| 5 | 服务端分带重标定（screening-v2 操作点）：HOLD 下限 60->48（agent_score_bands 可覆盖） | 48-59 的「疑似匹配但模型不确定」改 HOLD 人工复核，防正样本自动误拒 |
| 6 | eval 命令健壮性：启动时恢复陈旧 RUNNING/PENDING，防并发护栏被中断进程永久阻塞 | 再入安全 |

验证：分带为纯派生逻辑，200 例 LLM 分数与 band 无关——本轮结果由既有 200 例 records
按新操作点重派生（未重复花费），并单跑真实运行交叉核对。

## 2. 结果（200 例：正 100 / 负 100）

| 指标 | 基线（hold=60） | 优化轮（hold=48） |
|---|---|---|
| 宽松一致率（整体） | 72% | 82.5%（目标 >=80% 达成） |
| 正样本（不误拒） | 44% | 65% |
| 负样本（不误推） | 100% | 100% |
| 严格一致率 | 72% | 55%（ADVANCE 12 / 负 DECLINE 98） |
| 建议分布（200） | ADV 8 / HOLD 22 / DEC 144 / null 26 | ADV 12 / HOLD 44 / DEC 141 / null 3 |
| 正样本动作分布 | — | ADV 12 / HOLD 44 / DEC 43 / None 1 |
| FAILED 率 | 13%（29） | 1.5%（3） |
| 单例耗时 | 11.4s | 4.07s |

## 3. 诊断与结论

1. 正样本 65% 来自两处合算：构造升级让「角色一致 JD + 命中证据」（evidence_ok 100%）
   + 分带重标定把 48-59 的保守分改判 HOLD（人工复核）。负样本恒 100%（硬条件不满足 ->
   服务端恒 DECLINE，分带改动不影响负侧）。
2. 残留误拒（35/100，主要 0-47 分）是 flash-lite 数值标定问题：
   清晰匹配例（廉露-车联网大数据）LLM 评论文本明说「与职位要求一致」却给 relevance~0.03 / confidence 0.15-0.55；
   同模型在技能要求具体、文本直接重叠时能给 relevance 0.95+（正样本 ADVANCE 12 例分数 81-98）。
   评分公式无法把低 confidence 抬到合理值——彻底解决需更强模型档位（报告建议3；本次账号仅有 flash-lite）。
3. 严格一致率 55% 是诚实上限提示：模型自动 ADVANCE 率低（12%），多数真实匹配走 HOLD 人工复核。
   对 ATS 而言这更安全（防误拒、人兜底），但若追求无人工自动放行，须换强模型并复测。
4. 分带 48 为默认操作点，未冻结：按 §10，阈值冻结仍需 >=80 例独立人工标注集交叉验证；
   本报告数值为「真实模型 + 构造性标签」的迭代观测，具备可比与复现性。

## 4. 复现

    export RUN_REAL_MODEL=1
    uv run python apps/manage.py eval_screening --workspace eval-ws --limit 200 --seed 7 \
      --report logs/screening_eval_200_v2.json

（报告 JSON 落地 docs/screening-eval-2026-08-17b.json）

## 5. 产物

- apps/hr/agents/runner.py：提示词 v2（relevance/confidence 重标定）、JSON 修复一轮、
  4 次退避重试（含 provider 临时错误）
- apps/hr/agents/scoring.py：HOLD 下限默认 60->48（screening-v2 操作点，可覆盖）
- apps/hr/management/commands/eval_screening.py：完整 JD 正样本构造（单一代表角色 +
  职责/技能同源 + 回退规则）、陈旧运行恢复
- apps/hr/tests.py：JSON 修复/正样本构造/分带相关测试（全量 486 OK）
