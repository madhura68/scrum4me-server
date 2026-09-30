# Repository map — scrum4me-server

Audit baseline: branch `claude/repo-engineering-audit-66e5a7` at `4d9f873` (= `main` on 2026-09-30).
All numbers below were measured with `git ls-files` / `wc -l` on that commit.

## What this repository is

An **infrastructure / host-operations repository**, not an application. It holds:

1. The canonical *Forgejo Runner pool bundle* (`forgejo-runner/`) that is rolled out by hand to two
   hosts (`scrum4me-server`, `max2`) under `/opt/forgejo-runner/`.
2. Stand-alone host-operations scripts (`scripts/`) for credential rotation, compose-directory
   hygiene, the Forgejo→GitHub mirror and Docker rollback-tag retention.
3. Design documents, implementation plans, review reports, runbooks and captured evidence (`docs/`).

Single repository, no monorepo tooling, no package manifest of any kind.

| Property | Observed |
|---|---|
| Tracked files | 167 |
| History | 190 commits, 2026-08-31 → 2026-09-30 |
| Languages | Python 3 (stdlib only), Bash, Bats |
| Non-doc source + test lines | ≈ 10 600 |
| Package manager / lockfile | none (`package.json`, `pyproject.toml`, `requirements*.txt` absent) |
| Build step | none |
| CI/CD | none — no `.forgejo/workflows/`, no `.github/workflows/` |
| Database schema / migrations | none in this repo |
| Deployment | manual copy / SSH to the hosts (see `CLAUDE.md` "Niet deployen via Forgejo Actions") |
| Forge | Forgejo at `git.jp-visser.nl` (`origin`) |

## Top-level layout

| Path | Files | Content |
|---|---|---|
| `forgejo-runner/` | 66 | The shared bundle: compose stack, systemd units, policy files, scripts, tests |
| `forgejo-runner/scripts/` | 26 | Cycle controller (Python), trust-scope scanner (Python), deploy/verify/capture shell scripts |
| `forgejo-runner/tests/` | 28 | 17 `.bats` files, 10 `test_*.py` (unittest), `_harness.py` |
| `scripts/` | 22 | Host-ops tools + `scripts/tests/` (7 unittest modules) + 7 tracked `.pyc` files |
| `docs/forgejo-runner-pool/` | 59 | Migration design, implementation plans, reviews, step A/D/E evidence |
| `docs/runbooks/` | 11 | `credential-rotation.md` + dated evidence files |
| `docs/superpowers/` | 4 | Specs and plans (credential rotation, compose copies, ISS-18) |
| `CLAUDE.md`, `AGENTS.md`, `README.md` | 3 | Agent instructions and a short repo README |

## Components

### A. Forgejo Runner pool bundle (`forgejo-runner/`)

| Element | File(s) | Role |
|---|---|---|
| Container stack | `compose.yaml`, `.env.example` | `dind` (privileged Docker-in-Docker, plaintext TCP 2375 on an internal bridge) and `runner` (profile `cycle`, `one-job --wait`) |
| Cycle controller | `scripts/forgejo_runner_cycle.py` (422), `cycle_runtime.py` (418), `cycle_adapters.py` (231) | systemd-driven state machine that starts exactly one runner process per job and gates on readiness, trust verdict, fence and maintenance |
| systemd | `forgejo-runner-cycle.service`, `forgejo-runner-trust.service`, `forgejo-runner-trust.timer` | Long-running controller; periodic trust-verdict refresh |
| Trust scope | `scripts/trust_scope.py` (376), `trust_scope_cli.py` (263), `verify-trust-scope.sh`, `publish-trust-verdict.sh`, `trusted-actions-scope.yml` | Scans Forgejo repos via the API against an allow-list and publishes `trust-verdict.json` |
| Policy / pins | `runner-config.policy.yml`, `labels.txt`, `allowed-job-images.txt` | Runner policy, digest-pinned label and job image |
| Deploy gates | `scripts/preflight.sh`, `render-config.sh`, `bundle-hash.sh`, `verify-stack.sh`, `scrub-dind.sh`, `resolve-digests.sh` | Pre-rollout checks, config rendering, drift gate, image scrub |
| Inventory (read-only) | `scripts/capture-*.sh`, `measure-workload.sh`, `lib/readonly.sh`, `lib/redact_inspect.py`, `compute_caps.py`, `pick_heaviest_workflow.py`, `pick-heaviest-workflow.py` | Evidence capture for step A of the migration |
| Hygiene | `scripts/secret-scan.sh`, `install-git-hooks.sh` | Pre-commit secret scan |
| Host config template | `controller.toml.example` | Per-host controller configuration (not part of the bundle hash) |

