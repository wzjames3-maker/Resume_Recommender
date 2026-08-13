# B-2：PII 脱敏与 ResumeIR 加密设计

**状态：** 第一阶段（脱敏、新数据密文存储、回填命令、授权解密读取）已实现并通过全量回归；第二阶段（删除 `resume_irs.content` 明文、`content_enc` NOT NULL）待生产回填校验后独立发布，未在本计划编码。

**关联审查项：** [MVP 发布审查 B-2](../audits/2026-08-09-mvp-release-audit.md)

## 目标

修复以下发布阻塞：

- 出站 PII 脱敏遗漏地址和自由文本姓名，不符合 PRD F6 的 PII taxonomy。
- `resume_irs.content` 以明文存储，不符合 IR 分层加密要求。

本设计不改变已授权用户查看完整 IR 的 API 语义，也不改变现有 hired 候选人的 ACL。

## 已确认约束

- 历史 ResumeIR 采用原地迁移：先写入新增的密文字段，再删除明文字段。
- 数据库静态存储加密；通过现有 ACL 的用户读取 API 时仍返回解密后的完整 IR。
- 地址与自由文本姓名采用保守识别，宁可不识别模糊词，也不得误替换公司、项目或技能文本。
- 所有外部模型调用继续经既有 `desensitize_text` 路径；本设计不新增独立的出站通道。

## 方案选择

采用双列渐进迁移，而非一次性列替换或新建 IR 表：

1. 第一阶段发布的 schema migration 新增 `resume_irs.content_enc` 密文字段，暂时保留 `content` 明文字段。
2. 可重试的应用级回填命令将历史 `content` 加密写入 `content_enc`。
3. 第一阶段应用写路径仅写 `content_enc`；读路径优先解密 `content_enc`，在迁移窗口中可读取尚未迁移的 `content`。
4. 校验所有记录已迁移后，在独立的第二阶段发布中创建 schema migration：删除 `content`，并将 `content_enc` 设为 `NOT NULL`。

最终保留显式 `content_enc` 字段，避免密文被误认为可直接展示的文本。运行时代码必须只经解密 helper 获取 IR。

## 数据模型与迁移

### 第一阶段 schema migration

- 向 `resume_irs` 新增 nullable `content_enc TEXT`，并将旧 `content` 改为 nullable，使新写路径能只写密文。

### 数据回填命令

- 新增一次性、可重复运行的后端命令，按主键游标分批读取 `content_enc IS NULL AND content IS NOT NULL` 的记录。
- 使用现有 `encrypt_secret`（AES-GCM，随机 nonce）加密原文，写入 `content_enc`。
- 每个批次在独立事务中提交；失败则中止 migration，保留已完成批次，可安全重试未迁移记录。
- 命令完成后，若仍存在非空 `content` 且空 `content_enc` 的记录，报错而不是静默继续。

### 第二阶段 migration

- 前提：运行时代码与所有生产数据均已使用 `content_enc`；`content IS NOT NULL AND content_enc IS NULL` 计数为 0，且至少完成一次从 `content_enc` 解密回明文的抽样验证。
- 删除 `content` 明文字段。
- 将 `content_enc` 设为 `NOT NULL`。

第二阶段 migration 不与第一阶段 migration 同时提交或部署；否则 `alembic upgrade head` 会连续应用两者，失去回填验证与回退窗口。

不在第一阶段删除明文，确保部署回滚时仍具备可读路径；不长期保留双写，避免明文数据继续扩散。

## IR 读写边界

新增专用 helper：

- `encrypt_resume_ir(plain: str) -> str`：封装 `encrypt_secret`，只在入库与数据迁移调用。
- `decrypt_resume_ir(ir: ResumeIR) -> str`：优先解密 `content_enc`；第一阶段仅在密文缺失时读取旧 `content`。

调用方：

- `resume.ingest`：创建 ResumeIR 时只写密文和 `valid_chars`。
- `/api/v1/resume-runs/{run_id}/ir`：完成现有 workspace、候选人池 ACL 后解密并返回。
- 候选人详情：完成现有可见性检查后解密并返回最新 ResumeFile 关联 IR。
- purge：继续删除 ResumeIR 行；无需单独处理密文。

