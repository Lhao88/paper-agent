# Implementation Plan: 按覆盖缺口多轮研究

**Branch**: `001-coverage-research-loop` | **Date**: 2026-11-10 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-coverage-research-loop/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

一次新的 coverage 运行在用户确认研究规格后，按覆盖缺口多轮调用封闭工具，并把可引用主张写入项目级证据账本。确认点是 `approve_spec`。每轮由程序生成覆盖表，规划器最多提交 6 个 `RoundAction`，`admit_actions` 丢弃超预算、未知论文、未启用来源和越权精读。结果写入项目文献库、引文边、主张和一页研究笔记，然后进入现有 `write`、`validate`、`finalize`。

技术路线沿用现有 Python 3.12、FastAPI、LangGraph、PostgreSQL、SQLAlchemy 2、Pydantic 2 和现有 ModelGateway，不更换前端框架。legacy 快照继续走原来的 LangGraph 直链。开发默认在新研究循环完成前保持 `planner_mode=legacy`。来源请求上限从 20 提到 40 只写入 coverage 新 run 的快照。

## Technical Context

**Language/Version**: Python 3.12（仓库锁定 3.12.16），前端保持现有 TypeScript / React 工程

**Primary Dependencies**: FastAPI、LangGraph、SQLAlchemy 2、Pydantic 2、现有 ModelGateway、httpx（仅 Semantic Scholar 测试替身和已有来源客户端）

**Storage**: PostgreSQL。向量使用 `REAL[]`，余弦在进程内计算。不安装 pgvector，不引入独立向量库。嵌入默认 mock 哈希。

**Testing**: 后端在 `backend` 目录执行 `uv run --locked pytest -q`、`uv run --locked ruff check app tests`、`uv run --locked mypy app`。前端执行 `npm run typecheck`、`npm run lint`、`npm run test`、`npm run build`。浏览器验收使用 `npm run test:e2e`。live 测试默认跳过。Semantic Scholar 使用 httpx 测试替身。

**Target Platform**: 现有本机研究工作台。API 与独立 worker 分开运行。真实供应商、IDE 与桌面客户端、人工评价集、PostgreSQL 16、Docker 和备份恢复不作为本变更完成标准。

**Project Type**: 已有前后端研究工作台。后端增加规划、记忆和封闭工具；前端只扩展规格编辑、轮次笔记和主张侧栏。

**Performance Goals**: 一轮规划最多 6 个动作。coverage 运行默认最多 4 轮，允许 1 到 8 轮，以该 run 冻结的 `max_research_rounds` 为准。一跳引文默认最多新增 15 篇。篇内片段默认每篇最多 3 次。

**Constraints**: 默认模型和论文来源都是 mock。真实模型、OpenAlex、arXiv、Semantic Scholar 必须显式开启，调用记入现有预算账本。角色保持协调、检索、阅读、综述。不开放任意网页、任意 URL、shell、SQL，不抓取知网、万方。写作上下文只读已绑定原文跨度的主张和原文摘录。页码来自解析器。恢复前必须确认旧 worker 已退出。不自动 git commit，不 push。

