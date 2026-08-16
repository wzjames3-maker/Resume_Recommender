# 规模验证计划 v2（档位 3：200 份 + 生产对照）——审查修订版

> 日期：2026-08-16
> 状态：计划 v2（已过独立审查，修订 7 处；命令级可执行，执行需真实模型 key，由项目方授权后运行）
> 依据：PRD §9 档位 3；v2 设计 §6；HANDOFF（基线 403/403）
> 审查记录（v2 相对 v1）：① 新增 §3 锚点体系（修复锚点-语料不匹配，v1 致命缺口）；② 新增 §2.2 对照组设计；③ 新增 §4.1 语料预检（conditional 锚点稀缺兜底）；④ G1 放宽为「重试后 ≤1% + 无静默丢失」；⑤ ingest 规格补单份 60s 超时 + 重试 1 次；⑥ §7 预算按实际锚点数重算；⑦ 新增 §10 checklist 与附录 A 报告模板

---

## 1. 目标与验收标准

| # | 目标 | 验收标准 |
| --- | --- | --- |
| G1 | 全链路稳定性 | 200 份入库：单份 60s 超时 + 重试 1 次后失败率 ≤ 1%；无静默丢失（每份都有 document_id + 段落 + 向量，入库后核验计数一致） |
| G2 | 性能基线 | 入库吞吐（份/分钟）、检索总延迟 p50/p95 落表（meta.elapsed_ms.total，含 rerank） |
| G3 | typed 评测统计意义 | conditional 锚点 ≥ 20 条且条件精确率 = 1.0；lookup MRR 落表；语义锚点 ≥ 30 条（见 §3.3） |
| G4 | λ 最终裁决 | 大样本消融：λ=0.15 在 RRF+rerank 的 MRR/recall@5 上显著优于 λ=0（≥5 锚点翻转）才重开，否则维持关闭并记录 |
| G5 | 成本受控 | 总 API 消耗 ≤ §7 预算表（双 key，key1 耗尽切 key2） |
| G6 | 语料-锚点匹配 | 全部评测锚点的 targets 均存在于本轮语料（入库后脚本自检，缺失即中止并报错） |

## 2. 数据与对照组设计

### 2.1 语料

- 来源：/tmp/ds192080/label_studio.json（2000 份已脱敏 OCR 文本，合规：天池训练数据、README 声明已脱敏）；
- 抽样：seed=42 固定取 200 份（可复现）；长度过滤与 dataset30 一致（≥20 字）；
- 命名策略：入库文件名 ls_{idx:04d}.txt（idx = 抽样序号），与锚点生成共用同一抽样序号——保证锚点 targets 可回溯；
- 候选结构化字段：由 parse_resume_text 抽取（与现有链路一致），入库后统计各字段非空率。

### 2.2 对照组设计（口径声明，必须如实标注）

| 对比项 | 本轮（200 份） | 结论边界 |
| --- | --- | --- |
| title-chunks 前后对照 | 不可做（全部用新代码入库，无旧 chunks 版本） | 仅保留 30 份语料上已完成的对比（重建前后 recall@5 0.92 持平）；200 份只验证绝对水平与稳定性 |
| λ 消融 | 可做（同语料同进程双轮，仅改 λ） | 有效；注意 Skill-AND 列的 LLM 技能分解随机性（见 §5 方差处置） |
| typed 预筛 | 可做（SQL 保证精确率） | conditional 精确率 = 1.0 为结构性验证，与语料无关 |
| 与 30 份审计基线横向比 | 语料不同（generated vs OCR） | 仅作参考，不直接判定优劣；报告标注「不同语料口径」 |
| 生产对照 | 项目方真实数据（后置） | 生产数据为准，合成语料结论需生产复测 |

## 3. 锚点体系（v2 新增，修复锚点-语料不匹配）

### 3.1 lookup（自动，无标注）
- 来源：抽样候选的 name；生成规则同 build_typed_anchors；目标 = 该候选的 ls_*.txt。

