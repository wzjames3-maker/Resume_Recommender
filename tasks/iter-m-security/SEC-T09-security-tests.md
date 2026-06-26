# SEC-T09: 安全测试用例 + 回归

## 基本信息
- **对应 Spec**: AC-SEC-001 ~ AC-SEC-008
- **依赖**: SEC-T01 ~ SEC-T08
- **预计工时**: 0.5 天
- **优先级**: P0

## 输出
- `tests/security/__init__.py`
- `tests/security/test_rbac_enforcement.py`（T03 已建，此处补充完整）
- `tests/security/test_idor.py`（T04 已建，此处补充完整）
- `tests/security/test_upload_safety.py`（T06 已建，此处补充完整）
- `tests/security/test_key_separation.py`
- `tests/security/test_error_leakage.py`
- `tests/security/conftest.py` — 多角色 token fixture

## 实现要求
1. conftest.py 提供 fixture：
   - `admin_token`、`hr_token`、`viewer_token`（登录获取）
   - `user_a_token`、`user_b_token`（用于 IDOR 测试）
   - `client`（FastAPI TestClient）
2. 每个 AC 至少一个测试用例，断言 status_code + response body code 字段
3. 回归运行：
   ```bash
   pytest tests/ -v --cov=src --cov-report=term-missing
   ```
4. 安全相关代码覆盖率 ≥ 80%

## 验收检查点
- [ ] `pytest tests/security/ -v` 全部通过
- [ ] `pytest tests/unit/test_auth.py tests/unit/test_rbac.py` 回归通过
- [ ] `pytest tests/` 全量回归无新增失败
- [ ] 安全代码覆盖率 ≥ 80%
- [ ] 覆盖率报告生成

### 通过判定
全部 ✅ → Done | 任一 ❌ 且 retry<3 → 修复 | retry=3 → BLOCKED
