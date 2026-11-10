# MCP接入、业务复用与跨客户端实施指南

日期：2026-10-30。接入方案已按本文实现首版：9个工具、SDK2.3.0、真实本机HTTP及两个SDK客户端测试通过。真实IDE与桌面助手的人工验收尚待执行；实际验证与限制见[验收记录](acceptance-status.md)。配套[详细实施方案T09B](../superpowers/plans/2026-10-29-academic-research-workbench-detailed.md)。

## 1. 已确认的接入边界

网页使用REST，支持MCP的IDE与桌面助手使用MCP，两者连接同一后台项目、文献、证据与任务。首版仍为本机单用户、一个worker；增加客户端不会增加研究worker，也不会重置配额。

共享业务资料与客户端聊天历史分别管理。客户端通过明确的project_id、run_id、artifact_id调用；服务端不猜测“上一篇论文”或“当前项目”究竟指哪个客户端的状态。

首版提供一个学术工作台MCP服务，使用Streamable HTTP，端点为本机API服务的 `/mcp`。服务装配在已有FastAPI进程中，研究仍交独立worker。内部Python Agent直接调用同一业务服务。stdio、远程多人部署和接入任意第三方MCP服务作为后续扩展。

## 2. 模块怎样划分

| 文件 | 责任 |
| --- | --- |
| app/services/projects.py | 项目列表、项目归属、项目版本 |
| app/services/research.py | 创建run、读取计划与进度、批准计划、取消 |
| app/services/literature.py | 受控检索任务提交、论文资料读取 |
| app/services/results.py | 指定版本综述、证据、导出 |
| app/mcp_gateway/server.py | 创建SDK服务、注册工具、构造ASGI应用 |
| app/mcp_gateway/tools.py | 将MCP参数转换为业务请求，映射结果和错误 |
| app/mcp_gateway/schemas.py | 入参、结果及契约版本，不重复定义论文资料模型 |
| app/mcp_gateway/resources.py | 后续可选的只读资源模板 |
| app/main.py | 组合REST与MCP，统一生命周期和配置 |

依赖方向为 `REST/MCP → services → repositories/队列`。API不包含独立的一套预算实现，MCP不通过HTTP回调自己的REST端点。数据库和模型网关不导入MCP SDK，保持核心逻辑可被脚本与评价程序直接复用。

T09建立服务层时固定这些签名，所有request/response由Pydantic类型表达：

| 服务方法 | 入参及输出 |
| --- | --- |
| ProjectService.list_projects(context, cursor, limit) | 返回ProjectPage，只返回当前调用者可见项目 |
| ResearchService.start_research(context, request) | StartResearchRequest → RunAccepted；复用REST创建run用例 |
| ResearchService.get_research_status(context, project_id, run_id, task_id=None) | RunStatus，含必要的待确认计划或指定工具任务结果 |
| ResearchService.approve_research_plan(context, request) | ApprovePlanRequest → RunAccepted |
| ResearchService.cancel_research(context, project_id, run_id) | RunStatus |
| LiteratureService.submit_search(context, request) | SearchPapersRequest → SearchAccepted，立即返回任务ID |
| LiteratureService.get_paper_details(context, project_id, paper_id) | PaperDetails，返回元数据、摘要、卡片及资料版本 |
| ResultService.get_review(context, project_id, artifact_id, section_id=None) | ReviewView，明确指定不可变成果版本 |
| ResultService.get_evidence(context, project_id, evidence_id) | EvidenceRecord和文献/文档身份 |

context为服务端构造的ServiceContext，至少含principal_id、request_id、entrypoint。entrypoint取rest/mcp/internal，仅用于审计，不作为权限凭证；客户端自报名称只能用于诊断。首版本地模式映射同一个本机用户，后续认证系统从已验证身份注入principal_id。

## 3. 安装与装配

### 3.1 使用官方SDK并锁版本

在backend目录，执行T09B时加入依赖：

```powershell
uv add "mcp[cli]>=2,<3"
uv lock
uv sync --locked
uv run --locked python -c "from importlib.metadata import version; print(version('mcp'))"
```

