---

description: "Task list for the coverage research loop"
---

# Tasks: 按覆盖缺口多轮研究

**Input**: Design documents from `/specs/001-coverage-research-loop/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: 包含 quickstart.md 和 plan.md 已点名的测试文件。先补断言，确认未实现的行为会失败，再改对应实现。已经通过的断言不得改弱。

**Organization**: 按用户故事分组。US1、US2、US4 是 P1，US3 是 P2。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件，且不依赖本阶段未完成任务）
- **[Story]**: 用户故事标签，只用于故事阶段
- 描述中给出仓库内文件路径

## Path Conventions

- 后端代码在 `backend/app/`，后端测试在 `backend/tests/`
- 前端代码在 `frontend/src/`
- 不新增 Python 版本、前端框架、pgvector 或独立向量库

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 确认现有工程和缺失的文件边界，不初始化新项目

- [ ] T001 确认 `backend/pyproject.toml` 与 `frontend/package.json` 继续使用现有 Python 3.12、FastAPI、LangGraph、PostgreSQL、SQLAlchemy 2、Pydantic 2 和现有前端框架，不加入 pgvector
- [ ] T002 [P] 补齐第 3 节尚缺的职责文件 `backend/app/memory/notebook.py`、`backend/app/memory/library.py`、`backend/app/tools/runtime.py`，不把 legacy 图移出 `backend/app/workflow/graph.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 所有用户故事共用的契约、默认配置、向量存储和选图规则

**⚠️ CRITICAL**: 完成本阶段之前，不开始任何用户故事

- [X] T003 在 `backend/app/schemas/contracts.py` 对齐共享类型并保留 `PlanDraft` 与 `FollowupDecision`：`extra=forbid`；`ResearchSpec.questions` 最少 3 最多 5；规则最少 1 最多 12；抽取列最少 1 最多 12；列字段只允许 `method`、`dataset`、`experimental_setup`、`metric`、`result`、`limitation`；`description_zh` 与规则 `text_zh` 长度 1 到 300；覆盖目标 `min_included_papers` 默认 3、最小 1、最大 15；`RoundAction.kind` 只允许 `search_works`、`expand_citations`、`read_fulltext`、`search_in_paper`、`stop`；`RoundPlan.actions` 最少 1 最多 6；主张极性只允许 `support`、`contradict`
- [X] T004 [P] 在 `backend/app/config.py` 保持 `planner_mode=legacy`、`max_research_rounds` 默认 4 且范围 1 到 8、`max_actions_per_round` 默认 6 且范围 1 到 6、`max_citation_neighbors` 默认 15 且范围 1 到 30、`max_search_in_paper_calls_per_paper` 默认 3 且范围 1 到 6、`embedding_mode=mock`、`embedding_dimensions` 默认 256 且范围 32 到 3072、`enable_semantic_scholar=false`
- [X] T005 [P] 在 `backend/migrations/versions/` 新增只建 `text_embeddings` 的迁移，向量列为 PostgreSQL `REAL[]`，不创建 pgvector 扩展，不改已有行的含义
- [X] T006 在 `backend/app/worker/execute.py` 选图只读取该 run 已经冻结的 `planner_mode`：`coverage` 用 `build_coverage_graph`，`legacy` 用 `build_graph`。不读取后来的进程配置

**Checkpoint**: 契约、默认配置、向量表和选图规则已固定

---

## Phase 3: User Story 1 - 检索前确认研究规格 (Priority: P1) 🎯 MVP

**Goal**: 检索开始前，用户确认 3 到 5 个子问题、纳入和排除规则、至少一列抽取字段，以及每个子问题的覆盖目标

**Independent Test**: 只走到确认时，规格可见且可编辑，确认前没有论文检索；过期计划版本被拒绝

### Tests for User Story 1

- [X] T007 [P] [US1] 在 `backend/tests/unit/test_spec.py` 覆盖未知来源 `cnki` 被拒绝、悬空列被拒绝，以及问题、列和规则编号由程序重写
- [X] T008 [P] [US1] 在 `backend/tests/integration/test_spec_storage.py` 覆盖 `spec_json` 为空的 legacy 计划仍可读取，且过期 `expected_version` 确认被拒绝
- [X] T009 [P] [US1] 在 `frontend/src/features/research/PlanEditor.test.tsx` 覆盖确认前可增删规则和抽取列、显示覆盖目标，并可钉住或排除已知论文。这是确认规格前的操作，不是下一次运行才看见的文献库

