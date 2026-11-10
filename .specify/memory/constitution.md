<!--
Sync Impact Report
- Version change: unratified template (no version) → 1.0.0
- Modified principles:
  - template slot PRINCIPLE_1_NAME → I. 四类角色与封闭调度
  - template slot PRINCIPLE_2_NAME → II. 默认 mock 与显式真实来源
  - template slot PRINCIPLE_3_NAME → III. 已有 run 保持 legacy 直链
  - template slot PRINCIPLE_4_NAME → IV. 主张必须绑定原文跨度
  - template slot PRINCIPLE_5_NAME → V. 封闭工具与未授权中文全文
- Added sections:
  - VI. 进程内向量
  - VII. 恢复前确认旧 worker
  - VIII. 沿用现有验证命令
  - IX. 单独验收项不属于本次重构完成标准
  - 权威依据
  - 规划合规
- Removed sections: none
  (template example comments removed after placeholders were replaced)
- Follow-up TODOs: none
-->

# 学术调研多 Agent 工作台 Constitution

## Core Principles

### I. 四类角色与封闭调度

角色必须保持协调、检索、阅读、综述四类。
调度必须依据覆盖表、动作清单和运行时准入。
角色之间不得自由群聊，也不得互相调用 MCP。
现有 9 个 MCP 工具必须仍只作为外部入口。

理由：分工和外部工具面已经固定。后续规划不得把角色改成互调群聊，
也不得把 MCP 从外部入口改成角色之间的调用通道。

### II. 默认 mock 与显式真实来源

默认模型与论文来源必须是 mock。
真实模型、OpenAlex、arXiv 与 Semantic Scholar 必须显式开启。
这些调用必须记入现有预算账本。
live 测试必须默认跳过。

理由：未显式开启时不得产生真实供应商调用。用量继续记入现有预算账本。

### III. 已有 run 保持 legacy 直链

已有 run 必须继续走现有 LangGraph 直链。
在新研究循环完成前，开发默认必须保持 `planner_mode=legacy`。
写入 run 快照后的模式不得随后来的进程配置改变。

理由：未完成的研究循环不得打断现有演示和测试。
每个 run 以写入快照时的模式为准。

### IV. 主张必须绑定原文跨度

写作必须只使用已绑定原文跨度的主张。
页码必须来自解析器。模型不得生成页码。
程序必须只检查引用是否存在。
语义是否支持必须留给人工核验。

理由：程序只验收引用存在性。语义是否成立留给人工核验。

### V. 封闭工具与未授权中文全文

工具必须只包括已注册的检索、一跳引文、篇内片段，以及现有阅读和抽取。
不得开放任意网页、任意 URL、shell 或 SQL。
不得抓取知网、万方。
语言范围含 `zh` 且没有已配置中文全文源时，
覆盖表必须写入 `zh_fulltext_not_licensed`。

理由：工具面保持已注册能力。
未授权的中文全文必须记为覆盖限制，不得改用抓取替代。

### VI. 进程内向量

向量必须存放在 PostgreSQL `REAL[]`。
余弦必须在进程内计算。
不得安装 pgvector，不得引入独立向量库。
嵌入默认必须是 mock 哈希。

理由：向量计算保持在现有 PostgreSQL 与进程内。
本治理不得通过安装扩展或换独立向量库来改写这条边界。

### VII. 恢复前确认旧 worker

恢复前必须确认旧 worker 已退出。
不得自动执行 git commit，不得 push。

理由：接管前必须确认旧进程已经退出，避免两个 worker 同时推进同一 run。
提交和推送只在明确要求时进行。

### VIII. 沿用现有验证命令

验证命令必须沿用仓库现状，不得另换一套完成标准。

后端必须在 `backend` 目录执行：

- `uv run --locked pytest -q`
- `uv run --locked ruff check app tests`
- `uv run --locked mypy app`

前端必须在 `frontend` 目录执行：

- `npm run typecheck`
- `npm run lint`
- `npm run test`
- `npm run build`

浏览器验收必须使用 `npm run test:e2e`。

理由：完成判断使用仓库已经记录的命令，避免重构期间更换检查入口。

### IX. 单独验收项不属于本次重构完成标准

下列事项必须保持为单独验收项，不得计入这一次重构的完成标准：

- 真实供应商小样本
- IDE 与桌面客户端
- 人工评价集
- PostgreSQL 16
- Docker
- 备份恢复

理由：这些事项在验收记录中仍是单独验收项。
重构完成不得被写成上述外部验收已经通过。

## 权威依据

下列文档是这九条规则的依据。后续规划引用它们时，不得改写本宪章已经固定的规则。

- `docs/superpowers/specs/2026-10-29-academic-research-workbench-design.md`
- `docs/implementation/acceptance-status.md`
- `docs/superpowers/plans/2026-11-08-planning-memory-tools-refactor.md` 第 1 节和第 13 节

## 规划合规

规格、计划、任务与实现审查必须逐条核对上述原则。
与原则冲突的文字必须先通过宪章修订处理，不得在功能规划中直接改写这些规则。
本次重构的完成声明必须同时满足原则 VIII 的命令结果，
并且不得把原则 IX 的事项算作已完成。

## Governance

本宪章在上述九条上优先于后续功能规格、实施计划和任务清单。
修订必须改本文件，并在文首保留同步影响说明供审阅；该说明在提交前移除。
版本按语义化版本递增：

- MAJOR：删除或重新定义已批准原则，使既有治理不再兼容。
- MINOR：新增原则或对既有原则作实质性扩展。
- PATCH：澄清措辞、修正笔误或不改变含义的文字调整。

合规审查必须确认规格、计划、任务和实现仍满足全部原则。
无法同时满足时，停止采用冲突方案，先修订宪章并得到明确批准。

**Version**: 1.0.0 | **Ratified**: 2026-11-10 | **Last Amended**: 2026-11-10
