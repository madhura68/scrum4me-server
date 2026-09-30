# Testing and reliability audit

Scope: static reading only. No test, script, docker, ssh or network command was run by the author of
this file. Baseline: branch `claude/repo-engineering-audit-66e5a7` (= `main` at `4d9f873`).
Everything marked **Observed** was read in the cited lines; everything marked **Inference** is a
conclusion drawn from those lines.

> **Lead note.** Execution results for every suite are in [verification.md](verification.md): all executed
> tests pass; 17 of 95 `scripts/tests` cases and 1 of 137 bats cases were skipped on the audit workstation.
> Severities in this file are the specialist's; the consolidated, lead-verified rating is in
> [findings.json](findings.json) (mapping in [README.md](README.md)).

## 1. Automation present

- No CI: `.forgejo/` and `.github/` do not exist (`ls` confirmed). No Makefile, no `pyproject.toml`,
  no tox/nox, no pre-commit framework config.
- Only automation that exists is a **local git hook**: `forgejo-runner/scripts/install-git-hooks.sh`
  writes a `pre-commit` that `exec`s `secret-scan.sh`. This worktree's common git dir has a
  `pre-commit` hook installed (observed with `ls`), so it is opt-in per clone.
- The other hook is `scripts/compose-git-pre-commit`, installed by `compose-git-init` into
  *other* (host) compose directories, not into this repo.
- systemd units under `forgejo-runner/` are deployment artefacts, not test automation.

## 2. Test inventory

Counts: `@test` for bats, `def test_` for unittest (grep, per file).

| Suite | Location | Files | Test cases | Runner |
|---|---|---|---|---|
| Bats | `forgejo-runner/tests/*.bats` | 17 | 137 | `bats` |
| Python (cycle controller, trust scope, helpers) | `forgejo-runner/tests/test_*.py` (+ `_harness.py`) | 10 | 238 | `python3 <file>` (each has `unittest.main()`) |
| Python (host-ops scripts) | `scripts/tests/test_*.py` (+ `_load.py`) | 7 | 95 | `python3 -m unittest` (undocumented, see 6) |
| Total | | 34 | 470 | |

Per file (cases): bats: bundle_hash 10, capture_clock_skew 2, capture_current 4, capture_forgejo_records 3,
capture_host_facts 2, compose_contract 18, compose_runner_exec 1, preflight 10, publish_trust_verdict 2,
readonly_guard 6, render_config 13, scrub_dind 17, secret_scan 18, spike_ephemeral 5, trust_timer_contract 9,
unit_contract 8, verify_stack 9. Python (runner): compute_caps 7, cycle_eventloop 18, cycle_fence 24,
cycle_lifecycle 21, cycle_maintenance 16, cycle_readiness 20, cycle_runtime 49, pick_heaviest_workflow 4,
publish_trust_verdict 6, trust_scope 73. Python (scripts): alter_probe 13, compose_git 27, compose_inpak 14,
integration_pg 2, rewrite 17, rewrite_key 15, scan 7.

Conditional / skipped tests (observed):

| Test | Gate | Effect on macOS with bsdtar (this host: `tar` = bsdtar 3.5.3) |
|---|---|---|
| `test_compose_inpak.py::InpakTest` (all 14) | `skipUnless(gnu_tar())` line 35 | **all 14 skipped** |
| `test_integration_pg.py::PostgresIntegration` (2) | `REC_PG_INTEGRATION=1` | skipped by default |
| `test_rewrite.py::test_posix_acl_preserved` | needs `os.listxattr`, `setfacl`, `getfacl` | skipped (Linux/ACL only) |
| `test_compose_runner_exec.bats` (1) | `docker info` must work, `timeout`/`gtimeout` must exist | skipped without docker; **runs a real `docker pull` and `docker run` if docker is up** |
| `test_bundle_hash.bats` line 64 | skipped when uid 0 | runs as non-root |
| `test_scan.py::test_symlink_not_followed_and_unreadable_skipped` | inner `if os.geteuid() != 0` | as root the unreadable-file half silently does not execute (test still passes) |

## 3. Coverage matrix

