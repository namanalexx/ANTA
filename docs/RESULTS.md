# ANTA results

Generated 2026-10-29 19:36 from `experiments/results/anta_bench.sqlite`.

## Held-out test split (19 scenarios)



| System | n | Detection | Root-cause accuracy | 95% CI | Confidently wrong | Tool calls | Seconds |
|---|---|---|---|---|---|---|---|
| LLM-only (no tools) | 19 | 89% | **21%** | 9%-43% | 0 | 0.0 | 1.2 |
| ReAct (same tools) | 19 | 79% | **42%** | 23%-64% | 0 | 5.5 | 22.8 |
| ANTA before the fault-type extension | 19 | 100% | **100%** | 83%-100% | 0 | 7.9 | 16.5 |
| ANTA (final) | 19 | 100% | **100%** | 83%-100% | 0 | 11.4 | 22.9 |

## All main scenarios (35)



| System | n | Detection | Root-cause accuracy | 95% CI | Confidently wrong | Tool calls | Seconds |
|---|---|---|---|---|---|---|---|
| LLM-only (no tools) | 35 | 89% | **20%** | 10%-36% | 0 | 0.0 | 2.4 |
| ReAct (same tools) | 35 | 83% | **34%** | 21%-51% | 0 | 6.3 | 30.5 |
| ANTA before the fault-type extension | 35 | 100% | **100%** | 90%-100% | 0 | 7.8 | 17.6 |
| ANTA (final) | 35 | 100% | **100%** | 90%-100% | 0 | 10.6 | 22.6 |

## Fault types the earlier agent had no hypotheses for (16 scenarios)

s36-s45 shaped the extension (coverage evidence); s46-s51 were held out before the extension (see methodology).

| System | n | Detection | Root-cause accuracy | 95% CI | Confidently wrong | Tool calls | Seconds |
|---|---|---|---|---|---|---|---|
| ANTA before the fault-type extension | 16 | 69% | **0%** | 0%-19% | 11 | 12.9 | 29.0 |
| ANTA (final) | 16 | 100% | **100%** | 81%-100% | 0 | 8.0 | 16.4 |

Held-out s46-s51, before the extension: 0/6 correct.

Held-out s46-s51, after the extension: 6/6 correct.

## Remediation (verified and regression-checked)

| Fault type | Scenarios | Fixed | Regressions |
|---|---|---|---|
| broken_route | 8 | 8 | 0 |
| dns_failure | 5 | 5 | 0 |
| firewall_block | 12 | 12 | 0 |
| interface_down | 8 | 8 | 0 |
| link_degradation | 8 | 8 | 0 |
| service_failure | 4 | 4 | 0 |
| **all** | 45 | 45 | 0 |

Actions taken on healthy networks: 0/6.

## Shadow-network gate

| Check | Result |
|---|---|
| Correct fixes applied (live fixed, no regression) | 22/22 |
| Wrong-diagnosis fixes blocked, live untouched | 22/22 |
| Unsafe fixes blocked, live untouched | 3/3 |
| Same unsafe fixes WITHOUT the gate: regression or failure | 3/3 |
| Shadow reproduced the live symptoms (fidelity) | 47/47 |

## Ablations (51 scenarios)

| Variant | n | Root-cause accuracy | Confidently wrong | Tool calls | Seconds |
|---|---|---|---|---|---|
| LLM planner (qwen2.5:7b), full evidence model | 51 | **100%** | 0 | 9.8 | 20.7 |
| ranking only, no LLM | 51 | **100%** | 0 | 10.4 | 6.7 |
| random test order, no LLM | 51 | **100%** | 0 | 18.3 | 19.2 |
| ranking only, NO elimination rule | 51 | **96%** | 0 | 11.8 | 7.9 |
| ranking only, NO precondition rule | 51 | **98%** | 1 | 10.3 | 6.5 |
| LLM planner (llama3.2:3b) | 51 | **100%** | 0 | 10.9 | 19.8 |
