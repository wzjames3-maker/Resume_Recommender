# B-2：PII 脱敏与 ResumeIR 加密实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 扩展出站 PII 脱敏至保守地址和页首自由文本姓名，并将 ResumeIR 从明文存储迁移到 AES-GCM 密文存储，同时不改变授权 API 返回完整 IR 的语义。

**架构：** 第一阶段新增 `ResumeIR.content_enc`，新数据只写密文，统一读 helper 优先解密密文并暂时 fallback 历史明文。独立回填命令按主键游标批量加密存量数据。地址与姓名规则只在明确标签、结构式地址和页首候选信息内匹配，所有已有外部模型调用继续复用 `desensitize_text`。

**技术栈：** FastAPI、SQLAlchemy async、Alembic、PostgreSQL、cryptography AES-GCM、pytest。

---

## 文件边界

- 修改：`backend/app/models/candidate.py`
  - 为 `ResumeIR` 添加第一阶段的 nullable `content_enc` 列。
- 创建：`backend/app/services/resume/ir_storage.py`
  - 仅负责 ResumeIR 密文读写和历史明文 fallback。
- 创建：`backend/alembic/versions/<revision>_add_resume_ir_content_enc.py`
  - 第一阶段 schema migration：新增 `content_enc` 并允许旧 `content` 为 null。
- 修改：`backend/app/services/resume/ingest.py`
  - 入库时只写 `content_enc`。
- 修改：`backend/app/api/resumes.py`
  - 读取 run IR 时通过统一 helper 解密。
- 修改：`backend/app/api/candidates.py`
  - 候选人详情读取 IR 时通过统一 helper 解密。
- 修改：`backend/app/services/resume/pii.py`
  - 增加保守地址与页首自由文本姓名识别规则。
- 创建：`backend/scripts/backfill_resume_ir_encryption.py`
  - 可重复运行、游标分页的历史 IR 加密回填命令。
- 修改：`backend/tests/test_pii.py`
  - 覆盖地址、页首姓名与误伤防护。
- 创建：`backend/tests/test_ir_storage.py`
  - 覆盖加密写入、密文优先读取、旧明文 fallback 和解密失败。
- 修改：`backend/tests/test_ingest.py`
  - 证明 ingest 不再持久化 ResumeIR 明文。
- 修改：`backend/tests/test_resumes_api.py`
  - 证明授权 API 返回解密 IR 且 hired ACL 不回归。
- 修改：`backend/tests/test_candidates_api.py`
  - 证明候选人详情使用统一解密 helper。
- 创建：`backend/tests/test_backfill_resume_ir_encryption.py`
  - 覆盖回填幂等性与未迁移记录检测。

## 任务 1：先锁定保守 PII 识别契约

**文件：**
- 修改：`backend/tests/test_pii.py`
- 修改：`backend/app/services/resume/pii.py`

- [ ] **步骤 1：编写地址与姓名规则的失败测试**

  在 `backend/tests/test_pii.py` 追加：

  ```python
  def test_identify_labeled_address():
      masked, mapping = desensitize_text("现住址：浙江省杭州市西湖区文三路 90 号 2 楼\n技能：Python")
      assert "浙江省杭州市西湖区文三路 90 号 2 楼" not in masked
      assert any(entry.pii_type is PIIType.address for entry in mapping)


  def test_identify_structured_address_without_label():
      masked, mapping = desensitize_text("浙江省杭州市西湖区文三路 90 号\nJava 后端工程师")
      assert "浙江省杭州市西湖区文三路 90 号" not in masked
      assert any(entry.pii_type is PIIType.address for entry in mapping)


  def test_identify_labeled_name_only():
      masked, mapping = desensitize_text("姓名：张三 电话 13800000000")
      assert "张三" not in masked
      assert any(entry.pii_type is PIIType.name for entry in mapping)


  def test_does_not_identify_unlabeled_first_line_as_name():
      text = "---\nformat: docx\n---\n\n华为\n求职意向：后端开发\n<!-- block_id: 1 kind: paragraph -->\n任职于杭州科技有限公司"
      masked, mapping = desensitize_text(text)
      assert "华为" in masked
      assert all(entry.pii_type is not PIIType.name for entry in mapping)


  def test_does_not_redact_city_or_work_content_as_address_or_name():
      text = "杭州\n<!-- block_id: 1 kind: paragraph -->\n在北京创新科技有限公司负责支付项目"
      masked, mapping = desensitize_text(text)
      assert masked == text
      assert mapping == []
  ```