Legend for type: **U** = unit with fakes/in-memory; **F** = functional against real local tool (git, tar, sh) in a tmp dir;
**S** = script run with a fake CLI (docker/curl/ss/sudo) on `PATH`; **C** = contract/grep test on a config text;
**I** = integration against a real service; **-** = none.

### forgejo-runner/scripts

| Source | Tests | Type | Notes |
|---|---|---|---|
| `forgejo_runner_cycle.py` | `test_cycle_{eventloop,fence,lifecycle,maintenance,readiness}.py`, `_harness.py` | U (real state machine, fake clock, no mocks) | Strong for the pure state machine. `cycle_stappen()` test is a tautology (asserts order of a constant list, only used by tests) |
| `cycle_runtime.py` | `test_cycle_runtime.py` | U (fake adapters + fake Popen) | `_trust_green` is stubbed in the harness; `Runtime.run()`, signal registration and `_build_adapters` (only via `--check`) are not exercised |
| `cycle_adapters.py` | `test_cycle_runtime.py` (`import cycle_adapters as ca`) | U (injected `popen`/`run`/`opener`) | argv shape and error mapping proven; real subprocess, timeouts, `TimeoutExpired`, `docker` behaviour not |
| `trust_scope.py` | `test_trust_scope.py` (73) | U (fake client) | broad; pagination, 404/405/403/500 mapping covered |
| `trust_scope_cli.py` | `test_trust_scope.py` (patches `urlopen`) | U | `main()` exit-code mapping (10/20/30) not seen exercised end to end; `load_allowlist`/`load_shared_labels` covered indirectly at best |
| `publish-trust-verdict.sh` | `test_publish_trust_verdict.py`, `.bats`, `test_bundle_hash.bats`, `test_trust_timer_contract.bats` | F (real sh + fake CLI py) | fail-closed invalidation proven with real files |
| `verify-trust-scope.sh` | none | - | 16-line wrapper |
| `preflight.sh` | `test_preflight.bats` (10) | F (real script, TSV/env fixtures) | |
| `render-config.sh` | `test_render_config.bats` (13) | F | |
| `bundle-hash.sh` | `test_bundle_hash.bats` (10), `test_verify_stack.bats` | F | |
| `verify-stack.sh` | `test_verify_stack.bats` (9) | S (fake `ss`) | `ss` absent never tested |
| `scrub-dind.sh` | `test_scrub_dind.bats` (17) | S (stateless fake docker, run under bash not busybox ash) | see 4 |
| `secret-scan.sh`, `install-git-hooks.sh` | `test_secret_scan.bats` (18) | F (real git in tmp) | renames / partial staging not covered |
| `spike-ephemeral.sh` | `test_spike_ephemeral.bats` (5) | S (fake curl) | |
| `capture-current.sh` | `test_capture_current.bats` (4) | S (fake docker/sudo/du) | |
| `capture-clock-skew.sh`, `capture-forgejo-records.sh`, `capture-host-facts.sh` | matching `.bats` | S | |
| `lib/readonly.sh` | `test_readonly_guard.bats` (6) | S | |
| `lib/redact_inspect.py` | only indirectly via `test_capture_current.bats` | S | see 4 |
| `compute_caps.py` | `test_compute_caps.py` (7) | U | |
| `pick_heaviest_workflow.py` | `test_pick_heaviest_workflow.py` (4) | U | |
| `pick-heaviest-workflow.py` (hyphen, 120 lines, the CLI) | none | - | not importable by name; imports `trust_scope_cli.ForgejoClient` |
| `measure-workload.sh` | none | - | |
| `resolve-digests.sh` | none | - | |

### forgejo-runner config artefacts

| Artefact | Tests | Type |
|---|---|---|
| `compose.yaml`, `.env.example`, `labels.txt`, `allowed-job-images.txt` | `test_compose_contract.bats` (18) | C (grep / text split); `test_compose_runner_exec.bats` is the only I-type test (real image, dummy config) |
| `forgejo-runner-cycle.service` | `test_unit_contract.bats` (8) | C |
| `forgejo-runner-trust.{service,timer}` | `test_trust_timer_contract.bats` (9) | C |
| `runner-config.policy.yml`, `trusted-actions-scope.yml`, `controller.toml.example` | via render/preflight/trust tests only | partial |

