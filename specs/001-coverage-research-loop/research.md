# Research: 按覆盖缺口多轮研究

## Decision: 沿用现有技术栈

- **Decision**: 使用现有 Python 3.12、FastAPI、LangGraph、PostgreSQL、SQLAlchemy 2、Pydantic 2 和现有 ModelGateway。前端框架不更换。
- **Rationale**: 规格要求兼容现有 legacy 运行和现有写作、检查、完成阶段。宪章禁止为了本变更更换角色体系或前端框架。
- **Alternatives considered**: 独立研究编排服务、新的前端框架。二者都会把已有运行和界面拆成两套，因此不采用。

## Decision: 新代码按第 3 节文件边界放置

- **Decision**: 规划、覆盖、账本、笔记、项目库、索引、工具运行时、检索、一跳引文、篇内片段和 Semantic Scholar 适配器分别放在规格指定的 `planning/`、`memory/`、`tools/`、`sources/` 文件中。
- **Rationale**: 每个文件只承担一件事，准入和覆盖表才能脱离模型单独测试。仓库里已经存在的同名模块继续承担这些职责。
- **Alternatives considered**: 把循环继续堆进 `coverage_flow.py`。节点适配可以留在该文件，但覆盖计算、准入、笔记和工具调用不再新增第二套实现。

## Decision: coverage 在 approve_spec 之后进入研究循环

- **Decision**: coverage 图为 `draft_spec`、`approve_spec`、`begin_round`、`propose`、`execute`、`screen_new`、`read_selected`、`note`，然后回到下一轮或进入现有 `write`、`validate`、`finalize`。
- **Rationale**: 用户必须先确认 3 到 5 个子问题、规则、抽取列和覆盖目标。检索不得发生在确认之前。
- **Alternatives considered**: 确认提纲后沿固定图走到综述。这正是本变更要替换的 coverage 路径；legacy 快照仍保留该路径。

## Decision: 每条 run 只读自己冻结的模式

- **Decision**: `approve_spec` 成功时冻结 `planner_mode`、`max_research_rounds`、`max_actions_per_round`、`max_citation_neighbors`、`max_search_in_paper_calls_per_paper`、`embedding_mode`、`enabled_sources`，以及当时的来源请求上限、模型调用上限和精读篇数上限。执行选图和预算只读这份冻结值。
- **Rationale**: 规格要求 legacy 与 coverage 按 run 快照并存。进程里同时存在 `input_snapshot` 与 `config_snapshot` 时，确认后不得让另一份跟随新的进程配置，造成同一 run 出现两个模式。
- **Alternatives considered**: 每轮读取进程当前配置。这会让已确认运行被后来的配置改道，因此不采用。

## Decision: 开发默认保持 legacy，直到研究循环完成

- **Decision**: `planner_mode` 的开发默认值保持 `legacy`，直到 coverage 循环已经接入并且现有 legacy 测试仍然通过。
- **Rationale**: 宪章要求未完成的循环不得打断现有演示和测试。
- **Alternatives considered**: 现在就把默认值改成 coverage。旧演示会在循环未完成时进入新路径，因此不采用。

## Decision: 一轮最多 6 个动作，准入后再执行

- **Decision**: 规划器提交最多 6 个 `RoundAction`。`admit_actions` 是纯函数，丢弃超预算、未知论文、未启用来源和越权精读，并留下拒绝原因。
- **Rationale**: 规格要求调度权在覆盖表、动作清单和运行时准入，不在角色之间的自由调用。
- **Alternatives considered**: 规划器直接调用检索或精读。这会绕过预算和身份校验，因此不采用。

## Decision: 停止条件四者任一

- **Decision**: 必填列已满足且本轮没有新的高相关论文、连续两轮饱和、调用或来源或时长预算不足、达到该 run 冻结的 `max_research_rounds`，任一成立就进入写作。
- **Rationale**: 规格已澄清这四者是并列条件。只满足必填列而本轮仍有新的高相关论文时不得停止。
- **Alternatives considered**: 必填列一旦满足就停止。这会漏掉本轮新出现的高相关论文，因此不采用。

## Decision: 写作上下文只读主张和原文摘录

- **Decision**: coverage 的综述输入只包含已绑定原文跨度的主张和对应摘录。不读整篇 PDF，不读模型调用历史。
- **Rationale**: 主张必须落到现有 evidence。程序只检查引用存在，语义支持留给人工核验。
- **Alternatives considered**: 把全文或调用历史塞进写作提示。这与规格和宪章的证据边界冲突，因此不采用。

## Decision: 向量使用 REAL[] 和进程内余弦

- **Decision**: 向量存放在 PostgreSQL `REAL[]`。余弦在进程内计算。嵌入默认是 mock 哈希，同一文本得到同一向量。`embedding_mode=off` 或真实嵌入不可用时，篇内检索退回现有关键词相关度，并在笔记中标明。
- **Rationale**: 宪章禁止安装 pgvector 或引入独立向量库。
- **Alternatives considered**: pgvector、独立向量库。二者都改写已批准的存储边界，因此不采用。

## Decision: Semantic Scholar 用 httpx 替身，PDF 仍走文档服务

- **Decision**: Semantic Scholar 检索和一跳引文的测试使用 httpx 替身，不访问外网。响应中的 PDF 地址不在该适配器里下载；下载继续走现有文档服务及其白名单、大小限制和解析流程。
- **Rationale**: 新来源要能在 mock 测试中验证，同时不得绕过现有全文下载边界。live 测试默认跳过。
- **Alternatives considered**: 在引文工具里直接下载 PDF。这会绕过现有文档服务，因此不采用。

## Decision: coverage 快照单独使用 40 次来源请求

- **Decision**: 来源请求上限 40 和模型调用上限 180 只写入 coverage 新 run 的快照。legacy 快照保持 20 和 150。
- **Rationale**: 规格要求旧运行的预算不因本变更回写。
- **Alternatives considered**: 把进程默认来源上限直接改成 40。这会改变已冻结的 legacy 运行，因此不采用。