`ir_hash` 仍计算自明文 IR，用于现有审计和一致性校验；不得以密文 hash 替换。

## PII 脱敏规则

继续使用确定性的 `PII:<type>:<index>` token 与现有 token 映射持久化方式。

### 地址

仅识别以下明确地址形态：

- 标签式：`地址`、`住址`、`现住址`、`通讯地址`、`Address` 后的单行值，截断于换行或常见字段标签。
- 结构式：同一短文本中同时出现省/市/区/县之一，及路/街/巷/号/楼/室/苑/小区之一的地址组合。

不得把单独的 `city`、`hometown`、公司所在地、项目部署地域或仅含“北京”“杭州”等城市名识别为地址。

### 姓名

- 仅识别明确字段标签的姓名：`姓名`、`名字`、`联系人`、`Name`、`Contact` 等后接的独立值。
- 英文 `Name` 必须是行首独立字段标签，不得从 `Company Name`、`Project Name`、`Skill Name` 中匹配。
- 不识别无标签的页首自由文本中文或英文姓名，避免把公司名、品牌、岗位或技能误当姓名。

不在任意正文段落做全局人名猜测。

### fail-closed 行为

- 规则处理异常、UTF-8 编码失败、token 映射不一致或明文残留时，保持当前 `PIIRedactionError`，阻止外部模型调用。
- 已有结构化、画像、embedding、rerank 等调用点必须继续复用 `desensitize_text`，不得新增未脱敏出站路径。

## 错误处理与可观测性

- 解密失败：读取 API 返回受控 500，不返回密文、明文或加密错误细节；记录服务端错误日志并带 run_id。
- 第一阶段回填失败：命令失败退出，避免删除明文字段；重复执行只处理未迁移记录。
- 新写入不得同时写入明文与密文；测试应证明 `ResumeIR` 新记录的明文字段为空。

## 测试与验收

### PII 单元测试

- 标签式地址和结构式地址被替换为 `PII:address:*`。
- 页首自由文本姓名被替换为 `PII:name:*`。
- 工作经历中的公司、项目名、岗位名、单独城市名不被误替换。
- 既有手机号、邮箱、身份证、标签式姓名及 fail-closed 回归继续通过。

### IR 集成测试

- 新解析写入后，数据库中不存在对应 IR 明文，`content_enc` 可被解密回原文。
- 历史明文记录经迁移后具有可解密的 `content_enc`。
- 授权 API 仍返回完整 IR；member 读取 hired 候选人的 IR 仍为 404。
- candidate detail 的 IR 读取同样经过统一解密 helper。
- purge 后对应 IR 行删除，物理文件清理回归保持通过。

### 出站回归

- 结构化、画像与 embedding 输入不包含样本中的地址或页首自由文本姓名。
- `ir_hash` 对同一明文保持既有计算口径。

## 已接受边界（保守识别的漏识别清单）

以下地址/姓名形态因保守识别策略而可能漏识别，属已接受边界，不扩大识别范围到误伤公司/项目/技能：

- `号院`：如「文三路 90 号院」——结构化地址正则的 `号` 后缀不含 `院`。
- `大道`：如「解放大道」——路名后缀仅识别 `路|街|巷`。
- `缩进行`：行锚定正则（`(?m)^`）要求标签/地址位于行首，前导空格缩进的行不命中。
- `同行尾随字段`：标签式地址同行尾随**不在截断标签清单（电话|手机|邮箱|Email|姓名|名字|技能|工作|教育|毕业|学校|籍贯|政治面貌|期望|求职意向|薪资|民族|婚姻|性别|出生|年龄|身份证）内**的字段时，整行结构化校验失败而不脱敏；清单内标签已先行截断修复。
- 画像 token 回显：画像构建的 LLM 输出（`strengths`/`risks`/`career_pattern` 自由文本）可能回显输入中的 PII token（如 `PII:name:0`）并随 `profile_json` 持久化；token 在后续出站调用中若无对应映射即无法还原，属已知局限，不改代码。

## 不在范围内

- 原始文件对象存储加密替换。
- 模型供应商数据出境治理或不同租户的密钥轮换。
- 全文人名 NER、跨语言地址标准化或对模糊正文词做激进脱敏。
- F8 re-parse 和 override 继承。
