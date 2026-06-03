# Math Distill Stage 2 ProofBench

这是一个非官方 residual Lean certificate benchmark，用来在 SAIR Mathematics Distillation Challenge: Equational Theories Stage 2 的任务语境下，测试 solver、LLM、Codex skill workflow 和人工 proof search 能产出多少 Lean 4 可验证证书。

英文主版本：[README.md](README.md)

## Codex 求解结果

对于 `residual-100-v1`，Codex 结合 `stage2-proofbench-solver` workflow 在约 `21.9` 个 elapsed hours 时达到 `94 / 100`（`94.0%`）个首次 judge-accepted certificate。运行继续到约 `72.7` 小时后没有新增 official acceptance，仍有 6 题未解。

![Codex accepted progress](docs/assets/codex_accepted_progress.svg)

对于 `residual-1000`，同样口径比较三个版本，并将 `12-84h` 压缩显示以突出早期曲线：v1 为 `736 / 1000`（`73.6%`），v2 为 `792 / 1000`（`79.2%`），v3 为 `737 / 1000`（`73.7%`）。v2 综合最强，三条曲线在前 `12` 个 elapsed hours 后都明显变平，显示当前 Codex GPT-5.5 xhigh 加 `stage2-proofbench-solver` workflow 的长尾能力边界。

![Codex residual-1000 accepted progress by version](docs/assets/residual1000_versions_accepted_progress_12_84_compressed.png)

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
- `data/residual-1000-v1/problems.jsonl`
- `data/residual-1000-v1/manifest.json`
- `data/residual-1000-v2/problems.jsonl`
- `data/residual-1000-v2/manifest.json`
- `data/residual-1000-v3/problems.jsonl`
- `data/residual-1000-v3/manifest.json`

`residual-100-v1` 包含 100 个 Stage 2 equation implication 问题。每一行是一道题，重要字段包括：

- `equation1`：source equation，也就是前提方程。
- `equation2`：target equation，也就是目标方程。
- `eq1_id` / `eq2_id`：本地 `eq_size5.txt` 中的方程编号。
- `pair_index`：本地 order5 pair space 的确定性有序 pair 编号。
- `stratum`：order4/order5 source-target 分层。
- `shape_bucket`：采样诊断用的粗粒度 source-shape 到 target-shape bucket。
- `answer` / `expected_verdict`：始终为 `null`。

目前这些数据都没有真实标签。数据集中也不包含模型输出、judge 结果、私有 judge backend 地址或官方 `test_locked` 数据。

`residual-1000-v1`、`residual-1000-v2` 和 `residual-1000-v3` 每个版本都包含 1000 行，字段 schema 相同。三个 manifest 分别报告 1000 个 unique ordered pair，并包含 638、623、667 个不同的 `shape_bucket`。

## Residual 来源

本地 order5 有序 pair 宇宙一开始有 `3,915,693,200` 个可能 pair。通过 deterministic strategy coverage 和 residual filtering，目前把空间缩小到 `176,175,766` 个 unresolved residual pair，也就是大约 `1.8e8`。

这个公开 proofbench 现在包含一个 100 题样本和三个 1000 题样本。后续目标是尝试通过 LLM skill workflow 来解决这些问题：生成 Lean 4 certificate，并用 accepted certificate 反过来获得标签。

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

`residual-1000-v1`、`residual-1000-v2` 和 `residual-1000-v3` 沿用同样的无标签、certificate-only 口径。三版 stratum 分布如下：

| stratum | v1 | v2 | v3 |
| --- | ---: | ---: | ---: |
| `order4_source_to_order4_target` | 2 | 3 | 5 |
| `order4_source_to_order5_target` | 51 | 52 | 41 |
| `order5_source_to_order4_target` | 75 | 57 | 74 |
| `order5_source_to_order5_target` | 872 | 888 | 880 |

这些更大的样本不像 `residual-100-v1` 剩余 6 题那样集中在极端尾部，但 v1 当前达到 736（`73.6%`）个 accepted 后，仍然暴露出明显长尾。

## 注意事项

这个 benchmark 不是完整 1.76 亿 residual universe 的无偏估计。它更适合作为一个小而稳定的 public proofbench：比较不同模型、提示词、skill workflow 和 proof repair 方法在同一批 residual 上的表现。

因为这些行本身不带标签，任何声称的答案都应该先视为实验结果，直到它有一个被 Lean 4 judge 接受的 certificate。
