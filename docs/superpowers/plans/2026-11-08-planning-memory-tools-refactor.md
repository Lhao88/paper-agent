# 规划、记忆与工具重构 Implementation Plan

> **For agentic workers:** 实现时使用 superpowers:executing-plans，按任务顺序做。每项任务先写失败测试再改代码。不自动 commit、不 push。`planner_mode=legacy` 在阶段 6 之前保持默认，避免未完成的循环把现有演示和测试跑断。

**Goal:** 把一次研究从「生成提纲后沿固定图走到综述」改成「用户确认研究规格，然后按覆盖缺口多轮调用封闭工具，并把可引用主张写入项目级证据账本」。

**Architecture:** 新 run 在 `approve_spec` 之后进入研究循环。每轮先由程序根据账本生成覆盖表，规划器只提交一批有类型的动作，工具运行时做预算和身份校验后执行，结果写入项目文献库、引文边、主张和一页研究笔记。写作只读账本里已绑定原文的主张。旧 run 仍走现有 LangGraph 直链。

**Tech Stack:** 沿用 Python 3.12、FastAPI、LangGraph、PostgreSQL、SQLAlchemy 2、Pydantic 2、现有 ModelGateway。新增 Semantic Scholar 适配器。向量先存 PostgreSQL `REAL[]`，在进程内做余弦；不引入独立向量库，也不把 pgvector 当作本阶段的安装前提。嵌入默认 mock 哈希，真实嵌入走已配置的 OpenAI 兼容接口。

**依据：** 现有实现见 `backend/app/workflow/graph.py`、`backend/app/agents/coordinator.py`、`backend/app/workflow/nodes.py` 的 `decide`、`backend/app/llm/single_actor.py`。市场对标是 Elicit 的抽取列、Deep Research 的多轮改查询、Scite / ResearchRabbit 的支持—反驳与一跳引文。

**版本：** v0.1 方案，2026-11-08。本文只定义重构，不表示代码已改。

## 1. 为什么要改，以及本阶段不做什么

当前一次运行的实际控制流是：

`plan → approve_plan → retrieve → screen → select → read → analyze → decide → write → validate → finalize`

`decide` 最多回到检索或精读一次。补检把 `Question.search_terms_en` 拼成查询，不生成新检索式。`FollowupDecision` 看到的预算信息只有 `supplement_round`。模型不能选择工具。记忆是本次 run 的 artifact 指针；B0 另把最多 12 条、约 12KB 的原始模型输出塞回提示词。来源是 OpenAlex 和可选 arXiv。

本阶段做完后，新 run 必须能展示三件现在做不到的事：

1. 检索开始前，用户确认子问题、纳入/排除规则、抽取列和覆盖目标。
2. 至少两轮检索，第二轮的查询词来自覆盖表里的缺口，而不是第一轮英文词的重复拼接。
3. 综述中的文献判断能点开到主张，主张落到现有 `evidence` 行；同一项目的下一轮 run 能看见已入库论文、钉住项和排除项。

本阶段明确不做：

- 知网、万方全文抓取。语言范围含 `zh` 且没有已配置的中文全文源时，覆盖表写入 `zh_fulltext_not_licensed`。
- 开放网页浏览、任意 URL、shell、SQL。
- Agent 之间用 MCP 互调。现有 9 个 MCP 工具仍是外部入口。
- 把四个角色改成自由群聊。角色保留，调度权交给「覆盖表 + 动作清单 + 运行时准入」。
- 更换前端框架。只扩展计划编辑、轮次笔记和主张侧栏所需的字段。

## 2. 一次新 run 的目标行为

1. 用户提交主题和范围。协调模型产出 `ResearchSpec`：3–5 个子问题、纳入/排除规则、至少 1 列抽取字段、每个子问题的覆盖目标。程序重写问题编号、列编号和规则编号，范围以用户请求为准。
2. 图在 `approve_spec` 中断。用户可以改规则、列和覆盖目标，可以钉住或排除已知论文。确认时把 `planner_mode`、轮次上限、来源和预算写入 `run.input_snapshot`，之后不随进程配置漂移。
3. 每一轮：
   - 程序生成 `CoverageReport`。
   - 规划模型读取规格、最近两页笔记和这份覆盖表，输出最多 6 个 `RoundAction`。
   - `admit_actions` 丢弃超预算、未知论文、未启用数据源和越权精读。
   - 工具按顺序执行。新论文进入项目库；摘要筛选沿用现有阅读 Agent；全文只对已纳入或本轮被选中的论文下载。
   - 抽取结果经现有原文跨度校验后写入 `evidence`，再写入 `claims`。
   - 追加一页 `NotebookPage`。
