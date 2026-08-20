# 租户注销真实 staging 演练（2026-08-18）

> 环境：开发库 + 本机 Docker（maxkb-slim-pg / maxkb-slim-redis / maxkb-slim-minio）真实执行，目标工作区 ws-dbg。

## 1. 执行

```bash
# 1) dry-run 预览
uv run python apps/manage.py workspace_offboard ws-dbg --dry-run
# 2) 活跃守卫拦截（有内核知识库资源 → 拒绝，需确认）
uv run python apps/manage.py workspace_offboard ws-dbg
# 3) force 确认真实注销 + 导出脱敏返还包
uv run python apps/manage.py workspace_offboard ws-dbg --force --export /tmp/offboard-drill
# 4) 幂等重入
uv run python apps/manage.py workspace_offboard ws-dbg --dry-run
```

## 2. 清理前清单（dry-run）

- 内核：knowledge 1 / documents 1 / paragraphs 3 / embeddings 4 / workspace_permissions 1 / resource_mappings 1
- HR：candidates 2 / candidate_skills 4 / resume_files 3 / storage_files 3（简历语义索引 + 存储对象）

## 3. 结果

| 检查项 | 结果 |
|---|---|
| 活跃守卫 | 有内核知识库资源时拒绝注销，加 --force 确认后执行 |
| HR 清理 | candidates/resumes/candidate_skills/memberships 全部归零 |
| 内核清理 | knowledge/documents/paragraphs 全部归零 |
| 导出返还包 | workspace_offboard_ws-dbg_*.json，扫描无手机号/邮箱泄露 |
| tombstone | storage_status=COMPLETED、attempts=1、exported_path 留痕 |
| 存储账本 | WorkspaceOffboardStorageCleanup 3 条（对应 3 份简历对象） |
| MinIO 对象 | ws-dbg 前缀 0 剩余 |
| 幂等重入 | 二次执行报「已注销，无需重复执行」 |

## 4. 结论

租户注销跨域编排在真实数据库 + 对象存储 + tombstone 幂等机制下端到端正确，生产化的前置验证完成。剩余为外部租户平台生命周期接入（当前仓库无统一 Workspace ORM，`WorkspaceOffboardingService.offboard` 为明确接入点）。
