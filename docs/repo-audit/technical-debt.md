# Technical debt

This file separates **debt** (the system works, but carries a cost or a risk that grows with time)
from **defects** (behaviour that is wrong today). Defects are listed at the end for orientation only;
their records are in [findings.json](findings.json).

Debt items below are observations with evidence, not a work order. Prioritisation is the product
owner's.

## Architecture

| Item | What it costs | Evidence | Finding |
|---|---|---|---|
| **Two approved designs disagree.** `migratieontwerp.md` describes the full controller (stop a waiting runner, sticky quarantine, five-minute scrub limit, assignment proof); `controller-entrypoint-ontwerp.md` defines a thin slice that defers most of it. The code follows the thin slice; the unit comment, the README and parts of the tests follow the full design. | Every reader has to work out which protection is real. Five behaviours in this audit were "design says X, code does Y". | `docs/forgejo-runner-pool/migratieontwerp.md:115,335-347`; `docs/forgejo-runner-pool/controller-entrypoint-ontwerp.md:28-47,298-326` | AUDIT-003, -006, -007 |
| **Deferred controller paths ship as live-looking code.** `MaintenanceRecord`, `assignment_nulbewijs`, the `job_accepted` handler and the `RUNNING` state are reachable only from tests. | Tests for these paths pass and suggest protections production never exercises. | `forgejo-runner/scripts/forgejo_runner_cycle.py:149-183,195-208,340-350,381-388` | AUDIT-028 |
| **Controller state is memory-only**, apart from the operation marker. Quarantine, fence and drain do not survive a unit restart. | A restart is an undocumented way out of quarantine. | `forgejo-runner/scripts/forgejo_runner_cycle.py:218-231`; `forgejo-runner/forgejo-runner-cycle.service:12-15` | AUDIT-022 |
| **Part of the host configuration is outside the repository**: installation of the bundle's unit files, the mirror service and timer, the retention schedule, the `hosts/` overlay. | The byte-identity guarantee stops at `/opt/forgejo-runner/`; the rest cannot be reviewed or diffed. | `forgejo-runner/README.md:23-63`; `scripts/forgejo-mirror/README.md:3-4` | AUDIT-023 |

## Maintainability

| Item | What it costs | Evidence | Finding |
|---|---|---|---|
| **Same rule, several implementations**: secret-shape detection ×3, allowed-images format ×3, labels format ×2, headroom rule ×2, readiness confirmation ×2, base URL default ×7. | Fixes do not propagate; the strictest secret detector is not the one guarding this repository. | see AUDIT-027 evidence | AUDIT-027 |
| **Two files named almost identically with different semantics** (`pick_heaviest_workflow.py` vs `pick-heaviest-workflow.py`: seconds vs nanoseconds). | Confusion; the CLI variant is untested. | `forgejo-runner/scripts/pick_heaviest_workflow.py:11-17`; `forgejo-runner/scripts/pick-heaviest-workflow.py:50-61` | AUDIT-027 |
| **One-off step-A inventory tools live in the deployed bundle** (`capture-*.sh`, `measure-workload.sh`, `spike-ephemeral.sh`, `compute_caps.py`). | They are hashed and copied to both hosts although nothing calls them; their error handling is weaker than the rest. | `forgejo-runner/scripts/` | AUDIT-028, -030 |
| **Hand-rolled YAML-subset parser** for the allow-list, and thin validation of `controller.toml`. | Each new allow-list feature needs parser work; misconfiguration is silent. | `forgejo-runner/scripts/trust_scope_cli.py:121-161`; `forgejo-runner/scripts/cycle_runtime.py:52-71` | AUDIT-019 |
| **Complexity hot-spots** (cyclomatic 11–16) in `classify`, `_schrijvers`, `inventory`, `trust_scope_cli.main`. Readable today; they grow with every issue-driven rule. | Rising cost per change in the security-critical scanner. | `forgejo-runner/scripts/trust_scope.py:133,201,280` | code-quality.md §3.3 |
| **Tracked bytecode** and an incomplete root ignore file. | Dirty working tree after every test run. | `.gitignore`; `scripts/__pycache__/` | AUDIT-026 |

## Testing

