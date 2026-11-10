# 默认开发路线：使用 uv 管理 Python、环境与依赖

创建：2026-10-29；更新：2026-10-30。配套[详细实施方案](../superpowers/plans/2026-10-29-academic-research-workbench-detailed.md)。

**主路线：uv 下载并固定 Python 3.12，API、worker、迁移和测试在项目独立环境运行；React 使用 Node 24；PostgreSQL 可以本机安装，也可以单独运行数据库容器。Docker 不是 Python 开发的前置条件。**

以下命令是后续实施步骤，本次编写文档未执行安装、数据库变更或真实模型调用。命令引用的应用模块，需按主方案相应任务先实现。

## 1. 安装 uv 并建立独立 Python 环境

打开 PowerShell，先执行 `uv --version`。如果命令不存在，使用官方提供的安装方法之一：

```powershell
winget install --id astral-sh.uv -e
```

重新打开终端后执行：

```powershell
uv --version
uv python install 3.12
uv python list --only-installed
```

这会由 uv 管理 Python 安装，不要求替换已有 Conda 或系统 Python。参考 [uv 安装说明](https://docs.astral.sh/uv/getting-started/installation/)和 [Python 管理说明](https://docs.astral.sh/uv/guides/install-python/)。

在项目根目录下：

```powershell
New-Item -ItemType Directory -Force backend
Set-Location backend
uv init --app --name academic-workbench --python 3.12 --vcs none
uv python pin 3.12
uv venv --python 3.12 --managed-python
```

如果已经有 pyproject.toml，先阅读并在原文件上修改，不重复 init。`.venv` 已存在时先检查解释器，不自动删除它；如需要迁移已有环境，另行选择新环境路径或由用户处理旧环境。

`--managed-python` 指定使用 uv 管理的解释器。后续使用 `uv run`，无需激活环境，也不会误用命令行中原有的 Python 3.9。

## 2. 安装依赖并生成锁文件

在 backend 目录执行：

```powershell
uv add "fastapi>=0.115,<1" "uvicorn[standard]>=0.30,<1" "pydantic>=2,<3" "pydantic-settings>=2,<3"
uv add "sqlalchemy>=2,<3" "psycopg[binary,pool]>=3,<4" "alembic>=1,<2" "httpx>=0.27,<1"
uv add "langgraph>=1,<2" langgraph-checkpoint-postgres "langchain-core>=1,<2" "langchain-openai>=1,<2"
uv add "mcp[cli]>=2,<3"
uv add "pdfplumber>=0.11,<1" "defusedxml>=0.7,<1" "rank-bm25>=0.2,<1" "rapidfuzz>=3,<4" "python-multipart>=0.0.18,<1" "jinja2>=3,<4"
uv add --dev "pytest>=8.4,<10" "pytest-asyncio>=1.4,<2" "pytest-cov>=5,<8" "respx>=0.21,<1" ruff mypy "reportlab>=4,<5"
uv lock
uv sync --locked
uv run --locked python --version
uv run --locked python -c "import sys; print(sys.executable)"
uv run --locked python -c "import fastapi, langgraph, pdfplumber, psycopg; print('imports-ok')"
```

预期：Python 为3.12.x，解释器位于 backend/.venv，最后输出 imports-ok。将 pyproject.toml 的 requires-python 收窄为 `>=3.12,<3.13`，重新执行 uv lock。

为了记录实际补丁版本：

```powershell
$projectPythonVersion = uv run --locked python -c "import platform; print(platform.python_version())"
uv python pin $projectPythonVersion
```

保存 `.python-version`、`pyproject.toml` 和 `uv.lock`。以后重建环境使用 `uv sync --locked`。若 lock 与声明不一致，先处理原因，不能直接忽略。[uv 锁定机制](https://docs.astral.sh/uv/concepts/projects/sync/)

在 pyproject.toml 增加测试和静态检查配置：

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
asyncio_mode = "auto"
markers = [
  "integration: requires a dedicated test database",
  "live: explicitly opted-in real service call"
]

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.mypy]
python_version = "3.12"
check_untyped_defs = true
disallow_untyped_defs = true
```

## 3. PostgreSQL：选择一种安装方式

### 方式 A：本机 PostgreSQL 16

从 [PostgreSQL Windows 下载页](https://www.postgresql.org/download/windows/)进入官方列出的安装方式。安装服务、命令行工具，记录端口与管理员账号。项目应用不使用 postgres 管理员账号日常运行。

通过 psql 连接管理员账号：

```powershell
psql -h 127.0.0.1 -U postgres -d postgres
```

在 psql 会话内执行：

```sql
CREATE ROLE research LOGIN;
\password research
CREATE DATABASE research OWNER research;
CREATE DATABASE research_test OWNER research;
\q
```

`\password` 交互输入密码，避免把密码直接写进命令历史。若角色或数据库已存在，先确认归属，不重复创建或覆盖。

再使用应用账号验证：

```powershell
psql -h 127.0.0.1 -U research -d research -c "select current_database(), current_user;"
```

### 方式 B：只用 Docker 运行 PostgreSQL

已有 Docker 或偏好容器数据库时，在项目根目录创建 `compose.db.yaml`：

```yaml
name: academic-workbench-db
services:
  db:
    image: postgres:16-bookworm
    environment:
      POSTGRES_USER: ${DB_USER:-research}
      POSTGRES_DB: ${DB_NAME:-research}
      POSTGRES_PASSWORD: ${DB_PASSWORD:?Set DB_PASSWORD in .env}
    ports:
      - "127.0.0.1:${DB_PORT:-5432}:5432"
    volumes:
      - research_pg_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB"]
      interval: 5s
      timeout: 3s
      retries: 20
volumes:
  research_pg_data:
```

先完成下一节根目录 .env，再执行：

```powershell
docker compose -f compose.db.yaml up -d
docker compose -f compose.db.yaml ps
docker compose -f compose.db.yaml exec db sh -c 'createdb -U "$POSTGRES_USER" -O "$POSTGRES_USER" research_test'
```

最后一条只在 test 数据库首次建立时执行，已存在就不再创建。容器方式初始化的 POSTGRES_USER 具有较高权限，仅用于本地原型；后续部署可拆分迁移和应用角色。

## 4. 根目录配置与本地资料目录

创建 `.env.example`，复制到 `.env` 后填写必要值。API、worker、CLI 都从项目根目录读取同一份配置，不依赖终端当前工作目录猜测位置。

```dotenv
APP_ENV=development
APP_MODE=single_user_local
API_HOST=127.0.0.1
API_PORT=8000
MCP_ENABLED=false
MCP_ALLOWED_HOSTS=["127.0.0.1:*","localhost:*"]
MCP_ALLOWED_ORIGINS=["http://127.0.0.1:5173","http://localhost:5173"]
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=research
DB_USER=research
DB_PASSWORD=
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

默认LLM_MODE=mock与SOURCE_MODE=mock，分别使用模型fixture和来源fixture，无需真实密钥或外网。两者可以独立切换，做真实端到端联调时都设为live。以上预算为开发建议，运行时保存实际配置。STORAGE_ROOT相对于项目根目录解析，API和worker必须解析为同一个位置。

`.gitignore` 加入 `.env`、`.local-data/`、`.venv/`、`node_modules/`、`frontend/dist/`、`__pycache__/`、`.pytest_cache/`、`.ruff_cache/`、`.mypy_cache/`、`backups/` 和本地实验输出目录。不得忽略锁文件和原创测试 fixtures。

## 5. 统一 Windows 异步入口

Python 版本由 uv 解决；psycopg 的事件循环兼容是另一件事。使用 Python 3.12 的 `asyncio.Runner` 显式选择 Windows Selector 循环，不依赖全局系统设置。

创建 `backend/app/runtime.py`：

```python
import asyncio
import sys
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")

def create_event_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.SelectorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop

def run_async(coro: Coroutine[Any, Any, T]) -> T:
    with asyncio.Runner(loop_factory=create_event_loop) as runner:
        return runner.run(coro)
```

这里Coroutine的两个Any是标准协程发送/产出类型，业务资料仍使用明确类型。Windows Selector对子进程异步接口有限制，因此PDF处理使用受限的multiprocessing.Process，不能直接套用asyncio.create_subprocess_exec。单次解析使用一个spawn进程和Pipe返回结果，最多同时一个；超时终止该进程并join确认退出，避免依赖进程池私有属性来取消正在运行的任务。

创建 `backend/app/serve.py`：

```python
import uvicorn

from app.config import get_settings
from app.runtime import run_async

def main() -> None:
    settings = get_settings()
    config = uvicorn.Config(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )
    server = uvicorn.Server(config)
    run_async(server.serve())

if __name__ == "__main__":
    main()
```

开发阶段通过该入口启动，修改后手动重启，避免热重载子进程改变事件循环。worker 和 CLI 也统一调用 run_async。进入 Linux 部署后可用常规 uvicorn 命令。

集成测试也必须使用同样的 loop factory。采用 pytest-asyncio 1.4+，在 `tests/conftest.py` 按官方 hook 注册：

```python
from app.runtime import create_event_loop

def pytest_asyncio_loop_factories(config, item):
    return {"project": create_event_loop}
```

该 hook 只返回一个 factory，因此默认所有异步测试都使用 project 循环，不需要再设置选择参数。增加 `tests/unit/test_runtime.py`，在异步测试内调用 `asyncio.get_running_loop()`；Windows 上断言它是 `asyncio.SelectorEventLoop`，然后再运行数据库测试。不要使用已经弃用的 event_loop_policy fixture。参考 [pytest-asyncio 官方 hook 说明](https://pytest-asyncio.readthedocs.io/en/stable/reference/hooks.html)。

## 6. 迁移、检查点与启动

以下命令都在 backend 目录执行。T02 先完成 ORM，再初始化 Alembic（只执行一次）：

```powershell
uv run --locked alembic init migrations
```

编辑 migrations/env.py：导入所有模型的 metadata，使用同步 psycopg 引擎执行迁移，连接 URL 由 `URL.create` 从配置构造，避免把含特殊字符的密码拼进字符串或写进 alembic.ini。随后生成迁移：

```powershell
uv run --locked alembic revision --autogenerate -m "initial research schema"
```

审阅生成文件，核对外键、唯一约束、状态索引和 downgrade；确认目标是开发库后执行：

```powershell
uv run --locked alembic upgrade head
uv run --locked python -m app.cli init-checkpoints
uv run --locked python -m app.cli doctor
```

官方 checkpointer.setup 只在初始化/升级时执行；应用启动不反复修改检查点表。CLI 使用 run_async 运行异步初始化。

分别开两个终端，工作目录都为 backend：

```powershell
uv run --locked python -m app.serve
```

```powershell
uv run --locked python -m app.worker.main
```

另一个终端检验：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health/live
Invoke-RestMethod http://127.0.0.1:8000/api/health/ready
```

单机首版只启动一个 worker。终端关闭只影响该进程，已保存资料仍在数据库和本地资料目录。

### T09B完成后的MCP连接

按[MCP接入附录](mcp-integration-guide.md)完成SDK装配后，将本地.env的MCP_ENABLED改为true并重启API。MCP与REST使用同一API进程，默认连接地址为 `http://127.0.0.1:8000/mcp`；端口变化时按实际配置填写。无需为每个客户端启动一份worker。

在所选IDE/桌面助手中建立Streamable HTTP连接，先发现工具，再调用list_projects。具体客户端配置格式在实际兼容性验收时写入README；本指南不把一个客户端的配置JSON当作通用格式。MCP_ENABLED=false时不挂载MCP应用，早期T01环境不依赖MCP启动。

## 7. 前端建立和运行

从项目根目录执行：

```powershell
npm create vite@latest frontend -- --template react-ts
Set-Location frontend
npm install
npm install react-router-dom @tanstack/react-query react-markdown remark-gfm
npm install -D vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event @playwright/test openapi-typescript
npx playwright install chromium
```

保留 package-lock.json，之后使用 npm ci。在vite.config.ts中保留React插件并添加开发代理：

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

这里的地址只用于本地开发代理；浏览器业务代码统一使用相对路径。保留package.json原有scripts，在其中增加以下键（不是覆盖整个package.json）：

```json
{
  "test": "vitest run",
  "test:watch": "vitest",
  "test:e2e": "playwright test",
  "typecheck": "tsc -b"
}
```

```powershell
npm run dev
```

前端单元测试使用 Vitest 的 jsdom 环境，setupFiles 加载 `@testing-library/jest-dom/vitest`；include只匹配 `src/**/*.test.{ts,tsx}`。Playwright的testDir设为 `./tests/e2e`，避免两个测试框架互相收集测试。E2E使用独立的Playwright配置，不能把Vitest的DOM mock当成真实浏览器测试。

## 8. 日常验证命令

后端（backend目录；相应文件和配置实现后）：

```powershell
uv run --locked ruff check app tests
uv run --locked mypy app
uv run --locked pytest tests/unit -q
uv run --locked python -m app.cli prepare-test-db
uv run --locked pytest tests/integration -q
```

prepare-test-db只连接已经创建的research_test，验证数据库名、执行业务迁移并初始化测试库检查点表，不擅自提高应用账号权限。测试fixture同样核对实际连接库名，禁止在research业务库清空表。实现 `get_test_settings()`：从普通配置复制，db_name尚无 `_test` 后缀时加上该后缀，已有则保留；fixture显式注入该配置，不会因.env里的DB_NAME=research就直接连接业务库执行测试。

浏览器E2E的API和worker也必须显式设置 `APP_ENV=test`、`DB_NAME=research_test` 与独立STORAGE_ROOT；启动时拒绝test环境指向普通业务库。测试产物保留在独立目录，不自动批量删除用户文件。

前端（frontend目录）：

```powershell
npm run typecheck
npm run lint
npm run test
npm run build
npm run test:e2e
```

最终 release 可选用[Docker 交付附录](environment-and-operations.md)。也可保留本机 uv 运行方式，交付 README、锁文件、迁移、配置模板和启动步骤。

## 9. 本机备份与恢复演练

先停止接受新任务，等待当前任务结束或受控停止 worker，再备份数据库与文件。以下从项目根目录执行，需 PostgreSQL 客户端工具在 PATH：

```powershell
$backupStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
New-Item -ItemType Directory -Force backups
pg_dump -h 127.0.0.1 -U research -d research -Fc -f "backups/research-$backupStamp.dump"
Compress-Archive -LiteralPath .local-data -DestinationPath "backups/files-$backupStamp.zip"
```

pg_dump 的输出使用 -f，避免旧 PowerShell 重定向二进制文件损坏。使用交互密码或 PostgreSQL 的安全凭据机制，不把密码直接拼进命令。

恢复演练创建新数据库 research_restore_test 和新文件目录，使用 pg_restore 恢复到新库，并将测试配置指向它们；验证项目数、论文数、证据数、文件哈希和引用跳转。确认备份可恢复前不替换原库，也不删除原始目录。
