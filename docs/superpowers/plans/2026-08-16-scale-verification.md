# 规模验证计划（档位 3：200 份 + 生产对照）

> 日期：2026-08-16
> 状态：计划（命令级，随时可执行；执行需真实模型 key，由项目方授权后运行）
> 依据：PRD §9 档位 3（200 份，一直后置）；v2 设计 §6（分类型评测）；HANDOFF（基线 403/403，评测工具已升级）
> 前置：`production_landing.sh` 落地步骤与本计划互不阻塞；本计划使用 dev 库（maxkb）+ 数据集 192080.tar

---

## 1. 目标与验收标准

| # | 目标 | 验收标准 |
| --- | --- | --- |
| G1 | 全链路稳定性 | 200 份入库失败率 = 0（重试后）；无静默丢失（每份都有 document_id + 段落 + 向量） |
| G2 | 性能基线 | 入库吞吐（份/分钟）、检索延迟 p50/p95 落表，作为生产容量参考 |
| G3 | typed 评测统计意义 | lookup MRR、conditional 条件精确率 = 1.0、browse/skill-AND 与既有基线可比 |
| G4 | λ 最终裁决 | 大样本消融：λ=0.15 vs 0 差异显著才重开，否则维持关闭并记录结论 |
| G5 | 成本受控 | 总 API 消耗 ≤ 预算表（见 §6），双 key 策略 |

## 2. 数据

- **档位 3 语料**：`/tmp/ds192080/label_studio.json`（2000 份 OCR 原文，仅用过 30 份）固定 seed 抽样 200 份；
- **生产对照（后置，项目方执行）**：真实 docx/txt 简历经 `production_landing.sh` 落地后跑同一评测；
- **两者关系**：合成语料测稳定性/口径，生产数据测真实形态（技能/学历字段非空时 T5/T7 才真正生效）。

## 3. 执行步骤（命令级）

### 3.1 语料抽样与入库（需新增脚本 `installer/resume_ingest_n.py`）

脚本规格：
- 参数：`count`（默认 200）、`seed`（默认 42）、`--workspace`（默认 default）；
- 数据源：label_studio.json 的 `data.text`（与 resume_splitter_dataset30.py 同源）；
- 流程：sanitize → `split_resume_text`（T1 掩码前置）→ `index_resume`（T2 title-chunks）→ `embedding_by_document.run` 同步向量化；
- 统计：每份 path/llm_calls/段落数/耗时；汇总：成功/失败/重试/吞吐（份/分钟）；
- 幂等：按 `sha256` 跳过已入库（复用 resume_ingest_30.py 模式，抽取公共参数化版本）；
- 失败处理：单份失败记日志继续，最终失败率 > 0 则进程退出码非 0。

执行：
```bash
export MAXKB_CONFIG_TYPE=ENV MAXKB_DB_NAME=maxkb MAXKB_DB_HOST=127.0.0.1 MAXKB_DB_PORT=5432 MAXKB_DB_USER=postgres MAXKB_DB_PASSWORD=... MAXKB_DB_ENGINE=django.db.backends.postgresql MAXKB_DB_MAX_OVERFLOW=10 MAXKB_REDIS_HOST=127.0.0.1 MAXKB_REDIS_PORT=6379 MAXKB_REDIS_PASSWORD= MAXKB_REDIS_DB=0 MAXKB_REDIS_MAX_CONNECTIONS=10
SENSENOVA_API_KEY=<key1> .venv/bin/python installer/resume_ingest_n.py 200 42 > /tmp/ingest200.log 2>&1
tail -20 /tmp/ingest200.log   # 确认失败率与吞吐
```

### 3.2 typed 评测（两轮 λ 消融）

```bash
# 第一轮 λ=0.15（临时改 _EVIDENCE_LAMBDA 或等待脚本支持 --lambda 参数）
SENSENOVA_API_KEY=<key1> .venv/bin/python /tmp/eval_v2.py > /tmp/eval200_a.txt 2>&1
# 第二轮 λ=0（默认）
# 复用 /tmp/eval_v2.py 包装（先 λ=0.15 后 λ=0），或 eval 脚本增加 --lambda 参数
grep -A 8 '汇总' /tmp/eval200_a.txt /tmp/eval200_b.txt
```

