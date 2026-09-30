# Code quality and maintainability audit

> **Lead note.** Severities in this file are the specialist's; the consolidated, lead-verified rating is in
> [findings.json](findings.json) (mapping in [README.md](README.md)). Test and linter execution results are in
> [verification.md](verification.md).

Baseline: branch `claude/repo-engineering-audit-66e5a7` at `4d9f873`. Read-only audit. Nothing was executed
from the repository (no tests, no repo scripts, no docker/ssh/curl/network). Security-specific and
test-coverage analysis belong to other agents; overlaps are mentioned in one line only.

## 1. Scope

Every file below was read in full and every cited line was re-opened.

| Area | Files |
|---|---|
| Controller (Python) | `forgejo-runner/scripts/forgejo_runner_cycle.py` (422), `cycle_runtime.py` (418), `cycle_adapters.py` (231) |
| Trust gate (Python) | `trust_scope.py` (376), `trust_scope_cli.py` (263) |
| Evidence tooling (Python) | `compute_caps.py`, `pick_heaviest_workflow.py`, `pick-heaviest-workflow.py`, `lib/redact_inspect.py` |
| Bundle shell | all 16 `forgejo-runner/scripts/*.sh` plus `lib/readonly.sh` |
| Config / units | `compose.yaml`, `.env.example`, `runner-config.policy.yml`, `trusted-actions-scope.yml`, `controller.toml.example`, `labels.txt`, `allowed-job-images.txt`, `forgejo-runner-cycle.service`, `forgejo-runner-trust.service`, `forgejo-runner-trust.timer`, `forgejo-runner/.gitignore`, root `.gitignore` |
| Host tools | `scripts/rotate-env-credential`, `compose-inpak`, `compose-git-init`, `compose-git-pre-commit`, `scripts/forgejo-mirror/*.sh`, `scripts/docker-rollback-retention/*.sh` |

Not reviewed here: `tests/`, `docs/` (only grepped for callers and stale statements).

## 2. Tools run and results

| Command (run from the stated directory) | Result |
|---|---|
| `shellcheck -x <f>` for each of the 16 `forgejo-runner/scripts/*.sh` + `lib/readonly.sh` (from `forgejo-runner/scripts`) | 17 files, 0 findings, all rc=0 (shellcheck 0.11.0) |
| `shellcheck -x forgejo-mirror-lib.sh` / `forgejo-mirror-sync.sh` (from `scripts/forgejo-mirror`) | 1 x SC2155 (lib.sh:91), 2 x SC1090 (sync.sh:34, already has a `disable` on the line above that does not cover the `.` calls after `set -a;`) |
| `shellcheck -x docker-rollback-retention.sh` | 0 findings |
| `ruff check --no-cache forgejo-runner/scripts scripts/rotate-env-credential scripts/compose-inpak scripts/compose-git-init scripts/compose-git-pre-commit` (default rules) | "All checks passed!" |
| same paths with `--select E,F,W,B,UP,SIM,C90 --statistics` | 123 findings: 98 E501 (line length, not reported), 9 C901, 4 B904, 4 B905, 3 SIM105, 3 SIM115, 1 B007, 1 SIM113 |
| `shellcheck -x -o all -S style` on the bundle scripts | only style/optional noise (SC2250 x279, SC2292 x65, SC2312 x25, SC2310 x19, SC2154 x5, SC2249 x4); not reported |
| `ruff check --select C901,SIM115,...` detail | C901 > 10: `_on_readiness` (11), `trust_scope._schrijvers` (15), `inventory` (14), `classify` (16), `load_allowlist` (12), `trust_scope_cli.main` (16), `compose-git-init.check` (13), `compose-inpak.cmd_run` (11), `rotate-env-credential.cmd_scan` (12) |
| `grep -rnE "TODO|FIXME|HACK|XXX"` over all reviewed source | 0 hits |
| Behaviour probes of bash semantics with throw-away snippets (no repo code) | (a) `x=$(false \| true)` under `set -euo pipefail` aborts the script; (b) `${!key}` with `key=GH_TOKEN_FOO.BAR` gives "invalid variable name", rc=1; (c) macOS `/bin/bash` 3.2.57 has no `mapfile` |
| `git ls-files`, `git check-ignore`, `strings` on tracked `.pyc` | 7 tracked `.pyc`; root `.gitignore` has no `__pycache__` rule; `.pyc` embed `/Users/janpetervisser/Development/.worktrees/idea-221-tokens/...` |