- [ ] **步骤 2：运行测试确认失败**

  运行：

  ```bash
  cd backend && python -m pytest tests/test_pii.py -q
  ```

  预期：地址与页首自由文本姓名测试失败；现有手机号、邮箱、身份证和标签式姓名测试继续通过。

- [ ] **步骤 3：实现最小保守规则**

  在 `backend/app/services/resume/pii.py`：

  ```python
  _ADDRESS_LABEL_RE = re.compile(
      r"(?:^|\n)(?:现住址|通讯地址|住址|地址|Address)\s*[:：]?\s*([^\n]{4,120})",
      re.IGNORECASE,
  )
  _STRUCTURED_ADDRESS_RE = re.compile(
      r"(?=[^\n]{0,80}(?:省|市|区|县))(?=[^\n]{0,80}(?:路|街|巷|号|楼|室|苑|小区))[^\n]{6,120}"
  )
  _NAME_LABEL_RE = re.compile(
      r"(?:^|\n)(?:姓名|名字|联系人)\s*[:：]?\s*([\u4e00-\u9fa5]{2,4})",
  )
  _EN_NAME_LABEL_RE = re.compile(
      r"(?:^|\n)(?:Name|Contact)\s*[:：]\s*([A-Za-z][A-Za-z .]{1,48})",
      re.IGNORECASE,
  )
  ```

  移除页首自由文本姓名识别；`identify_pii` 只识别标签式中文与英文姓名，英文标签必须是行首独立字段标签，不得从 `Company Name` 等复合标签中匹配。

- [ ] **步骤 4：运行 PII 测试验证通过**

  运行：

  ```bash
  cd backend && python -m pytest tests/test_pii.py -q
  ```

  预期：全部通过，且误伤防护断言保持文本不变。

- [ ] **步骤 5：Commit**

  ```bash
  git add backend/app/services/resume/pii.py backend/tests/test_pii.py
  git commit -m "fix: redact conservative address and header name PII"
  ```

## 任务 2：新增 ResumeIR 密文存储抽象

**文件：**
- 创建：`backend/app/services/resume/ir_storage.py`
- 修改：`backend/app/models/candidate.py`
- 创建：`backend/alembic/versions/<revision>_add_resume_ir_content_enc.py`
- 创建：`backend/tests/test_ir_storage.py`

- [ ] **步骤 1：编写密文存储单元测试**

  创建 `backend/tests/test_ir_storage.py`：

  ```python
  import pytest

  from app.models import ResumeIR
  from app.services.resume.ir_storage import decrypt_resume_ir, encrypt_resume_ir


  def test_encrypt_resume_ir_does_not_keep_plaintext():
      plain = "姓名：张三\n电话：13800000000"
      encrypted = encrypt_resume_ir(plain)
      assert encrypted != plain
      assert plain not in encrypted


  def test_decrypt_resume_ir_prefers_ciphertext():
      ir = ResumeIR(run_id="ir-1", content="old plain", content_enc=encrypt_resume_ir("new plain"), valid_chars=9)
      assert decrypt_resume_ir(ir) == "new plain"


  def test_decrypt_resume_ir_falls_back_to_legacy_plaintext():
      ir = ResumeIR(run_id="ir-2", content="legacy plain", content_enc=None, valid_chars=12)
      assert decrypt_resume_ir(ir) == "legacy plain"


  def test_decrypt_resume_ir_rejects_missing_content():
      ir = ResumeIR(run_id="ir-3", content=None, content_enc=None, valid_chars=0)
      with pytest.raises(ValueError, match="缺少 IR 内容"):
          decrypt_resume_ir(ir)
  ```

- [ ] **步骤 2：运行测试确认失败**

  运行：

  ```bash
  cd backend && python -m pytest tests/test_ir_storage.py -q
  ```

  预期：FAIL，报错 `ModuleNotFoundError: app.services.resume.ir_storage`，且 `ResumeIR` 尚无 `content_enc`。

- [ ] **步骤 3：扩展模型并实现 helper**

  在 `backend/app/models/candidate.py` 的 `ResumeIR` 增加：

  ```python
  content: Mapped[str | None] = mapped_column(Text, nullable=True)
  content_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
  ```

  创建 `backend/app/services/resume/ir_storage.py`：

  ```python
  from app.models import ResumeIR
  from app.services.crypto import decrypt_secret, encrypt_secret


  def encrypt_resume_ir(plain: str) -> str:
      return encrypt_secret(plain)


  def decrypt_resume_ir(ir: ResumeIR) -> str:
      if ir.content_enc:
          return decrypt_secret(ir.content_enc)
      if ir.content is not None:
          return ir.content
      raise ValueError(f"ResumeIR {ir.run_id} 缺少 IR 内容")
  ```

