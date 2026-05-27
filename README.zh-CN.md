# Math Distill Stage 2 ProofBench

这是一个非官方 residual Lean certificate benchmark，用来在 SAIR Mathematics Distillation Challenge: Equational Theories Stage 2 的任务语境下，测试 solver、LLM、Codex skill workflow 和人工 proof search 能产出多少 Lean 4 可验证证书。

英文主版本：[README.md](README.md)

## Codex 进展

下图展示了 Codex 使用 `stage2-proofbench-solver` skill workflow 攻击 `residual-100-v1` 时，随着经过小时数增长，累计首次被 judge accepted 的 certificate 数量。这里每一题只按第一次 accepted 计数，重复 re-verification 不重复累计。

![Codex accepted progress](docs/assets/codex_accepted_progress.svg)

## 比赛背景

这个数据集来自 [SAIR Mathematics Distillation Challenge: Equational Theories Stage 2](https://competition.sair.foundation/competitions/mathematics-distillation-challenge-equational-theories-stage2/evaluation-setup) 的比赛任务语境。官方 Stage 2 仓库是 [SAIRcompetition/equational-theories-lean-stage2](https://github.com/SAIRcompetition/equational-theories-lean-stage2)。

任务是 magma 上的 equational implication：给定一个 source equation 和一个 target equation，判断前者是否蕴含后者。这里的 magma 只有一个二元运算 `*`，默认没有结合律、交换律等额外公理。

Stage 2 的有趣之处在于，答案不是普通的 `true` / `false` 文本，而是 Lean 4 certificate：

- `true`：用 Lean 4 证明 source equation 蕴含 target equation。
- `false`：用 Lean 4 证明存在一个有限 magma，满足 source equation 但不满足 target equation。

因此这个比赛和普通数学数据集不太一样。普通数学 benchmark 往往需要先有真实标签才能评测；而这里有确定性 Lean 4 verifier，只要提交的 `true` 或 `false` certificate 被 judge 接受，就可以间接获得该题的真实标签。

本仓库不是官方 leaderboard split，而是一个小而固定的公开 proofbench，用来尝试 proof search、prompt design、LLM-assisted repair，以及后续的 Codex skill workflow。

## 数据集

当前版本：

- `data/residual-100-v1/problems.jsonl`
- `data/residual-100-v1/manifest.json`

`residual-100-v1` 包含 100 个 Stage 2 equation implication 问题。每一行是一道题，重要字段包括：

- `equation1`：source equation，也就是前提方程。
- `equation2`：target equation，也就是目标方程。
- `eq1_id` / `eq2_id`：本地 `eq_size5.txt` 中的方程编号。
- `pair_index`：本地 order5 pair space 的确定性有序 pair 编号。
- `stratum`：order4/order5 source-target 分层。
- `shape_bucket`：采样诊断用的粗粒度 source-shape 到 target-shape bucket。
- `answer` / `expected_verdict`：始终为 `null`。

目前这些数据都没有真实标签。数据集中也不包含模型输出、judge 结果、私有 judge backend 地址或官方 `test_locked` 数据。

## Residual 来源

本地 order5 有序 pair 宇宙一开始有 `3,915,693,200` 个可能 pair。通过 deterministic strategy coverage 和 residual filtering，目前把空间缩小到 `176,175,766` 个 unresolved residual pair，也就是大约 `1.8e8`。

这个公开 proofbench 是从 residual 空间里抽出的 100 道固定题。后续目标是尝试通过 LLM skill workflow 来解决这些问题：生成 Lean 4 certificate，并用 accepted certificate 反过来获得标签。

## 采样口径

`residual-100-v1` 来自 2026-05-25 的本地 current residual 采样：

- order5 总 pair 宇宙：`3,915,693,200`
- 当前 unresolved estimate：`176,175,766`
- false-uncovered 初始随机池：`2,000`
- true strategy 过滤后 residual source pool：`207`
- 最终公开样本：`100`
- 选择方法：先按 `stratum` 做 largest-remainder proportional quotas，再在每个 stratum 内按 `shape_bucket` 做确定性 round-robin 抽样，以提高形状多样性。

最终 100 题的 stratum 分布：

| stratum | count |
| --- | ---: |
| `order4_source_to_order5_target` | 6 |
| `order5_source_to_order4_target` | 7 |
| `order5_source_to_order5_target` | 87 |

最终样本包含 98 个不同的 `shape_bucket`，单个 `shape_bucket` 最多出现 2 次。

## 实验协议

建议把这个 repo 当作固定 challenge set 使用：

1. 对 `problems.jsonl` 中每一题生成 Stage 2 judge-compatible certificate。
2. 使用官方兼容的 Lean 4 judge/verifier 验证 certificate。
3. 只把 judge accepted 的 certificate 计入 solved。
4. 记录模型、提示词、skill 版本、raw response、judge verdict 和错误摘要。

建议报告：

- `attempted`：尝试题数。
- `accepted`：accepted 题数。
- `accepted_rate`：`accepted / 100`。
- `true_accepted` / `false_accepted`：如果能区分 certificate verdict，则分别报告 true/false accepted。
- `reproducibility_notes`：模型、日期、提示词、solver code、skill workflow 和工具链版本。

## 注意事项

这个 benchmark 不是完整 1.76 亿 residual universe 的无偏估计。它更适合作为一个小而稳定的 public proofbench：比较不同模型、提示词、skill workflow 和 proof repair 方法在同一批 residual 上的表现。

因为这些行本身不带标签，任何声称的答案都应该先视为实验结果，直到它有一个被 Lean 4 judge 接受的 certificate。

## 快速检查

```bash
wc -l data/residual-100-v1/problems.jsonl
jq '.selected_summary' data/residual-100-v1/manifest.json
```