| Item | What it costs | Evidence | Finding |
|---|---|---|---|
| **No CI and no single entry point.** 470 test cases run only when someone remembers three commands in one README; half of the test code has no documented command. | Regressions reach two production hosts unless a person runs the right commands in the right directory. | `forgejo-runner/README.md:89-93` | AUDIT-014 |
| **Platform gap.** Development happens on macOS; the target is Ubuntu. 18 tests need the target platform and skip silently elsewhere. | A green local run over-states what was proven. | [verification.md](verification.md) | AUDIT-015 |
| **Runtime wiring untested.** The state machine is tested thoroughly; the layer that connects it to Docker, the trust verdict and signals is tested with a stubbed gate and never through its main loop. | The five controller findings of this audit were expressible with the existing harness but not present. | `forgejo-runner/tests/_harness.py:69-98` | AUDIT-025 |
| **Newest scripts are untested** (mirror, retention). | Destructive operations without a regression net. | `scripts/forgejo-mirror/`, `scripts/docker-rollback-retention/` | AUDIT-016 |
| **Contract tests on unit files match text only**; there is no `systemd-analyze verify`. | A syntactically matching but semantically wrong unit passes. | `forgejo-runner/tests/test_unit_contract.bats`, `test_trust_timer_contract.bats` | testing.md §4 |

## Infrastructure and operations

| Item | What it costs | Evidence | Finding |
|---|---|---|---|
| **Silent stall modes.** Blocked latch, operation without deadline, red health gate: in each the unit is `active`, DinD is healthy and no runner is offered. The repository's own history (max2 ISS-8) shows this failure shape has already cost two outages for the trust gate. | The stability definition in §9 of the design (seven clean days) depends on noticing these. | `forgejo-runner/scripts/cycle_runtime.py:168-192,214-238,299-317` | AUDIT-004, -005, -021 |
| **Drift gate has a fail-open branch** (`ss` missing) and does not cover unit files or the rendered runner config. | "Verified" is narrower than it reads. | `forgejo-runner/scripts/verify-stack.sh:19-34` | AUDIT-023 |
| **Undeclared tool-chain**: Python ≥ 3.11, bash ≥ 4, GNU userland, GNU tar. | Works on the hosts by coincidence of their distribution; one difference is security-relevant on workstations. | [dependencies.md](dependencies.md) §DEP-5 | AUDIT-032 |

## Security

| Item | What it costs | Evidence | Finding |
|---|---|---|---|
| **The accepted risk rests on one control.** Every job controls a privileged DinD; the trust gate is the only thing between a workflow and the production host. Each weakness in the gate or around it is therefore amplified. | See the cross-cutting section of the executive summary. | `docs/forgejo-runner-pool/migratieontwerp.md:220-224` | AUDIT-001, -003, -009, -010, -012, -013 |
| **Secrets pass through argv and URLs in the oldest script** (mirror), against the repository's own rule A.1, while the newest script (`rotate-env-credential`) shows the intended standard. | Two standards for the same concern; the rotation runbook does not know one of the places a token is stored. | `scripts/forgejo-mirror/forgejo-mirror-lib.sh:381-405`; `docs/runbooks/credential-rotation.md:30-33` | AUDIT-011 |
| **The secret scan is a local, optional, pattern-based hook.** | The "no secrets in Git" hard-stop is enforced only where someone installed the hook, and only for the shapes it knows. | `forgejo-runner/scripts/secret-scan.sh` | AUDIT-002 |

## Dependencies

| Item | What it costs | Evidence | Finding |
|---|---|---|---|
| **Frozen digests without a refresh cadence.** Pinning by digest is the right mechanism; nothing prompts a review of the pins. | The privileged component and the component that executes repository code age silently. | `forgejo-runner/.env.example:3-10` | AUDIT-024 |
| **Third-party community job image** for every job of every repository. | Content is outside the owner's control. | `forgejo-runner/labels.txt:5` | AUDIT-024 |

## Documentation

| Item | What it costs | Evidence | Finding |
|---|---|---|---|
| **Top-level documents describe the repository as it was on 31 August.** | Agents and people start from "there is no code and no verify command". | `CLAUDE.md:13,35-41`; `AGENTS.md:11`; `README.md:8-12` | AUDIT-022 |
| **Documentation examples contradict rule A.1** (token inline on the command line). | Copy-paste puts a token in shell history. | `forgejo-runner/README.md:53`; `docs/forgejo-runner-pool/implementatieplan-forgejo-15.0.7.md:49` | AUDIT-013 |
| **A documented command does nothing** (`cycle_runtime.py --check`). | False assurance during rollout. | `forgejo-runner/controller.toml.example:7` | AUDIT-019 |

## Not debt: defects

These are wrong today and are tracked as findings, not as debt: AUDIT-002 (scanner bypasses),
AUDIT-008 (scrub proof on a silent daemon), AUDIT-017 (mirror logic), AUDIT-018 (retention guard),
AUDIT-019 (no-op check), AUDIT-020 (unguarded exceptions).

## Not debt: deliberate choices

Recorded so they are not re-raised as problems: privileged DinD in phase 1, digest pinning to "what
demonstrably runs", no deployment through Forgejo Actions, Python standard library only, the trust
scan on the default branch, and the deferral list in `controller-entrypoint-ontwerp.md` §2. Each is
written down with its reasoning in the design documents.