### 3.2 conditional（自动，无标注）
- 来源：抽样候选的 years_experience / highest_degree / current_city 非空字段 → 查询「X年以上 / 学历词 / 城市词」；
- 预检兜底（§4.1）：若全部条件锚点 < 20 条（字段抽取率低），追加「确定性区间锚点」：从字段非空候选集中取年限分位数（P25/P50/P75）生成「≥n 年」查询并标注全部满足条件的候选为目标（脚本自动判定，无需人工）。

### 3.3 语义锚点（browse / skill-AND，需生成，二选一）

方案 A（推荐，LLM 辅助 + 人工抽检）：
1. 对 30-50 份抽样简历，LLM 依据切片内容生成 1-2 条「找这类人」查询（prompt 限定：描述岗位/技能/经验特征，禁止含姓名联系方式）；
2. 目标 = 该简历的 ls_*.txt；
3. 人工抽检 ≥ 10 条：剔除与简历内容不符的生成查询（防幻觉），抽检规则与记录写入报告；
4. 成本：30-100 次 LLM 调用（计入 §7）。

方案 B（人工标注，项目方）：由项目方对抽样简历人工编写 30 条语义查询（无需任何工具，但耗时）。

> 决策点（§6）：执行前确认 A 或 B；默认 A（可代为生成 + 抽检记录，抽检由项目方确认）。

### 3.4 锚点自检（G6）
- 评测脚本执行前：断言每个锚点 targets 至少 1 个存在于语料（ResumeFile.file_name 在已入库集合），缺失 > 0 即中止；
- 避免「锚点失效但评测静默通过」的假阳性（v1 12 锚点对 OCR 语料即属此类）。
## 4. 执行步骤

### 4.0 执行前 checklist（§10 逐项打勾）

### 4.1 语料预检（新增）

```bash
# 抽样 200 份文本后、入库前：
# 1) 统计抽取字段非空率（用 parse_resume_text 干跑 20 份样本）
# 2) 若 years/degree/city 非空率 < 20% → 启动 §3.2 确定性区间锚点兜底
# 3) 确认 key 可用性与剩余额度（curl 一次 chat completions）
```

### 4.2 入库（新增脚本 installer/resume_ingest_n.py）

脚本规格：
- 参数：count（默认 200）、seed（默认 42）、--workspace（默认 default）、--dry-run（只打印计划不执行）；
- 数据源：label_studio.json 的 data.text，抽样序号即 ls_{idx:04d}.txt 命名；
- 流程（与现有链路完全一致）：sanitize → split_resume_text（T1 掩码前置，chat_fn 带 thinking=disabled）→ index_resume（T2 title-chunks）→ embedding_by_document.run 同步向量化；
- 超时与重试（P5）：单份整体 60s 超时（signal.alarm 或线程包装），超时/异常 → 重试 1 次；仍失败记日志计入失败率；
- 统计：每份 path/llm_calls/段落数/耗时；汇总：成功/失败/重试/吞吐（份/分钟）/超时次数；
- 幂等：按 sha256 跳过已入库（可断点续跑）；
- 退出码：失败率 > 1% 或存在静默丢失（段落数 = 0 却标记成功）→ 非 0。

```bash
export MAXKB_CONFIG_TYPE=ENV MAXKB_DB_NAME=maxkb MAXKB_DB_HOST=127.0.0.1 MAXKB_DB_PORT=5432 MAXKB_DB_USER=postgres MAXKB_DB_PASSWORD=... MAXKB_DB_ENGINE=django.db.backends.postgresql MAXKB_DB_MAX_OVERFLOW=10 MAXKB_REDIS_HOST=127.0.0.1 MAXKB_REDIS_PORT=6379 MAXKB_REDIS_PASSWORD= MAXKB_REDIS_DB=0 MAXKB_REDIS_MAX_CONNECTIONS=10
SENSENOVA_API_KEY=<key1> .venv/bin/python installer/resume_ingest_n.py 200 42 > /tmp/ingest200.log 2>&1
tail -25 /tmp/ingest200.log   # 失败率/吞吐/超时
```

### 4.3 锚点生成（§3）+ 自检（脚本已就位：installer/resume_search_anchor_gen.py，方案 A）