### scripts/

| Source | Tests | Type |
|---|---|---|
| `rotate-env-credential` | `test_rewrite.py`, `test_rewrite_key.py`, `test_scan.py`, `test_alter_probe.py` | U/F (real tmp files, real signals, `subprocess.run` mocked for docker) |
| `rotate-env-credential` against Postgres | `test_integration_pg.py` | I (gated, needs Docker, see 5) |
| `compose-git-init`, `compose-git-pre-commit` | `test_compose_git.py` (27) | F (real git, isolated `GIT_CONFIG_*`) |
| `compose-inpak` | `test_compose_inpak.py` (14) | F (real GNU tar; `compose_ls` replaced by lambda) - skipped without GNU tar |
| `forgejo-mirror/forgejo-mirror-sync.sh`, `-lib.sh` | none | - (554 lines) |
| `docker-rollback-retention/docker-rollback-retention.sh` | none | - (62 lines) |

Source files with **no** tests at all: `forgejo-mirror-sync.sh`, `forgejo-mirror-lib.sh`,
`docker-rollback-retention.sh`, `measure-workload.sh`, `resolve-digests.sh`, `verify-trust-scope.sh`,
`pick-heaviest-workflow.py`. (Name-grep across both test dirs; module imports were checked separately, so
`cycle_adapters`, `forgejo_runner_cycle` and `trust_scope_cli`, which are imported under aliases, are
counted as covered above.)

## 4. Proven versus assumed

**Proven (strong evidence):**
- The pure cycle state machine (`Controller`, `Fence`, `Confirmation`, `EventLoop`, `MaintenanceRecord`,
  `assignment_nulbewijs`) is driven for real with a fake clock; there are no mocks of the unit under test
  (`test_cycle_fence.py` lines 1-60 drive `c.Controller(c.EventLoop(klok))` directly).
- `rotate-env-credential` rewrite/rollback: mid-batch failure, `KeyboardInterrupt`, real `SIGTERM` via
  `os.kill`, broken stdout, file changed during write, mode/owner/backup permissions and leak checks
  (`assertNoLeak`) are all tested on real temp files with only `os.replace`/`os.fsync` patched to inject the fault.
- `compose-git-*`: real `git` with isolated config, including "no half repo after failure" and "staged content is judged, not the working file".
- Trust publisher: real shell + fake CLI; failed measurement overwrites active green verdict.

**Merely assumed / only text-proven:**
- Runtime behaviour of `compose.yaml`, unit and timer files: the tests grep text
  (`test_compose_contract.bats` lines 21-25 split the file on `'runner:'`/`'dind:'`; `test_unit_contract.bats` greps `ExecStart`, `Restart=`). No `systemd-analyze verify`. *Lead correction:* three tests in `test_compose_contract.bats` (lines 116-160) do render the file with `docker compose -f compose.yaml config` and inspect the result, so the runner command line, the read-only allow-list mount and the DinD CPU quota are checked on the rendered model; the remaining compose assertions and all unit/timer assertions are text matches.
- Controller against real Docker: adapters are tested for argv only. `Runtime.run()` (the actual main loop, SIGTERM handler, stop deadline) has no test; the harness stubs `rt._trust_green` (`_harness.py`, last lines), and the probe result is fixed per built runtime, so no Runtime-level test can drive "probe fails then recovers".
- `scrub-dind.sh` cleanup effectiveness: the fake docker in `test_scrub_dind.bats` is stateless (`rm`, `rmi`, `volume rm` are no-ops), so a test can only seed residue and check that the proof stage fails (exit 50); "dirty DinD cleaned to exit 0" cannot be expressed. The script is executed with `bash` in tests but runs as `sh -s` (busybox ash) in the DinD container; only `shellcheck -s sh` bridges that.
- `redact_inspect.py`: the fixture in `test_capture_current.bats` puts the same token in `Config.Env` *and* inline in `Cmd`. The redactor removes the inline copy only because it first collected the value from `Env` (mechanism 2, `redact_inspect.py` lines 14-16, 101-102). A secret present only inside a `sh -c "... --token X"` string (a single list element, so `SECRET_FLAG` at line 29 does not match) is not covered by any test, and the fixture would not reveal the gap. **Inference**: such a secret would survive.
- `verify-stack.sh` isolation gate: only tested with a fake `ss`.
- Mirror sync, retention: nothing is proven.