- [ ] **步骤 4：运行单元测试验证通过**

  运行：

  ```bash
  cd backend && python -m pytest tests/test_ir_storage.py -q
  ```

  预期：4 passed。

- [ ] **步骤 5：创建第一阶段 schema migration**

  运行：

  ```bash
  cd backend
  python -m alembic revision -m "add encrypted resume ir content"
  ```

  在生成文件中实现：

```python
   def upgrade() -> None:
       op.add_column("resume_irs", sa.Column("content_enc", sa.Text(), nullable=True))
       op.alter_column("resume_irs", "content", existing_type=sa.Text(), nullable=True)


   def downgrade() -> None:
       op.alter_column("resume_irs", "content", existing_type=sa.Text(), nullable=False)
       op.drop_column("resume_irs", "content_enc")
   ```

   不在此 migration 内加密数据或删除 `content`。

   **downgrade 可逆性说明：** 第一阶段 upgrade 后写路径只写 `content_enc`（`content` 为 NULL）。
   因此本 migration 的 downgrade（`content` 改回 `NOT NULL`）仅在库中不存在 `content IS NULL` 的新数据时
   才能成功；一旦第一阶段上线并写入新数据，downgrade 即失败——这是渐进迁移的固有局限，
   回滚窗口只保证「无新数据」或「仍以明文读取历史数据」阶段有效。生产回滚需先确认无
   `content IS NULL` 记录，或改走第二阶段完成后再回滚。

- [ ] **步骤 6：Commit**

  ```bash
  git add backend/app/models/candidate.py backend/app/services/resume/ir_storage.py backend/tests/test_ir_storage.py
  git commit -m "feat: add encrypted ResumeIR storage helper"
  ```

## 任务 3：让新入库数据只写密文，所有 API 统一解密

**文件：**
- 修改：`backend/app/services/resume/ingest.py`
- 修改：`backend/app/api/resumes.py`
- 修改：`backend/app/api/candidates.py`
- 修改：`backend/tests/test_ingest.py`
- 修改：`backend/tests/test_resumes_api.py`
- 修改：`backend/tests/test_candidates_api.py`

- [ ] **步骤 1：扩展 ingest 与 API 的失败测试**

  在 `backend/tests/test_ingest.py::test_ingest_writes_real_vectors_pii_mapping_and_pending_review` 末尾追加：

  ```python
  from app.models import ResumeIR
  from app.services.resume.ir_storage import decrypt_resume_ir

  ir = await db.get(ResumeIR, "run-ingest")
  assert ir.content is None
  assert ir.content_enc and "# 王五" not in ir.content_enc
  assert decrypt_resume_ir(ir) == "# 王五"
  ```

  在 `backend/tests/test_resumes_api.py` 增加一个 owner 可读密文 IR 的 API 测试：直接插入 `ResumeIR(content=None, content_enc=encrypt_resume_ir("完整 IR"))`，请求 `/api/v1/resume-runs/{run_id}/ir` 并断言返回 `"完整 IR"`。

  在 `backend/tests/test_candidates_api.py` 增加候选人详情测试：为 candidate 创建 ResumeFile 与密文 ResumeIR，断言 `GET /candidates/{id}` 的 `ir` 是解密原文。

- [ ] **步骤 2：运行定向测试确认失败**

  运行：

  ```bash
  cd backend
  python -m alembic upgrade head
  python -m pytest tests/test_ingest.py::test_ingest_writes_real_vectors_pii_mapping_and_pending_review tests/test_resumes_api.py tests/test_candidates_api.py -q
  ```

  预期：ingest 测试失败，因为仍写明文 `content=ir_text`；API 测试失败，因为路由仍直接读取 `ir.content`。

- [ ] **步骤 3：改写入库与读取调用点**

  在 `backend/app/services/resume/ingest.py`：

  ```python
  from app.services.resume.ir_storage import encrypt_resume_ir

  db.add(ResumeIR(run_id=run_id, content=None, content_enc=encrypt_resume_ir(ir_text),
                  valid_chars=ir_valid_chars))
  ```

  在 `backend/app/api/resumes.py` 的 IR route：

  ```python
  from app.services.resume.ir_storage import decrypt_resume_ir

  try:
      content = decrypt_resume_ir(ir)
  except ValueError:
      raise HTTPException(500, "IR 内容不可读取") from None
  return {"run_id": run_id, "content": content, "valid_chars": ir.valid_chars}
  ```

  在 `backend/app/api/candidates.py` 的 candidate detail：

  ```python
  from app.services.resume.ir_storage import decrypt_resume_ir

  ir = decrypt_resume_ir(ir_row) if ir_row else None
  ```

  若候选人详情解密失败，抛受控 `HTTPException(500, "IR 内容不可读取")`，不得返回密文或原始异常。