**Scale/Scope**: 本变更只覆盖一条 coverage 研究循环及其与 legacy 快照的并存。进程内余弦服务一个项目内的摘要和已精读分块；超出这个范围也不在本变更安装向量扩展。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 本计划如何满足 | 结果 |
| --- | --- | --- |
| I. 四类角色与封闭调度 | 调度只依据覆盖表、动作清单和 `admit_actions`。规划器不直接调用来源。MCP 仍是现有 9 个外部入口，角色之间不互调。 | 通过 |
| II. 默认 mock 与显式真实来源 | 默认 mock。Semantic Scholar、OpenAlex、arXiv 和真实模型都要显式开启，并记入现有预算账本。live 测试默认跳过。 | 通过 |
| III. 已有 run 保持 legacy 直链 | `build_graph` 保持 plan 到 finalize。`planner_mode=legacy` 在研究循环完成前保持开发默认。选图读取该 run 已冻结的模式。 | 通过 |
| IV. 主张必须绑定原文跨度 | 主张写入前走现有原文跨度核对，并指向已有 evidence。模型不生成页码。程序只检查引用存在。 | 通过 |
| V. 封闭工具与未授权中文全文 | 工具只包括已注册检索、一跳引文、篇内片段和现有阅读抽取。无中文全文授权时覆盖表写入 `zh_fulltext_not_licensed`。 | 通过 |
| VI. 进程内向量 | 向量存 PostgreSQL `REAL[]`，余弦在进程内计算，嵌入默认 mock 哈希。不安装 pgvector。 | 通过 |
| VII. 恢复前确认旧 worker | 沿用现有恢复规则。本计划不自动 commit 或 push。 | 通过 |
| VIII. 沿用现有验证命令 | 完成判断只使用宪章列出的后端、前端和浏览器命令。 | 通过 |
| IX. 单独验收项不属于本次完成标准 | 真实供应商小样本、IDE 与桌面客户端、人工评价集、PostgreSQL 16、Docker 和备份恢复保持单独验收。 | 通过 |

Phase 0 之前无未决澄清，无宪章违规。

## Project Structure

### Documentation (this feature)

```text
specs/001-coverage-research-loop/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── coverage-api.md
│   └── round-actions.md
└── tasks.md              # 由 /speckit-tasks 生成，本命令不创建
```

### Source Code (repository root)

```text
backend/app/planning/spec.py
backend/app/planning/planner.py
backend/app/planning/admit.py
backend/app/memory/coverage.py
backend/app/memory/ledger.py
backend/app/memory/notebook.py
backend/app/memory/library.py
backend/app/memory/index.py
backend/app/tools/runtime.py
backend/app/tools/search_works.py
backend/app/tools/citations.py
backend/app/tools/search_in_paper.py
backend/app/sources/semantic_scholar.py
backend/prompts/planner_round.j2
backend/prompts/coordinator_spec.j2
backend/app/schemas/contracts.py
backend/app/config.py
backend/app/workflow/graph.py
backend/app/workflow/coverage_flow.py
backend/app/worker/execute.py
backend/app/agents/coordinator.py
backend/app/agents/review.py
backend/app/services/research.py
backend/app/api/router.py
backend/app/schemas/api.py
backend/app/mcp_gateway/server.py
backend/tests/unit/test_admit.py
backend/tests/unit/test_coverage.py
backend/tests/unit/test_index.py
backend/tests/integration/test_research_loop.py
frontend/src/features/research/PlanEditor.tsx
frontend/src/features/research/ResearchPage.tsx
frontend/src/features/papers/EvidencePanel.tsx
```

**Structure Decision**: 新职责按 `docs/superpowers/plans/2026-11-08-planning-memory-tools-refactor.md` 第 3 节放入上列文件。已有同名模块继续承担该职责，不另起一套目录。`coverage_flow.py` 只做 coverage 图的节点适配，并调用 planning、memory 和 tools。`build_graph` 继续编排 legacy 直链。前端沿用现有 React 页面，只增加规格、笔记和主张所需字段。

## Complexity Tracking

无宪章违规，不填写例外。

## Post-Design Constitution Check

Phase 1 的数据模型、接口契约和验收步骤复核后，九条原则仍全部通过。

- 数据模型把主张绑到现有 evidence，页码仍来自解析器。
- 契约没有新增 MCP 工具，也没有开放网页、shell 或 SQL。
- 向量契约是 PostgreSQL `REAL[]` 加进程内余弦，嵌入默认 mock 哈希。
- quickstart 使用宪章中的验证命令，并把 live 测试保持为默认跳过。
- legacy 与 coverage 的分界仍是每条 run 冻结的模式，不是后来的进程配置。
