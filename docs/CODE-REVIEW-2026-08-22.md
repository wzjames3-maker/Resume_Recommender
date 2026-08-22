# 全项目代码审查报告(2026-08-22)

> 审查方式:4 个并行审查代理分模块深入(hr ATS / knowledge RAG / application+chat / common+users+ops+oss 安全面)+ 全仓 ruff 静态检查。高危项均经代码交叉验证或运行时复现。

## 一、最高优先级问题(跨模块去重合并)

### 安全类

1. **[高] SSRF(可回显内网响应)** — `apps/oss/serializers/file.py:372`,经 `apps/oss/views/file.py:77` 暴露于 `/chat/api/oss/get_url/<application_id>`。URL 完全由客户端提供、无 scheme/内网 CIDR 校验、`verify=False`、先下载后限流、text 响应体回显。匿名 embed 用户可探测内网/云元数据。**修复**:私网 CIDR 黑名单 + 仅 http(s) + 禁回显 text 体 + 开证书校验 + 流式限额中断。

2. **[高] embed.js 反射型 JS 注入/XSS** — `apps/chat/serializers/chat_embed_serializers.py:69-86,103-106` + `apps/chat/template/embed.js:31,65`。`host` 参数含换行符可打断 JS 字符串字面量;query 值未 URL 编码;`insertAdjacentHTML` 还原实体。端点无需有效 token 即渲染。**修复**:host/protocol 服务端 allowlist、query 用 `urllib.parse.quote`、模板改 DOM API 或 `escapejs`/`json.dumps`。

3. **[高] admin 调试对话端点无权限校验** — `apps/application/views/application_chat.py:140-154`。仅 TokenAuth 无 `has_permissions`,任意登录用户可对任意活跃 chat_id 以 debug 模式跨工作空间使用模型/知识、绕过配额;缓存 miss 另有 None 崩溃(`chat/serializers/chat.py:167`)。**修复**:补权限装饰器 + 校验 chat 归属 + 缓存 miss 抛业务异常。

4. **[高] Celery pickle 信任模型** — `apps/ops/celery/hmac_signed_serializer.py:8` HMAC 默认密钥可猜测 + pickle 反序列化 → 伪造任务消息 RCE;`maxkb/settings/celery.py:76` accept_content 含明文 json,签名机制可整体绕过。**修复**:强制配置密钥、accept_content 仅保留签名格式。

5. **[高] 默认密钥族** — `maxkb/settings/base.py:21` SECRET_KEY 硬编码默认值(可伪造 mk_file_auth 文件票据);`apps/common/utils/rsa_util.py:25` RSA 私钥静态口令硬编码;DB/Redis 默认口令。**修复**:启动时检测默认密钥并拒绝启动(非 dev 模式)。

6. **[高] 匿名密码重置无防护** — `apps/users/views/user.py:301-319`:无速率限制 + 非加密随机验证码 + CheckCode 预言机。**修复**:限流 + 统一错误响应 + secrets 模块。

### 功能断裂类(0030 字段删除迁移未清扫引用方)

7. **[高] CSV 候选人导入整体崩溃** — `apps/hr/serializers/import_service.py:70-89`:引用 13 个已删字段 + 5 个不存在的 helper,任何导入请求 500。同根因:`hr_agent_probe.py:123`、`eval_screening.py:55,177-208`、`import_resume_dataset.py:253`。

8. **[高] similar_jobs 击穿 JD 起草与面试 Copilot** — `apps/hr/services/similar_jobs.py:21,24` 引用已删字段,有录用历史的租户内 Agent run 必 FAILED。

9. **[高] Application 队列 city 筛选 FieldError 500** — `apps/hr/services/application_service.py:582-584`。

10. **根因** — 迁移 0030 只删模型字段,未清扫引用方,且约 20 余处回归测试被 `# 0030 stub assertTrue(True)` 掏空。**修复**:全仓清剿 `current_city|target_city|years_experience|highest_degree|candidate.skills` 引用 + 恢复被 stub 的测试。

### 数据合规类