截至本次核对，官方文档的稳定线为2.x，使用 `from mcp.server import MCPServer`。它与1.x示例中的类和生命周期有差异；按照锁定版本开发，不混用旧版教程。安装及解析没有在本次文档任务执行。[官方安装说明](https://py.sdk.modelcontextprotocol.io/get-started/installation/)

### 3.2 复用API进程的ASGI入口

实现 `build_mcp_server(services, settings)`，返回已注册工具的MCPServer。先调用它的 `streamable_http_app()` 创建子应用，再在FastAPI顶层lifespan中管理SDK资源。

关键装配步骤：

1. main.py初始化统一ServiceContainer，复用数据库session factory、配置与服务；不启动第二套worker。
2. MCP_ENABLED开启时构造MCPServer并注册工具，创建Streamable HTTP ASGI子应用。
3. 先注册所有REST、health、OpenAPI路由，再将MCP子应用挂到根路径，保留其默认 `/mcp` 端点。根路径挂载必须最后注册，避免遮挡业务路由。
4. 顶层lifespan进入SDK的 `session_manager.run()` 上下文，并与现有数据库/HTTP资源生命周期组合；退出时按逆序关闭。
5. 沿用app.serve的Windows Selector运行入口。只有协议和资料查询在API进程运行，PDF解析与研究循环仍在worker。

不能只mount子应用就假设它的lifespan自动运行。ASGI挂载时由顶层应用管理SDK生命周期，官方对此有专门说明。[ASGI接入文档](https://py.sdk.modelcontextprotocol.io/run/asgi/)

不把SDK内部“session manager”的名字当作业务会话保证。协议版本、是否存在连接会话与旧客户端兼容由SDK处理，业务持久性始终来自数据库中的run。

### 3.3 增加配置

根目录.env.example增加：

```dotenv
MCP_ENABLED=false
MCP_ALLOWED_HOSTS=["127.0.0.1:*","localhost:*"]
MCP_ALLOWED_ORIGINS=["http://127.0.0.1:5173","http://localhost:5173"]
```

两个allowlist使用Pydantic Settings的JSON数组解析，传入SDK的transport_security设置；不能为了连通把Host/Origin检查整体关闭。Native客户端没有Origin时按SDK规范处理，有Origin时必须校验。

实施完成后将本地.env的MCP_ENABLED设为true，再通过现有API命令启动。默认API_HOST保持127.0.0.1。API_PORT变动时客户端连接地址一并调整，不在工具函数里硬编码端口。

本机客户端配置表填写transport=Streamable HTTP、URL=实际 `/mcp` 地址；不同客户端配置文件格式不同，依据所选版本填写，不提供一个未经验证的通用JSON冒充适配所有客户端。SDK负责协议版本协商；只支持旧SSE或stdio的客户端不作为首版通过对象。

## 4. 首版9个工具的明确契约

所有UUID由客户端从服务返回值中取得。分页limit默认20、上限100；未知输入字段拒绝。业务返回包含contract_version="1.0"和request_id；UUID使用字符串，事件游标仍为十进制字符串。

| 工具 | 必需输入 | 可选输入 | 返回与副作用 |
| --- | --- | --- | --- |
| list_projects | 无 | cursor、limit | 项目ID/主题/最近run；只读，不调用模型 |
| start_research | project_id、idempotency_key | scope、budget_overrides | accepted、run_id、status；创建后台研究，待确认计划 |
| get_research_status | project_id、run_id | task_id | 阶段、计数、预算、停止原因；waiting_user时含plan_id/version及可编辑计划；指定task时含其状态/结果 |
| approve_research_plan | project_id、run_id、expected_plan_version、idempotency_key | edited_plan | 冻结计划并入队；过期版本冲突，不能覆盖新版 |
| cancel_research | project_id、run_id | 无 | 请求受控取消，重复调用安全，返回真实状态 |
| search_papers | project_id、run_id、query、question_ids、idempotency_key | source、limit（默认20/最大100） | accepted、task_id；检索阶段受控追加查询，结果通过status查询 |
| get_paper_details | project_id、paper_id | 无 | 来源、原始摘要、筛选与精读卡片及版本；不触发全文下载 |
| get_review | project_id、artifact_id | section_id | 指定综述版本或章节，附引用映射、warnings与阅读范围 |
| get_evidence | project_id、evidence_id | 无 | quote、basis、文献版本、页码及可用位置；不触发重新抽取 |

首版MCP复用已存在的项目，项目从网页创建后可由list_projects找到。以后增加create_project工具时，直接映射同一项目服务并补充创建幂等，不改变已有研究流程。

get_review的大结果按章节返回：超过服务端配置的结果大小时返回目录、artifact_id和需要分章节读取的提示，不静默截断结论或引用。get_paper_details仅返回必要摘要与卡片，不顺便返回整个PDF解析文本。

### 4.1 search_papers如何保持预算与单worker约束

首版将它定义为“当前已确认研究的追加检索”，不是无项目归属的无限搜索入口。这样可以复用既有run预算和队列，也不需要新增一套独立搜索账本。

实现过程：

1. 服务验证项目归属、run对应关系、已确认计划、合法question_ids及已启用来源。
2. 只有run处于running、stage=retrieve且检索入口未关闭时接受。未批准计划返回PLAN_NOT_APPROVED；已进入筛选/阅读则返回STAGE_CONFLICT，并提示新建后续run。
3. 在短事务中锁定run，保存tasks.operation=source_search、input_json、client_request_key、request_hash、status=queued；返回task_id。相同键/相同请求返回原任务，不重新派发。
4. worker在retrieve节点检查已排队的来源任务，按原有来源限流、候选上限和剩余请求额度执行；MCP接入层不直接抢占worker执行职责。
5. 来源HTTP请求实际派发前预留used_source_requests/reserved_source_requests，分页和重试分别计入，完成后结算。没有余额的工具任务标budget_exhausted，不能悄悄加额。
6. 结果按原有DOI与版本规则入库；tasks.output_json保存返回paper_ids、数量、警告与停止原因。用户通过带task_id的get_research_status读取。
7. worker在退出retrieve前锁定run并关闭检索入口，同时确认已接受任务全部处理或明确停止；关闭和新请求入队使用同一行锁，避免“刚受理就永远无人执行”的竞态。

在T02定义tasks.client_request_key、request_hash及unique(run_id,operation,client_request_key)；空键的内部普通任务不受该唯一键限制。runs补充retrieval_accepting、used_source_requests、reserved_source_requests，额度上限来自运行快照。

网页、MCP和协调Agent发起的查询都进入同一LiteratureService用例。之后若增加独立的主题即搜即得模式，需要单独定义预算作用域和执行语义，再扩展契约；不能借用无上限的隐藏HTTP路径。

### 4.2 长任务与幂等

start_research只创建并返回任务，不在一次tools/call里等待完整综述。业务状态accepted与MCP/HTTP协议层的状态分别表示，不能直接把REST的HTTP 202对象当完整MCP响应。

客户端断开时，已经提交的研究和检索任务继续在队列运行。取消某次工具请求不等于取消run，停止研究必须明确调用cancel_research。若响应丢失，客户端复用原idempotency_key重试，由数据库返回原run/task。

JSON-RPC请求ID、客户端连接标识均不代替业务幂等键。网页的Idempotency-Key请求头与MCP的idempotency_key字段映射到同一服务字段，因此从不同入口重试同一操作也可复用结果。

批准计划的键保存到对应控制任务记录，重复相同请求返回已批准版本；相同键但不同编辑内容冲突。客户端不得通过重连触发重新批准或重置预算。

### 4.3 错误与可信边界

协议解析/无效参数交给SDK；业务错误通过SDK的工具执行错误机制返回，保留code、message、retryable、request_id和安全details。MCP工具内部不直接抛出FastAPI HTTPException，也不将堆栈或原始供应商响应直接返回给模型。

常见错误包括PROJECT_NOT_FOUND、ACTIVE_RUN_EXISTS、PLAN_NOT_APPROVED、VERSION_CONFLICT、STAGE_CONFLICT、BUDGET_EXHAUSTED、SOURCE_UNAVAILABLE。对外不存在与无权访问使用相同安全语义。

工具描述应明确：start_research可能产生模型消费，search_papers会消耗来源额度，cancel_research改变任务状态。只读工具不触发隐含重算。客户端展示的只读/破坏性标注是交互辅助，服务端仍独立检查权限、预算和状态。

首版本机模式的访问者属于同一本机用户。未来跨用户或远程开放时，需要已验证身份、项目授权、TLS及相应认证流程；仅知道project_id、填写client_name或连上MCP不视为获得访问权限。遵循[Streamable HTTP的端点保护要求](https://modelcontextprotocol.io/specification/latest/basic/transports/streamable-http)。

## 5. 只读Resources的增强路径

工具版本通过后，可增加下面的URI模板；这是项目自定义命名，不是MCP内置资源：

- `research://projects/{project_id}/reviews/{artifact_id}`：指定版本综述。
- `research://projects/{project_id}/evidence/{evidence_id}`：可定位证据。

资源读取复用ResultService，执行相同权限、版本和大小限制。模板参数不作为本地文件路径。客户端不支持资源展示时仍可使用get_review/get_evidence，核心验收不依赖资源订阅或MCP Prompts。

## 6. 测试如何安排

### 6.1 契约与服务复用测试

tests/unit/test_mcp_contracts.py检查9个工具的名称、必填参数、UUID和limit约束，输出模型引用共用资料契约，不要求模型自行生成系统ID。

tests/integration/test_mcp_tools.py先用官方SDK内存客户端调用服务器，验证工具执行与业务错误；此测试只覆盖映射层，不能作为HTTP传输已正常的证据。

tests/integration/test_cross_client.py创建两个独立SDK客户端实例：A发起研究，B读取同一run；REST再用相同幂等键提交，数据库仍只有一个run。并发请求共享来源和模型预算。

### 6.2 实际HTTP测试

tests/integration/test_mcp_http.py用测试专用配置和短生命周期API子进程，在本机可用端口启动，使用SDK HTTP客户端连接实际 `/mcp`。子进程退出只处理测试自己创建的PID。

至少验证：

- [ ] 工具发现与9个工具的输入/输出schema正确。
- [ ] MCP查询与REST读取的artifact_id、版本、evidence_id一致。
- [ ] health、OpenAPI与REST路径没有被MCP根挂载遮挡。
- [ ] 顶层lifespan启动和退出不产生未初始化task group或泄漏连接。
- [ ] 无效Origin/Host被拒绝，合法本机客户端可连接。
- [ ] HTTP断开后已提交run继续；重新连接能查询。
- [ ] 未确认计划不能检索，关闭检索入口与入队并发时不遗失任务。
- [ ] 同幂等键的重复操作不新增来源请求或模型调用。
- [ ] 旧计划版本被拒绝，工具错误不泄露密钥、路径与堆栈。

测试使用SOURCE_MODE=mock、LLM_MODE=mock与独立_test库，不产生实际服务消费。

### 6.3 两个真实客户端的验收

在T09B选择并记录一个IDE类客户端A、一个桌面AI助手类客户端B。两者均需实际支持当前服务的Streamable HTTP及可协商协议版本；先检查所选安装版本，不只按产品名称推定兼容。

完整操作：

1. 网页创建项目，A调用list_projects找到它。
2. A调用start_research，记录run_id；B调用get_research_status读取待确认计划。
3. B提交一处计划编辑并批准，网页显示同一新版本，worker开始研究。
4. A断开；B继续查询，后台研究正常推进。使用较慢mock fixture保证有时间观察跨客户端切换。
5. 对独立的检索阶段fixture，A提交search_papers，B按task_id读取结果，计数纳入同一run；真实流程若已结束该阶段，则观察正确的状态冲突。
6. 完成后网页与B读取同一artifact_id；A重新连接并查询其中一个evidence_id，原文和版本一致。
7. 单独演示重复提交、预算不足和取消，用日志证明没有重复入队或重新计费。

每个客户端记录名称、版本、系统、连接方式、协商协议、通过日期和未支持项。Inspector是开发诊断工具，不计作第二个用户客户端。未完成的格子保持待验证：

| 验收项 | IDE客户端A | 桌面客户端B |
| --- | --- | --- |
| 客户端名称/版本 | 待执行填写 | 待执行填写 |
| 工具发现与结构化结果 | 待验证 | 待验证 |
| 启动、确认与查询研究 | 待验证 | 待验证 |
| 断线后读取同一run | 待验证 | 待验证 |
| 引用与证据一致 | 待验证 | 待验证 |
| 错误与预算提示 | 待验证 | 待验证 |

## 7. 交付边界与官方参考

决策记录ADR-MCP-001（2026-10-30）：用户已确认需要跨客户端扩展。选择REST和MCP复用业务服务，先部署一个本机Streamable HTTP入口；比较过仅REST和所有内部调用都经MCP两种方式。前者需要各AI客户端自行适配工具，后者会给本机内部调用增加协议和连接维护。因此首版采用外部MCP、内部服务调用的组合，增加约2—4人日的接入与兼容性验证工作。SDK大版本、协议兼容和实际客户端版本写入交付记录。

T09B交付包括服务映射、配置、SDK锁版本、自动测试、两客户端验收记录与README接入步骤。首版核心业务仍由原四类Agent与原worker执行；MCP连接不参与分配研究角色。

本附录没有安装SDK、创建应用模块、调用真实模型或完成客户端验收。代码开发完成前，只能称为已确定的接入设计。

- [MCP架构](https://modelcontextprotocol.io/docs/learn/architecture)：能力接入边界。
- [MCP服务端概念](https://modelcontextprotocol.io/docs/learn/server-concepts)：工具与只读资源。
- [官方Python SDK](https://github.com/modelcontextprotocol/python-sdk)：实现与版本文档。
- [SDK接入现有ASGI应用](https://py.sdk.modelcontextprotocol.io/run/asgi/)：挂载与生命周期。