- [ ] **步骤 4：运行定向测试验证通过**

  运行：

  ```bash
  cd backend && python -m pytest tests/test_ingest.py tests/test_resumes_api.py tests/test_candidates_api.py -q
  ```

  预期：通过；既有 hired IR 读取 404 回归继续通过。

- [ ] **步骤 5：Commit**

  ```bash
  git add backend/app/services/resume/ingest.py backend/app/api/resumes.py backend/app/api/candidates.py backend/tests/test_ingest.py backend/tests/test_resumes_api.py backend/tests/test_candidates_api.py
  git commit -m "fix: encrypt new ResumeIR records at rest"
  ```

## 任务 4：第一阶段 schema migration 与可重试回填命令

**文件：**
- 创建：`backend/scripts/backfill_resume_ir_encryption.py`
- 创建：`backend/tests/test_backfill_resume_ir_encryption.py`

- [ ] **步骤 1：编写回填失败测试**

  创建 `backend/tests/test_backfill_resume_ir_encryption.py`：

  ```python
  import pytest

  from app.models import ResumeIR
  from app.services.resume.ir_storage import decrypt_resume_ir
  from scripts.backfill_resume_ir_encryption import backfill_resume_irs


  @pytest.mark.asyncio
  async def test_backfill_encrypts_legacy_plaintext_and_is_idempotent():
      legacy = ResumeIR(run_id="legacy-ir", content="历史原文", content_enc=None, valid_chars=4)
      # 将 legacy 写入真实测试 session 后：
      migrated = await backfill_resume_irs(batch_size=1)
      assert migrated == 1
      refreshed = await db.get(ResumeIR, "legacy-ir")
      assert refreshed.content == "历史原文"
      assert refreshed.content_enc
      assert decrypt_resume_ir(refreshed) == "历史原文"
      assert await backfill_resume_irs(batch_size=1) == 0
  ```

  测试 fixture 应创建自己的 `SessionLocal`、user/workspace（如模型 FK 需要），并在测试结束时提交。

- [ ] **步骤 2：运行测试确认失败**

  运行：

  ```bash
  cd backend && python -m pytest tests/test_backfill_resume_ir_encryption.py -q
  ```

  预期：FAIL，报错 `ModuleNotFoundError: scripts.backfill_resume_ir_encryption`。

- [ ] **步骤 3：实现可重试回填命令**

  创建 `backend/scripts/__init__.py` 和 `backend/scripts/backfill_resume_ir_encryption.py`：

  ```python
  import argparse
  import asyncio

  from sqlalchemy import select

  from app.core.database import SessionLocal
  from app.models import ResumeIR
  from app.services.resume.ir_storage import encrypt_resume_ir


  async def backfill_resume_irs(batch_size: int = 500) -> int:
      migrated = 0
      while True:
          async with SessionLocal() as db:
              stmt = select(ResumeIR).where(
                  ResumeIR.content_enc.is_(None), ResumeIR.content.is_not(None)
              ).order_by(ResumeIR.run_id).limit(batch_size)
              rows = (await db.execute(stmt)).scalars().all()
              if not rows:
                  return migrated
              for ir in rows:
                  ir.content_enc = encrypt_resume_ir(ir.content)
              migrated += len(rows)
              await db.commit()


  def main() -> None:
      parser = argparse.ArgumentParser()
      parser.add_argument("--batch-size", type=int, default=500)
      args = parser.parse_args()
      print(asyncio.run(backfill_resume_irs(args.batch_size)))


  if __name__ == "__main__":
      main()
  ```

  让命令只处理 `content_enc IS NULL AND content IS NOT NULL`。第一阶段不清除 `content`；第二阶段删除明文字段必须等待独立发布。

- [ ] **步骤 4：运行回填测试和 migration 循环验证**

  运行：

  ```bash
  cd backend && python -m pytest tests/test_backfill_resume_ir_encryption.py -q
  python -m alembic upgrade head
  python -m alembic downgrade -1
  python -m alembic upgrade head
  ```

  预期：回填测试通过；迁移升级、降级、重升均成功。

- [ ] **步骤 5：Commit**

  ```bash
  git add backend/scripts backend/tests/test_backfill_resume_ir_encryption.py
  git commit -m "feat: add ResumeIR encryption backfill"
  ```

