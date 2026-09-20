# PolicyPilot V1 Requirement Modeling + Retrieval Planning 评测报告

评测日期：2026-09-06  
模型：`deepseek/deepseek-chat`（Agent 与 User Simulator）  
配置：seed 0、max steps 40、max errors 10、BM25、禁用缓存

## 结论

本次实现完成了 Requirement -> Coverage -> Gap -> Query -> Open Question 的闭环，未修改 tau2 Orchestrator、Environment、工具执行器、Evaluator、hidden criteria，也未让 Agent 访问 `required_documents`。

两个任务在最新代码的独立复测中均达到 Reward 1.0，Required Actions 3/3；但同批 smoke 中 task_001 仍出现一次 Platinum 锚定，最终 smoke 仍为 1/2。由此可以确认：原始 Reward=0 不是 DeepSeek 响应慢导致，直接原因是约束提取、候选级覆盖、用户事实路由和最终建议之间的信息链偏差；模型延迟只影响 latency/cost。当前机制显著提高了可达正确性，但单次 seed 不能消除远端模型与用户模拟的非确定性。

## 实现范围

- `DecisionRequirements`：维护 objective、hard constraints、preferences、optimization criteria，多轮累积而不复制 Goal/Known Facts/Open Questions/Evidence。
- `RetrievalCoverage`：维护 requirement coverage、candidate labels、candidate policy aspects、fee-free candidates 和 evidence refs；完整矩阵不进入 LLM context。
- `RetrievalGap`：只表示缺少的 Policy 信息；`OpenQuestion` 只表示必须向用户确认的事实。
- Query planner：由目标类型、选中的主 gap、全部 hard constraints 和 LLM 语义扩展共同构造；candidate-specific terms 前置，并记录 proposed/planned query 与实际 gap keys。
- Source router：存在 Open Question 时直接切换到 USER，防止 LLM 继续搜索知识库；图节点会直接输出待确认问题，避免 action repair 循环。
- Evidence：修复编号步骤误判为新文档的问题，并按 query anchors 保留 fee、subscription、eligibility、rewards、timing、limits 等关键行。
- 约束顺序：先以 hard constraints 筛选候选，再优化收益；首年 fee waiver 不等同于长期 fee-free。
- task_010：从已验证非成功状态生成 remediation/retry/timing policy requirement，并在用户可立即重试时保留明确行动请求。

## 测试

- 修改前 V1 测试：65 passed，1 skipped。
- 修改后 V1 测试：85 passed，1 skipped，2 warnings，2.02s。
- Ruff：All checks passed。
- 裸 `pytest` 不作为本项目口径：它会额外收集上游 voice/gym/Agentify 实验及 `work/uv-cache` 第三方测试，因缺少可选的 `pyaudio`、`scipy`、`gymnasium`、`a2a` 等依赖在收集阶段失败。
- 两个 warnings 为既有环境问题：Python `audioop` deprecation，以及未知 pytest asyncio 配置项。

## 基线与最终单任务

| Run | Reward | DB Check | Required Actions | Steps | Tools (A/U) | Retrieval | Context avg/max chars | Tokens in/out | Cost | Latency |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Baseline task_001 | 0.0 | false | 0/1 | 30 | 7/1 | 6 | 23,735.9 / 35,979 | 109,463 / 1,999 | 0.031009 | 28.782s |
| Final task_001 single | 1.0 | true | 1/1 | 21 | 5/1 | 5 | 28,627.9 / 37,238 | 72,942 / 1,439 | 0.022107 | 20.540s |
| Baseline task_010 | 1.0 | true | 2/2 | 35 | 12/1 | 6 | 30,091.6 / 43,262 | 160,727 / 5,012 | 0.053507 | 42.081s |
| Final task_010 single | 1.0 | true | 2/2 | 25 | 8/1 | 3 | 25,734.6 / 39,903 | 94,930 / 2,421 | 0.026262 | 23.797s |

最终两个独立 run 合计：Reward 2/2、Required Actions 3/3、15 次工具调用、8 次检索、167,872 input tokens、3,860 output tokens、成本 0.048369、延迟 44.337s。相对两项基线合计，检索减少 4 次，成本减少约 42.8%，总延迟减少约 37.4%。

## V1 Smoke 对比