Static tooling is clean at its default strictness; the findings below are behavioural and were found by reading.

## 3. Findings

Severity is impact. Confidence is how sure I am that the behaviour is real and reachable.

### 3.1 Correctness / misleading gates

**CQ-1 (MEDIUM, HIGH) The documented `--check` validation is a silent no-op.**
`controller.toml.example:7` and `docs/forgejo-runner-pool/evidence/stap-d/bring-up-runbook.md:155-158` tell the operator to run
`python3 scripts/cycle_runtime.py --config controller.toml --check` and expect `exit=0` (or `config-fout ... exit 2`).
`cycle_runtime.py` ends at `main()` (line 418) with no `if __name__ == "__main__"` block; only `forgejo_runner_cycle.py:420-422`
has one. Running `cycle_runtime.py` just defines names and exits 0, so a broken `controller.toml` also "passes".
Even the real entry (`forgejo_runner_cycle.py --check`) only parses TOML and constructs adapters (`cycle_runtime.py:402-417`); it does not
check that any path exists.

**CQ-2 (MEDIUM, MEDIUM) `scrub-dind.sh` "bewezen schoon" proof passes when the DinD daemon is unreachable.**
The script is POSIX `sh` with `set -eu` and no `pipefail` (line 11). Every proof is `[ -z "$(d ... )" ]`-shaped:
`d ps -aq` (67), `d volume ls -q` (68), `d network ls | grep -vx || true` (70), the images loop (73-76), and
`CACHE="$(d system df ... | awk ...)"` with `${CACHE:-0B}` (81-82). If `docker -H tcp://127.0.0.1:2375` cannot connect, all of these yield empty
output, all report OK and the script exits 0 without having measured anything; the cleanup loops (42-58) likewise do nothing.
Mitigation: `compose exec` fails when the container is down and the controller re-checks `dind.healthy()` before starting
(`cycle_runtime.py:187-192`), so the window is dockerd not answering while the container is up (start-up/crash-restart). No test
covers an unreachable endpoint (`tests/test_scrub_dind.bats` cases listed by `grep @test`).

**CQ-3 (MEDIUM, MEDIUM) Controller loop has no guard against unexpected exceptions; some are reachable from I/O.**
`Runtime.tick` (`cycle_runtime.py:268-288`) and `run` (342-358) have no top-level `try`. Unhandled paths:
`TransportProbe.probe` catches `(URLError, TimeoutError, OSError)` (`cycle_adapters.py:53`) but not `http.client.HTTPException`
(e.g. `IncompleteRead` from `resp.read()` at line 29 when Forgejo restarts mid-response); `TrustVerdictReader.read` catches only
`FileNotFoundError, ValueError` (221) so `PermissionError`/`IsADirectoryError` on the verdict or labels/allowlist (`_sha256`, 226-231)
propagate; `RunnerLifecycle.start` (`Popen`, 90-91) can raise `OSError`. Result: traceback, exit, `Restart=on-failure` after 10 s. If a job was
running, the leftover runner container makes the next start `_blocked` (`_reconcile_once`, 304-307) until an operator intervenes.
Probability is low; the trigger (Forgejo restart/upgrade) is a routine event for this host.

**CQ-4 (MEDIUM, HIGH) A red DinD-health gate is silent, the same class of failure the code comments say already cost two incidents.**
`_readiness_and_gates` (`cycle_runtime.py:187-192`) logs only when `healthy()` raises; a non-zero `docker info` returns `False`
(`cycle_adapters.py:80-86`) with no log line, and `ensure_up` ignores the return code of `docker compose up -d dind` (77-78).
Compare `_log_trust_transition` (168-179), whose comment (168-172) says a silent gate caused undiagnosable outages. The controller
just never reaches WAITING.

**CQ-5 (MEDIUM, MEDIUM) `docker.subprocess_timeout_seconds` is not applied to the long-running operations; a hung pull/scrub stalls the pool silently.**
`_Compose` stores `self._t` (`cycle_adapters.py:66-73`) but `PullOp.start`, `ScrubOp.start` and `RunnerLifecycle.start` call `Popen` without any deadline
(90-91, 100-114, 126-143) and `_advance_op` (`cycle_runtime.py:214-238`) never checks elapsed time. `scrub-dind.sh` compares its own duration only after it completes
(`scrub-dind.sh:84-86`), so `exit 51` can never interrupt a hang. The unit is `Type=simple` with no `WatchdogSec`
(`forgejo-runner-cycle.service:8-21`), so a stuck `op` looks like a healthy, `active` service with no log output.