4. 停止：必填列已满足且本轮没有新的高相关论文，或连续两轮饱和，或调用/来源/时长预算不足，或达到该 run 冻结的 `max_research_rounds`（默认 4）。然后进入现有 `write → validate → finalize`。写作上下文是主张和原文摘录，不是整篇 PDF，也不是模型调用历史。

## 3. 文件边界

新增文件各管一件事：

| 文件 | 职责 |
| --- | --- |
| `backend/app/planning/spec.py` | 把模型草稿规范成 `ResearchSpec`，拒绝未知来源和悬空列 |
| `backend/app/planning/planner.py` | 调用 `planner_round.j2`，解析 `RoundPlan` |
| `backend/app/planning/admit.py` | 纯函数。输入覆盖表、预算余量、动作；输出可执行动作和拒绝原因 |
| `backend/app/memory/coverage.py` | 由账本和项目库计算覆盖表，不调用模型 |
| `backend/app/memory/ledger.py` | 写入和读取 `claims`；同一证据、同一列、同一极性不重复插入 |
| `backend/app/memory/notebook.py` | 按轮追加笔记；规划器只取最近两页 |
| `backend/app/memory/library.py` | `project_papers` 的钉住、排除、跨 run 复用 |
| `backend/app/memory/index.py` | 摘要和分块的 mock/live 嵌入，以及 BM25 与余弦的融合排序 |
| `backend/app/tools/runtime.py` | 按准入后的动作调用具体工具，并记来源请求和模型调用 |
| `backend/app/tools/search_works.py` | 按 provider 调用已注册来源，DOI 优先并入已有论文 |
| `backend/app/tools/citations.py` | 向前或向后一跳，限制新增篇数 |
| `backend/app/tools/search_in_paper.py` | 在已解析全文中取片段，供补列 |
| `backend/app/sources/semantic_scholar.py` | Semantic Scholar 检索与 citation/reference |
| `backend/prompts/planner_round.j2` | 轮次规划提示词 |
| `backend/prompts/coordinator_spec.j2` | 规格草稿提示词 |
| `backend/tests/unit/test_admit.py` | 准入规则 |
| `backend/tests/unit/test_coverage.py` | 覆盖与饱和 |
| `backend/tests/unit/test_index.py` | 混合排序与 BM25 回退 |
| `backend/tests/integration/test_research_loop.py` | 两轮查询不同、账本被写作引用、同项目第二 run 看见库 |

修改时保持旧入口可读：

| 文件 | 改什么 |
| --- | --- |
| `backend/app/schemas/contracts.py` | 增加本文第 4 节的类型。保留 `PlanDraft`、`FollowupDecision`，供 legacy 图使用 |
| `backend/app/config.py` | 增加第 5 节配置。默认 `planner_mode=legacy` |
| `backend/app/db/models_projects.py` | `plans` 增加 `spec_json`；新增 `project_papers` |
| `backend/app/db/models_artifacts.py` | 新增 `claims`、`research_notes`、`paper_neighbors`、`text_embeddings` |
| `backend/migrations/versions/` | 一条新迁移，只建新列和新表，不改旧行含义 |
| `backend/app/workflow/state.py` | 增加 `round_index`、`coverage_artifact_id`、`notebook_ids` |
| `backend/app/workflow/graph.py` | `build_graph` 继续编 legacy 图；新增 `build_coverage_graph` |
| `backend/app/workflow/nodes.py` | 新增 spec、round、note 节点。现有 `decide` 留在 legacy 图 |
| `backend/app/worker/execute.py` | 按该 run 快照里的 `planner_mode` 选图 |
| `backend/app/agents/coordinator.py` | 新增 `draft_spec`。现有 `plan` 留给 legacy |
| `backend/app/agents/review.py` | coverage 模式下章节生成只接收主张包 |
| `backend/app/services/research.py` | 确认规格、保存人工钉住/排除、创建 run 时冻结模式 |
| `backend/app/api/router.py` 与 `backend/app/schemas/api.py` | 规格、覆盖表、笔记、主张的读接口 |
| `backend/app/mcp_gateway/server.py` | 不增加工具数量。`get_research_status` 的结果里带覆盖摘要和当前轮 |
| `frontend/src/features/research/PlanEditor.tsx` | 编辑规则、列、覆盖目标 |
| `frontend/src/features/research/ResearchPage.tsx` | 显示轮次笔记和未满足的列 |
| `frontend/src/features/papers/EvidencePanel.tsx` | 显示主张极性 |