```bash
# 语义锚点生成（LLM 切片 + LLM 生成查询；抽样与入库同 seed，targets 必在 200 份内）
SENSENOVA_API_KEY=<key1> .venv/bin/python installer/resume_search_anchor_gen.py --count 40 --seed 42
# 输出：/tmp/eval200_semantic_anchors.json + /tmp/anchor_review.txt（抽检清单）
# 人工抽检 ≥10 条：核对查询与简历内容相符，不符者从锚点 JSON 删除该条（防幻觉）
# G6 自检已内置评测脚本（check_anchors_grounded）：targets 未入库即退出码 3
```

### 4.4 typed 评测（两轮 λ 消融；脚本已就位：resume_search_eval.py --typed/--semantic-anchors/--latency）

```bash
# 双轮：λ 覆盖走环境变量（F6，替代包装脚本）；锚点 = 基础 12 + typed + 语义锚点
SENSENOVA_API_KEY=<key1> MAXKB_HR_EVIDENCE_LAMBDA=0.15 .venv/bin/python installer/resume_search_eval.py --typed 30 --semantic-anchors /tmp/eval200_semantic_anchors.json > /tmp/eval200_a.txt 2>&1
SENSENOVA_API_KEY=<key1> .venv/bin/python installer/resume_search_eval.py --typed 30 --semantic-anchors /tmp/eval200_semantic_anchors.json > /tmp/eval200_b.txt 2>&1
# Skill-AND 列方差处置（§5）：该模式再单独跑 2 次，取 3 次中位数
grep -A 10 '汇总' /tmp/eval200_a.txt /tmp/eval200_b.txt
# 注意：G6 自检要求全部 targets 已入库；语义锚点文件须先经抽检（§4.3）
```

### 4.5 性能测量（已内置评测脚本 --latency）

```bash
# 检索延迟：随机 50 锚点逐个计时（mode=auto，meta.elapsed_ms.total，含 rerank），输出 p50/p95；
# 同时输出 DB 核验：简历/段落/向量行数一致性 + 简历知识库 hnsw 索引存在性
SENSENOVA_API_KEY=<key1> .venv/bin/python installer/resume_search_eval.py --latency 50 > /tmp/eval200_latency.txt 2>&1
tail -20 /tmp/eval200_latency.txt
```

- 入库吞吐：4.2 汇总输出；

## 5. 指标口径与方差处置

- recall@5 / recall@3 / Top-1 / MRR：沿用 resume_search_eval.py 定义（MRR = 全部相关目标 1/rank 均值，仅横向可比）；
- conditional 精确率：top-5 内目标简历且满足全部条件 / 全部 conditional 锚点，目标 = 1.0；
- 方差处置：LLM 切片与技能分解非确定（temperature 0.1）→ ① 双轮 λ 对比只取 dense/RRF/RRF+rerank 三列（无 LLM 依赖，确定性）；② Skill-AND 列跑 3 次取中位数并标注 p25/p75；③ 报告附 seed、语料、key 使用清单，保证可复现；
- 吞吐：份/分钟（含 LLM 切片 + 向量化）；延迟：ms（p50/p95）。

## 6. 决策点

| 决策 | 判定规则 | 默认 |
| --- | --- | --- |
| 语义锚点方案 A/B | §3.3，执行前确认 | A（LLM 生成 + 项目方抽检 ≥10 条） |
| λ 重开 | 大样本下 λ=0.15 显著优于 λ=0（≥5 锚点翻转）才开 | 维持 0 |
| _PREFILTER_MAX | conditional 预筛空比例 > 30% 则提阈值或分页预筛 | 2000 |
| T5/T7 生效 | 生产数据 skills 非空后 backfill，结构化基线抬起 | 待生产 |
| 语料形态 | OCR 结论不可迁移时生产优先 | 生产优先 |

## 7. 预算与时间（按实际锚点数重算）