### Implementation for User Story 1

- [X] T010 [US1] 在 `backend/app/planning/spec.py` 把草稿规范成研究规格，范围以用户请求为准，来源只接受 `openalex`、`arxiv`、`semantic_scholar`
- [X] T011 [US1] 通过 `backend/prompts/coordinator_spec.j2` 和 `backend/app/agents/coordinator.py` 起草规格，现有 `plan` 路径继续留给 legacy
- [X] T012 [US1] 在 `backend/app/workflow/coverage_flow.py` 的 `approve_spec` 成功时，把同一组冻结字段同时写入该 run 的 `input_snapshot` 和 `config_snapshot`：`planner_mode`、`max_research_rounds`、`max_actions_per_round`、`max_citation_neighbors`、`max_search_in_paper_calls_per_paper`、`embedding_mode`、`enabled_sources`，以及当时的来源请求上限、模型调用上限和精读篇数上限
- [X] T013 [US1] 在 `backend/app/services/research.py`、`backend/app/api/router.py` 和 `backend/app/schemas/api.py` 保持 `expected_version` 为计划版本，并返回规格、规则、抽取列和覆盖目标
- [X] T014 [US1] 在 `frontend/src/features/research/PlanEditor.tsx` 允许确认前增删纳入和排除规则、增删抽取列、显示覆盖目标，并钉住或排除已知论文。这是确认规格前的操作，不是 T037 里下一次运行才看见的文献库

**Checkpoint**: 用户故事 1 可以单独演示。确认前没有检索

---

## Phase 4: User Story 2 - 按覆盖缺口进行下一轮检索 (Priority: P1)

**Goal**: 已确认的 coverage 运行按覆盖缺口多轮执行封闭工具，第二轮查询来自缺口

**Independent Test**: 第一轮后仍有必填缺口且预算足够时，第二轮查询与第一轮不同，并能对应到覆盖表缺口

### Tests for User Story 2

- [X] T015 [P] [US2] 在 `backend/tests/unit/test_coverage.py` 覆盖空账本的未满足子问题、相关性不少于 3 的新论文为 0 且没有新必填单元格时的饱和，以及语言含 `zh` 且无中文全文源时写入 `zh_fulltext_not_licensed`
- [X] T016 [P] [US2] 在 `backend/tests/unit/test_admit.py` 覆盖八条准入规则，包括必填目标未满足且预算足够时拒绝单独 `stop` 并补出缺口检索。断言写明：全文只能下载已纳入或本轮选中的论文；没有摘要不得当成不相关
- [X] T017 [P] [US2] 在 `backend/tests/unit/test_index.py` 覆盖同一文本的 mock 哈希稳定，以及 `embedding_mode=off` 时排序与现有关键词相关度一致
- [X] T018 [P] [US2] 在 `backend/tests/unit/test_semantic_scholar.py` 用 httpx 替身验证检索和一跳，并断言 PDF 地址不由该适配器下载

### Implementation for User Story 2

