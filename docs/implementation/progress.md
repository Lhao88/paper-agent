# 实施记录 — plan: docs/superpowers/plans/2026-10-29-academic-research-workbench-detailed.md

开始：2026-10-30。执行方式：当前会话按模块实施，模块测试通过后继续；不提交或推送Git。

## 环境与裁定

- 当前目录只有方案文档，没有README、业务代码、依赖清单或Git仓库。
- Ruling（初始）: 在用户指定目录内实施，起初没有Git仓库，不创建worktree。
- 用户随后授权初始化Git，已采用codex/implementation分支；不提交、不配置远程、不推送。未产生首次提交，继续在当前目录实施并保留所有原文档。
- Ruling: 使用项目本地工具目录引导uv，应用使用uv管理的Python 3.12 — 不更改现有Conda解释器和系统PATH — .tools及缓存加入忽略规则。
- 初始检查：uv、psql、docker未在PATH找到；Python指向已有Conda，Node/npm可用。

## 跨模块接口预检

| 生产任务 → 消费任务 | 接口/约束 | 处理 |
| --- | --- | --- |
| T01 → T02/T03 | Settings、Windows异步入口、项目根目录 | 统一配置；密码安全构造DSN，禁止按cwd推导路径 |
| T02 → T08/T09/T09B | 版本化资料、短事务、幂等与活动run唯一性 | PostgreSQL语义，不以SQLite替代数据库验收 |
| T03 → 所有Agent | 结构化输出、预留预算、unknown调用 | 默认mock；真实服务仅显式启用 |
| T04/T05 → T06 | 摘要筛选后才精读 | 无摘要保留信息不足；全文处理要求已入选 |
| T06 → T07 | 绑定具体文档的原文证据 | 位置由解析器与程序匹配确定，模型不生成页码 |
| T09 → T09B | 统一services用例 | REST/MCP共享预算、身份、幂等和成果版本 |

## 模块状态

- T01：完成。uv管理Python3.12.16，backend/uv.lock已生成；15项测试、ruff和mypy通过。
- T02：完成。13张业务表、2个迁移、项目/论文/成果仓库、检查点初始化、doctor与prepare-test-db、真实就绪检查。
- T03：完成。模型网关、mock与真实协议适配器、持久化预算/缓存、有限修复及probe-model。
- T04：完成。协调/检索规划、OpenAlex与arXiv适配、mock来源、分页限流、原摘要、去重持久化、请求缓存和明确范围过滤。
- T05：完成。BM25预算预选、摘要初读、覆盖与冗余选择、人工覆盖及版本化筛选结果。
- T06：完成。入选限制、PDF安全下载、独立解析进程、分块定向阅读、精确原文证据、仅摘要降级及阅读缓存。
- T07：基础模块已贯通。综合分析、对照表、大纲、分节综述、引用结构校验、一次自检/有限修订和Markdown导出；长输入边界继续补测。
- T08：后台图与持久化恢复已贯通。计划审批中断、领取与归属保护、累计时间、取消、未知调用拦截；故障矩阵继续补测。
- T09：REST业务入口已接通，上传与版本化编辑已实现，补充版本和范围测试中。
- T09B：9个MCP工具已接通并通过真实HTTP及两个SDK客户端测试；IDE与桌面助手人工验收待执行，不宣称完成跨客户端验收。
- T10：首版界面贯通。React Router、TanStack Query、实际OpenAPI类型、项目/计划/文献/证据/综述编辑与导出；复杂筛选组合及部分专用冲突页仍有限制。
- T11：离线故障与浏览器流程通过；合成演示12记录去重10篇、精读3篇。真实服务测试默认skip，真实小样本待凭据与资料验证。
- T12：评价执行、五种候选策略、manifest、CSV/JSON导出、人工审核导入已实现。15次合成冒烟完成；正式独立数据、人工评分与统计结论尚未完成。

## 验证记录