`backend/app/llm/single_actor.py` 在 coverage 模式的新调用路径上不再拼接。B0 若仍用 legacy 图，行为不变。

## 4. 契约

以下类型放进 `backend/app/schemas/contracts.py`，全部 `extra="forbid"`。编号一律由程序生成，模型草稿里的编号丢掉。

```python
class ExtractionColumn(StrictModel):
    column_id: str
    question_id: str
    field: Literal[
        "method", "dataset", "experimental_setup", "metric", "result", "limitation"
    ]
    required: bool
    description_zh: str = Field(min_length=1, max_length=300)

class InclusionRule(StrictModel):
    rule_id: str
    polarity: Literal["include", "exclude"]
    text_zh: str = Field(min_length=1, max_length=300)

class CoverageTarget(StrictModel):
    question_id: str
    min_included_papers: int = Field(default=3, ge=1, le=15)
    required_column_ids: list[str] = Field(min_length=1)

class ResearchSpec(StrictModel):
    topic: str
    questions: list[Question] = Field(min_length=3, max_length=5)
    scope: Scope
    inclusion_rules: list[InclusionRule] = Field(min_length=1, max_length=12)
    columns: list[ExtractionColumn] = Field(min_length=1, max_length=12)
    coverage: list[CoverageTarget]
    assumptions: list[str] = Field(default_factory=list)

class RoundAction(StrictModel):
    action_id: str
    kind: Literal[
        "search_works", "expand_citations", "read_fulltext", "search_in_paper", "stop"
    ]
    question_ids: list[str] = Field(min_length=1)
    rationale: str
    query: str | None = None
    providers: list[str] = Field(default_factory=list)
    paper_ids: list[UUID] = Field(default_factory=list)
    direction: Literal["references", "cited_by"] | None = None
    column_ids: list[str] = Field(default_factory=list)

class RoundPlan(StrictModel):
    actions: list[RoundAction] = Field(min_length=1, max_length=6)

class CoverageCell(StrictModel):
    question_id: str
    column_id: str
    filled_papers: int
    required: bool

class CoverageReport(StrictModel):
    round_index: int
    questions: list[dict[str, int]]
    cells: list[CoverageCell]
    unmet_question_ids: list[str]
    remaining_source_requests: int
    remaining_llm_calls: int
    remaining_deep_reads: int
    new_relevant_papers_last_round: int
    consecutive_saturated_rounds: int
    corpus_limits: list[str]
    saturated: bool

class NotebookPage(StrictModel):
    round_index: int
    executed_action_ids: list[str]
    rejected_actions: list[dict[str, str]]
    new_paper_ids: list[UUID]
    filled_column_ids: list[str]
    open_gaps: list[str]
    index_mode: Literal["hybrid", "bm25"]

class ClaimRecord(StrictModel):
    claim_id: UUID
    paper_id: UUID
    question_id: str
    column_id: str
    evidence_id: UUID
    polarity: Literal["support", "contradict"]
    value_zh: str
```

`Scope.enabled_sources` 的合法值扩大为 `openalex`、`arxiv`、`semantic_scholar`。年份、语言、排除词仍由服务端过滤，模型填的值不生效。

`Question` 保留 `search_terms_en`，只作为第一轮没有缺口词时的种子。从第二轮起，`search_works.query` 必须来自规划器或准入规则生成的缺口查询。

