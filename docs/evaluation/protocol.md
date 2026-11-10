# 评价执行与人工审核协议 v1

本仓库已实现评价执行工具及B0/B1/B2/A1/A2与coverage候选配置。当前验证数据是原创合成资料，只说明工程链路能够运行，不能据此声称多Agent改善学术研究质量，也不能据此声称优于Elicit或Deep Research。`benchmark.test.jsonl`刻意留空，正式独立测试集必须人工准备。

## 环境与命令

在backend目录执行。沿用uv管理的Python3.12，数据库使用配置派生的`_test`库；先运行`prepare-test-db`。评价运行建立独立项目和run，不覆盖业务研究。模型调用缓存仅在同一run内恢复时复用，跨实验创建新run；下载文件允许暖缓存。

```powershell
uv run --locked python -m app.cli prepare-test-db
uv run --locked python -m app.cli evaluate --config ../evals/configs/B2.json --output ../evals/output/experiment-001
```

输出目录已存在时拒绝执行。默认配置均为mock，不产生供应商消费。真实实验须显式设置配置的llm_mode=live和实际模型ID，并在本机.env配置凭据；先进行probe。source_mode虽为离线，frozen profile可配合真实模型，不能把“离线语料”误解为“不会产生模型费用”。

## 现有策略的实际差别

| 配置 | 实际行为 | 公平性核查 |
| --- | --- | --- |
| B0 | 单一研究身份，跨阶段共享前序结构化结果，串行阅读；相关性Top-K，无反馈补充 | 共享记忆限12条/12000字节，增加的上下文计入同一预算；不是一个主题直接生成综述 |
| B1 | 四角色固定流程、相关性Top-K，无反馈补充 | 与B0使用相同来源、字段契约、模型映射与预算 |
| B2 | 问题覆盖/冗余选择，至多一轮共享补检或补读 | 首版默认策略 |
| A1 | 与B2相同，精读选择改为纯相关性排序 | 用于检查覆盖选择的影响 |
| A2 | 跳过摘要模型初读，按冻结候选顺序选择精读，仍受同一精读及总预算限制 | 报告实际完成数量，不追加预算补齐全部全文 |
| coverage | 与B2使用同一研究身份设置，但规划模式为多轮覆盖循环 | 与B0使用同一冻结语料、同一mock模型和同一四项调用预算；只多`max_research_rounds: 2`。B0仍走旧图、串行、单身份 |

这些是可运行的候选基线，不是已经通过独立实验验证的公平比较。正式实验前应人工核对提示词、B0阶段划分、记忆差异、模型参数与预算。首次验证未设置或检验供应商temperature/seed行为，不宣称生成完全可复现。

## 冻结数据准备

1. 先选定可人工审核的领域。在开发集调整方案；独立测试集建议6个主题，冻结后不据其结果调参再当作独立测试。
2. 主题格式见`evals/dataset.schema.json`。每行记录cutoff_date、scope、问题ID、候选池、人工相关性标注及文档清单路径。所有输入相对evals目录，目录穿越和不存在路径被拒绝。
3. 候选池JSONL使用PaperRecord契约；不能只标最终入选材料。真实冻结资料用provider=frozen，提供原始摘要、稳定provider_id和版本。禁止在线pdf_url；本地文档通过raw_payload.local_pdf_key引用evals/documents中的明确文件名。
4. 文档清单每行包括path、sha256、license、allowed_to_process=true。文件哈希须匹配。许可是否允许处理需准备者实际核查，程序不会推定授权。
5. 相关性标注每行包括paper_key=`provider:provider_id:原始版本`、relevance=0..4或null、key_paper布尔值、rater_id。至少部分样本由两位领域审核者独立标注；记录分歧及裁决。当前合成gold由fixture作者编写，不是人工学术评价。
6. 冻结文件后，程序在manifest保留数据、prompt、源码及依赖锁文件SHA256。没有Git首次提交时仍以源码哈希记录实际版本。

## 输出及人工核验

每次执行生成manifest.json、run-UUID.json、results.csv、metrics.json、human-review.csv、report.md。失败、预算停止与unknown调用均保留，不从结果中丢弃。CSV包含公式起始字符转义，原始JSON保留文本原值。

`human-review.csv`对所有实质性事实块提供原句、证据ID和原文。审核者填写rater_id与support（supported/partial/unsupported/unclear），不能让模型代填。重复审核同一块时保留不同审核者行；当前支持率采用严格口径：所有有效审核均充分支持才计充分支持，分歧另报数量。

```powershell
uv run --locked python -m app.cli score-evaluation --input ../evals/output/experiment-001 --human ../evals/annotations/reviewed.csv --output ../evals/output/scored-001
```

计分不会调用模型，也不覆盖原实验。零分母返回null。引用存在率和人工引用支持率分别统计，未审核的支持率不能写成100%。Precision@K以实际返回数为分母，同时报告返回数；关键论文覆盖率仅代表精读入选对金标种子的覆盖。

另外三项自动指标与人工支持率分开：

- `seed_paper_recall`：金标`key_paper`出现在预选候选中的比例。分母是种子论文数；没有种子时为null。它不看精读入选。
- `required_column_fill_rate`：最新覆盖产物中，必填格`filled_papers > 0`的比例。分母是必填格数；旧图没有覆盖表时为null。
- `sentence_evidence_existence_rate`：综述里`literature_claim`与`synthesis`句子中，引用的证据编号都能在综述证据表找到的比例。分母是这两类句子数；没有这类句子时为null。它只说明编号存在，不表示人工判定支持。

`citation_support_rate`在没有人工标注时继续为null。合成冒烟只证明覆盖循环能够跑完，不能据此声称本工具优于Elicit或Deep Research。

当前这些人工指标尚未审核，数值保持null。扩展人工CSV时：question_ids用竖线分隔（如q1|q2），仅在标注充分支持时计有效覆盖；字段审核在field_status填写supported、unsupported或omitted，必须把应有但漏填字段一并列入；覆盖性、组织性、可比性、准确性和局限表达分别使用coverage、organization、comparability、accuracy、limitations列，填写1—5分。空列保持null，原始表与分歧裁决另行留档。字段正确率和漏填率按审核行统计，重复审核应先完成裁决，不能混合重复行改变分母。正式研究至少3次重复并报告范围/标准差；现有五配置各3个合成主题、每主题1次仅为冒烟测试。

## 当前验证范围

2026-10-30：Windows、uv Python3.12.16、PostgreSQL17.6，五种配置共15个mock运行完成；支持率保持null。真实供应商、真实论文质量、PostgreSQL16单独复现和两类实际MCP客户端兼容性未验收。