### 3.3 性能测量

- 入库吞吐：由 3.1 汇总输出；
- 检索延迟：对 50 个随机 typed 锚点逐个计时（脚本内 `time.time()` 包 `search_resumes`），输出 p50/p95；
- 记录 DB 侧：`embedding` 表行数、`paragraph` 行数、hnsw 索引存在性（`SELECT indexname FROM pg_indexes WHERE tablename='embedding'`）。

## 4. 指标口径（与既有审计一致）

- recall@5 / recall@3 / Top-1 / MRR：沿用 resume_search_eval.py 定义（MRR = 全部相关目标 1/rank 均值，多目标锚点数值系统性偏低，仅横向可比）；
- conditional 精确率：typed conditional 锚点中「目标简历在 top-5 且满足全部条件」的比例，目标 = 1.0（SQL 预筛保证）；
- lookup MRR：typed lookup 锚点（姓名）下 MRR；
- 吞吐：份/分钟（含 LLM 切片 + 向量化）；延迟：ms（p50/p95）。

## 5. 决策点（计划产出后按数据定）

| 决策 | 判定规则 | 默认 |
| --- | --- | --- |
| λ 重开 | 大样本下 λ=0.15 在 RRF+rerank 的 MRR/recall@5 上显著优于 λ=0（≥5 锚点翻转）才开 | 维持 0 |
| _PREFILTER_MAX | conditional 预筛空比例过高（>30%）则考虑提阈值或分页预筛 | 2000 |
| T5/T7 实测 | 生产数据 skills 非空后跑 backfill，结构化基线从 0 抬起才生效 | 待生产数据 |
| 语料形态 | 若 OCR 语料与生产 docx/txt 差异导致结论不可迁移，则生产数据优先 | 生产优先 |

## 6. 预算与时间

| 项 | 用量估算 | 来源 |
| --- | --- | --- |
| SenseNova LLM | 200（切片）+ 评测 ~400（12+50 锚点 × 4 模式 × 2 轮）≈ 600 次 | key1 余 ~1380 + key2 全新 1500 |
| SiliconFlow embedding | 200 份 × ~10 段 ÷ 5/批 ≈ 400 次 | 无配额提示 |
| SiliconFlow rerank | 评测 ~50 次 | 同上 |
| 时长 | 入库 ~15-25 分钟（30 份 110s → 200 份 ~15 分钟）+ 评测 ~10 分钟 | 实测外推 |
| 建议 | 低峰执行；key1 耗尽自动切 key2（脚本支持 `SENSENOVA_API_KEY2` 环境变量可选） | — |

## 7. 风险与回滚

| 风险 | 缓解 |
| --- | --- |
| OCR 语料与业务 docx/txt 形态差异 | 结论标注「合成语料口径」，生产数据复测为准 |
| 200 份污染 dev 库 | dev 库可重建（`DROP DATABASE maxkb` 后从 TEMPLATE 重建，勿动 test_maxkb） |
| key 耗尽中断 | 双 key + 断点续跑（ingest 幂等按 sha256 跳过） |
| embedding 批失败 | 单份重试一次；仍失败记日志并计入失败率（G1 验收） |

## 8. 产出物

1. `installer/resume_ingest_n.py`（新增，参数化入库脚本）；
2. 报告 `docs/superpowers/audits/2026-08-16-scale-verification.md`：稳定性/性能/typed 指标/λ 决策/成本实际消耗；
3. 原始输出留档 `installer/ingest200.log`、`installer/eval200_*.txt`（未跟踪，按惯例）。

## 9. 前置依赖

- 评测工具已就绪：`resume_search_eval.py --typed N`（0963d04）；
- 待办：`resume_ingest_n.py` 实现（规格见 §3.1，实现后需 dry-run 验证 1 份再全量）；
- 待办（可选）：eval 脚本 `--lambda` 参数（当前用 /tmp/eval_v2.py 包装实现双轮）。
