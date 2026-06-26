# SEC-T01: .gitignore + .env.example + 密钥吊销

## 基本信息
- **对应 Spec**: SEC-REQ-004
- **对应 AC**: AC-SEC-004
- **依赖**: 无
- **预计工时**: 0.5 天
- **优先级**: P0

## 输入
- CodeGraph Review #1
- 现有 `.env`（含真实密钥）

## 输出
- `.gitignore`（新建）
- `.env.example`（重写，仅键名）
- `CHANGELOG.md` 追加密钥吊销记录

## 实现要求
1. 创建 `.gitignore`，包含：
   ```
   .env
   .env.*
   !.env.example
   __pycache__/
   *.pyc
   *.log
   server_stdout.log
   server_stderr.log
   .coverage
   .pytest_cache/
   screenshot_*.png
   test_screenshots/
   .codegraph/
   ```
2. 重写 `.env.example`：所有键保留，值改为占位符 `<your-key-here>`，删除所有 `sk-` 真实 key
3. 人工步骤（在任务备注中记录，不自动化）：
   - 登录 SenseNova 控制台吊销当前 `LLM_API_KEY`、`OCR_API_KEY`、`EMBEDDING_API_KEY`、`RERANKER_API_KEY`
   - 生成新 key 写入新的 `.env`（不入库）
   - 生成 Fernet key：`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` 作为 `PII_ENCRYPTION_KEY`

## 验收检查点
- [ ] `.gitignore` 存在且包含 `.env`、`__pycache__`、`*.log`
- [ ] `.env.example` 无任何 `sk-` 开头的真实 key
- [ ] `.env.example` 含 `PII_ENCRYPTION_KEY=` 占位
- [ ] CHANGELOG 记录密钥吊销事件
- [ ] `git init && git check-ignore .env` 返回 `.env`（若仓库已存在直接 check-ignore）

### 通过判定
全部 ✅ → Done | 任一 ❌ 且 retry<3 → 修复 | retry=3 → BLOCKED
