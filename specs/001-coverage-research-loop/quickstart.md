# Quickstart: 验证覆盖研究循环

本指南只证明规格中的行为。实现代码、迁移和完整测试套件不在这里展开。默认模型和论文来源保持 mock。不要为了这次验证开启真实供应商。

## 准备

在 `backend` 目录使用锁定的依赖启动所需测试环境。live 测试保持默认跳过。Semantic Scholar 只通过 httpx 测试替身验证，不下载 PDF。

恢复已有运行前，先确认旧 worker 已经退出。本验证不执行 git commit 或 push。

## 后端

在 `backend` 目录执行：

```powershell
uv run --locked pytest -q
uv run --locked ruff check app tests
uv run --locked mypy app
```

期望：

- 现有 legacy 测试通过，旧模式仍经过 plan、approve_plan、retrieve、screen、select、read、analyze、decide、write、validate、finalize。
- 准入测试拒绝超预算、未知论文、未启用来源和越权精读。
- 必填目标未满足且预算足够时，单独的停止被拒绝，并补出一条与第一轮不同的缺口查询。
- 覆盖测试在语言范围含中文且没有中文全文源时写出 `zh_fulltext_not_licensed`。
- 同一文本的 mock 哈希稳定。嵌入关闭时，篇内排序与现有关键词相关度一致。
- coverage 集成路径至少两轮检索，第二轮查询对应覆盖缺口。综述中的证据都能在主张中找到，主张指向现有 evidence。
- 同一项目的下一次运行在检索前看见已入库论文、钉住项和排除项。被排除论文不进入新候选集。
- legacy 快照的来源请求上限仍是 20，模型调用上限仍是 150。只有 coverage 新 run 的快照使用 40 和 180。

## 前端

在 `frontend` 目录执行：

```powershell
npm run typecheck
npm run lint
npm run test
npm run build
npm run test:e2e
```

期望：

- 确认前可以编辑至少一条排除规则和抽取列，并看见覆盖目标。
- 研究页按轮次显示已执行动作、被拒绝动作和未满足问题。
- 证据侧栏能区分支持与反驳，并保留原来的原文位置。
- 浏览器路径仍能完成创建、确认、mock 运行、打开主张和导出。页面框架保持不变。

## 不作为完成标准

真实供应商小样本、IDE 与桌面客户端、人工评价集、PostgreSQL 16、Docker 和备份恢复仍单独验收。命令通过不等于这些事项已经完成。