- [X] T019 [US2] 在 `backend/app/memory/coverage.py` 只根据账本和项目库生成覆盖表，不调用模型
- [X] T020 [US2] 在 `backend/app/planning/admit.py` 用纯函数丢弃超预算、未知论文、未启用来源和越权精读，每轮最多保留 `max_actions_per_round`，默认 6 个。准入规则写明：全文只能下载已纳入或本轮选中的论文；没有摘要不得当成不相关
- [ ] T021 [US2] 在 `backend/app/planning/planner.py` 和 `backend/prompts/planner_round.j2` 只依据规格、最近两页笔记和覆盖表解析最多 6 个 `RoundAction`
- [ ] T022 [US2] 在 `backend/app/tools/runtime.py` 只执行 T020 已经准入的结果，再调用 `backend/app/tools/search_works.py`、`backend/app/tools/citations.py` 和 `backend/app/tools/search_in_paper.py`，并把来源请求和模型调用记入现有预算账本
- [X] T023 [US2] 在 `backend/app/sources/semantic_scholar.py` 保持检索与一跳引文，PDF 下载继续交给现有文档服务
- [X] T024 [US2] 在 `backend/app/memory/index.py` 读取 PostgreSQL `REAL[]`，在进程内计算余弦，默认使用 mock 哈希
- [ ] T025 [US2] 在 `backend/app/memory/notebook.py` 每轮追加一页笔记，记录已执行动作、被拒绝动作、未满足问题和排序方式
- [ ] T026 [US2] 在 `backend/app/workflow/graph.py` 与 `backend/app/workflow/coverage_flow.py` 实现确认后的多轮循环；四者任一即进入现有 `write`、`validate`、`finalize`：必填列已满足且本轮没有新的高相关论文、连续两轮饱和、预算不足、达到该 run 冻结的 `max_research_rounds`
- [ ] T027 [P] [US2] 在 `frontend/src/features/research/ResearchPage.tsx` 按轮次显示已执行动作、被拒绝动作和未满足问题
- [ ] T028 [P] [US2] 在 `backend/app/mcp_gateway/server.py` 的现有 `get_research_status` 返回 `round_index`、`unmet_question_ids` 和 `stop_reason`，不新增 MCP 工具，也不等待循环结束
- [ ] T029 [US2] 在 `backend/tests/integration/test_research_loop.py` 证明确认前没有检索，且第二轮查询来自覆盖缺口并与第一轮不同

**Checkpoint**: 用户故事 1 和 2 都能单独验证。缺口检索不再重复拼接第一轮英文词

---

## Phase 5: User Story 4 - 旧模式运行保持原路径 (Priority: P1)

**Goal**: legacy 快照继续走原来的固定阶段，预算保持 20 与 150

**Independent Test**: 不启用 coverage 时，一次运行仍依次经过原来的 11 个阶段，且进程配置变更不改写已冻结快照

### Tests for User Story 4

- [ ] T030 [P] [US4] 用现有 legacy 集成测试确认 `backend/app/workflow/graph.py` 的 `build_graph` 仍依次经过 plan、approve_plan、retrieve、screen、select、read、analyze、decide、write、validate、finalize

### Implementation for User Story 4

- [ ] T031 [US4] 在 `backend/app/worker/execute.py` 把 legacy 快照的来源请求上限保持为 20、模型调用上限保持为 150，只让 coverage 新 run 的快照使用 40 和 180
- [ ] T032 [US4] 在 `backend/app/config.py` 与 `backend/app/services/research.py` 保持开发默认 `planner_mode=legacy`，并保证一条 run 的冻结模式不会被另一条 run 或后来的进程配置改写

**Checkpoint**: 同一项目里的 legacy 运行与 coverage 运行按各自快照并存

---

## Phase 6: User Story 3 - 从综述打开主张并留给下一轮 (Priority: P2)

**Goal**: 综述判断能打开到主张，主张落到现有 evidence；下一轮能看见项目文献库

**Independent Test**: 综述中的文献判断都能打开到主张，同一项目的下一次运行在检索前看见入库论文、钉住项和排除项

### Tests for User Story 3

- [ ] T033 [P] [US3] 在 `backend/tests/integration/test_research_loop.py` 覆盖综述证据都能在主张中找到，以及同项目第二次运行能看见钉住项和排除项
- [ ] T034 [P] [US3] 在 `frontend/src/features/papers/EvidencePanel.test.tsx` 覆盖主张显示 `support` 或 `contradict`，以及原来的原文位置

### Implementation for User Story 3

