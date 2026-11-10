# 可选的 Docker 开发、运行与交付操作手册

日期：2026-10-29。本文属于[详细实施方案](../superpowers/plans/2026-10-29-academic-research-workbench-detailed.md)的操作附录。

默认开发方式已经按用户意见改为 [uv 管理 Python 的本机开发路线](uv-development-guide.md)。本附录只供选择全容器环境或后续容器化交付时使用，不是开发前置要求。

本文中的应用文件、接口、测试和 CLI 都是接下来需要实现的内容，并非当前仓库已经具备。按主方案完成对应任务后，再执行该任务引用的命令。本次编写手册没有安装依赖、启动服务或进行付费调用。

## A. 统一环境与执行位置

仅在选择本可选路线时，采用 Windows 宿主机、Docker Desktop 的 Linux 容器、Node.js 24、Python 3.12、PostgreSQL 16。Python API、worker、测试和迁移在容器内运行；前端在宿主机运行。它与默认 uv 本机路线是两种运行方式，不必同时执行。

2026-10-29 的只读检查结果：宿主机 Python 3.9.15、Node.js 24.14.0、npm 11.9.0；PATH 中没有找到 uv 和 docker 命令。未找到命令不能证明软件完全没有安装，应先检查安装与 PATH。无需修改现有 Conda Python。

