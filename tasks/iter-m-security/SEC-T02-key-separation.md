# SEC-T02: 密钥分离（PII_ENCRYPTION_KEY）+ fail-fast

## 基本信息
- **对应 Spec**: SEC-REQ-003, SEC-RULE-003/004
- **对应 AC**: AC-SEC-003
- **依赖**: SEC-T01
- **预计工时**: 0.5 天
- **优先级**: P0

## 输入
- `src/resume_store/encryption.py`（当前 `_get_key` 读 `settings.jwt.JWT_SECRET_KEY` + sha256 派生 + getattr 兜底）
- `src/common/config.py`（无 PIISettings；Settings 聚合 app/llm/embedding/milvus/mongodb/redis/queue/jwt）

## 输出
- `src/common/config.py` — 新增 PIISettings；Settings 聚合 pii；密钥 Field 改必填
- `src/resume_store/encryption.py` — `_get_key` 改读 PII_ENCRYPTION_KEY
- `scripts/migrate_pii_key.py` — 旧密文迁移脚本
- `tests/unit/test_encryption.py` — 密钥分离测试

## 实现要求
1. `config.py` 新增（各子配置已是独立 BaseSettings，聚合在 Settings）：
   ```python
   class PIISettings(BaseSettings):
       model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
       PII_ENCRYPTION_KEY: str = Field(..., description="PII 加密密钥（Fernet 原生 key）")
   ```
   在 `Settings` 类新增 `pii: PIISettings = Field(default_factory=PIISettings)`
2. `config.py` 必填化（default 改 `...`）：
   - `JWTSettings.JWT_SECRET_KEY`
   - `MongoDBSettings.MONGODB_PASSWORD`
   - `RedisSettings.REDIS_PASSWORD`
   - **不改** `LLM_API_KEY`/`EMBEDDING_API_KEY`（保持空串默认）
3. `encryption.py._get_key`：
   ```python
   def _get_key(self) -> bytes:
       settings = get_settings()
       key = settings.pii.PII_ENCRYPTION_KEY
       return key.encode() if isinstance(key, str) else key
   ```
   删除 `hashlib.sha256` 派生与 `getattr` 兜底。`_get_fernet` 直接 `Fernet(key)`。
4. PIIEncryptor 单例缓存了 `_fernet`，key 来源改变后需支持重置：新增 `reset()` 方法清空 `_fernet`
5. 迁移脚本 `migrate_pii_key.py`：
   - 旧 key = sha256(旧 JWT_SECRET_KEY) 派生的 base64
   - 遍历 MongoDB resumes，对 `_encrypted_fields` 中的 phone/email 用旧 key 解密 → 新 PII_ENCRYPTION_KEY 加密 → 写回
   - 无存量数据时可跳过

## 验收检查点
- [ ] `PIISettings` 存在，`Settings.pii` 聚合存在
- [ ] `encryption.py` 不再 import 或引用 `settings.jwt`
- [ ] 无 `getattr(..., "default-secret-key")` 与 sha256 派生残留
- [ ] 不配置 PII_ENCRYPTION_KEY 时 `get_settings()` 抛 ValidationError
- [ ] JWT_SECRET_KEY/MONGODB_PASSWORD/REDIS_PASSWORD default 为 `...`
- [ ] LLM_API_KEY/EMBEDDING_API_KEY 仍为空串默认
- [ ] `tests/unit/test_encryption.py` 新 key 加解密往返通过
- [ ] 迁移脚本对测试数据验证通过（若有存量数据）

### 通过判定
全部 ✅ → Done | 任一 ❌ 且 retry<3 → 修复 | retry=3 → BLOCKED
