# AgentKB-HR（基于 MaxKB v2 派生）

本仓库源自 MaxKB v2（GPL-3.0，https://github.com/1panel-dev/MaxKB）。
依据 GPL-3.0，本衍生仓库及其后续代码必须以 GPL-3.0 开源。
基线 commit：`65c5ff8`

## 裁剪范围（仅隐藏入口，不删除底层代码）
- 可视化工作流编排（前端路由层隐藏）
- MCP 工具库（前端菜单隐藏）
- 应用市场（前端视图层隐藏）
- 触发器（已上游隐藏）

## 新增模块
- apps/hr：人事业务 Django app（骨架）
- ui/src/views/hr：人事占位页

## 旧版参考

- `references/agentkb/` 是旧版 AgentKB 的固定源码快照，仅用于业务规则、状态机、接口和测试迁移参考。
- 旧版参考代码不参与 MaxKB 的运行、构建或部署，不应从该目录直接导入模块。
- 新版实现以本仓库的 MaxKB 内核、产品 PRD 和当前设计规格为准；旧版行为仅作为迁移参考。
- 参考快照来源：`maxkb-replica`，commit `40278bc0cbd48855ebf017214da22d7419cea88b`。