uv 可以安装并固定项目所需 Python，宿主机的 Python 3.9 不构成使用容器的理由。本可选路线用于希望统一 Linux 运行环境的情况；默认本机路线使用 Selector 事件循环处理 psycopg 的 Windows 异步兼容要求。官方约束见 [psycopg 异步说明](https://www.psycopg.org/psycopg3/docs/advanced/async.html)。

以下 PowerShell 命令，除明确标注外，都从项目根目录执行。路径通过当前目录解析，不在业务代码中写本机绝对路径。

### A1. 安装和验证 Docker

1. 根据 [Docker Desktop Windows 安装说明](https://docs.docker.com/desktop/setup/install/windows-install/)检查 Windows、虚拟化和 WSL 2 要求。
2. 按官方安装器完成安装，选择 Linux 容器后端；需要重启时先重启。
3. 启动 Docker Desktop，等待引擎就绪，重新打开 PowerShell。
4. 执行以下只读检查：

```powershell
docker version
docker compose version
node --version
npm --version
```

预期：`docker version` 同时显示 Client 与 Server，Compose 显示 v2 版本，Node 显示 v24.x。只有 Client、没有 Server 时，先解决 Docker 引擎问题。

Docker 无法使用时，可在 WSL 2 的 Linux 环境直接安装 Python 3.12、uv 和 PostgreSQL；不要把本手册的容器路径直接当成 Windows 路径。首轮开发坚持一种运行方式，避免同时维护两套部署。

### A2. 建立目录

先保留仓库已有的 docs。依次执行：

```powershell
New-Item -ItemType Directory -Force backend
New-Item -ItemType Directory -Force backend/app
New-Item -ItemType Directory -Force backend/tests
New-Item -ItemType Directory -Force backend/prompts
New-Item -ItemType Directory -Force backend/fixtures
New-Item -ItemType Directory -Force evals
```

Python 各包创建空的 `__init__.py`。后文目录树中的应用模块按任务逐一创建，不要求第一天创建空壳文件占位。

## B. 后端依赖和容器

### B1. 创建 backend/pyproject.toml

版本区间是首版兼容范围，安装时由 uv 解析后生成精确的 `uv.lock`。首次锁定成功后按锁文件安装；后续升级单独验证，不在每次启动时更新依赖。

```toml
[project]
name = "academic-workbench"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
  "fastapi>=0.115,<1",
  "uvicorn[standard]>=0.30,<1",
  "pydantic>=2,<3",
  "pydantic-settings>=2,<3",
  "sqlalchemy>=2,<3",
  "psycopg[binary,pool]>=3,<4",
  "alembic>=1,<2",
  "httpx>=0.27,<1",
  "langgraph>=1,<2",
  "langgraph-checkpoint-postgres",
  "langchain-core>=1,<2",
  "langchain-openai>=1,<2",
  "mcp[cli]>=2,<3",
  "pdfplumber>=0.11,<1",
  "defusedxml>=0.7,<1",
  "rank-bm25>=0.2,<1",
  "rapidfuzz>=3,<4",
  "python-multipart>=0.0.18,<1",
  "jinja2>=3,<4"
]

[dependency-groups]
dev = [
  "pytest>=8.4,<10",
  "pytest-asyncio>=1.4,<2",
  "pytest-cov>=5,<8",
  "respx>=0.21,<1",
  "ruff",
  "mypy",
  "reportlab>=4,<5"
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
asyncio_mode = "auto"
markers = [
  "integration: requires a dedicated test database",
  "live: requires explicit external service access"
]

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.mypy]
python_version = "3.12"
check_untyped_defs = true
disallow_untyped_defs = true
```

不为第三方缺失类型整体关闭类型检查；只对无法提供类型的单个模块写有解释的配置。reportlab 仅用于生成原创测试 PDF。

### B2. 创建 backend/Dockerfile

```dockerfile
FROM python:3.12-slim-bookworm AS toolchain
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /bin/
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

FROM toolchain AS runtime
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev
COPY app ./app
COPY prompts ./prompts
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
RUN useradd --create-home appuser && mkdir -p /data && chown appuser /data
USER appuser
CMD ["uv", "run", "--locked", "--no-dev", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

开发时只构建 `toolchain`，所以迁移目录尚未存在也能开始。最终构建 `runtime` 前必须完成上面所有 COPY 对应文件。镜像版本为本方案的起始建议；正式交付记录实际镜像 digest，基础镜像安全更新单独测试。uv 的容器和锁文件方法见 [官方 Docker 集成说明](https://docs.astral.sh/uv/guides/integration/docker/)及[锁定说明](https://docs.astral.sh/uv/concepts/projects/sync/)。

### B3. 创建根目录 .env.example

这是配置模板，空白凭据需要使用者自行填写。基础 URL 仅存配置，由适配器读取；不散落硬编码到函数中。

```dotenv
APP_ENV=development
APP_MODE=single_user_local
API_HOST=127.0.0.1
API_PORT=8000
MCP_ENABLED=false
MCP_ALLOWED_HOSTS=["127.0.0.1:*","localhost:*"]
MCP_ALLOWED_ORIGINS=["http://127.0.0.1:5173","http://localhost:5173"]
DB_NAME=research
DB_USER=research
DB_PASSWORD=
DB_HOST=127.0.0.1
DB_PORT=5432
STORAGE_ROOT=.local-data
LOG_LEVEL=INFO

LLM_MODE=mock
LLM_API_KEY=
LLM_BASE_URL=
LLM_SCREEN_MODEL=
LLM_RESEARCH_MODEL=
LLM_OUTPUT_MODE=json_schema
LLM_TIMEOUT_SECONDS=120

SOURCE_MODE=mock
OPENALEX_BASE_URL=https://api.openalex.org
OPENALEX_API_KEY=
ARXIV_BASE_URL=https://export.arxiv.org/api/query
CONTACT_EMAIL=
HTTP_USER_AGENT=AcademicWorkbench/0.1
ENABLE_ARXIV=false

MAX_CANDIDATES=200
MAX_SCREEN_PAPERS=60
MAX_DEEP_READ_PAPERS=20
MAX_SOURCE_REQUESTS=20
READ_CONCURRENCY=3
MAX_LLM_CALLS=150
MAX_ESTIMATED_TOTAL_TOKENS=400000
MAX_RESEARCH_SECONDS=1200
MAX_SUPPLEMENT_ROUNDS=1
MAX_REVISION_ROUNDS=1
MAX_MODEL_RETRIES=1
MAX_DOWNLOAD_MB=30
MAX_PDF_PAGES=120
MAX_CHUNKS_PER_PAPER=12
CHUNKS_PER_EXTRACTION_CALL=4
CHUNK_TARGET_TOKENS=700
```

默认不开启 arXiv，因为用户尚未限定学科。计算机、物理等有明确覆盖的主题再启用。400000 token 等值都是开发起点，应写进 run 快照并据实评估；不代表一定会耗尽或保证完成时间。

复制配置并设置独立数据库密码：

```powershell
Copy-Item -LiteralPath .env.example -Destination .env
```

只在 `.env` 尚不存在时执行复制。编辑 `.env` 填写 `DB_PASSWORD`，初期保持 `LLM_MODE=mock`。添加 `.gitignore`：`.env`、`*.local`、`.venv/`、`node_modules/`、`frontend/dist/`、`backend/.pytest_cache/`、`backend/.ruff_cache/`、`backend/.mypy_cache/`、`__pycache__/`、`backups/`、本地实验结果目录。锁文件必须保留。

### B4. 创建根目录 compose.yaml

```yaml
name: academic-workbench

x-backend: &backend
  build:
    context: ./backend
    target: toolchain
  env_file: .env
  environment:
    DB_HOST: db
    STORAGE_ROOT: /data
  working_dir: /app

services:
  db:
    image: postgres:16-bookworm
    environment:
      POSTGRES_DB: ${DB_NAME:-research}
      POSTGRES_USER: ${DB_USER:-research}
      POSTGRES_PASSWORD: ${DB_PASSWORD:?Set DB_PASSWORD in .env}
    volumes:
      - pg_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB"]
      interval: 5s
      timeout: 3s
      retries: 20

  tools:
    <<: *backend
    profiles: ["tools"]
    volumes:
      - ./backend:/app
      - tools_venv:/opt/venv
      - research_files:/data

  api:
    <<: *backend
    ports: ["127.0.0.1:8000:8000"]
    volumes:
      - ./backend:/app
      - api_venv:/opt/venv
      - research_files:/data
    depends_on:
      db:
        condition: service_healthy
    command: ["sh", "-c", "uv sync --locked && uv run --locked uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"]

  worker:
    <<: *backend
    volumes:
      - ./backend:/app
      - worker_venv:/opt/venv
      - research_files:/data
    depends_on:
      db:
        condition: service_healthy
    command: ["sh", "-c", "uv sync --locked && uv run --locked python -m app.worker.main"]
    stop_grace_period: 45s

volumes:
  pg_data:
  tools_venv:
  api_venv:
  worker_venv:
  research_files:
```

API 与 worker 分别使用虚拟环境卷，避免两个服务启动时同时写同一虚拟环境。数据库不映射宿主机端口，所有开发命令通过 tools 服务访问。整个首版只启动一个 worker，禁止 scale worker。

Compose 的 `.env` 插值和 `env_file` 注入是两件事，见 [Docker 环境变量说明](https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/)。

### B5. 锁定与验证依赖

```powershell
docker compose config --quiet
docker compose build tools
docker compose run --rm --no-deps tools uv lock
docker compose run --rm --no-deps tools uv sync --locked
docker compose run --rm --no-deps tools uv run --locked python -c "import fastapi, langgraph, pdfplumber, psycopg; print('imports-ok')"
```

预期：生成 `backend/uv.lock`，最后输出 `imports-ok`。解析冲突时读取 uv 冲突报告，调整明确不兼容的一项依赖并重新验证；不使用强行跳过解析或忽略依赖的安装方式。本次手册未执行这些依赖安装命令。

### B6. 建立最小 API

在 `backend/app/main.py` 写入：

```python
from fastapi import FastAPI

app = FastAPI(title="Academic Research Workbench", version="0.1.0")

@app.get("/api/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}
```

然后：

```powershell
docker compose up -d db api
Invoke-RestMethod http://127.0.0.1:8000/api/health/live
```

预期：返回 `status=ok`。`/api/health/ready` 在数据库任务完成后增加连接检查；不要把 live 和 ready 都实现为固定返回成功。

## C. 前端环境

从根目录创建项目；如果 `frontend` 已有内容，先检查，不覆盖重建。

```powershell
npm create vite@latest frontend -- --template react-ts
Set-Location frontend
npm install
npm install react-router-dom @tanstack/react-query react-markdown remark-gfm
npm install -D vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event @playwright/test openapi-typescript
npx playwright install chromium
```

使用脚手架当次生成的兼容 React/Vite/TypeScript 组合，保存 `package-lock.json` 并记录版本。重现环境使用 `npm ci`，不再次创建脚手架。入口方法见 [Vite 官方指南](https://vite.dev/guide/)。

在 `package.json` 保留模板原有脚本，增加：

```json
{
  "test": "vitest run",
  "test:watch": "vitest",
  "test:e2e": "playwright test",
  "typecheck": "tsc -b"
}
```

在 `vite.config.ts` 保留 React 插件，配置开发代理：

```typescript
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
});
```

上述地址是本地开发代理配置，不进入业务函数。生产由同域反向代理处理 `/api`。前端不得存放模型密钥，`VITE_*` 环境变量会进入浏览器构建结果。

开发运行 `npm run dev`，浏览器访问命令显示的本地地址。API 请求统一使用 `/api/...`。

## D. 数据库与 CLI 操作约定

以下 `app.cli` 子命令需要主方案对应任务先实现。实现方式：`app/cli.py` 使用标准库 argparse 分派命令，异步命令通过统一的 `run_async` 运行；失败返回非零退出码。本机与容器共用CLI实现。

| 命令 | 参数和行为 | 实现阶段 |
| --- | --- | --- |
| `init-checkpoints` | 从配置连接 PostgreSQL，执行一次 checkpointer.setup | T02 |
| `doctor` | 检查 DB、存储可写性、配置和依赖版本；只报告密钥是否存在 | T02 |
| `probe-model --profile screen` | 仅显式 live 时发一个小型结构化调用，报告模式、耗时和用量 | T03 |
| `demo-seed` | 从原创 fixture 建立一个项目；固定标识重复执行不复制项目 | T11 |
| `run-demo --approve-fixture-plan` | 推进mock演示；省略参数则停在计划确认点 | T11 |
| `recover-run --run-id ID --confirmed-worker-stopped` | 检查旧进程已由操作者停止、保留未知调用预留，重新排队同一 run | T08 |
| `prepare-test-db` | 验证预先创建的 `_test` 数据库并迁移；拒绝普通业务库名，不提升账号权限 | T02 |
| `evaluate --config PATH --output NEW_DIRECTORY` | 读取实验配置、输出逐样本结果及统计；不覆盖已有目录 | T12 |

迁移初始化（T02 实现 ORM 后）：

```powershell
docker compose run --rm tools uv run --locked alembic init migrations
```

只执行一次。编辑 Alembic 的 env.py：导入所有 ORM 模型；从配置用 SQLAlchemy `URL.create` 构造同步 psycopg URL；通过 `create_engine` 建立迁移连接，避免密码插入 ini 时的百分号转义。应用使用 `create_async_engine`，两者可共用配置字段。

```powershell
docker compose run --rm tools uv run --locked alembic revision --autogenerate -m "initial research schema"
docker compose run --rm tools uv run --locked alembic upgrade head
docker compose run --rm tools uv run --locked python -m app.cli init-checkpoints
docker compose run --rm tools uv run --locked python -m app.cli doctor
```

自动生成迁移后先人工检查索引、JSONB、外键和唯一约束，再执行 upgrade。checkpointer 表由其 setup 负责，不把它们加入本项目 ORM 的 autogenerate 管理范围。

## E. 固定检查命令

对应测试文件创建后再执行；某任务尚未完成时，不将“没有测试文件”记录为测试通过。

先确保db服务已启动。测试库只在首次创建时执行 `docker compose exec db sh -c 'createdb -U "$POSTGRES_USER" -O "$POSTGRES_USER" research_test'`；存在则跳过。prepare-test-db在专用测试库迁移业务表并初始化检查点表，不操作业务库。

```powershell
docker compose run --rm tools uv run --locked ruff check app tests
docker compose run --rm tools uv run --locked mypy app
docker compose run --rm tools uv run --locked pytest tests/unit -q
docker compose run --rm tools uv run --locked python -m app.cli prepare-test-db
docker compose run --rm tools uv run --locked pytest tests/integration -q
```

集成测试 fixture 从配置派生 `_test` 数据库名，并在连接后断言 `current_database()`；禁止在业务库清空表。每个测试使用独立项目标识，结束后由事务回滚或明确的测试数据清理策略处理，不批量删除本地文件。

前端检查（在 frontend）：

```powershell
npm run typecheck
npm run lint
npm run test
npm run build
npm run test:e2e
```

Playwright 的 webServer 指向启动中的本地前端；E2E 使用 mock 后端、独立测试库和原创 PDF，默认不访问真实模型或数据源。

## F. 真实服务联调

1. 保留 `.env` 中原有配置，设置模型服务商提供的 API URL、密钥和两个模型 ID；允许两个 ID 相同。
2. 配置实际支持的输出模式：`json_schema`、`function_calling` 或 `json_prompt`。
3. 将 `LLM_MODE` 改为 `live`，显式运行 `probe-model`；真实检索另将 `SOURCE_MODE` 改为 `live`。记录供应商、模型版本、上下文上限、输出限制、用量返回能力和测试日期。
4. 探测失败时先查兼容性，不通过多次完整调研来试错。若原生结构化不支持，改为 JSON 提示词加 Pydantic 验证，保留一次修复上限。
5. 将规模暂时设为 10 个候选、3 个摘要、1 篇精读；跑通后再提高至正常配额。
6. 记录 API 错误、缺全文比例、论文解析质量、各阶段调用次数和实际耗时。没有得到用量的请求记为未知，不记为零费用。

模型结构化返回也可能包含事实错误；JSON 语法合法和事实正确要分别验证。参考 [OpenAI Structured Outputs 官方说明](https://developers.openai.com/api/docs/guides/structured-outputs)及 [ChatOpenAI 接入文档](https://docs.langchain.com/oss/python/integrations/chat/openai)。兼容服务不保证实现全部 OpenAI 参数。

## G. 本地交付与备份

交付目标是单机本地使用，数据库/API 不暴露公网。多人使用、认证与公网发布另列后续任务，不把开发模式端口直接放到公网。

完成代码后新增 `compose.release.yaml`，使用完整独立配置，不依赖开发 compose 的目录挂载：

- `api` 和 `worker` 使用 `backend/Dockerfile` 的 runtime 阶段。
- `api` 取消 `--reload`，worker 只保持一个实例。
- `web` 使用 Node 24 构建 `frontend/dist`，再由 nginx 提供静态文件。
- nginx 将 `/api/` 转发到 `http://api:8000`，其他路径使用 `try_files $uri $uri/ /index.html`。
- 启用MCP时，额外为精确路径 `/mcp` 配置代理到API对应端点，保持请求头和所需流式响应；不可让它落入前端index.html兜底。按实际本机访问地址配置Host/Origin允许列表，不能关闭校验。[MCP接入附录](mcp-integration-guide.md)
- 只有 web 绑定 `127.0.0.1:8080:80`；DB、API 仅容器内部可达。
- API 和 worker 使用同一文件卷；数据库、文件卷保持与开发环境明确区分，先完成备份再迁移。
- 首次部署迁移和 `init-checkpoints` 使用同一 runtime 镜像的临时命令，执行成功后启动 worker。

在 release 文件实现并验证后执行：

```powershell
docker compose -f compose.release.yaml config --quiet
docker compose -f compose.release.yaml build
docker compose -f compose.release.yaml up -d db
docker compose -f compose.release.yaml run --rm api uv run --locked --no-dev alembic upgrade head
docker compose -f compose.release.yaml run --rm api uv run --locked --no-dev python -m app.cli init-checkpoints
docker compose -f compose.release.yaml up -d
```

复现交付前保存依赖锁、镜像 digest、数据库迁移版本、prompt 版本、模型配置快照（去除密钥）。

数据库备份避免 PowerShell 旧版本重定向二进制造成损坏，先在容器内生成文件再复制。以下以开发 compose 为例，备份时间戳唯一：

```powershell
$backupStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
New-Item -ItemType Directory -Force backups
docker compose exec db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/research.dump'
docker compose cp db:/tmp/research.dump "backups/research-$backupStamp.dump"
```

文件备份在正在运行的 api 容器执行，然后复制到宿主机：

```powershell
docker compose exec api tar -czf /tmp/research-files.tar.gz -C /data .
docker compose cp api:/tmp/research-files.tar.gz "backups/research-files-$backupStamp.tar.gz"
```

对正式备份，先取消接受新 run 并等待或停止 worker，再同时备份 DB 和文件卷，避免出现数据库引用了尚未复制的文件。恢复演练使用独立数据库和文件卷，先验证计数、文件哈希和引用跳转，再考虑替换运行环境。不要通过删除现有卷解决迁移错误。

## H. 常见失败的定位顺序

| 现象 | 先检查 | 处理方式 |
| --- | --- | --- |
| Docker 只有 Client | Docker Desktop 引擎、WSL、虚拟化 | 完成环境修复后再安装应用依赖 |
| `uv lock` 失败 | 包解析报告、网络、Python 版本 | 修正冲突或镜像网络；保留锁定要求 |
| DB 密码不生效 | 已初始化的持久卷 | 初始化环境变量不会自动修改旧账号；通过数据库管理操作修改密码 |
| API 正常，任务不动 | worker 进程、queued 状态、最近心跳 | 查 worker 日志，不在 API 中直接重跑研究 |
| 任务状态过期 | 旧 worker 是否已退出 | 先确认停止旧进程，再执行受控恢复 |
| 来源返回 429 | Retry-After、日额度、并发配置 | 有界退避；额度耗尽则停止该源并报告覆盖范围 |
| 模型 JSON 校验失败 | 输出模式、schema、截断 | 一次修复；仍失败保存错误，不用默认假数据填充 |
| PDF 没有文本 | 扫描件、加密、损坏 | 标记失败或仅摘要，不声称完成精读 |
| 中文摘要检索效果差 | 实际论文语言、检索术语 | 保留中文需求，用领域英文术语查询；记录映射 |
| 前端进度重复增长 | 轮询缓存和后端累计计数 | 使用服务端绝对计数，不把每次轮询值累加 |
| 引用点开错误论文 | 论文版本、映射、项目权限 | 按稳定 ID 查找，禁止按标题模糊定位引用 |

## I. 操作完成检查单

- [ ] tools 容器能导入所有关键依赖。
- [ ] API live 与 ready 各自通过，DB 使用独立持久卷。
- [ ] mock 模式无密钥即可运行完整演示。
- [ ] 前端使用相对 API 路径，浏览器看不到模型密钥。
- [ ] 独立测试库验证失败场景，没有对业务库执行清空操作。
- [ ] 单 worker 中断恢复通过，未知计费调用不会被自动重试。
- [ ] 真实服务以小规模完成联调并记录实际成本。
- [ ] release 构建、备份和独立恢复演练完成。