11. **[高] 30 天 TTL 漏删流转日志,未脱敏简历全文永久留存** — `apps/hr/task/resume.py:41-60` TTL 清理不调 `delete_flow_logs`,而 EXTRACT/SANITIZE 节点把原文写入 ResumeFlowLog(task/resume.py:74-77、services/resume_index.py:140-143)。违反 PRD §4.4/§7 上线门槛。

12. **[高] knowledge 批量操作 IDOR 家族** — `apps/knowledge/serializers/document.py:1444-1647,462-553`、`paragraph.py:628-651`:批量删除/迁移/导出的 id_list 不校验 workspace 归属 → 跨租户读写删;`serializers/paragraph.py:265,291-302` 段落编辑带 `problem_list` 必然 500。

### 状态一致性类

13. **[中→必修] Offer 并发窗口** — `apps/hr/serializers/offer.py:154-176,237-248,291-304`:无 DB 唯一约束;withdraw 用事务外旧快照做 `_transition` 判断后**整行 save()**,与 accept 并发会把 ACCEPTED 覆写为 WITHDRAWN 并抹掉 accepted_at,而 Application 已是 HIRED——状态机永久不一致(比"双时间戳"更严重,修复视为必做):select_for_update + `filter(status=期望前态).update()` 乐观守卫 + 活跃 Offer 部分唯一索引;accept 的 handoff 创建在事务外不可恢复(offer.py:285-288),移入同事务(get_or_create 幂等)。

14. **[中] 面试状态机与审计缺口** — `recruitment.py:1175-1198` update_interview 无转移矩阵/无审计;`recruitment.py:1309-1312` 面试反馈原文写入不可清除的审计日志(PII 风险)。

15. **[中] 降级链未兑现(G5)** — `apps/hr/services/resume_search.py:224-228` 与 `apps/knowledge` 同源:embed 挂时直接抛 500,keyword 兜底腿不可达;`resume_search.py:825-844` structured_only 补位不过滤候选人 ACTIVE 状态(归档简历可重新被搜到)。

16. **[中] Celery 异步管线完整性** — `.delay()` 在事务内发出(M1,孤儿向量);无 retry/acks_late(STARTED 段落永久卡死);`post_delete` 兜底信号缺失(旁路删除残留可检索向量 ≤30 天)。

17. **[中] hr_agent_probe 凭据落库副作用** — `hr_agent_probe.py:58-90` 崩溃前将环境凭据加密写回全工作区同名生产模型行,按 model_name 匹配无 workspace 过滤。

18. **[中] S3 临时文件泄漏** — `apps/hr/services/storage.py:39-49` 每次 open() 物化完整简历到 tmp 且无任何 unlink——含 PII 副本磁盘永久累积。

## 二、中低危精选(修复成本低、建议同批处理)

- `apps/common/utils/common.py:219,284,290` — 未导入 `io` 的 NameError 死代码(多模态残留),连同 `split_and_transcribe` 等 5 个无调用方函数一并删除。
- `chat_authentication.py:35,43` — 匿名 token 永不过期、chat_user_id 可继承:加 max_age。
- `chat_record.py:182-201`+`application_chat_record.py:65-112` — 单条会话详情缺 chat_user 属主绑定(同应用 IDOR)。
- `base_chat_step.py:282-319` — GeneratorExit 捕获后再 yield → RuntimeError;上游流未 finally close。
- `models_provider/tools.py:112-121` — 社区版跨 workspace 模型可用,mismatch 应拒绝。
- `recruitment.py:1105-1107` — keyword 检索跨租户全表 ILIKE 扫描(noisy neighbor)。
- `recruitment.py:435-444` email N+1(每页 ~101 查询)、`recruitment.py:638-656` get_job 死代码双查询。
- ruff 全仓 279 项(79 unused-import、57 F403/F405、52 unused-variable、4 bare-except、3 F821),130 项可 `--fix` 自动修复。
- `chat/views/chat.py:42-65,228-247` — 未挂载的死代码 `ResourceProxy`(SSRF 形态)/`UploadFile`,建议删除以免将来误挂载。