## 5. 配置与 run 快照

`Settings` 增加：

```python
planner_mode: Literal["legacy", "coverage"] = "legacy"
max_research_rounds: int = Field(default=4, ge=1, le=8)
max_actions_per_round: int = Field(default=6, ge=1, le=6)
max_citation_neighbors: int = Field(default=15, ge=1, le=30)
max_search_in_paper_calls_per_paper: int = Field(default=3, ge=1, le=6)
embedding_mode: Literal["off", "mock", "live"] = "mock"
embedding_dimensions: int = Field(default=256, ge=32, le=3072)
semantic_scholar_base_url: AnyHttpUrl = AnyHttpUrl("https://api.semanticscholar.org/graph/v1")
semantic_scholar_api_key: SecretStr = Field(default_factory=lambda: SecretStr(""))
enable_semantic_scholar: bool = False
```

创建 run 时把下列字段复制进 `input_snapshot`，执行期间只读快照：`planner_mode`、`max_research_rounds`、`max_actions_per_round`、`max_citation_neighbors`、`max_search_in_paper_calls_per_paper`、`embedding_mode`、`enabled_sources`，以及当时的来源请求、模型调用、精读篇数上限。coverage 模式的新 run 使用快照内的来源请求上限 40、模型调用上限 180；不修改 legacy run 已冻结的 20 和 150。进程级 `max_supplement_rounds` 只约束 legacy 图。

`embedding_mode=off` 或 live 嵌入不可用时，`index_mode=bm25`，笔记里写明，检索仍继续。测试使用 `mock`：对 token 做哈希分桶，同一文本得到同一 256 维向量。

## 6. 数据

一条 Alembic 迁移完成下列变更。旧表的既有行不回填，旧 run 不读这些表。

`plans` 增加可空 `spec_json JSONB`。legacy 计划保持 `NULL`。

```text
project_papers
  project_id, paper_id, status(active|pinned|excluded),
  first_run_id, created_at
  primary key (project_id, paper_id)

claims
  id, project_id, run_id, paper_id, question_id, column_id,
  evidence_id -> evidence.id, polarity, value_zh, created_at
  unique (project_id, paper_id, column_id, evidence_id, polarity)

research_notes
  id, project_id, run_id, round_index, payload_json, created_at
  unique (run_id, round_index)

paper_neighbors
  project_id, from_paper_id, to_paper_id, direction, provider, created_at
  primary key (project_id, from_paper_id, to_paper_id, direction, provider)

text_embeddings
  id, project_id, owner_type(abstract|chunk), owner_id,
  paper_id, dimensions, vector REAL[], model_id, created_at
  unique (project_id, owner_type, owner_id, model_id)
```

`evidence` 继续是原文位置的唯一记录。`claims.evidence_id` 必须指向同一 `paper_id` 的证据，写入时在同一事务检查。全文证据仍要求 `chunk_id` 和 `page_number`。摘要证据的 `polarity` 可以写入，但 `value_zh` 不得写成实验结论；沿用现有「仅摘要不产生全文层面实验判断」。

论文身份：有 DOI 则并到已有 DOI；没有 DOI 时用现有 `rapidfuzz` 标题阈值，与当前去重规则保持同一常数。引文邻居解析不到本地论文时，先以对方返回的标题、年份、DOI 建 `papers` 行，再写入 `paper_neighbors`。

## 7. 准入规则

`admit_actions` 是纯函数，测试不连数据库。规则按下面的顺序执行。