**CQ-6 (LOW, HIGH) `capture-clock-skew.sh` cannot reach its "ONBEKEND" branch on curl failure.**
`REMOTE_DATE="$(curl ... 2>/dev/null | tr ... | awk ...)"` (34-35) under `set -euo pipefail` aborts the script when curl fails, and curl's error is discarded
by `2>/dev/null`, so the evidence file ends after the header written at 23-31 with no message. The handler at 38-40 only covers "curl succeeded, no Date header".

**CQ-7 (MEDIUM, MEDIUM) `secret-scan.sh` can pass without scanning (portability and index-vs-worktree).**
(a) Line 11 uses `mapfile` (bash >= 4) with shebang `#!/usr/bin/env bash` and no `set -e` (line 7). On bash 3.2 (`/bin/bash` on macOS, verified: `mapfile: command not found`)
`bestanden` stays empty and line 13 `exit 0` silently approves the commit; on this machine Homebrew bash 5 shadows it, so it works only through PATH.
(b) It greps the working-tree file (`grep ... "$pad"`, lines 28, 43), not the staged blob, so `git add -p` staging of a secret hunk with a clean working tree file is not seen.
(c) `git diff --cached --name-only` (no `-z`, line 11) quotes non-ASCII paths, so `[ -f "$pad" ]` (line 17) is false and the file is skipped.
(Security agent owns severity; noted because it is a fail-open by construction.)

**CQ-8 (LOW, MEDIUM) `has_workflows` maps every non-200 to "no workflows".**
`forgejo-mirror-lib.sh:168-172` returns true only for HTTP 200; a 5xx, 401, 429 or a curl failure (empty code) is indistinguishable from the expected 404,
so the repo is mirrored with a PAT that lacks the Workflows scope (`sync.sh:70-76`). Failure surfaces later as a sync/SHA error. Fail-closed would treat non-404 as an error.

**CQ-9 (LOW, LOW) `gh_token_for_repo` breaks for repo names containing characters other than `[A-Za-z0-9_-]`.**
`forgejo-mirror-lib.sh:91-92` builds the variable name with `tr '[:lower:]-' '[:upper:]_'` (dots are kept) and expands `${!key:-$GH_TOKEN}`;
verified that `GH_TOKEN_FOO.BAR` gives "invalid variable name" and an empty result, so the caller proceeds with an empty bearer token (401, skipped/error every night).
Reachability unknown: I could not see the live repo list; no repo in `trusted-actions-scope.yml` has a dot.

**CQ-10 (MEDIUM, LOW) `verify_tags` compares only the first page of each tags endpoint.**
`forgejo-mirror-lib.sh:363-364` calls `/tags` on Forgejo and GitHub with no `limit`/`page` (contrast `enumerate_repos`, 152-164, which paginates).
Both APIs default to 30 items, so a repo with more tags than that yields either a false match or a permanent mismatch, which triggers `tags_fallback`
(`git push --tags --force`, 404-405) every night. Depends on tag counts and default page sizes I did not measure.

**CQ-11 (LOW, HIGH) `update_state` failure aborts the whole run; state file is write-only.**
`update_state` (`lib.sh:411-425`) returns non-zero on any `mv`/`jq` failure and is called at top level of the loop (`sync.sh:101`) under `set -euo pipefail`,
so a non-writable state directory kills the script after the first repo, before the `Summary:` line, leaving the other repos unmirrored. An empty existing `state.json`
makes `jq` emit nothing and `mv` replaces it with an empty file (421-424). `git grep state.json` shows no reader anywhere; the state records success but nothing consumes it.

**CQ-12 (LOW, MEDIUM) `tags_fallback` keeps credentials in the clone config and goes stale after rotation.**
`lib.sh:389-391` clones with `https://$FORGEJO_USERNAME:$FORGEJO_TOKEN@...`; the bare clone stores that URL as `origin`, and later runs only `fetch origin` (398).
After a Forgejo token rotation (this repo ships the rotation tool) the fetch keeps using the old token. `${FORGEJO_BASE_URL#https://}` also silently breaks an `http://` base URL.
(Token-in-argv/on-disk exposure is for the security agent.)

