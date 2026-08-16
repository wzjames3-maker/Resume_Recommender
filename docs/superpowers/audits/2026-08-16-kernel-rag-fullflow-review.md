# RAG 内核全链路独立审查报告（第三轮）

> 日期：2026-08-16
> 触发：项目方要求对内核 RAG 全流程（knowledge/application/chat/common）做首次系统审查；HR 简历链路已在前两轮（742fafe、1961bad+e1960d4）审查修复
> 审查提示词：`docs/rag-full-flow-review-prompt.md`（v3，commit 43f62be）；区间 A `65c5ff8..HEAD`
> 结论：**3 项 P1（均上游原样）+ 6 项 P2 + 6 项 P3 + 4 项建议**；fork 自身内核改动干净，风险集中在边界 I/O（网络抓取/解压/异常文本外泄）
> **修复状态（2026-08-16，内核 P1 修复轮）：P1×3 已全部修复**——K1 Fork 抓取 SSRF 加固（8638956，超时 5s/20s + 私网/元数据黑名单含重定向）；K2 Web 文档同步网络抓取移出事务（6fc68c5）；K3 聊天异常文本不回传用户（99292fa）。
> **修复状态（2026-08-16，内核 P2 修复轮）：P2-4/5/6/7/8 已修复**——P2-4 PIL 像素上限 50MP（29222d2）；P2-5 zip 解压炸弹防护 200MB/50MB + 失败文件记日志（29222d2）；P2-6 切点字符表半角修正 + 4096 死代码清理（29222d2，与设计 §6.1 对齐）；P2-7 embedding 派发失败记日志（bbaa1c6）；P2-8 索引 DDL IF NOT EXISTS/IF EXISTS 防竞态（bbaa1c6）。**P2-9（简历库管理员旁路）为产品决策项，未动**。
> **修复状态（2026-08-16，内核 P3 低风险项）：P3-10/P3-12 已修复**（822330b：chat 路径查询文本先 normalize 与 hit_test 双轨一致；_batch_save Termbase 按知识库预取一次消除 N+1）。P3-11 blend 尺度、P3-13 LIMIT LEAST 截断、P3-14 死代码、P3-15 ruff 清理未立项（需评测基线或属 chore）。基线 403/403。

---

## 0. 归属事实（本轮最重要前提）

`65c5ff8` 为仓库根提交（整棵上游快照，提交信息复用上游 HEAD 的 "fix: show tool execution source"）。检索核心组件自导入起**零后续提交**，属上游原样：

- `apps/knowledge/vector/pg_vector.py`、`apps/knowledge/sql/{embedding,keywords,blend}_search.sql`
- `apps/common/chunk/`（MarkChunkHandle 256 字符切块）、`apps/common/utils/ts_vecto_util.py`
- `apps/common/utils/split_model.py`、`apps/common/handle/impl/common_handle.py`

fork 对内核的改动（+926/−39261，590 文件）基本为裁剪与延迟导入；内核侧实质性修复仅 96afbd0（应用链路裁剪残留）、af4c52a（sanitize+thinking 透传，HR 侧）、626ee61（外部模型注册）。以下「上游」= 65c5ff8 导入快照原样。

## 1. 总体评价

架构成熟、分层清晰（解析 -> 分块 -> 256 字 chunk -> 向量化 -> 检索 -> 生成）。删除链路清理完整（document/knowledge 删除显式清 Paragraph/Embedding/Problem/File/索引）；QueueOnce+RedisLock 双防重；native SQL 全程参数化（QuerySet 编译、参数分离）；ModelManage 8h 缓存且模型编辑时 delete_key 失效；裁剪零活跃残留 import（`from workflow/local_model/tools.` 计数 0）。**最大风险在边界 I/O**：网络抓取（Fork）无超时无内网防护、解压无上限、异常文本直达终端用户。此前担心的「内核长段落超 bge 512 token 上限」被 MarkChunkHandle 256 字符切块化解（重要正面结论，见 §4-②）。

## 2. 审查覆盖度

- **精读**：split_model、pg_vector、task/embedding、base_vector、chunk、ts_vecto_util、base_split_handle、base_search_dataset_step、base_chat_step（724 行全）、common_handle、zip/text split handle、fork、sql_execute、db/search、knowledge/serializers/common、document.py 关键段（577-1160：Sync/Operate.delete/refresh/Create）、knowledge.py 关键段（HitTest/Operate.embedding/edit/delete）、listener_manage（embedding_by_document 段）、views/document+knowledge 权限装饰器、authenticate
- **略读**：models_provider（rerank/embedding/超时）、chat_api（纯 OpenAPI schema）、mark_chunk_handle
- **未读（显式声明）**：ImportKnowledge 845-1076（zip 导入 `_restore_source_file` 路径穿越**未验证，待确认**）、qa/table/pdf/doc 解析器、application/serializers 全量、generate_human_message/reset_problem step、前端

## 3. 发现清单

### P1（3 项，均上游）

1. `common/utils/fork.py:238` | Web 同步 SSRF+挂死：`requests.get(url, verify=False)` 无超时、无私网/元数据地址（169.254.169.254）黑名单、TLS 校验关闭。入口三处：`knowledge/serializers/common.py:42`（WebMeta.is_valid **在序列化校验阶段同步抓取**，阻塞 web 请求线程）、`document.py:617`（Sync.sync）、celery sync_web_document。证据：fork.py 全文件无 timeout/allowlist/redirect 策略。
2. `document.py:597-617` | `@transaction.atomic` 内执行无超时网络抓取：长事务占用 DB 连接并持锁，慢站点可拖垮连接池。
3. `base_chat_step.py:287/707` | 异常路径 `"Exception:"+str(e)` 作为回答内容返回终端用户**并存入 chat_record**（post_response_handler）：信息泄露（str(e) 可含内部 URL/模型报错细节）+ 脏问答数据。