| Run | Success | Avg Reward | Required Actions | Tools | Retrieval | Avg context chars | Tokens in/out | Total cost | Avg latency |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Baseline smoke | 1/2 | 0.5 | 2/3 | 21 | 12 | 26,913.8 | 270,190 / 7,011 | 0.084516 | 35.431s |
| Final smoke | 1/2 | 0.5 | 2/3 | 21 | 12 | 35,759.3 | 382,487 / 14,357 | 0.120394 | 58.667s |

最终 smoke 明细：task_001 Reward 0、DB false、Actions 0/1、31 steps、9 tools、6 retrievals、context 32,850.0/39,807、137,864/3,240 tokens、cost 0.046288、37.622s；task_010 Reward 1、DB true、Actions 2/2、37 steps、12 tools、6 retrievals、context 38,668.5/70,088、244,623/11,117 tokens、cost 0.074106、79.712s。两次运行 source DB 均 unchanged=true。

这组 smoke 没有性能提升，主要是 DeepSeek 在同一 seed 下仍会返回不同自然语言与 tool proposals；task_001 失败后又进入无必要的身份查询，task_010 也生成了更长解释。报告因此同时保留独立成功结果与同批稳定性结果，不用单次成功替代真实波动。

## 最终成功 Queries 与工具调用

### task_001 single

1. `card credit cash back rewards everyday purchases highest cash back rate`
2. `card diamond elite cash back rate fees annual no annual fee fee-free alternatives annual fee eligibility annual fee 0.00 fee-free cash back all purchases subscription required alternatives rewards`
3. `card platinum rewards cash back rate fees annual no annual fee fee-free alternatives annual fee eligibility annual fee 0.00 fee-free cash back all purchases subscription required alternatives`
4. `card diamond elite annual fee pricing waiver no annual fee fee-free alternatives annual fee eligibility standard fee fee waiver cash back rewards rate`
5. `card personal credit annual fee cash back rate bronze gold no annual fee fee-free alternatives annual fee eligibility cash back rewards`

工具流：5 x `KB_search` -> user `apply_for_credit_card(card_type="Gold Rewards Card", customer_name="Sarah Bosch", annual_income=100000, rho_bank_subscription=true)`。

### task_010 single

Retrieval queries：

1. `cards referral bonus status complete in_progress rejected reward eligibility status explanation retry procedure timing window next step remediation`
2. `cards credit card referral weekly limit rolling 7-day window third rejected status explanation retry procedure timing window next step`
3. `cards credit card referral rejected rolling 7-day window wait retry oldest status explanation retry procedure timing window next step`

工具流：`get_user_information_by_email` + `get_user_information_by_name` -> `get_current_time` + `get_referrals_by_user` -> `log_verification` -> 3 x `KB_search` -> user `submit_referral(user_id="76ad9cc60e", account_type="Platinum Rewards Card")`。

## task_001 归因

- 第一轮已保留 personal card、everyday purchases、highest cash back；用户随后给出 no annual fee 条件后，被规范化为“只有不存在合格 fee-free alternative 才接受年费”的 hard constraint。
- 检索成功发现 Bronze、Silver、Gold 等零年费候选；候选级 Coverage 能区分“某候选有 cost 信息”和“系统曾见过 cost 信息”。
- 成功发现 Gold 的 Rho-Bank+ requirement；Open Question 向用户确认订阅，回答被保存为 `subscription_status` 并进入最终 action 参数。
- 独立成功 run 的最终 action 正确；失败 smoke 的失败点不是 Retrieval 完全缺失，也不是 Action 参数缺失，而是 Decision LLM 的最终候选排序再次被 Platinum 的 10% 锚定，随后执行了错误产品 action。
- 多次中间实验还分别暴露过：Gold subscription 行被 evidence compaction 丢失、Open Question 未优先于 Retrieval Gap、以及用户 action 缺少 `rho_bank_subscription`。这些路径均已有对应单元测试与修复。

## 限制与下一步

当前实现严格停留在 Requirement -> Retrieval Planning，没有加入 Policy Decision Engine、Hybrid RAG、Memory、Multi-Agent 或大规模 prompt 重写。剩余主要风险是生成模型仍可违反已显示的硬约束。要进一步提高 task_001 的跨运行稳定性，下一步应单独立项做“constraint-compliance verifier / policy decision layer”，并用多 trial 而非单 seed 评测；这不应混入本次实验，否则无法继续清楚归因。