**Tests that cannot fail / are weak (observed):**
- `test_cycle_lifecycle.py::TestCyclusvolgorde::test_scrub_komt_voor_een_nieuwe_runnerstart` asserts on the list returned by `Controller.cycle_stappen()`, a constant that no production code consumes (grep: only tests call it). It documents intent, proves no behaviour.
- `test_alter_probe.py::test_reject` ends with a dead assignment `rc, out, err = (None, None, None)` and never asserts the "geweigerd zoals verwacht" text; it only checks `rc == 0`.
- `test_scan.py` root-conditional (see table above).
- `test_compose_git.py::test_refuses_to_run_as_root` mocks `os.geteuid`; conversely, if the whole suite is run as root, `check()` refuses every other test (environment dependence, **inference** from `compose-git-init` line 47).

**Portability / host dependence:** compose-inpak tests need GNU tar; ACL test needs `setfacl`; `capture-*` scripts use `stat -c`/`sudo -n` (GNU) behind fakes; mirror uses `date -d` (GNU). Bats tests use `$BATS_TEST_DIRNAME`-relative paths for scripts but `test_publish_trust_verdict.bats` calls `scripts/publish-trust-verdict.sh` relative to the CWD (so it must be run from `forgejo-runner/`).

**Real-system contact (observed):**
- `test_compose_runner_exec.bats`: `docker pull -q "$image"` (registry) and `docker run` if the daemon is up.
- `test_integration_pg.py` (gated): `docker rm -f rec-it`, `docker run ... -p 127.0.0.1:55432:5432 postgres:17` with `--pull never`; touches only container `rec-it` and that port; docs claim it does not touch production Postgres. Nothing else in the suites contacts a network; all other Forgejo/GitHub/curl access is faked or `.invalid`.
- `test_secret_scan.bats` and compose-git tests run real `git init` in tmp dirs. The bats tests do **not** isolate global git config, so a global `core.hooksPath` would make `install-git-hooks.sh` (line 14, unscoped `git config --get`) install into that global hooks dir. Not the case on this host (no `core.hooksPath` set, checked).

## 5. `scripts/tests/test_integration_pg.py` - exactly what it needs and touches

