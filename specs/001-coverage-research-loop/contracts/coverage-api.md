# Contract: 研究规格、笔记与主张

现有 REST 入口保持不变。本契约只增加 coverage 运行需要被用户和现有外部入口看见的内容。不新增 MCP 工具。

## 确认

- 确认仍使用现有批准入口。`expected_version` 指计划版本。
- 计划内容变化后版本增加。过期版本被拒绝，检索不开始。
- coverage 运行确认成功即 `approve_spec` 完成，并冻结 [data-model.md](../data-model.md) 中的 RunSnapshot。
- legacy 运行仍走 `approve_plan`，不进入 `approve_spec`。

## 读取

- 计划读取能返回 coverage 规格：子问题、纳入和排除规则、抽取列、覆盖目标。legacy 计划没有规格时仍按原计划返回。
- 笔记读取按 `round_index` 返回已执行动作、被拒绝动作和未满足问题。
- 主张读取能从综述中的文献判断打开，并显示 `support` 或 `contradict`，以及原来的原文位置。
- 同一项目的论文列表在下一次运行检索前包含已入库论文、钉住项和排除项。

## 编辑

- 确认前可以增删纳入和排除规则、增删抽取列、修改覆盖目标，并钉住或排除已知论文。
- 范围、年份和语言以用户请求为准。
- 前端只扩展现有计划编辑、研究页和证据侧栏，不更换框架。

## 外部状态

现有 `get_research_status` 继续是只读外部入口，不等待研究循环结束。coverage 运行的结果额外包含：

- `round_index`
- `unmet_question_ids`
- `stop_reason`

工具数量保持现有 9 个。一次调用不得推进或等待一轮执行。

## 错误

- 旧计划版本确认：拒绝，运行仍停在确认前。
- 规格引用未知来源或悬空列：拒绝保存。
- 语言范围含中文且没有已配置中文全文源：不报成抓取失败；覆盖表写入 `zh_fulltext_not_licensed`。
