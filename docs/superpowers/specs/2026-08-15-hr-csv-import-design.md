# 候选人批量导入设计（B4：CSV 导入 + 失败/疑似重复报告）

## 背景

PRD §9.2 B 阶段最后一项：批量导入与来源录入体验完善。当前候选人只能逐条建档（create_candidate）；导入需支持 CSV 批量建档，产出失败原因与疑似重复报告，不产生半成品数据。

## 范围

### 范围内

- CSV 上传导入候选人（ADMIN）：固定表头、逐行校验、失败行跳过并报原因、疑似重复标注、汇总与明细报告。
- 模板下载（GET /import/candidates/template，任意 HR）：含表头与示例行。
- 审计：新增 IMPORT 动作（object_type=CANDIDATE，detail 含成功/失败/重复统计）；成功行逐条写 CREATE 审计（与手工建档一致）。
- 前端：候选人页「批量导入」入口（ADMIN）→ 弹窗（模板下载 + 上传）→ 结果报告展示。

### 不在范围内

- 简历文件随 CSV 导入、职位关联导入、可配置字段映射、异步导入（当前同步，单文件 ≤ 2MB / ≤ 200 行）。

## CSV 格式

- 编码：UTF-8（兼容 BOM，utf-8-sig 读取）。
- 表头：name（必填）phone email current_city target_city highest_degree years_experience skills source_type source_detail collected_at consent_status consent_version contact_preference source note
- skills：按中文/英文逗号或分号分隔（[,，;；]）。
- 枚举列（source_type/consent_status/contact_preference）非法 → 该行失败。
- 行内姓名缺失、年限/日期非法、字段超长 → 该行失败并报原因。
- 疑似重复：与库内候选人 phone 相同或 email 忽略大小写相同，或文件内前序行冲突 → 仍创建，标记 duplicate 并在报告统计（与手工建档查重提示语义一致）。
- 行数上限 200，文件大小上限 2MB（超出 400）。

## 数据模型

无新表。审计动作新增：IMPORT = "IMPORT"。

## 服务方法（ImportService，apps/hr/serializers/import_service.py）

| 方法 | 说明 |
|---|---|
| import_candidates_csv(file_path) | 解析→逐行校验→创建→报告；一条 IMPORT 审计 + 逐条 CREATE 审计 |
| import_template() | 返回 (表头列表, 示例行) 供 CSV 模板生成 |

报告结构：{"total": N, "success": N, "failed": N, "duplicates": N, "records": [{row_no, name, status: created|duplicate|failed, reason, candidate_id}]}

- 校验逻辑与 create_candidate 保持一致（复用 RecruitmentService 静态校验器：_required_string/_optional_string/_skills/_years_experience/_source_type/_collected_at/_consent_status/_contact_preference）。
- 失败不中断整批；单行失败仅计入报告。
- 跨工作区隔离：候选人在导入服务工作区创建。

## API

统一前缀：/admin/api/workspace/{workspace_id}/hr。

| 方法 | 路径 | 权限 |
|---|---|---|
| POST | /import/candidates | ADMIN（multipart file） |
| GET | /import/candidates/template | 任意 HR |

## 前端

- candidates/index.vue：ADMIN 可见「批量导入」按钮 → 弹窗：
  - 「下载模板」链接（GET template → 导出 CSV）。
  - 上传 CSV（el-upload，accept=.csv）。
  - 结果报告：成功/失败/疑似重复计数 + 明细表（行号、姓名、状态、原因）。
- api wrapper：importCandidates / downloadImportTemplate。

## 测试

- 服务层：正常导入成功（含全字段行）；表头缺 name 400；非法枚举行失败且有原因；姓名缺失行失败；skills 中文逗号分隔解析；年限非法失败；文件内重复标记 duplicate；库内 phone/email 重复标记 duplicate 且仍创建；成功后审计 IMPORT + 逐条 CREATE；行数超限 400。
- 路由层：ADMIN 上传 200 + 报告；OPERATOR 403 + ACCESS_DENIED 审计；模板下载 200 含表头。
- 回归：既有 287 用例全部通过。

## 验收

HR 全量 PASS、makemigrations 无漂移、ruff 干净、vue-tsc 与双构建 PASS、HANDOFF.md §5.2 批量导入标记交付（B 阶段完成）。
