# Evaluation methodology

## Benchmark
51 JSON scenarios (injected fault, symptom wording, ground truth, required evidence).

| Split | n | Purpose |
|---|---|---|
| dev | 16 | tuned on |
| test | 19 | headline split (see disclosures) |
| stress | 10 | interface-down and packet-loss/delay faults the first agent had no hypotheses for |
| stress_test | 6 | fresh scenarios of those two types, held out before the extension |

Tiers: seen faults, rephrased symptoms, variants (other devices, ports, mechanisms), controls (healthy network, harmless firewall rules), and unknown fault types. The six fault types are the hard cap.

## Metrics
Detection (did it know something was wrong), root-cause accuracy (cause and device correct), device and layer localisation, evidence quality (cited findings include the required ones), tool calls, seconds, confidently-wrong rate (wrong with status "confirmed"), remediation success, regression rate.

## Baselines
Both use the same local model and, where applicable, the same 11 tools and the same network description, and answer in the same label vocabulary.
* **LLM-only:** description and symptom, no tools.
* **ReAct:** thought, tool call, observation loop; 15 tool calls; JSON observations truncated to 700 characters. Evidence quality counts only calls that map onto one of ANTA's standard checks.

## Protocol and disclosures (chronological)
1. 25 scenarios written; first full run scored 52% overall because of a bug I introduced (the "no fault" hypothesis got a score bonus from every healthy reading). Misses also revealed missing hypotheses and a ground-truth bug in two control scenarios.
2. Fixes were tuned on **dev only**. Four scenarios whose misses motivated fixes (s08, s09, s16, s17) were moved from test to dev. Ten fresh scenarios (s26-s35) were added before the test split was run once.
3. The test split was then run once on the frozen agent: 19/19. Nine of its 19 scenarios had been run once before tuning.
4. Stress test, stage 1: the agent without hypotheses for interface-down and loss/delay faults scored 0/16 (11 confidently wrong, 5 hedged). Results were archived as `anta_v1` before any change.
5. Extension (hypotheses, interface/netem inspection, precondition rule). First pass on the held-out s46-s51: 5/6 correct, 0 confidently wrong. It also caused a regression on two in-library scenarios (ICMP-drop firewall rules), which led to the elimination rule. After that fix: 51/51. **The elimination fix was informed by two of the held-out scenarios, so the clean held-out evidence is the first-pass 5/6 and the final held-out batch.**
6. s36-s45 shaped the extension, so they show coverage, not generalisation.

## Statistics
Wilson 95% intervals. n is small (19 on the headline split; a perfect score only supports "at least about 83%"). One run per scenario at temperature 0, so variance across LLM sampling is not measured.

## Remediation and gate evaluation
Remediation: full loop (reset, inject, diagnose, fix, verify, regression check) on every fault scenario and every healthy control. Gate: for each scenario, a deliberately wrong diagnosis (an ineffective fix) and the correct one; plus three crafted unsafe fixes, each also run without the gate for contrast. The wrong-diagnosis fixes are ineffective rather than harmful; the harmful-fix evidence is the three crafted unsafe fixes, which is a small sample.

## Ablations
On all 51 scenarios, switched by environment variables: LLM planner vs ranking only vs random order; without the elimination rule; without the precondition rule; llama3.2:3b instead of qwen2.5:7b. The baseline reuses the existing `anta` rows. Results (clean run, after an earlier overlapping-jobs incident was found and rerun): the evidence model carries correctness. Ranking only and random order are both 100% (random needs 18.3 tool calls against 10.4 for ranking); llama3.2:3b is 100% with 99% of its LLM calls usable; removing the elimination rule gives 96% (the two ICMP-drop firewall scenarios); removing the precondition rule gives 98% with one confidently wrong answer (an interface-down fault diagnosed as a route fault). The qwen2.5:7b planner uses 9.8 tool calls on average against 10.4 for ranking alone but takes about 14 seconds longer per diagnosis (20.7 s vs 6.7 s), so its measurable contribution is the natural-language explanation, not accuracy. Full table in docs/RESULTS.md.

## Bugs the evaluation found (and how)
* "No fault" hypothesis bias: benchmark scored 52%.
* Incomplete lab reset after a config-poisoning test: only 4 of 15 correct fixes passed the gate; diagnosis of two scenarios flipped. Fixed by restoring known-good configs on reset and checking baseline health before every run.
* Packet-loss faults made the shadow fidelity check fail closed: symptom-level findings are random, so fidelity now uses configuration-level findings for those faults.
* The extension broke two in-library scenarios: caught by the regression run; fixed by the elimination rule.
* Capture noise (ARP) counted as traffic: fixed by filtering captures to the probe's own traffic.
* Two overlapping ablation jobs on the same lab corrupted each other's faults (a healthy control was diagnosed with the neighbouring scenario's fault). Detected from that pattern, rows deleted and rerun; the runner and evaluations now take a lab lock so overlapping runs refuse to start.

## Limitations and threats to validity
Hand-written hypothesis table; benchmark and agent written by the same author around the same fault families; small n; a single lab topology; "no fault" is not proof of health; the shadow is a Docker stack that clones a fixed set of state categories; not compared with published systems.
