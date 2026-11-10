# 学术调研多 Agent 工作台

面向研究生和高校科研人员，围绕研究主题完成论文检索、摘要筛选、按需精读、证据整理与综述生成。四类角色为协调、检索、阅读和综述，REST与MCP复用业务服务。

项目正在分模块实施。实际状态与测试证据见[实施记录](docs/implementation/progress.md)，完整设计见[详细方案](docs/superpowers/plans/2026-10-29-academic-research-workbench-detailed.md)。

首版已贯通后端工作流与React界面：主题→确认计划→检索→摘要筛选→按需精读→证据→综述→编辑和导出。MCP的9个工具已通过SDK/真实HTTP测试。已提供合成演示和评价执行工具，实际验收范围及未完成项见[验收记录](docs/implementation/acceptance-status.md)。真实供应商、实际IDE/桌面客户端、独立人工学术评价尚未验收。

## 开发环境

- uv管理的Python 3.12，实际锁定3.12.16；不依赖全局Conda版本。
- backend/uv.lock锁定后端依赖。
- 默认模型与论文来源均为mock；接入真实服务需要显式配置。
- PostgreSQL目标为16+，本机可复用已有17的程序建立独立开发集群。

在backend目录使用已安装的uv：

```powershell
uv sync --locked
uv run --locked python -m app.serve
```

本机未将uv加入PATH时，可以使用项目包装脚本（同样在backend）：

```powershell
& ../scripts/uv.ps1 sync --locked
& ../scripts/uv.ps1 run --locked python -m app.serve
```

包装脚本优先使用项目内.tools/bootstrap/bin/uv.exe，否则查找PATH中的uv，并将缓存与Python下载目录设置在项目.tools下。该工具目录不提交到Git；新机器按[uv开发指南](docs/implementation/uv-development-guide.md)安装uv即可。

访问 `http://127.0.0.1:8000/api/health/live` 验证API。目前健康检查不依赖数据库或模型服务。

另开一个终端，在backend目录启动独立worker：

```powershell
uv run --locked python -m app.worker.main
```

通过 `/docs` 创建项目与run。worker生成计划后暂停；读取plan中的version，作为approve的expected_version提交确认，再继续研究。只启动API不会执行后台研究。

配置 `MCP_ENABLED=true` 后，同一API进程在 `/mcp` 提供Streamable HTTP。接入仍遵守同一计划确认、预算与幂等规则，不在MCP请求中等待整篇综述生成。

需要自定义配置时，将根目录.env.example复制为.env并编辑；已经有.env时不要覆盖。密钥、下载文件、工具、虚拟环境与缓存均在.gitignore中排除。

### PostgreSQL初始化

可以使用已有PostgreSQL，按配置分别建立research与research_test。也可使用已有PostgreSQL程序启动项目专属集群，在backend目录执行（PG_BIN由本机安装位置设置）：

```powershell
uv run --locked python ../scripts/dev_postgres.py --pg-bin "$env:PG_BIN"
```

此脚本在项目.tools/postgres-data初始化独立集群，默认端口54329，自动生成开发密码，不修改已有数据库和系统服务。首次自动创建.env；存在配置时先检查是否指向这个隔离集群，不覆盖用户配置。

数据库创建后，在backend目录：

```powershell
uv run --locked alembic upgrade head
uv run --locked python -m app.cli init-checkpoints
uv run --locked python -m app.cli prepare-test-db
uv run --locked python -m app.cli doctor
```

初始化完成后 `/api/health/ready` 检查真实数据库连接与存储可写性，不可用时返回503。检查点表由LangGraph维护，业务迁移不管理它们。集成测试只访问配置派生的_test数据库，并通过事务回滚隔离仓库测试。

### 模型诊断

```powershell
uv run --locked python -m app.cli probe-model --profile screen
```

默认读取本地mock fixture，调用账本同样记录模拟用量。真实调用需在.env显式设置LLM_MODE=live、实际模型ID、服务地址与密钥，命令会产生供应商消费。当前仅验证过mock和注入HTTP响应的适配器协议测试，尚未验证任何真实供应商组合。

## 测试与检查

在backend目录：

```powershell
uv run --locked pytest -q
uv run --locked ruff check app tests
uv run --locked mypy app
```

没有全局uv时，将上述 `uv` 换为 `& ../scripts/uv.ps1`。Windows受限沙箱可能无法创建pytest默认临时目录；这属于运行权限问题，需要在正常本机终端测试，不应当通过跳过文件测试隐藏。

## 后续实施

按T02数据存储→T03模型网关和预算→检索与筛选→证据与综述→编排、REST、MCP与界面的顺序推进。每个模块结束运行对应测试，并在实施记录保留真实结果。Git仓库已经初始化，当前不自动提交、配置远程或推送。

## 启动前端

API和worker分别启动后，另开终端进入frontend目录：

```powershell
npm ci
npm run dev
```

打开Vite输出的本机地址，默认http://127.0.0.1:5173。默认代理API端口8000；自定义时使用API_PROXY_TARGET环境变量。界面不保存模型密钥。

前端检查：`npm run typecheck`、`npm run lint`、`npm run test`、`npm run build`。实际浏览器验收先执行`npx playwright install chromium`，然后`npm run test:e2e`。测试自动启动独立端口的API和仅领取本次测试项目前缀的worker，使用_test库及mock，运行完关闭自身服务；不复用业务worker。

## 合成演示与评价工具

在backend目录：

```powershell
uv run --locked python -m app.cli demo-seed
uv run --locked python -m app.cli run-demo
# 仅明确批准合成计划时自动推进到结束：
uv run --locked python -m app.cli run-demo --approve-fixture-plan
uv run --locked python -m app.cli evaluate --config ../evals/configs/B2.json --output ../evals/output/new-experiment
```

演示含12条来源记录、10篇去重文献、缺摘要与不相关样本、3份文字层PDF及空白/损坏样本，均明确标为Synthetic。重复执行复用同一演示run，不删除历史。

评价配置与人工审核说明见[评价协议](docs/evaluation/protocol.md)。输出目录不得已存在。默认合成配置不用于证明学术效果；独立测试集刻意留空，待正式数据与人工标注准备后冻结。
