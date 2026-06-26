# SEC-T10: 集成验收 + spec 冻结

## 基本信息
- **对应 Spec**: specs/security-hardening/06-acceptance.md
- **依赖**: SEC-T01 ~ SEC-T09
- **预计工时**: 0.5 天
- **优先级**: P0

## 输出
- `tasks/iter-m-security/acceptance-report.md` — 逐项验收记录
- `CHANGELOG.md` — 追加 v1.1-security 变更记录
- spec 基线标记为 v1.1-security（冻结）

## 实现要求
1. 按 `06-acceptance.md` 逐项核对 AC-SEC-001 ~ AC-SEC-008，记录通过/失败
2. 失败项回退到对应任务修复（断路器：≤3 次）
3. 全部通过后：
   - `CHANGELOG.md` 记录本次安全加固变更摘要
   - 在 `specs/security-hardening/00-overview.md` 标注"已冻结 v1.1-security"
   - 更新 `tasks/task.md` 主看板新增迭代记录段落
4. 人工确认项（密钥吊销）需人工签字确认

## 验收检查点
- [ ] AC-SEC-001 ~ AC-SEC-008 逐项记录结果
- [ ] 失败项为 0 或已回退修复
- [ ] CHANGELOG 已更新
- [ ] spec 标注冻结
- [ ] 主看板 task.md 已更新迭代记录
- [ ] 人工确认项（密钥吊销）已签字

### 通过判定
全部 ✅ → Done → 迭代完成，可合并 PR | 任一 ❌ 且 retry<3 → 修复 | retry=3 → BLOCKED