### B. Host-operations scripts (`scripts/`)

| Tool | Lines | Language | Role |
|---|---|---|---|
| `rotate-env-credential` | 569 | Python | Rotate a Postgres role password and rewrite `.env` files without the secret reaching argv/logs |
| `compose-inpak` | 267 | Python | Archive stray compose copies into a verified tar, then delete |
| `compose-git-init` | 155 | Python | Put a live compose directory under local git with an allow-list and hook |
| `compose-git-pre-commit` | 109 | Python | The hook installed by `compose-git-init` |
| `forgejo-mirror/forgejo-mirror-sync.sh` + `-lib.sh` | 129 + 425 | Bash | Nightly Forgejo→GitHub push-mirror maintenance and verification |
| `docker-rollback-retention/docker-rollback-retention.sh` | 62 | Bash | Keep the N newest `rollback-*` image tags per repository |

## External systems touched by the code

| System | Used by | Transport |
|---|---|---|
| Forgejo API (`git.jp-visser.nl`) | trust scanner, controller transport probe, capture scripts, mirror | HTTPS + token |
| GitHub API | mirror | HTTPS + token |
| Docker daemon (host) | controller (`docker compose`), preflight, verify-stack, retention | CLI subprocess |
| Docker-in-Docker daemon | runner container, scrub | TCP 2375, no TLS, bridge-internal |
| PostgreSQL (`scrum4me-postgres`) | `rotate-env-credential` | `psql` subprocess |
| systemd | units in the bundle; mirror and rotation services on the host | unit files |
| Container registries | `resolve-digests.sh` | HTTPS |

## Validation tooling

Documented in `forgejo-runner/README.md` ("Verifiëren"):

    bats tests/*.bats
    for f in tests/test_*.py; do python3 "$f"; done
    shellcheck -x scripts/*.sh

No documented command exists for `scripts/tests/`. No linter, formatter or type-checker configuration
is tracked. No CI executes any of this; see `verification.md`.

## Documentation structure

| Location | Content |
|---|---|
| `CLAUDE.md`, `AGENTS.md` | Agent rules, product binding, hard-stop rules |
| `docs/forgejo-runner-pool/migratieontwerp.md` | The approved pool design (steps A–H) |
| `docs/forgejo-runner-pool/implementatieplan-*.md` | Per-step implementation plans |
| `docs/forgejo-runner-pool/reviews/` | Review-loop reports |
| `docs/forgejo-runner-pool/evidence/` | Captured host/Forgejo state (JSON, TSV, TXT) |
| `docs/runbooks/` | Credential-rotation runbook and dated evidence |
| `docs/superpowers/{specs,plans}/` | Specs and plans for the host-ops scripts |
| Scrum4Me product docs (database, not in git) | Additional ADR/plan/runbook documents; not inspected file-by-file in this audit |

## Discovery-time observations (followed up in the reports)

- `CLAUDE.md` and `AGENTS.md` state that the repo "contains no code yet" and that `forgejo-runner/`
  does not exist; both are contradicted by the tree.
- Seven compiled `.pyc` files under `scripts/__pycache__/` and `scripts/tests/__pycache__/` are tracked.
- Two near-identically named files exist: `pick-heaviest-workflow.py` (120 lines) and
  `pick_heaviest_workflow.py` (34 lines).
