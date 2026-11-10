# 首版整体审查包

仓库为本任务新建，无Git首次提交，不存在可比的base/head。用户要求不自动commit/push。审查对象为工作区源码，排除.env、.tools、.venv、node_modules、.local-data及输出缓存。

规格：docs/superpowers/specs/2026-10-29-academic-research-workbench-design.md。
计划：docs/superpowers/plans/2026-10-29-academic-research-workbench-detailed.md。
记录及裁定：docs/implementation/progress.md。
明确未验收范围：docs/implementation/acceptance-status.md。

实现：四角色Agent、原始来源检索与摘要筛选、入选后全文阅读、证据/综述、LangGraph PostgreSQL检查点、独立worker、REST/MCP共享服务、React界面、演示和评价工具。

审查优先级：预算并发和unknown、取消/恢复与claim fencing、检查点重入、公开资料与私有上传跨项目保护、证据版本、引用/语义边界、输入/下载及MCP边界、真实API契约、评价指标与缓存诚实性。视问题对实际用户的后果定级，不能仅因规格没列出就忽略。

验证：后端100 passed/2 skipped，ruff和mypy通过；前端4项组件测试、类型/lint/build通过；实际Chromium完整流程1 passed；五种评价策略15个mock运行完成。真实供应商和人工学术评价未执行。

本次fresh review只读，不修改代码、不切换Git、不读取密钥。列出具体文件/行、触发条件、实际后果、优先级和覆盖建议；对考虑后未评判的行为另列“Declined to judge”。不再委派其他审查者。
