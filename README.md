# Math Distill Stage 2 ProofBench

Unofficial residual Lean certificate benchmark for solver, LLM, and skill-workflow experiments on the SAIR Mathematics Distillation Challenge: Equational Theories Stage 2.

Chinese version: [README.zh-CN.md](README.zh-CN.md)

## Competition Context

This dataset is derived from the competition setting of the [SAIR Mathematics Distillation Challenge: Equational Theories Stage 2](https://competition.sair.foundation/competitions/mathematics-distillation-challenge-equational-theories-stage2/evaluation-setup). The official Stage 2 repository is [SAIRcompetition/equational-theories-lean-stage2](https://github.com/SAIRcompetition/equational-theories-lean-stage2).

The task is equational implication over magmas: given a source equation and a target equation over one binary operation `*`, decide whether the source equation implies the target equation. In Stage 2, an answer is not just a `true` or `false` string. A solver must submit a Lean 4 certificate:

- `true`: a Lean 4 proof that the source equation implies the target equation.
- `false`: a Lean 4 proof that there exists a finite magma satisfying the source equation but not the target equation.

The competition is especially interesting because the verifier is deterministic. Unlike many ordinary math datasets, this public residual set does not need to ship with ground-truth labels in order to be useful: a successful Lean 4 certificate can indirectly recover the label. If the judge accepts a `true` certificate, the row is proven true; if it accepts a `false` certificate, the row is proven false.

This repository is not an official leaderboard split. It is a small, fixed public proofbench for trying proof search, prompt design, LLM-assisted repair, and Codex skill workflows against residual problems from the Stage 2 style of task.

## Dataset

Current version:

- `data/residual-100-v1/problems.jsonl`
- `data/residual-100-v1/manifest.json`

`residual-100-v1` contains 100 Stage 2 equation implication problems. Each JSONL row is one problem. Important fields include:

- `equation1`: source equation.
- `equation2`: target equation.
- `eq1_id` / `eq2_id`: equation IDs from the local `eq_size5.txt`.
- `pair_index`: deterministic ordered-pair index from the local order5 pair space.
- `stratum`: order4/order5 source-target size stratum.
- `shape_bucket`: coarse source-shape to target-shape bucket used for sampling diagnostics.
- `answer` / `expected_verdict`: always `null`.

No ground-truth labels are included. The dataset also does not include model outputs, judge results, private judge backend URLs, or official `test_locked` rows.

## Residual Source

The local order5 ordered-pair universe starts from `3,915,693,200` possible pairs. Using deterministic strategy coverage and residual filtering, this project narrows that space to an unresolved estimate of `176,175,766`, roughly `1.8e8` residual pairs.

The current public proofbench is a compact 100-problem sample from that residual space. The intended next step is to use LLM skill workflows to attack these problems, generate Lean 4 certificates, and let accepted certificates become recovered labels.

## Sampling

`residual-100-v1` was created from the 2026-05-25 local current residual sample:

- Total order5 pair universe: `3,915,693,200`
- Current unresolved estimate: `176,175,766`
- Initial false-uncovered random pool: `2,000`
- Residual source pool after true-strategy filtering: `207`
- Final public sample: `100`
- Selection method: largest-remainder proportional quotas by `stratum`, then deterministic round-robin sampling over `shape_bucket` groups for diversity.

Final stratum distribution:

| stratum | count |
| --- | ---: |
| `order4_source_to_order5_target` | 6 |
| `order5_source_to_order4_target` | 7 |
| `order5_source_to_order5_target` | 87 |

The final sample contains 98 distinct `shape_bucket` values. No `shape_bucket` appears more than twice.

## Experiment Protocol

Treat this repository as a fixed challenge set:

1. Generate a Stage 2 judge-compatible certificate for each row in `problems.jsonl`.
2. Verify the certificate with the official-compatible Lean 4 judge/verifier.
3. Count only judge-accepted certificates as solved.
4. Record the model, prompt, skill version, raw response, judge verdict, and error summary.

Remote judge backend URLs are intentionally not committed. Pass your own official-compatible simple-api backend with `--base-urls` or the `PROOFBENCH_REMOTE_SIMPLE_API_BASE_URLS` environment variable when using the helper verifier.

Recommended report fields:

- `attempted`: number of attempted rows.
- `accepted`: number of judge-accepted rows.
- `accepted_rate`: `accepted / 100`.
- `true_accepted` / `false_accepted`: accepted counts by certificate verdict, if available.
- `reproducibility_notes`: model, date, prompt, solver code, skill workflow, and toolchain versions.

## Current Accepted Snapshot

The following is a current working snapshot for `residual-100-v1`. It reports only certificates accepted by the official-compatible Lean 4 judge/verifier.

| date | workflow | attempted | accepted | accepted rate | true accepted | false accepted | notes |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 2026-05-26 | Codex with `stage2-proofbench-solver` skill workflow | 100 | 21 | 21.0% | 21 | 0 | Accepted certificates recover labels for 21 rows; raw attempts and judge logs are kept out of the committed dataset. |

## Notes

This benchmark is not an unbiased estimate of the full 176M residual universe. It is meant to be a small but stable proofbench for comparing models, prompts, skill workflows, and proof repair methods on exactly the same rows.

Because the rows do not contain labels, a claimed answer should be considered experimental until it is backed by an accepted Lean 4 certificate.

## Quick Checks

```bash
wc -l data/residual-100-v1/problems.jsonl
jq '.selected_summary' data/residual-100-v1/manifest.json
```