| 项 | 估算 | 说明 |
| --- | --- | --- |
| 切片 LLM | 200 + 重试余量 ≈ 230 次 | key1 |
| 语义锚点生成（方案 A） | 30-100 次 | key1 |
| 评测 LLM（Skill-AND/auto） | 锚点 ~100-250 × 3 轮 ≈ 300-750 次 | key1 耗尽切 key2 |
| embedding | 200 份 × ~10 段 ÷ 5/批 ≈ 400 次 | SiliconFlow |
| rerank | 评测 ~100-250 × 2-3 轮 ≈ 300-750 次 | SiliconFlow |
| 总 LLM | ~700-1100 次 | key1（余 ~1380）+ key2（1500）充足；若超预算：语义锚点改方案 B |
| 时长 | 入库 ~12-20 分钟（串行，LLM ~3.5s/份）+ 评测 ~15-25 分钟 | 合计 ~40-50 分钟 |

## 8. 风险与回滚

| 风险 | 缓解 |
| --- | --- |
| 锚点幻觉（方案 A LLM 生成查询与简历不符） | 人工抽检 ≥10 条 + 报告记录剔除清单 |
| OCR 语料与业务 docx/txt 形态差异 | 结论标注「合成语料口径」；生产复测为准 |
| 200 份污染 dev 库 | 可重建（DROP DATABASE maxkb 后重建，勿动 test_maxkb）；或按 ls_ 前缀清理（delete_resume_index 逐份） |
| key 耗尽中断 | 双 key + 幂等断点续跑 |
| embedding 挂起 | 单份 60s 超时 + 重试 1 次（§4.2） |
| 结构化字段抽取率低 | §3.2 确定性区间锚点兜底（预检触发） |

## 9. 产出物

1. installer/resume_ingest_n.py（参数化入库，含超时/重试/统计/自检；已就位）；
2. installer/resume_search_anchor_gen.py（语义锚点生成方案 A + 抽检清单；已就位）；
3. resume_search_eval.py 扩展：--typed / --semantic-anchors / --latency / G6 自检（已就位）；
4. 语义锚点清单 + 抽检记录（方案 A）；
5. 报告 docs/superpowers/audits/2026-08-16-scale-verification.md（模板见附录 A）；
6. 原始输出留档 installer/ingest200.log、installer/eval200_*.txt（未跟踪，按惯例）。

## 10. 执行前 checklist

- [ ] dev 库可达（pg_isready）、Redis 可达（redis-cli ping）；
- [ ] dev 库当前文档数/简历库状态记录（执行前基线，便于回滚判定）；
- [ ] key1/key2 可用性 curl 验证 + 剩余额度记录；
- [ ] label_studio.json 在位（/tmp/ds192080/）；磁盘余量 ≥ 2GB；
- [ ] 语义锚点方案 A/B 已确认；
- [ ] 语料预检（§4.1）完成，conditional 锚点数量满足 ≥20；
- [ ] 评测脚本与包装脚本就位（resume_search_eval.py --typed / /tmp/eval_v2.py）。

## 附录 A：报告模板

```
# 规模验证报告（档位 3，200 份）
> 日期 / 执行人 / key 使用清单（key1: n 次, key2: n 次）/ seed / 语料来源

## 1. 入库结果
| 总数 | 成功 | 失败(重试后) | 超时 | 吞吐(份/分) | 段落总数 | 向量总数 | 静默丢失 |

## 2. 语料画像
| 字段 | 非空率 | 备注 |
| years_experience / highest_degree / current_city / skills | % | 触发兜底？ |

## 3. typed 评测（锚点数: lookup=, conditional=, 语义=）
| 模式 | recall@5 | recall@3 | Top-1 | MRR | conditional 精确率 |
| dense / RRF / RRF+rerank / Skill-AND(3次中位) | | | | | |
分类型指标表（每类型 × 每模式 recall@5/MRR）

## 4. λ 消融（λ=0.15 vs λ=0）
| 模式 | recall@5 差 | MRR 差 | 结论 |

## 5. 性能
| 检索延迟 p50 | p95 | 最慢锚点 | 入库吞吐 |

## 6. 决策记录
λ / _PREFILTER_MAX / 语义锚点方案 / 其他

## 7. 结论与生产建议
```