1. 丢掉 `question_ids`、`column_ids`、`providers` 不在规格内的动作。
2. `search_works` 必须有非空 `query`。provider 限制为该 run 已启用的来源。年份和语言由调用方在执行时覆盖，准入不相信动作里的范围字段，所以 `RoundAction` 里根本不放年份。
3. `expand_citations` 的 `paper_ids` 必须已经在本项目库，且状态不是 `excluded`。`direction` 必填。本动作新增论文数不超过 `max_citation_neighbors`。
4. `read_fulltext` 只能选择相关性不少于 3，或状态为 `pinned` 的论文，并且不得超过剩余精读名额。
5. `search_in_paper` 只能选择已有解析文档、且指定必填列仍为空的论文。每篇累计调用不超过快照上限。
6. 按剩余来源请求和模型调用裁剪。一个 `search_works` 计每个 provider 1 次来源请求；`expand_citations` 计 1 次；`read_fulltext` 在需要下载时计 1 次来源请求外加预估抽取调用；`search_in_paper` 计 1 次模型调用。裁剪后一个动作都不剩，则本轮停止并在笔记写 `budget_exhausted`。
7. 规划器给出 `stop` 时：若 `saturated` 为真，或 `consecutive_saturated_rounds >= 2`，或预算已不够任何检索/精读，接受停止。若仍有未满足的必填目标且预算够，拒绝这次 `stop`。规划器没有留下替代动作时，准入自己补一个 `search_works`：query 由未满足列的 `description_zh` 与对应问题的 `search_terms_en` 拼接，provider 取已启用来源的第一个。这个补动作写入 `rejected_actions` 的对立面，记为 `synthesized_from_gap`。
8. 一轮最多保留 `max_actions_per_round` 个动作。`stop` 若被接受，则它是唯一动作。

饱和的定义放在 `coverage.py`：本轮新纳入的相关性 ≥ 3 的论文数为 0，且没有新填上的必填单元格。`consecutive_saturated_rounds` 存在笔记序列上，由程序计数。

## 8. 图

`build_coverage_graph` 的节点：

```text
START → draft_spec → approve_spec → begin_round
begin_round → propose → execute → screen_new → read_selected → note
note → begin_round        当本轮没有接受 stop，且 round_index < max_research_rounds
note → write              当接受 stop，或轮次用尽
write → validate → finalize → END
```

`screen_new` 和 `read_selected` 调用现有 `ReadingAgent.screen`、`ReadingService` 和 `documents/evidence.py`。没有新论文或没有新全文时，这两个节点直接返回，不发起模型调用。

`ResearchState` 在现有字段上增加：

```python
round_index: int
coverage_artifact_id: str | None
notebook_ids: list[str]
stop_reason: str
```

状态里仍然只放 ID。覆盖表和笔记正文放 `research_notes` 与 artifact，不放进 LangGraph checkpoint。

`execute` 按动作种类调用工具。工具失败写成该动作的 warning，不把整轮标成未执行的成功。来源全部失败时，笔记记录失败，覆盖表的 `corpus_limits` 增加对应 provider，然后允许规划器换来源或停止。

## 9. 工具语义

`search_works`：对每个 provider 调用现有 `PaperSource.search`。Semantic Scholar 的 `PaperSource` 与 OpenAlex 一样返回 `PaperRecord`，另外在 `raw_payload` 中保留 `paperId`、`citationCount`。mock 模式从现有 fixture 按查询词过滤，不联网。

`expand_citations`：OpenAlex 用 work 的 `referenced_works` 与 `cited_by_api_url` 的一页；Semantic Scholar 用 `/paper/{id}/references` 和 `/citations`，`limit` 等于本动作剩余名额。只扩一跳。邻居写 `paper_neighbors`。新论文进入 `project_papers`，状态 `active`，等待本轮或下一轮 `screen_new`。不因为被引用就直接精读。

`search_in_paper`：取该论文已持久化的 `chunks`。`embedding_mode` 不是 `off` 且该论文有向量时，分数为 `0.65 * 归一化BM25 + 0.35 * 余弦`；否则只用现有 `bm25_scores`。返回不超过 `max_chunks_per_paper` 的片段给 `ReadingAgent.extract`。抽取候选的 `chunk_id` 必须属于这次返回的集合，否则整次抽取失败且不写主张。成功的候选走现有 quote span 校验，再写 `evidence` 和 `claims`。

`read_fulltext`：沿用下载白名单、大小限制、解析子进程和「多栏只标定向阅读」。解析完成后为 chunk 写嵌入；`embedding_mode=off` 时跳过嵌入。

规划器不直接调用这些函数，也不得到 HTTP 客户端。

## 10. 写作与界面