## 二·补、修复积压(审查代理核实有效、因篇幅未入主榜)

- **[中] `apps/hr/services/resume_search.py:614-618,644-645`** — 显式选库(含前端默认查总库)时把全库 document_id 物化进内存做巨型 IN,且原样写入响应 `meta["scope_document_ids"]`:大库下响应无界膨胀并泄露内部 UUID。scope 只在服务端传递,meta 仅输出计数。**10k 规模下影响实打实,建议优先于 #14 死代码子项处理**。
- **[中] `apps/hr/services/resume_index.py:122-129,208-214`** — 简历重建索引"删旧文档→建新文档"无外层事务,中途失败留悬空 document_id(该简历永久不可搜)。
- **[低] `apps/hr/services/resume_search.py:1001-1012`** — `_write_search_audit` 裸 except 静默吞审计失败,补 warning 日志。
- **[低] `apps/hr/services/resume_parser.py:30-40`** — 返回值仍带已删字段恒空键(current_city 等),`Model(**parsed)` 脚枪,删键。
- **[中] 无 post_delete 兜底信号** — `ResumeFile.candidate` 为 SET_NULL,语义索引/向量清理完全靠 service 层自律;任何旁路物理删除(admin/脚本)使向量继续可检索 ≤30 天。给 Candidate/ResumeFile 加幂等 post_delete receiver 兜底调 delete_resume_index + delete_flow_logs。
- **[低] `parse_resume_task` 无幂等入口护栏** — 重投递会再建 Candidate 幽灵档案;任务开头检查 candidate_id/status。
- **[低] offboarding 两点** — 导出 JSON 以默认 umask(0644)落盘且失败成孤儿(改 0600+临时文件原子改名);清理清单漏 ResumeDatabase 表(库元数据跨注销残留)。
- **[低] `write_audit_log object_id[:64]` 截断** — 多文件上传的 RESUME_UPLOAD 审计丢失大部分 ID。
- **[低/加固] 附件下载路径无 workspace 包含性校验** — `apps/hr/serializers/offer.py:378-383` + `services/storage.py:39-49`:LocalStorage 绝对路径原样放行且 save() 返回绝对路径持久化进 DB(ambient authority)。当前唯一写入点是服务端 save() 返回值,属纵深防御缺口而非可利用漏洞:下载前断言 key 前缀 `resume/{workspace_id}/`、`offer/{workspace_id}/` 并 normpath 校验,LocalStorage 改存相对 key(存量迁移)。

两项关键确认:(a) 生产活跃路径无未掩码简历文本直达 LLM;(b) workspace+ACTIVE 库范围在召回层强制生效(dense/sparse 两腿共享过滤)。

## 三、正面确认(审查中验证为健全的设计)

- workspace 隔离纪律严格,权限矩阵(VIEWER/OPERATOR)双层拦截,跨租户资源统一 404
- Application 状态机 select_for_update + 幂等事件唯一约束设计正确;"AI 只写 Proposal、人确认后走命令端点"红线实现干净
- 简历切片链路 mask_pii 前置、Agent 上下文投影脱敏构成纵深防御
- 检索 SQL 全参数化,文件解析无 XXE/路径穿越;SSRF 黑名单、zip 炸弹防护等历史修复真实落地
- 认证主干(deny-by-default、缓存态 token 双校验、PBKDF2)设计健全

## 四、建议修复顺序

1. **安全快修**(均小改动):SSRF、embed.js 注入、debug 端点权限、默认密钥检测、密码重置限流
2. **0030 引用清剿** + 恢复被 stub 测试(恢复"已交付"功能真实性)
3. **PII 生命周期**:TTL 漏删 flow_logs、审计日志去原文、S3 临时文件清理、mask_pii 死代码
4. **Offer/Interview 并发与事务加固** + handoff 事务内幂等
5. **异步管线**:on_commit 发任务、降级链贯通、post_delete 兜底
6. **长期**:recruitment.py(1313 行)/resume_search.py(1012 行)拆分;agents/ 双轨 runner(~1900 行重复)二选一;ruff `--fix` 清理
