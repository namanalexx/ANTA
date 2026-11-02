# Architecture

## 1. Design principles
1. **The LLM reasons, tools state facts.** Every network fact comes from a diagnostic tool that returns typed JSON.
2. **Evidence, not guesses.** Hypothesis confidence is computed from tool findings. The LLM cannot change it.
3. **Fail closed.** A fix reaches the live network only after a shadow copy of the fault has been repaired and checked.
4. **Everything is reproducible.** Docker lab, JSON scenarios, SQLite results, one runner.

## 2. The lab
Five Linux containers on three bridge networks (client 10.10.1.0/24, core 10.10.2.0/24, servers 10.10.3.0/24):
`client - router - firewall - {dns-server (dnsmasq), web-server (nginx)}`. Containers carry `NET_ADMIN`, static IPs and static routes set by an entrypoint script. Docker NAT is disabled and default routes are removed, so the lab is isolated from the host and the internet. (Docker `internal: true` networks were rejected because Docker's own anti-spoofing rules drop routed traffic between bridges.)

## 3. Tool layer (11 tools, typed JSON)
`get_topology`, `get_interface_status` (link state, packet-loss/delay settings), `get_route_table`, `get_arp_table`, `ping` (loss, RTT, failure mode, which device sent an ICMP error), `traceroute`, `inspect_dns`, `inspect_firewall` (rules, policies, hit counters), `capture_packets` (tcpdump with traffic patterns), `check_service`, `get_logs`. A `namespace()` switch points the same tools, verifier and remediation code at the shadow stack.

## 4. Evidence model
* A **test** calls one tool and turns the JSON into **findings** such as `route_complete:router = False`.
* **22 hypotheses** (21 faults plus "no fault"). Each has a table of predictions: finding, expected value, likelihood ratio.
* Scoring (log-odds): an anomalous finding that matches a prediction raises the score; any finding that contradicts a prediction lowers it; a healthy reading that matches a "stays healthy" prediction is neutral.
* **Elimination:** a hypothesis whose decisive prediction (likelihood ratio >= 10) is observed false is eliminated, and confidence is renormalised over the survivors.
* **Preconditions:** strong "this part stays healthy" claims must be verified before a conclusion. A missing route is only a root cause if the interface under it is up.
* **Conclusion rule:** leader >= 90%, a decisive supporting finding, no decisive contradiction, no unverified precondition. "No fault" is proven by elimination: nothing anomalous seen and every fault hypothesis decisively ruled out.

## 5. Planner and LangGraph graph
`init -> decide -> (plan -> act -> update -> decide)* -> conclude`.
* **Ranking:** each untested test is scored by how well it splits the surviving hypotheses (Gini impurity weighted by log of the strongest likelihood ratio).
* **LLM:** chooses among the top six candidates and gives a reason; an invalid choice falls back to the top-ranked test.
* **Confirm step:** once a leader passes 90% without decisive proof, a rule runs its most decisive test (or the unverified precondition).
* 26 tests in the catalog; budget 30.

## 6. Remediation
A playbook maps each hypothesis to one of six actions: restore routes, remove blocking rules (only rules that affect http/dns/ping), start a service, restore a known-good config from the repo, bring an interface up (and restore its static routes), clear netem settings. Actions have explicit commands and rollbacks, and are planned from fresh tool facts. After applying: three scenario checks (ping, HTTP 200, DNS), a full health fingerprint, and a state-snapshot diff that flags any change the action did not declare (the **regression check**). The detector is self-tested with four crafted fixes (over-broad, collateral damage, does nothing, correct).

## 7. Shadow network gate
A second Compose project (`shadow-*`, 10.20.x.x). At proposal time the live state (iptables rules and policies, routes, service state, configs, interface state and netem settings) is replayed onto it with IPs translated: a **static clone**, never kept in sync. The gate: (1) fidelity: the shadow must show the same configuration-level anomalies as live (symptom-level findings are also compared, except for probabilistic faults); (2) apply the fix to the shadow; (3) verify and regression-check there; (4) only then apply to live and verify again. Decisions: `applied`, `blocked_failed_shadow`, `blocked_inconclusive`. A block leaves the live network untouched.

## 8. Dashboard
FastAPI runs a job in a thread and streams events (server-sent events). React + D3 draws the topology (heat from hypothesis confidence, active tests highlighted), hypothesis bars, an investigation timeline that separates LLM reasons from measured evidence, and the gate stepper. A Results tab reads the SQLite results.

## 9. Data and reproducibility
Scenarios: `benchmark/scenarios/*.json`. Results: `experiments/results/anta_bench.sqlite` (tables `runs`, `remediation_runs`, `gate_runs`). `scripts/reproduce.sh` regenerates everything; `python3 -m experiments.final_report` writes docs/RESULTS.md.