coverage 模式的 `ReviewAgent` 输入改为按子问题分组的 `ClaimRecord` 加证据摘录。`ClaimBlock.evidence_ids` 只能引用这批证据。没有主张的子问题写成未覆盖说明，不生成该子问题的实验比较。

支持与反驳都保留。同一列上极性相反的两条主张，在方法比较里分成两行，不合并成一个排名。

界面最小增量：

- 计划页能增删纳入/排除规则和抽取列，确认前显示覆盖目标。
- 研究页按 `round_index` 显示笔记里的已执行动作、被拒动作和未满足问题。
- 证据侧栏对每条主张显示 `support` 或 `contradict`，以及原来的原文位置。

MCP `get_research_status` 增加 `round_index`、`unmet_question_ids`、`stop_reason`。不在一次 MCP 调用里等待循环结束。

## 11. 实施顺序

每一步都保持 `uv run --locked pytest -q` 可运行。新测试文件单独先红再绿。legacy 测试在阶段 6 结束前保持通过。

### 任务 1：契约与迁移

**文件：** `contracts.py`，新迁移，`config.py`，`test_admit.py` 里先只测规格校验。

- [ ] 规格校验测试：模型把来源写成 `cnki` 时 `draft_spec` 抛 `SOURCE_NOT_ENABLED`；列引用了不存在的 `question_id` 时抛 `SPEC_INVALID`；程序把问题和列重编为 `q1`、`c1`。
- [ ] 迁移升级后，旧 `plans.spec_json` 为 NULL 的行仍能被现有计划接口读出。
- [ ] 默认配置下新 run 的快照是 `planner_mode=legacy`。

### 任务 2：覆盖表与账本

**文件：** `memory/coverage.py`，`memory/ledger.py`，`tests/unit/test_coverage.py`。

- [ ] 空账本时，所有带必填列的问题都在 `unmet_question_ids`。
- [ ] 插入一条绑定了证据的必填主张后，对应单元格 `filled_papers` 加 1；重复插入同一 `(paper, column, evidence, polarity)` 不增加计数。
- [ ] 一轮没有新的高相关论文、也没有新单元格时 `saturated` 为真；下一轮再如此，`consecutive_saturated_rounds` 为 2。
- [ ] `languages` 含 `zh` 且没有中文全文适配器时，`corpus_limits` 含 `zh_fulltext_not_licensed`。

### 任务 3：准入

**文件：** `planning/admit.py`，`tests/unit/test_admit.py`。

用第 7 节的 8 条各写一个测试。其中必须有：

- [ ] 未饱和且预算足够时，单独的 `stop` 被拒绝，并合成一条 `search_works`，其 query 同时含缺口列描述和该问题的种子词。
- [ ] 连续两轮饱和时，`stop` 被接受且不合成检索。
- [ ] 剩余来源请求为 0 时，检索动作被裁掉，笔记原因是 `budget_exhausted`。
- [ ] `read_fulltext` 不能选相关性 2 且未钉住的论文。

### 任务 4：Semantic Scholar 与引文一跳

**文件：** `sources/semantic_scholar.py`，`tools/citations.py`，`tools/search_works.py`，`tests/unit` 用 httpx mock transport。

- [ ] 记录的请求 host 只能是配置的 Semantic Scholar 基址。响应里的 PDF URL 不在本工具里下载，下载仍走现有文档服务。
- [ ] 同一 DOI 已在库中时不新建 `papers` 行，只增加 `paper_neighbors`。
- [ ] 一跳返回 40 条时只保留 15 条，并在 warning 里写 `citation_cap`。
- [ ] `enable_semantic_scholar=false` 时，动作里的该 provider 被准入拒绝。live 测试继续默认 skip。

### 任务 5：篇内混合检索

**文件：** `memory/index.py`，`tools/search_in_paper.py`，`tests/unit/test_index.py`。

- [ ] mock 嵌入对同一文本稳定；`embedding_mode=off` 时排序与当前 BM25 顺序一致。
- [ ] 中文查询能命中含对应中文术语的片段；英文种子词命中不了时，混合分数仍能把语义上相近的 mock 向量排到前面。测试用两段固定文本和手工构造的向量，不依赖外网。
- [ ] 抽取引用了未返回的 `chunk_id` 时不写 `claims`。
- [ ] 同一论文第四次 `search_in_paper` 被准入拒绝。