**CQ-13 (LOW, HIGH) `docker-rollback-retention.sh` can abort mid-`--apply` and its in-use guard can silently be empty.**
`size=$(docker image inspect ... | awk ...)` (49) under `pipefail` + `set -e` exits the script if an image vanished between listing and inspect, before the summary (62).
The in-use set is built from a process substitution (33-35) whose failure is ignored, so a failed `docker ps`/`inspect` yields an empty `in_use` and the
"never touches an image a container still uses" claim (header, lines 9-11) then rests only on `docker rmi` refusing. With zero rollback tags `"${rows[@]}"` (45) is unbound under `set -u` on bash < 4.4.
The script has no caller, unit, README or test anywhere in the tree (`git grep docker-rollback-retention`).

**CQ-14 (LOW, HIGH) `spike-ephemeral.sh` leaves a runner record behind if it fails after creating it.**
No `trap`: after `POST` (43-45) any failure of the JSON parsing (47-49) or `GET` (59) exits under `set -e` with the record still registered; only the label-not-empty branch (68-73) deletes it.
The label is interpolated into JSON with `printf '%s'` (44), so a `"` in a label that passes the `ephemeral-spike-*` prefix test breaks the payload. One-off step-A diagnostic, hence LOW.

**CQ-15 (LOW, MEDIUM) Evidence scripts report failures as data.**
`measure-workload.sh:29` turns a failed `docker stats` (including the guard's exit 64, hidden by `2>/dev/null`) into a synthetic `0%  0B / 0B  0` sample, so a wrong container name produces an all-zero series that
`compute_caps.py` then converts to the floor caps without any warning. `capture-current.sh:59` treats a failing `sudo -n test -f` (no sudo rights) like "no .runner found" and writes `{"fout":"geen .runner gevonden"}` (72).
`capture-forgejo-records.sh:36` appends rows to an existing `runners-summary.tsv` on every run (duplicates on re-run) and does not paginate.

### 3.2 Duplication, dead code, structure

**CQ-16 (LOW, HIGH) Same-named twin, different unit semantics.**
`pick_heaviest_workflow.py` (library) and `pick-heaviest-workflow.py` (CLI, not importable by name, no test, no caller other than the plan doc `implementatieplan-stap-a-b.md`).
Lib `_duration_seconds` (lines 11-17) treats a bare number as seconds; CLI `_duur_seconden` (`pick-heaviest-workflow.py:50-61`) treats it as nanoseconds and overwrites `run["duration"]` before the lib sees it (46).
Feeding raw Forgejo runs to `pick()` reports durations 10^9 too large. The CLI also calls the client's private `client._get` (33) and hard-codes the default URL (98).

**CQ-17 (LOW, HIGH) The same rule or file format is implemented several times.**
- Headroom rule (50 % vCPU, 50 % MemAvailable): `compute_caps.headroom_ok` (`compute_caps.py:57-68`, no non-test caller) and `preflight.sh:39-53` independently.
- `allowed-job-images.txt` "digest TAB bytes" format: `cycle_runtime.parse_allowed_images` (77-87), `preflight.sh:60`, `scrub-dind.sh:29`; `labels.txt`: `trust_scope_cli.load_shared_labels` (164-174) and `render-config.sh:31`.
- "Two-observation confirmation": `Confirmation` (`forgejo_runner_cycle.py:64-83`, resets after confirming) vs `ReadinessConfirmed` (`cycle_runtime.py:112-126`, latches); two sources of truth for "ready" (`_may_start`, 197-207, needs both).
- Secret-shape detection: `secret-scan.sh:43`, `compose-git-pre-commit:22-28`, `redact_inspect.py:26-31`, each with different rules.
- `measure-workload.sh:38-49` and `50-61` contain the same 10-line Python parser verbatim; `MemAvailable` awk repeated in `capture-host-facts.sh:24-25` and `measure-workload.sh:36`.
- `Stop`, `sha256_file` duplicated in `compose-inpak` and `compose-git-init`.
- HTTP-to-Forgejo: `ForgejoClient`, `TransportProbe`, and four separate curl wrappers in shell.

**CQ-18 (LOW, HIGH) Hard-coded hosts and paths in several layers.**
`https://git.jp-visser.nl` default in `trust_scope_cli.py:193`, `pick-heaviest-workflow.py:98`, `capture-forgejo-records.sh:7`, `render-config.sh:11`, `spike-ephemeral.sh:13`, `controller.toml.example:11`, `forgejo-runner-trust.service:27`.
`cycle_runtime.py:374` hard-codes `/etc/forgejo-runner/allowed-job-images.txt` (the in-DinD path) while `cfg.allowed_images_file` holds the host path of the same file; the coupling to `compose.yaml:18` is undocumented in code.
`compose.yaml:53` hard-codes `/opt/forgejo-runner/credentials/forgejo-token` while its sibling mounts are relative. Mirror script defaults `/srv/scrum4me/...`, `/var/lib/forgejo-mirror`; `rotate-env-credential` defaults container/user/db `scrum4me-postgres`/`scrum4me`.

**CQ-19 (LOW, HIGH) Dead or never-wired code.**
- `MaintenanceRecord`, `_startupuitzondering_actief`, `algemene_readiness_bevestigd` (`forgejo_runner_cycle.py:149-183, 340-350`): the runtime never sets `controller.maintenance` or `algemene_readiness_bevestigd` (grep of `cycle_runtime.py`/`cycle_adapters.py`); acknowledged in `docs/forgejo-runner-pool/forgejo-upgrade-onderzoek-2026-09.md:35`.
- `assignment_nulbewijs` (195-208), `Controller.cycle_stappen` (234-247) and the `nulbewijs_ok` branch (321-325): never called/set in production; deliberate per `controller-entrypoint-ontwerp.md:35-37`, so recovery always goes through the 60 s deadline watchdog (and emits an `alarm`) after even one failed probe.
- Step-A tooling with no runtime caller (only docs/tests): `pick-heaviest-workflow.py`, `measure-workload.sh`, `spike-ephemeral.sh`, `compute_caps.py` (no CLI entry), `verify-trust-scope.sh` (the unit calls the Python CLI directly).
- Small leftovers: `Controller.drain(now)` ignores `now` (249); `getattr(self, "_ev_cursor", 0)` (`cycle_runtime.py:291-293`) although `__init__` sets it; `import signal as _sig` inside `run` (343) despite the top-level import; `rc is not None and` after an `is None` return (222-223).

**CQ-20 (LOW, HIGH) Tracked build artefacts and inconsistent ignore rules.**
Seven `.pyc` files are tracked (`scripts/__pycache__/rotate-env-credentialcpython-314.pyc`, six under `scripts/tests/__pycache__/`), added with the idea-221 commits
(`git log -- scripts/__pycache__`). `forgejo-runner/.gitignore:1-2` ignores `__pycache__/` and `*.pyc`, the root `.gitignore` does not, so `scripts/` is unprotected
(`git check-ignore` returns 1). They are CPython-3.14-specific and embed an absolute author worktree path (`strings`).

**CQ-21 (LOW, HIGH) Executable-bit inconsistency.**
`capture-*.sh`, `measure-workload.sh`, `spike-ephemeral.sh`, `pick-heaviest-workflow.py`, `lib/readonly.sh` are mode 100644 while all other `.sh` files are 100755; the shebang files are invoked via `bash`/`python3` in docs, and the trust unit deliberately calls `/bin/sh` explicitly, so this is cosmetic, but it makes `./scripts/capture-current.sh` fail.

### 3.3 Configuration, parsing, complexity

**CQ-22 (LOW, HIGH) Controller config validation is thin and one setting is silently wrong for common input.**
`load_config` (`cycle_runtime.py:52-71`) checks presence only. `logging.basicConfig(level=getattr(logging, cfg.log_level, logging.INFO))` (407-410) maps `level = "info"` (lowercase, the spelling used in `runner-config.policy.yml:5`) to INFO by luck and any typo to INFO silently;
`getattr` on a name like `basicConfig` would even pass a function as level. Numeric bounds are not checked (`poll_interval_seconds = 0` is a busy loop; `probe_timeout` <= 0).

**CQ-23 (LOW, HIGH) Hand-rolled YAML subset parser and an exit-code contract that is not always honoured.**
`load_allowlist` (`trust_scope_cli.py:121-161`) opens the file without closing (125), does not support trailing comments or multi-line lists (both fail closed, but surprisingly), and is cyclomatic 12.
`classify` does `{i["name"] for i in ...}` and `r["full_name"]` (`trust_scope.py:285-286`) so a malformed identity raises `KeyError` outside the `try` in `main` (236): traceback and exit 1, contradicting the documented 0/10/20/30 contract (`trust_scope_cli.py:4`). `publish-trust-verdict.sh` treats any other code as failure, so it stays fail-closed.

**CQ-24 (LOW, MEDIUM) Portability assumptions are implicit.**
GNU-only tools in host scripts (`df --output`, `stat -c`, `date -d`, `flock`, `ss`, `nproc`); `rotate-env-credential` uses `os.listxattr`/`setxattr` guarded by `hasattr`; `tomllib` needs Python >= 3.11 with no in-code guard (the requirement is documented only in the design doc, `controller-entrypoint-ontwerp.md:51,497`).
`verify-stack.sh:30` silently passes the isolation check when `ss` is missing (`ss ... 2>/dev/null | grep -q` inside `if`). Acceptable for Ubuntu 26.04 hosts, but the mac is the authoring platform and the scripts are run from there in tests.

**CQ-25 (LOW, HIGH) Complexity hot-spots.**
`trust_scope.classify` (C901 16, ~95 lines, lines 280-376), `_schrijvers` (15), `inventory` (14), `trust_scope_cli.main` (16), `compose-git-init.check` (13). Each is readable and heavily commented, but they mix I/O, validation and message formatting and the ISS-driven branches keep growing.

## 4. What is done well (with evidence)

- Fail-closed is applied consistently and explained at the decision point: `classify_probe` has no default hole (`forgejo_runner_cycle.py:38-61`), `_valideer_repo`, `_decodeer`, `_eis_lijst_van_dicts` (`trust_scope.py:51-107`), `verdict_green` rejects bool/NaN/future/stale (`cycle_runtime.py:90-109`), `is not True` for `actions_enabled` (`trust_scope.py:305`).
- The verdict pipeline invalidates the old verdict on any failure and validates JSON strictly (duplicate keys, constants, list types, exit-code/result agreement): `publish-trust-verdict.sh:31-93`; atomic `os.replace`.
- Trust-gate transitions are logged only on change, with reasons (`cycle_runtime.py:168-179`).
- `rotate-env-credential` is careful engineering: all files read before any write, backups with `O_EXCL`, mode/owner/ACL preservation, `st_mtime_ns/size/ino` recheck, signal-to-rollback, secrets never in error text (`_reason`), stdin-only secrets (lines 133-261, 85-87).
- `compose-inpak` verifies by extracting and hashing before deletion and re-tests per file (`cmd_run`, 200-234); `compose-git-init` rolls back its own `.git` and `.gitignore` on failure (112-116).
- Adapters are dependency-injected (`cycle_adapters.py`: `opener`, `popen`, `run`), which is why the controller is unit-testable; pure decision logic is separate from side effects.
- `bundle-hash.sh` uses `-prune` and `LC_ALL=C sort -z`, NUL-delimited path+content hashing, and documents the exclusion set (lines 6-10, 27-48).
- Shell hygiene: 17 bundle scripts are shellcheck-clean with `set -euo pipefail`; secrets to curl via `--config <(...)` (`capture-forgejo-records.sh:29`, `spike-ephemeral.sh:33`); `readonly.sh` is a proper allow-list guard returning 64.
- Configuration is externalised in `controller.toml.example` with comments tying each value to a design section; compose caps are `.env`-driven with explanations (`compose.yaml:25-28`).
- No TODO/FIXME/HACK/XXX markers in source; comments explain the "why" and reference issue IDs.

## 5. Open questions

1. Are there Forgejo repositories under `janpeter` with `.` or other non `[A-Za-z0-9_-]` characters in their names, and repos with more than 30 tags (CQ-9, CQ-10)?
2. Which bash resolves `#!/usr/bin/env bash` in the commit hooks on each machine that uses `install-git-hooks.sh` (CQ-7)?
3. Is `docker-rollback-retention.sh` scheduled anywhere on a host (no unit/timer in the repo), and is `/var/lib/forgejo-mirror/state.json` read by any external tool (CQ-11, CQ-13)?
4. Should `MaintenanceRecord`/`assignment_nulbewijs` stay in the bundle as documented-but-unwired code, or move out until stap H?