## 任务 5：验证新增 PII 规则确实覆盖所有出站调用

**文件：**
- 修改：`backend/tests/test_structured.py`
- 修改：`backend/tests/test_parse_resume.py`
- 修改：`backend/tests/test_ingest.py`

- [ ] **步骤 1：编写外发失败测试**

  在 `backend/tests/test_structured.py` 的 fake LLM 测试中加入输入捕获，使用：

  ```python
  ir = "---\nformat: docx\n---\n\n张三\n现住址：浙江省杭州市西湖区文三路 90 号\n<!-- block_id: 1 kind: paragraph -->\n负责支付系统"
  ```

  断言传给 `chat_json` 的 user prompt：

  ```python
  assert "张三" not in captured_user
  assert "浙江省杭州市西湖区文三路 90 号" not in captured_user
  assert "PII:name:" in captured_user
  assert "PII:address:" in captured_user
  ```

  在 profile 与 `_embed_segments` 的测试中复用同一 candidate 样本，断言模型输入不含地址、页首姓名和联系方式。

- [ ] **步骤 2：运行测试确认失败**

  运行：

  ```bash
  cd backend && python -m pytest tests/test_structured.py tests/test_parse_resume.py tests/test_ingest.py -q
  ```

  预期：在任务 1 完成前，地址与页首姓名断言失败；任务 1 完成后全部通过。

- [ ] **步骤 3：只在调用点发现遗漏时补最小修复**

  不新增旁路。若测试显示某外发调用未脱敏：

  ```python
  masked, _ = desensitize_text(payload)
  await client.<method>(masked)
  ```

  仅修改未调用 `desensitize_text` 的具体调用点；不要重新包装已有模型客户端。

- [ ] **步骤 4：运行所有 PII/解析相关测试验证通过**

  运行：

  ```bash
  cd backend && python -m pytest tests/test_pii.py tests/test_structured.py tests/test_parse_resume.py tests/test_ingest.py tests/test_ir_storage.py tests/test_backfill_resume_ir_encryption.py -q
  ```

  预期：全部通过。

- [ ] **步骤 5：Commit**

  ```bash
  git add backend/tests/test_structured.py backend/tests/test_parse_resume.py backend/tests/test_ingest.py
  git commit -m "test: cover PII redaction across resume model calls"
  ```

## 任务 6：最终验证、审查报告更新与第二阶段发布门槛

**文件：**
- 修改：`docs/superpowers/audits/2026-08-09-mvp-release-audit.md`
- 修改：`docs/superpowers/specs/2026-08-09-b2-pii-ir-protection-design.md`

- [ ] **步骤 1：运行完整后端验证**

  ```bash
  cd backend
  python -m pytest -q
  python -m ruff check app tests
  python -m alembic upgrade head
  python -m alembic downgrade base
  python -m alembic upgrade head
  ```

  预期：pytest 全绿、ruff 全绿、迁移全链可逆。

- [ ] **步骤 2：验证无 `.env` Compose 配置仍可解析**

  ```bash
  docker compose config
  ```

  预期：exit code 0。

- [ ] **步骤 3：更新审查报告**

  在 B-2 的状态中记录：

  ```markdown
  第一阶段已验证修复：保守地址/页首姓名出站脱敏、ResumeIR 新数据密文存储、历史回填命令与授权解密读取。
  第二阶段待生产回填完成后独立发布：删除 `resume_irs.content` 明文字段并将 `content_enc` 设为 NOT NULL。
  ```

  不将 B-2 标记为最终关闭，直到生产回填校验与第二阶段 migration 完成。

- [ ] **步骤 4：Commit**

  ```bash
  git add docs/superpowers/audits/2026-08-09-mvp-release-audit.md docs/superpowers/specs/2026-08-09-b2-pii-ir-protection-design.md
  git commit -m "docs: record B-2 encryption rollout status"
  ```

## 第二阶段独立发布门槛（不在本计划编码）

在生产运行第一阶段代码并成功执行回填命令后，必须先检查：

```sql
SELECT count(*)
FROM resume_irs
WHERE content IS NOT NULL AND content_enc IS NULL;
```

仅当结果为 `0`，且至少完成一次从 `content_enc` 解密回明文的抽样验证后，才允许创建独立的第二阶段 migration：

```python
def upgrade() -> None:
    op.drop_column("resume_irs", "content")
    op.alter_column("resume_irs", "content_enc", nullable=False)
```

第二阶段 migration 不得与第一阶段合并提交或作为同一次 `alembic upgrade head` 部署。
