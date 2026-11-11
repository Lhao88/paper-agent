# Data Model: 按覆盖缺口多轮研究

逻辑对象来自规格。持久化沿用现有 PostgreSQL 表；本变更不新建第二套论文库或证据表。

## ResearchSpec

检索前确认的合同，保存在现有计划的 `spec_json`。legacy 计划该字段保持为空，旧计划接口仍能读取。

- 子问题：3 到 5 个。程序重写编号。
- 纳入和排除规则：1 到 12 条。程序重写编号。
- 抽取列：1 到 12 列。字段只允许方法、数据集、实验设置、指标、结果、局限。
- 覆盖目标：每个子问题一个。默认至少 3 篇已纳入论文，允许 1 到 15。
- 范围：以用户请求为准。模型填写的来源、年份和语言不生效。
- 合法来源：`openalex`、`arxiv`、`semantic_scholar`。未知来源在规范化时拒绝。

确认时的 `expected_version` 仍指计划版本。旧版本确认被拒绝，计划版本不前进。

## RunSnapshot

一条 run 在 `approve_spec` 成功时冻结的执行依据。coverage 运行才进入这个确认点。

冻结字段：

- `planner_mode`
- `max_research_rounds`
- `max_actions_per_round`
- `max_citation_neighbors`
- `max_search_in_paper_calls_per_paper`
- `embedding_mode`
- `enabled_sources`
- 来源请求上限、模型调用上限、精读篇数上限

coverage 新 run 的来源请求上限是 40，模型调用上限是 180。legacy run 保持 20 和 150，不进入 `approve_spec`。确认后只读本 run 的冻结值；进程配置变更不得改写它。现有 `input_snapshot` 与 `config_snapshot` 若都参与执行，二者对上述字段必须一致。

## CoverageReport

由程序根据账本和项目库计算，不由模型编造。

- 轮次、未满足子问题、必填单元格的已填充篇数。
- 剩余来源请求、模型调用和精读名额。
- 上一轮新的高相关论文数、连续饱和轮数、语料限制。
- 语言范围含 `zh` 且没有已配置中文全文源时，语料限制包含 `zh_fulltext_not_licensed`。

饱和：本轮新纳入的相关性不少于 3 的论文数为 0，且没有新填上的必填单元格。连续饱和由笔记顺序计数。

## RoundAction

一轮中的封闭动作。类型只包括 `search_works`、`expand_citations`、`read_fulltext`、`search_in_paper`、`stop`。每轮经过准入后最多保留 6 个。`stop` 被接受时，它是该轮唯一动作。

动作不携带可被信任的年份或语言。这些过滤在执行时使用用户请求。

## NotebookPage

每一轮追加一页。包含已执行动作、被拒绝动作、新论文、新填上的列、未完成缺口和当时的排序方式。规划只读取最近两页。重复记录同一轮不得新增来源请求。

## Claim

项目级可引用判断。指向同一篇论文上已有的 evidence，并带有子问题、抽取列、极性和中文值。极性只允许 `support` 或 `contradict`。

同一项目、论文、列、证据和极性不得重复插入，也不增加覆盖计数。摘要证据可以记录极性，但不得写成全文层面的实验结论。全文证据继续要求解析器给出的页码。

## Evidence

沿用现有证据表。它是原文位置的唯一记录。主张只能引用同一 `paper_id` 的证据。程序只检查引用存在，不判断语义是否支持。

## ProjectPaper

项目文献库中的论文，后续 run 在检索前可见。状态表达在库、钉住和排除。被排除的论文不进入新候选集，也不得被一跳引文扩出后直接精读。

现有 `project_papers.user_decision` 继续保存这个项目级决定，不另建第二张成员表。钉住必须能让相关性低于 3 的论文通过精读准入；排除必须跨 run 保持。

## PaperNeighbor

项目内的一跳引文边。方向只允许向前引用或被引。一次动作新增论文不超过该 run 冻结的邻居上限，默认 15。已有 DOI 的论文并入已有论文，只增加边。

## TextEmbedding

摘要或正文分块的向量。存储为 PostgreSQL `REAL[]`，默认 256 维。余弦在进程内计算。默认嵌入是 mock 哈希，同一文本得到同一向量。不安装 pgvector。`embedding_mode=off` 时不写向量，篇内排序退回现有关键词相关度。

## State Transitions

coverage run:

1. 起草规格，等待 `approve_spec`。此阶段没有论文检索。
2. 确认成功后冻结快照，进入第一轮。
3. 每一轮：覆盖表、最多 6 个动作、准入、执行、筛选、按资格精读、追加笔记。
4. 未接受停止且未达到冻结轮次上限时进入下一轮。
5. 停止条件任一成立时进入现有写作、检查和完成。

legacy run 不使用以上状态。它仍经过 plan、approve_plan、retrieve、screen、select、read、analyze、decide、write、validate、finalize。

同一项目可以同时有两种 run。一条 run 的迁移不得修改另一条的快照。