- [ ] T035 [US3] 在 `backend/app/memory/ledger.py` 只在现有原文跨度核对通过后写入主张，主张必须指向同一 `paper_id` 的已有 evidence；同一 `project_id`、`paper_id`、`column_id`、`evidence_id`、`polarity` 不重复插入
- [ ] T036 [US3] 在 `backend/app/agents/review.py` 让 coverage 写作上下文只读已绑定主张和对应原文摘录；没有主张的子问题写成未覆盖说明，极性相反的主张分成两行
- [ ] T037 [US3] 在 `backend/app/memory/library.py` 用现有 `project_papers.user_decision` 保存在库、钉住和排除，使下一次运行检索前可见，且被排除论文不进入新候选集
- [ ] T038 [US3] 在 `frontend/src/features/papers/EvidencePanel.tsx` 显示主张极性 `support` 或 `contradict` 和原来的原文位置，页码仍来自解析结果

**Checkpoint**: 四个用户故事都可独立验证

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: 按 quickstart 做整次验证，并守住完成边界

- [ ] T039 按 `specs/001-coverage-research-loop/quickstart.md` 在 `backend` 执行 `uv run --locked pytest -q`、`uv run --locked ruff check app tests`、`uv run --locked mypy app`，在 `frontend` 执行 `npm run typecheck`、`npm run lint`、`npm run test`、`npm run build`、`npm run test:e2e`
- [ ] T040 在规格定义的研究循环完成点，也就是 T029 与 T030 都已通过时，才把 `backend/app/config.py` 的开发默认改为 `planner_mode=coverage`。这个完成点不是任务清单的 Phase 6。已经写入快照的 run 保持原模式
- [ ] T041 [P] 核对 `backend/app/mcp_gateway/server.py` 仍只有现有 9 个工具，并且真实供应商小样本、IDE 与桌面客户端、人工评价集、PostgreSQL 16、Docker 和备份恢复不被写成这次完成

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 可以立即开始
- **Foundational (Phase 2)**: 依赖 Setup，并阻塞所有用户故事
- **User Stories (Phase 3+)**: 都依赖 Foundational
- **Polish (Phase 7)**: 依赖打算交付的用户故事

### User Story Dependencies

- **User Story 1 (P1)**: Foundational 完成后即可开始，不依赖其他故事
- **User Story 2 (P1)**: 依赖 User Story 1 的规格确认，因为它验证确认之后的轮次
- **User Story 4 (P1)**: Foundational 完成后即可开始，不依赖 User Story 1 或 2
- **User Story 3 (P2)**: 依赖 User Story 2 写出的主张和项目文献库，但验收仍使用它自己的集成断言

### Within Each User Story

- 该故事的测试任务先于实现任务
- 模型与纯函数先于流程接线
- 流程接线先于界面和外部状态入口
- 不要自动 git commit，不要 push

### Parallel Opportunities

- T002 可与 T001 并行
- T004 与 T005 可并行
- T007、T008、T009 可并行
- T015、T016、T017、T018 可并行
- T027 与 T028 可并行
- Foundational 完成后，User Story 4 可与 User Story 1 并行
- T033 与 T034 可并行

---

## Parallel Example: User Story 1

```bash
# 三个测试文件彼此独立，可同时补断言：
Task: "T007 backend/tests/unit/test_spec.py"
Task: "T008 backend/tests/integration/test_spec_storage.py"
Task: "T009 frontend/src/features/research/PlanEditor.test.tsx"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. 完成 Phase 1 和 Phase 2
2. 完成 Phase 3 的 User Story 1
3. 停下来单独验证确认前没有检索
4. 通过后再进入多轮检索

### Incremental Delivery

1. Setup 与 Foundational 完成后，先交付规格确认
2. 再交付缺口驱动的第二轮检索
3. User Story 4 可在 Foundational 之后并行，保证旧演示不被打断
4. 最后交付主张追溯和项目文献库复用
5. 只有新旧路径都通过后，才考虑切换开发默认模式

### Parallel Team Strategy

1. 一起完成 Setup 与 Foundational
2. 之后一人做 User Story 1，另一人做 User Story 4
3. User Story 1 完成后接 User Story 2
4. User Story 2 完成后再做 User Story 3

---

## Notes

- [P] 表示不同文件且没有未完成的依赖
- 故事阶段的任务必须带 [US1]、[US2]、[US3] 或 [US4]
- 每个故事都能在自己的检查点单独验证
- 不要自动 git commit，不要 push
- 恢复已有运行前先确认旧 worker 已退出
- live 测试保持默认跳过