### 任务 6：研究循环接入 worker

**文件：** `graph.py`，`nodes.py`，`planner.py`，`worker/execute.py`，`tests/integration/test_research_loop.py`。

- [ ] 快照为 coverage 的 run 使用 `build_coverage_graph`；legacy 快照仍走原图，原有审批中断测试通过。
- [ ] 用 fixture 模型让第一轮查询为 `graph neural networks`，覆盖表仍缺 `limitation`，第二轮查询字符串与第一轮不同，且含 limitation 的描述或规划器给出的新词。
- [ ] 第二轮结束后综述 artifact 的证据 ID 都能在 `claims` 里找到。
- [ ] 同项目再建一个 run，检索前 `project_papers` 里已有上一轮的论文；被排除的论文不会进入新的候选集。
- [ ] 重放已完成的轮次不新增来源请求，沿用现有 operation key 与缓存。

此任务通过后，把开发默认值改为 `planner_mode=coverage`。已经写进快照的 run 不变。

### 任务 7：API、MCP 与界面

**文件：** `api/router.py`，`schemas/api.py`，`mcp_gateway/server.py`，`PlanEditor.tsx`，`ResearchPage.tsx`，`EvidencePanel.tsx`，对应 Vitest 与现有 Playwright。

- [ ] 确认规格时 `expected_version` 仍指计划版本。改列后版本增加，旧版本确认返回 409。
- [ ] 研究页能读到两页笔记和未满足问题。
- [ ] 证据侧栏能区分 support 与 contradict。
- [ ] MCP 工具仍是原来的 9 个。`get_research_status` 含 `round_index` 与 `unmet_question_ids`。
- [ ] 现有 Chromium 路径改为：创建项目、编辑至少一条排除规则、确认规格、跑完 mock 循环、打开主张、导出。

### 任务 8：评价

**文件：** `backend/app/evaluation/`，`evals/configs/`，`docs/evaluation/protocol.md`。

- [ ] 新增 coverage 策略快照，与 B0 使用同一冻结语料、同一模型和同一调用预算。B0 可以调用同一套工具，但规划、检索、阅读、写作串行，并仍用单身份；coverage 策略使用多轮规划。
- [ ] 指标增加：种子论文召回、必填列填对率、综述句子的证据存在率。人工支持率继续允许为 null。
- [ ] 空的 `benchmark.test.jsonl` 仍然拒绝执行。合成冒烟只证明循环跑完，协议里写明不能据此声称优于 Elicit 或 Deep Research。

## 12. 做完时的对照

| 能力 | 做完后应有的表现 |
| --- | --- |
| 对标 Elicit 的抽取 | 检索前确认列；账本按列填充；缺列出现在覆盖表 |
| 对标 Deep Research 的多轮 | 默认最多 4 轮；后一轮查询随缺口变化；饱和或预算用尽才写 |
| 对标引文工具 | 已入库论文可向前、向后各一跳，并留在项目库 |
| 证据约束 | 主张必须指向现有 `evidence`；全文页码仍来自解析器 |
| 旧演示 | `planner_mode=legacy` 的快照继续走原图 |

真实供应商、Semantic Scholar 配额、中文全文授权和人工盲评仍按 `docs/implementation/acceptance-status.md` 的口径单独验收。本重构不把这四项算作已完成。

## 13. 风险与处理

- 来源请求从 20 增到 40 只发生在 coverage 新 run 的快照里。legacy 预算不变。
- Semantic Scholar 无密钥时约 1 次/秒。适配器沿用现有限流，超限记为该 provider 的 warning，不重试到把整轮打满。
- `REAL[]` 精确余弦只打算覆盖「一个项目最多 200 篇摘要 + 已精读全文的分块」。库超过这个规模时再单独立项 pgvector，不在本迁移里创建扩展。
- 规划器若连续返回无法执行的动作，准入在预算允许时合成缺口检索；预算不够则停止。不允许为了填满轮次而空转模型。
- 恢复规则不变：接管前仍要确认旧 worker 已退出。新节点的幂等键包含 `run_id` 和 `round_index`。
