# ScholarAIO 升级计划入口

Status: Current entry point

Last Updated: 2026-04-24

此前的大型总方案书、收敛轮次记录、以及代码-文档交叉验证附录，已经退出执行规范角色。

当前重构升级只以以下文档为准：

- `docs/development/directory-structure-spec.md`
- `docs/development/directory-migration-sequence.md`
- `docs/development/migration-mechanism-spec.md`
- `docs/development/user-data-migration-strategy.md`
- `docs/development/config-surface-audit.md`
- `docs/development/upgrade-validation-matrix.md`
- `docs/development/breaking-compat-cleanup-plan.md`

当前执行状态：

- the compatibility-window generation is complete and now serves as historical execution context
- the breaking cleanup generation is now the active release gate: legacy public import facades are removed, `scholaraio.cli` is reduced to an entrypoint, and runtime path resolution is fresh-layout-only
- post-migration user cleanup is now standardized as `scholaraio migrate finalize --confirm`
- the canonical implementation surface is `core` / `providers` / `stores` / `projects` / `services` / `interfaces`

从旧稿里仅保留下面这些仍然有效的结论：

1. 不推倒重写；保留现有对外行为，做分阶段重构。
2. 先把 `Config` 做成完整路径权威，再谈真实物理迁移。
3. 先落 migration control plane，再动真实用户数据。
4. `workspace/` 是项目边界，不是 `papers` 的附属视图。
5. `papers` 是最后迁移的大库；根级 agent surfaces 与 canonical skill root 在迁移期间保持不动。

当前发布级验证与迁移演练以 `docs/development/upgrade-validation-matrix.md` 为准。

当前 breaking cleanup generation 以
`docs/development/breaking-compat-cleanup-plan.md` 为准。

任何与上述 7 份权威文档冲突的旧结论，均视为废止。
