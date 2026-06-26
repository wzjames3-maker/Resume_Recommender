# 迭代任务看板：iter/m-security-hardening

## 基本信息
- **迭代类型**: Tier M（模块增强）
- **分支**: `iter/m-security-hardening`
- **触发**: CodeGraph 全项目 Review 报告（2026-06-25）
- **Spec 基线**: v1.1-security（specs/security-hardening/）
- **预计工时**: 3 天
- **串行门控**: 一次只执行一个任务，过检查点才进下一个；同一任务修复 ≤3 次

## 任务列表

| # | 任务 | 对应 Spec | 优先级 | 依赖 | 状态 |
|---|------|-----------|--------|------|------|
| SEC-T01 | .gitignore + .env.example + 密钥吊销 | SEC-REQ-004 | P0 | 无 | ✅ done |
| SEC-T02 | 密钥分离（PII_ENCRYPTION_KEY）+ fail-fast | SEC-REQ-003, SEC-RULE-003/004 | P0 | SEC-T01 | ✅ done |
| SEC-T03 | RBAC 权限强制挂载 | SEC-REQ-001, SEC-RULE-001 | P0 | SEC-T02 | ✅ done |
| SEC-T04 | IDOR 资源归属校验 | SEC-REQ-002, SEC-RULE-002 | P0 | SEC-T03 | ✅ done |
| SEC-T05 | CORS 白名单 + debug 配置化 + 异常信息最小化 | SEC-REQ-006, SEC-RULE-005/007 | P0 | SEC-T04 | ✅ done |
| SEC-T06 | 文件上传安全校验 | SEC-REQ-007, SEC-RULE-006 | P1 | SEC-T05 | ✅ done |
| SEC-T07 | 密码哈希 + 用户表迁移 | SEC-REQ-005 | P1 | SEC-T06 | ✅ done |
| SEC-T08 | 登录限流 | SEC-REQ-008, SEC-RULE-008 | P1 | SEC-T07 | ✅ done |
| SEC-T09 | 安全测试用例 + 回归 | AC-SEC-001~008 | P0 | SEC-T01~T08 | ✅ done |
| SEC-T10 | 集成验收 + spec 冻结 | 06-acceptance.md | P0 | SEC-T09 | ✅ done |

## 状态图例
- ✅ done — 未开始
- 🔄 in_progress — 执行中
- ✅ done — 检查点通过
- ⛔ blocked — 修复超限，需人介入

## 通过判定
每个任务附检查点（checkpoint）。全部 ✅ → Done | 任一 ❌ 且 retry<3 → 修复 | retry=3 → BLOCKED