Observed lines 1-84: requires `REC_PG_INTEGRATION=1`; `setUpClass` runs `docker rm -f rec-it`, then
`docker run -d --rm --pull never --name rec-it -p 127.0.0.1:55432:5432 -e POSTGRES_PASSWORD=itpw ... postgres:17 -c log_statement=all`
(image must already be present locally), waits with `pg_isready`, creates role `r_it`, and writes two temp env
files. Tests then run `rotate-env-credential alter-role|probe` as subprocesses; `probe` itself runs
`docker run --rm --pull never --network host --env-file ... postgres:17 psql`. It touches only the container `rec-it`,
host port 55432 and temp files, and removes the container in `tearDownClass`. With the env var unset it is skipped. On Docker
Desktop for Mac `--network host` does not reach the host loopback, so the probe would likely not connect there
(**inference**; designed for the Linux host, see the plan's `ssh scrum4me-srv` recipe).

## 6. Documented verify commands

`forgejo-runner/README.md` lines 90-93 ("Verifiëren"):

    bats tests/*.bats
    for f in tests/test_*.py; do python3 "$f"; done
    shellcheck -x scripts/*.sh

- All three are relative to `forgejo-runner/`; the README does not say so.
- The `for` loop's exit status is that of the **last** `python3` invocation only; a failing earlier file is
  invisible to a caller that checks `$?` (shell semantics, no `set -e`/`|| exit`).
- `shellcheck` covers `forgejo-runner/scripts/*.sh` only: not `scripts/lib/*.sh` (sourced, followed by `-x`
  but not checked as targets), not `scripts/forgejo-mirror/*.sh`, not `scripts/docker-rollback-retention/*.sh`
  (outside the bundle). No Python linter or type checker exists.
- No documented command for `scripts/tests/`. The only mention is in the historical plan
  `docs/superpowers/plans/2026-09-25-credential-rotation.md` lines 141-146, 240: `cd scripts && python3 -m unittest discover -s tests -v`
  and, for the integration test, `REC_PG_INTEGRATION=1 python3 -m unittest tests.test_integration_pg -v`.
  Root `README.md` and both agent files do not mention any test command.
- `CLAUDE.md`/`AGENTS.md` claim "this repo contains no code yet" and verification is "to be determined"; both are outdated.

## 7. Reliability mechanisms

| Mechanism | Implemented at | Tested by | Gap |
|---|---|---|---|
| Two-observation confirmation, fence, 60 s deadline watchdog | `forgejo_runner_cycle.py` 64-83, 126-147, 277-379 | `test_cycle_fence/eventloop/readiness` (real machine) | Recovery path needs `nulbewijs_ok=True`, which production never sets (REL-2) |
| Fail-closed classification, default PROTOCOL | `forgejo_runner_cycle.py` 38-61 | `test_cycle_readiness.py` | none noted |
| HTTP timeout on probe | `cycle_adapters.py` 27 (`timeout=self._t`) | `test_readtimeout` (fake opener raising) | real timeout value not exercised |
| Subprocess timeout for short docker calls | `cycle_adapters.py` 62-63 (`_run`) | `TestDindHealthResilience` (fake raising `TimeoutExpired`) | Popen-based `pull`, `scrub`, runner have **no** timeout (REL-1) |
| Crash recovery marker (write-before, clear on rc>=0, keep on signal) | `cycle_runtime.py` 209-230, 299-317; `cycle_adapters.py` 193-204 | `test_marker_*`, `test_stop_killed_op_is_unclean` | marker is tmp+`os.replace` without `fsync` of file or directory (REL-3); no test of a real crash |
| Fail-closed startup on leftover runner | `cycle_runtime.py` 299-317 | `test_leftover_blocks_all_mutation` | reconcile runs once per process; a `_blocked` controller never recovers without restart (by design, undocumented in tests) |
| SIGTERM handling and stop deadline | `cycle_runtime.py` 319-358 | `TestStop` calls `request_stop`/`_stop_result` directly | `run()`, `signal.signal` wiring and the deadline loop never executed in a test; signal can arrive between `write_marker` and `self.op = ...` (**inference**, `_begin_op` 209-212) |
| Single-instance guarantee for the controller | systemd unit only (no flock/pidfile in code; `grep flock` finds only the mirror script) | none | two manual instances would both act on DinD (**inference**); unit contract test checks text only |
| Trust verdict fail-closed publish | `publish-trust-verdict.sh` 21-94 | `.py` and `.bats` publisher tests | tmp file written without fsync and leaked if `os.replace` fails (lines 72-78); cosmetic |
| Verdict age/binding checks | `cycle_runtime.py` 90-109 | `TestVerdict` (9 cases) | none |
| Forgejo API pagination + timeout, no retry | `trust_scope_cli.py` 45, 56-73 | `test_trust_scope.py` (pagination, 4xx/5xx) | loop stops when `len(items) < 50`; a server capped below 50 truncates silently (REL-8); no retry (a unit-level `Restart=on-failure` compensates, timer unit lines) |
| Atomic rewrite (tmp+fsync+`os.replace`+dir fsync), backup, rollback batch | `rotate-env-credential` 133-156, 199-229 | `test_rewrite*.py` | signal between `os.replace` (149) and `done.append` (212) leaves that file rewritten but not restored (REL-7, tiny window); no lock against two concurrent runs |
| Signal to rollback | `rotate-env-credential` 240-261 | `test_sigterm_midbatch_restores` | none |
| Partial-failure order for rotation (files first, then ALTER ROLE) | runbook `docs/runbooks/credential-rotation.md` lines 125-132 | not testable in code (procedure) | no code-level coupling; `alter-role` and `probe` call `subprocess.run` without `timeout` (392-395, 425-428) |
| Verify tar before delete | `compose-inpak` 201-235 | `test_change_between_*`, `test_post_check_*` | all skipped without GNU tar; a failed `tar` leaves a partial `.tar` (no cleanup, but never overwritten next time, so needs manual removal); no timeout on `tar` |
| Per-file re-check before each delete | `compose-inpak` 218-226 | `test_file_that_becomes_registered_during_removal_is_kept` etc. | real `docker compose ls` JSON parsing (61-67) replaced by a lambda in tests |
| Local git init rollback | `compose-git-init` 112-116 | `test_a_failure_during_the_install_leaves_no_half_repo` | none |
| Mirror: single instance | `forgejo-mirror-sync.sh` 114-122 (`flock -n 9`) | none | untested |
| Mirror: per-repo failure isolation | `forgejo-mirror-sync.sh` 61-105 (`if !` counters) | none | `update_state` failure aborts the whole run (REL-4) |
| Mirror: HTTP timeout, retry with backoff | `forgejo-mirror-lib.sh` 39-46 (`-m 30`), 295-303 (3 attempts, 2/4/8 s) | none | `git clone/fetch/push` at 389-405 have no timeout |
| Mirror: state file write | `forgejo-mirror-lib.sh` 411-425 | none | `mktemp` (in `$TMPDIR`) then `mv` to `/var/lib/...`: not atomic across filesystems, and resets mode to `mktemp`'s 0600 (**inference**) |
| Retention: never remove in-use image | `docker-rollback-retention.sh` 33-35, 52 | none | failure of the producer inside `< <(...)` is not propagated (REL-6) |
| Drift/isolation gate | `verify-stack.sh` 24-32 | `test_verify_stack.bats` | fail-open when `ss` is missing (REL-5) |
| Scrub proof-based exit codes | `scrub-dind.sh` 60-87 | `test_scrub_dind.bats` | elapsed time is checked once at the end (84-86); a hung `docker` call is never interrupted |
| Secret scan at commit time | `secret-scan.sh` | `test_secret_scan.bats` | scans the working-tree file, and `--diff-filter=ACM` (line 11) omits renames (TEST-7) |

Transactions towards Postgres: the code never opens a transaction from Python; `alter-role` sends a single
psql stdin script `DO $$ ... $$; ALTER ROLE ...;` with `ON_ERROR_STOP=1` (`rotate-env-credential` 386-395), which
is atomic per statement, and there is no rotation state kept in the database. No test at unit level covers a
failure between the existence check and the ALTER (only the gated integration test covers "role missing").

## 8. Findings

IDs used above: TEST-1..TEST-9, REL-1..REL-8. The full finding records (observation, evidence, impact,
recommendation, verification) are consolidated in [findings.json](findings.json); the table below maps to them via
[README.md](README.md). Summary:

| ID | Sev | Title |
|---|---|---|
| TEST-1 | MEDIUM | compose-inpak suite silently skipped on non-GNU tar |
| TEST-2 | MEDIUM | Mirror sync and rollback-retention scripts have no tests |
| TEST-3 | MEDIUM | Documented verify loop hides failures; scripts/tests has no documented runner |
| TEST-4 | MEDIUM | Runtime-level tests stub the trust gate and never run `Runtime.run()` or real subprocess timeouts |
| TEST-5 | LOW | Fixtures pre-fill the proven fact (redact_inspect, stateless scrub fake) |
| TEST-6 | LOW | Most config-file contract tests prove text, not runtime behaviour (three compose tests render via `docker compose config`) |
| TEST-7 | MEDIUM | secret-scan.sh skips renamed files and reads working tree instead of the index, untested |
| TEST-8 | LOW | A few tests cannot fail or silently skip halves |
| TEST-9 | LOW | One bats test hits the real Docker daemon and registry when docker is up |
| REL-1 | MEDIUM | Popen-based pull/scrub/runner have no timeout; hung docker stalls the controller |
| REL-2 | MEDIUM | Fence recovery, maintenance record and job_accepted are unwired in production |
| REL-3 | LOW | Crash marker is not fsynced |
| REL-4 | MEDIUM | Mirror: a state-file failure aborts remaining repos |
| REL-5 | LOW | verify-stack isolation check fails open without `ss` |
| REL-6 | LOW | Retention safety set built inside process substitution, failure not propagated |
| REL-7 | LOW | rotate-env-credential: tiny non-atomic window, no lock, no subprocess timeouts |
| REL-8 | LOW | Trust scanner pagination assumes server page size 50 |