### P2（6 项）

4. [上游] `common_handle.py:26-27`：`PILImage.MAX_IMAGE_PIXELS = None` + `ImageFile.LOAD_TRUNCATED_IMAGES = True` --xlsx 内嵌图片解压炸弹 -> OOM DoS。
5. [上游] `zip_split_handle.py:173-174`：解压无大小/压缩比上限（`f.read()` 全量进内存）；内层文件解析失败 `except Exception: pass` **静默丢内容**（用户不知文档缺段）。
6. [上游] `split_model.py:322-325`：切点表全角写重（`('!',0),('!',0)`、`('?',0),('?',0)`，半角缺失）且 tuple 第二元 offset 从未使用；`:281/:288/:424` 三处 `if len(...)>4096: pass` 死代码。设计文档 §6.1 点名项确认仍在。
7. [上游] `task/embedding.py:128`：`embedding_by_knowledge` 对 `.delay` 失败 `except Exception as e: pass` --broker 故障时部分文档静默跳过向量化、无状态标记。
8. [上游] `knowledge/serializers/common.py:257-267`：索引 DDL 全 f-string（k_id 源自 DB UUID，注入不可直达，但应参数化）；并发 CREATE INDEX 无 `IF NOT EXISTS`，竞态失败仅记日志（embedding_by_knowledge 先 drop 后多文档并发 recreate 场景索引可能缺失）。
9. [已知限制复核成立]：WORKSPACE_MANAGE 角色经内核知识库 API（hit_test/文档读取/源文件下载）可读简历知识库，绕过 HrAccess（views `workspace_manage_role` 分支；与检索设计文档 §9.3 记录一致）。

### P3（6 项）

10. [上游] 双轨不一致：`pg_vector.py:125` hit_test 对 query 做 `normalize_for_embedding`，chat 链路 `base_search_dataset_step.py:69` 用原始文本 embed（入库侧已 normalize）--含 emoji/多空白 query 两轨召回有细微偏差；hit_test 恒 `is_active=True` 且无 document/exclude 维度。评测结论互换需注意。
11. [上游] `blend_search.sql`：`1 - distance + ts_rank_cd` 尺度未归一（ts_rank_cd ~0.x vs cosine 分 ~1）--blend 实际近似 embedding+微调，关键词权重近乎不可见。
12. [上游] `pg_vector._batch_save:96-100`：每条 embedding 行单独查一次 Termbase（同 batch 同 knowledge 重复查询，N+1）。
13. [上游] `embedding_search.sql`：`LIMIT LEAST(top*10, 500)`--top>50 时候选池截断（大 top 语义静默降级）。
14. [上游] `base_chat_step.py:477/499`：filtered_message_list 构建后未使用（死代码）；execute 签名携带 mcp_tool_ids 等裁剪后死参数（接口兼容可接受）。
15. [fork 可清]：ruff 内核 214 项（90 可自动修复，主要为未用 import）--上游遗留；hr/installer 干净。

### 建议

- 检索三轨重复（hit_test / query / HR resume_search 直调 ISearch）抽公共检索门面；HR 已过两轮审查，下轮统一。
- `knowledge.edit` 允许改 embedding_model_id 而不提示/强制重向量化（向量空间错配，上游同款）。
- chat 检索 step 的 `embed_query` 无 try/except（模型不可用时裸异常）；HR 侧已有 AppApiException 友好错误，建议对齐。
- 模型 HTTP 客户端未显式设置超时（OpenAI SDK 默认 600s；rerank 60s）--建议统一超时配置。

## 4. 设计-实现偏差

① 设计 §6.1 点名的切点缺陷仍在（未修，内核上游）；② 「normalize_for_embedding 不截断」属实，但入库侧 MarkChunkHandle 256 字符切块使 bge 512 token 上限实际安全--设计文档未记录此依赖，建议补记；③ PRD「AI 与知识库边界」受 §9.3 已知限制约束，未新增偏差；④ v3 提示词两处小误差（`base_split_handle` 实在 `handle/` 而非 `impl/`；「8 种格式」与实际文件清单基本一致）。

## 5. Top 5 优先事项（ROI 排序）

1. fork.py 加超时 + 私网黑名单 + verify 策略（小 diff，三处入口同时受益）
2. chat 异常文本不回传用户（两处改通用文案+日志）
3. Sync.sync 网络操作移出事务
4. zip/xlsx 解压上限 + 失败文件不静默（至少计数上报）
5. 切点字符表修正 + 4096 死代码清理（与设计 §6.1 对齐）

## 6. 提问清单（待项目方决策）

1. 简历库 WORKSPACE_MANAGE 旁路：本迭代加固（如知识库 meta 打 HR 标记并在内核 API 拒绝）还是维持已知限制？
2. 内核 214 ruff：现在独立 chore 清理，还是守「上游原样最小 diff」原则不动？
3. 上游原样 P1×3 是否纳入修复（会偏离上游基线，影响未来合并）？
4. blend 尺度归一是否做（需评测基线支持，避免指标漂移）？

## 7. 对照结论

本轮发现全部位于内核链路，与第一轮（742fafe）、第二轮（1961bad+e1960d4）HR 侧修复清单**零重合**；HR 侧已修项未在内核复发。

## 8. 验证记录

- 单测：`hr.tests application.tests knowledge.tests models_provider.tests ops.tests --keepdb` -> **367/367 PASS**（HR 333）
- `makemigrations --check --dry-run` / `migrate --check`：无变更
- ruff：apps/hr + installer 干净；内核六 app 214 项（详见发现 15）
- 裁剪遗留：`grep 'from workflow|from local_model|from tools.'` 活跃 import 计数 0