- 初始工具引导：默认pip索引未找到uv，改用显式官方PyPI索引诊断；尚未创建应用环境。
- 代理指向不可连接地址；下载工具与依赖时仅在该进程中清除代理，使用官方PyPI，未更改系统代理设置。
- T01 RED：14 failed、1 error；缺失配置/运行功能及404均被测试捕获，另有沙箱临时目录权限错误。
- T01 GREEN：`uv run --offline --locked pytest -q` → 15 passed；`ruff check app tests` → passed；`mypy app` → 5 source files clean。测试在正常本机权限下完成临时目录验证。
- Ruling: 本机已有PostgreSQL17.6程序，使用这些二进制在项目内新建集群，不更改现有17-data或系统服务 — 与16所需JSONB/事务/索引能力兼容 — 16版本的单独复现仍需后续验证。
- T02：项目独立集群位于.tools/postgres-data，端口54329；开发与测试库research/research_test，自动生成的密码仅在忽略的.env与工具目录，不写入记录。
- Ruling: SQLAlchemy2.1不再默认带greenlet，依赖改为sqlalchemy[asyncio]并重新锁定 — 缺失依赖由真实集成测试发现 — 后续统一使用异步extra。
- T02 RED：缺表测试失败；全文证据page_number=NULL最初被SQL CHECK放行，新增测试捕获后增加显式非空约束及修订迁移；readiness实现前两项测试失败。
- T02迁移：初始测试先通过metadata建表；仅在核对表集和元数据完全一致后，为这个项目创建的测试库登记初始revision，再升级第二个约束迁移。常规prepare-test-db不自动接管未知既有表。
- T02 GREEN：全套23 passed；ruff passed；mypy 19 source files clean。doctor报告数据库17.6与存储ok、模型和来源mock、模型凭据不存在。
- Git：已执行git init -b codex/implementation，未提交，未设置远程，未推送。
- T03 RED：4项预算测试及6项网关行为测试先因目标功能缺失失败；数据库预留实现后4 passed，网关实现后6 passed。
- T03：增加模型调用输入哈希、输出缓存及模型配置快照字段，升级开发/测试库；修正迁移autogenerate过滤，禁止将LangGraph自管表生成删除操作。
- Ruling: 当前LangChain/OpenAI SDK使用httpx2，协议测试通过注入httpx2.MockTransport拦截 — 原respx仅拦截httpx，发现后更换边界工具 — 新增直接依赖并锁定，真实来源适配仍用httpx。
- T03 GREEN：全套34 passed；适配器HTTP请求与用量解析通过本地响应测试；mock probe-model成功且账本记录20 token（模拟用量），没有真实模型消费。
- Ruling: AgentContext在T04引入实际研究资料类型时实现，避免T03建立未定义的仓库/计划占位类型；网关独立使用CallContext。
- T04 RED：摘要/DOI六项用例、来源四项、规划两项分别先失败；另以源忽略年份条件的用例捕获服务端漏过滤。
- T04 GREEN：全套49 passed；检索入库集成测试覆盖重复DOI合并来源、重入不增加请求、单源失败、候选配额和年份过滤。来源测试使用拦截HTTP，未执行真实论文检索。
- T04：采用原有审批文档中的8份prompt模板；增加3篇明确标注Synthetic的原创合成资料和规划/查询fixture，避免把演示资料当真实学术成果。
- Ruling: 增加retrieval成果类型与逐页source_search结果缓存 — 支持检索节点重入并保留查询/失败记录 — 不能把缓存结果归零为一次新检索的实际费用。
- T04类型依赖：安装types-defusedxml，未关闭XML模块类型检查。include_terms作为检索指导保留在计划中；年份和明确排除词由服务端确定性过滤，未知年份保留警告。
- T05 RED：8项行为测试先失败；另用持久化集成用例发现人工调整时旧预选操作键冲突，改为输入哈希区分版本后通过。
- T05 GREEN：全套58 passed，ruff passed，mypy 49 source files clean。集成验证3条候选仅2次摘要模型调用、缺摘要保留、未下载全文、重入不重复调用、人工选择另存版本。
- Ruling: 使用rank-bm25的BM25Plus处理小语料时的负IDF问题，并对无词面重叠材料置0；补充最小公共接口.pyi保持类型检查，不屏蔽第三方导入。
- T05：新增preselection成果类型、排序分项和未入选理由。mock模型只对明确的合成资料ID使用对应fixture，未知fixture直接失败；fixture键不发送给真实供应商。
- T06 GREEN：全套80 passed，ruff passed，mypy 56 source files clean。包括真实PDF解析页码、精确原文、未入选拦截、缓存重入、摘要降级、超时子进程退出、私网与重定向复查、固定IP保留TLS主机名和流式大小限制。
- T06：两份原创合成PDF由scripts/generate_demo_fixtures.py可重复生成；未获取真实论文全文。新增解析警告字段迁移e08391ce4f5b，开发与测试库已升级。
- Ruling: PDF多栏阅读顺序未经验证时保留READING_ORDER_NOT_VERIFIED并标记定向阅读，不宣称完整精读；测试存储派生到独立test目录，避免触碰业务文件。
- T07 RED→GREEN：假证据、缺引用、未知问题/证据、稳定编号、未验证语义与范围导出测试先失败后通过。全套85 passed，ruff/mypy通过；合成资料完整流程验证synthesis/outline/review持久化、跨项目拦截、重入不重复调用。
- T08 RED→GREEN：领取与路由测试先缺模块失败；真实PostgreSQL saver验证审批暂停/编辑恢复、共享一轮补充、最终检查点补齐终态、旧claim拒绝写入、未知调用不自动重试、等待审批时间不增长。全套90 passed，ruff/mypy通过。
- T09：REST测试先404失败；实现后91 passed。新迁移c91de0234a01为上传source/document增加owner_project_id，开发和测试库已升级。伪PDF、目录穿越、跨项目下载被拒绝；上传不自动加入模型处理。
- T09B：MCP契约测试先缺模块失败；官方mcp 2.3.0实际注册9个工具。真实本机TCP/HTTP测试通过：两个独立SDK客户端、REST共享幂等run、断线后run仍queued、跨项目拒绝、恶意Origin拒绝、health/OpenAPI不被根挂载遮挡。未连接真实IDE/桌面客户端。
- Ruling: 审批expected_version统一指计划版本，而非run的阶段版本；run_version另供状态并发诊断。追加检索与关闭入口使用同一run行锁，已受理任务由原worker排空或保存明确失败。
- T10 RED→GREEN：计划编辑、引用、恶意HTML与状态组件先缺模块失败，后4项组件测试通过；typecheck、oxlint及Vite生产构建通过。
- T10/T11：实际Chromium流程通过：创建项目→生成/编辑/确认计划→完成研究→查看真实证据→刷新→导出→另存编辑版本。E2E曾发现测试命名空间跨进程不一致、证据DTO多余字段、编辑控件可访问名称问题，逐项修正后完整通过。
- Ruling: Vite脚手架当前带TypeScript7，但openapi-typescript要求5.x，锁定5.9.3满足peer约束，不使用--force或关闭检查。前端从实际app.openapi生成schema.d.ts。
- T11：故障集成测试在阅读结果已保存后中断analyze，恢复只新增分析/写作的7次模拟调用，不重复精读；同时验证证据HTTP、跨项目404、旧版本编辑409和旧文不变。
- T11：unknown调用阻止同run的新收费操作；全局初读/精读按累计唯一论文计数。过长模型输入在预算预留前拒绝，综合分析和章节按上下文界限分批。
- T12 RED→GREEN：零分母、语义支持与存在率分离、失败/unknown保留的指标测试先缺模块失败，后通过。B0/B1/B2/A1/A2各3个合成主题共15个运行completed，人工支持率保持null；不据此推断真实效果。
- Ruling: B0采用单一研究身份、串行调用及持久前序结果记忆；其余配置使用原工具/证据/预算服务。作为候选基线交付，正式实验须审核公平性。真实评价资料缺失的代价是尚不能得出多Agent效果结论，独立test集保持空且执行器拒绝空集。
- 综合验证（独立审查前）：后端100 passed、2个live测试skip；ruff通过，mypy99个模块通过；前端4项测试、类型、lint、构建通过；Chromium端到端1 passed。
- 最终独立只读审查：发现5项Important和1项Minor，无Critical。Ruling: 将“幂等重试改变冻结预算”由Minor提升为Important，实际可能扩大原用户调用额度，按费用边界处理并一并修复。
- Final: fixed 追加检索检查点重放丢失 — `test_completed_extra_search_is_replayed_without_another_source_request` RED→GREEN；覆盖任务完成后和bundle保存后两个窗口，复用持久成果且不重开入口、不新增请求。
- Final: fixed reserved未派发调用无法恢复 — `test_pre_send_reservation_recovers_and_reuses_same_unbilled_attempt` RED→GREEN；仅在确认旧worker退出后释放已知未派发预留，保留调用ID和原attempt安全复用，sent/unknown仍须核对。
- Final: fixed 摘要新版本操作键冲突 — `test_new_abstract_version_uses_new_model_operation_then_caches_it` RED→GREEN；操作键加入材料/计划哈希，新版本新调用，重放不再调用。
- Final: fixed 评价全库来源覆盖论文身份 — `test_evaluation_identity_uses_current_corpus_instead_of_other_sources` RED→GREEN；按当前冻结候选池的精确source版本/内容哈希映射，忽略额外来源和历史快照，重复金标身份明确拒绝。
- Final: fixed 追加检索未执行却报告成功 — `test_unexecuted_extra_search_reports_budget_exhausted_instead_of_empty_success` RED→GREEN；区分completed、partial、failed和budget_exhausted，保留原因及成果引用。
- Final: fixed 幂等重试修改原预算 — `test_idempotent_retry_does_not_change_frozen_budget_after_server_config_change` RED→GREEN；首次入库时初始化额度，相同输入重试原样返回，不受后来服务器配置改变影响。
- 六项回归同时先观察到6 failed，再逐项修复，后6 passed；全套107 passed、2 live skipped，ruff通过，mypy99模块通过。修复后B2三个合成主题再次completed；尚不推断真实学术效果。
- Final: Ruling（未评判1）: 真实供应商/账单/论文质量仍不声称通过 — 缺真实调用和人工数据 — 风险是live契约与学术效果仍不确定，先小样本核验。
- Final: Ruling（未评判2）: IDE/桌面、PostgreSQL16、Docker与备份恢复维持待验收 — 当前验证路线为Windows原生与PostgreSQL17.6 — 其他环境的兼容性不能保证。
- Final: Ruling（未评判3）: 保留现有私有上传归属检查 — 审查与测试未找到可成立的跨项目路径 — 新入口仍须延续owner_project_id与研究证据归属约束。
- Final: Ruling（未评判4）: 恢复仍须人工确认旧进程退出 — saver检查点不受业务claim fencing保护 — 误确认时旧进程可能干扰检查点，不允许仅因租约过期自动接管。
- Final: Ruling（未评判5）: 现有分块持久顺序保留 — created_at由客户端逐条生成，当前无乱序复现 — 将来并行批量插入需再次验证顺序。
- Final: Ruling（未评判6）: 不认定多Agent优势或引用语义可靠 — 只有合成冒烟及引用存在性证据 — 正式结论必须独立人工评价。
- 分支收尾沿用用户既有决定：保持codex/implementation工作区，不commit、不push、不设置远程；不删除任何计划目录或批量清理文件。
- 待验收边界详见acceptance-status.md；未运行真实供应商、实际IDE/桌面客户端、Docker或PostgreSQL16复现。所有模型用量记录为模拟数值，不是真实账单。
- 修复后的最终验证：后端107 passed、2 live skipped；Ruff通过、mypy 99个源文件通过；前端typecheck、oxlint、4项组件测试、生产构建全部通过；Chromium端到端1 passed（13.1秒）。Git仍为codex/implementation未提交状态，未设置远程或推送。
