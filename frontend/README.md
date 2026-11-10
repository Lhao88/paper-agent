# 知研前端

React + TypeScript + Vite 的本地研究工作台。使用 React Router 和 TanStack Query 读取同一后端 REST 服务，浏览器不保存模型密钥。

## 开发

先在 backend 分别启动 API 和 worker，再在此目录：

```powershell
npm ci
npm run dev
```

默认页面地址 http://127.0.0.1:5173，API 代理 http://127.0.0.1:8000。可通过 API_PROXY_TARGET 调整代理。

## 检查

```powershell
npm run typecheck
npm run lint
npm run test
npm run build
npx playwright install chromium
npm run test:e2e
```

E2E 自动启动测试专用 API、受项目命名空间限制的 mock worker 和 Vite，使用 _test 数据库；不复用业务服务。

API 类型来自实际后端导出的 openapi.json，运行 npm run generate:api 更新 src/api/schema.d.ts。不要手写另一套后端领域类型。

项目、计划、文献详情和综述都从持久化接口读取。缺摘要显示信息不足，引用结构校验与人工语义核验分开，用户改写另存新版本。
