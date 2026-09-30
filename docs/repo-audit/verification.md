# Executable verification

Executed by the lead auditor on 2026-09-30 against commit `4d9f873`, on the audit workstation
(`mac`, macOS / Darwin 27, arm64) — **not** on the target hosts (`scrum4me-server`, `max2`, Ubuntu).
Every result below is therefore a statement about the code on macOS with BSD userland; see
"Environment limits".

## How the commands were discovered

The repository has no package manifest, Makefile, task runner or CI workflow. The only documented
validation commands are in `forgejo-runner/README.md` ("Verifiëren"):

    bats tests/*.bats
    for f in tests/test_*.py; do python3 "$f"; done
    shellcheck -x scripts/*.sh

`scripts/tests/` has no documented invocation; the same per-file `python3 <file>` pattern was used
because every module ends in `unittest.main()`.

There is no lint configuration, no type checker configuration and no build step. `ruff` (present on
the workstation) was run with default rules as an extra, undocumented check.

## Tool versions

| Tool | Version |
|---|---|
| python3 | 3.14.6 |
| bats | 1.14.0 |
| shellcheck | 0.11.0 |
| ruff | 0.15.13 |
| bash | 5.3.9 |
| tar | bsdtar 3.5.3 (no GNU tar) |
| docker | daemon reachable, 29.7.2 |
| `timeout` / `gtimeout` | not installed |
| mypy, shfmt, yamllint, systemd-analyze | not installed |

All Python runs used `PYTHONDONTWRITEBYTECODE=1` so that the tracked `.pyc` files were not rewritten.
`git status` after all runs showed only `docs/repo-audit/` as untracked; nothing else changed.

## Results

| # | Command (cwd) | Result | Notes |
|---|---|---|---|
| 1 | `bats tests/*.bats` (`forgejo-runner/`) | **PASS** — 137 tests, 136 ok, 1 skipped, exit 0, ≈21 s | Skipped: test 40 in `test_compose_runner_exec.bats` ("het gerenderde runnercommando start in de gepinde image EN laadt de config") — no `timeout(1)`/`gtimeout` on this machine. This is the only test that runs the real runner image. |
| 2 | `for f in tests/test_*.py; do python3 "$f"; done` (`forgejo-runner/`) | **PASS** — 10 modules, 238 tests, 0 failures, 0 skipped | Per module: compute_caps 7, cycle_eventloop 18, cycle_fence 24, cycle_lifecycle 21, cycle_maintenance 16, cycle_readiness 20, cycle_runtime 49, pick_heaviest_workflow 4, publish_trust_verdict 6 (≈5 s), trust_scope 73 |
| 3 | `shellcheck -x scripts/*.sh` (`forgejo-runner/`) | **PASS** — no output, exit 0 | The documented glob does not include `scripts/lib/readonly.sh`; run separately: also clean |
| 4 | `for f in test_*.py; do python3 "$f"; done` (`scripts/tests/`) | **PASS with 17 of 95 tests skipped** | See breakdown below |
| 5 | `shellcheck -x *.sh` (`scripts/forgejo-mirror/`) | **3 warnings**, exit 1 | `forgejo-mirror-lib.sh:91` SC2155 (declare-and-assign masks return value); `forgejo-mirror-sync.sh:34` SC1090 ×2 (non-constant `source` of the env files). Repository-related, low impact; not covered by any documented check |
| 6 | `shellcheck docker-rollback-retention/*.sh` (`scripts/`) | **PASS** | |
| 7 | `bash -n` on all 20 tracked `*.sh` | **PASS** | syntax only |
| 8 | `ast.parse` on all tracked `*.py` and the 4 extension-less Python scripts | **PASS** | syntax only, no bytecode written |
| 9 | `ruff check --no-cache` on all production Python | **PASS** — "All checks passed!" | default rule set (E4, E7, E9, F) |
| 10 | `ruff check --no-cache` on `forgejo-runner/tests scripts/tests` | **82 findings** | 60× E702, 12× E701, 1× E703, 2× E401 (statement-packing style), 6× F401 unused import, 1× F841 unused variable. Test code only; stylistic except the unused names |

### Breakdown of `scripts/tests/`

| Module | Tests | Executed | Skipped | Skip reason |
|---|---|---|---|---|
| `test_alter_probe.py` | 13 | 13 | 0 | |
| `test_compose_git.py` | 27 | 27 | 0 | (≈7 s, uses real `git` in temp dirs) |
| `test_compose_inpak.py` | 14 | **0** | **14** | "vereist GNU tar; draai deze tests op de host" |
| `test_integration_pg.py` | 2 | **0** | **2** | `REC_PG_INTEGRATION=1` not set |
| `test_rewrite.py` | 17 | 16 | 1 | `test_posix_acl_preserved`: needs Linux `setfacl` |
| `test_rewrite_key.py` | 15 | 15 | 0 | |
| `test_scan.py` | 7 | 7 | 0 | |

## Checks that could not be executed

| Check | Why | Consequence |
|---|---|---|
| `test_compose_inpak.py` (all 14 tests) | requires GNU tar; macOS has bsdtar | **No behaviour of `scripts/compose-inpak` was verified in this audit.** The suite exits 0 and prints `OK (skipped=14)`, which is easy to misread as a pass |
| `test_integration_pg.py` | needs `REC_PG_INTEGRATION=1`, a Docker daemon and a locally present `postgres:17` image (`--pull never`); it starts a container on `127.0.0.1:55432`. Deliberately not run: the audit must not create containers or pull images | The end-to-end claim "new password works, old is rejected, secret absent from the Postgres log" is unverified here |
| `test_compose_runner_exec.bats` test 40 | no `timeout`/`gtimeout`; would also pull and run the pinned runner image | The claim that the pinned runner image accepts the rendered command line and config is unverified here |
| `test_rewrite.py::test_posix_acl_preserved` | Linux-only | ACL preservation on `.env` rewrite unverified here |
| Type checking | no type checker configured in the repo; `mypy` not installed | No static type evidence exists |
| systemd unit validation (`systemd-analyze verify`) | not available on macOS; not part of the repo's checks either | Unit files are only checked by text-matching bats tests |
| `docker compose config` against the real `.env` | the bats contract tests do run `docker compose … config` with inline values (passed); the host `.env` is not in the repo | |
| Any test on the target platform | audit ran on macOS | GNU-vs-BSD differences (`stat`, `date`, `tar`, `sha256sum`) are not exercised the way the hosts exercise them |
| Live behaviour (controller with a real job, trust scan against Forgejo, mirror run, rotation against Postgres) | requires the production hosts, credentials and external systems; out of scope for a read-only audit | All runtime claims in the audit rest on code reading plus the fake-backed tests |
| CI | none exists | Nothing enforces any of the above on push or merge |

## Environment limits on interpretation

- A green run on macOS does not prove a green run on Ubuntu, and vice versa. The 14 + 2 + 1 + 1
  skipped tests are exactly the ones that need the target environment.
- No failure in this table was repaired. The shellcheck warnings and ruff findings are recorded as
  observed.

## Lead reproductions

Performed to confirm findings before accepting them. None touched a host, a container or a
credential; temporary files lived outside the repository and were removed.

### Controller behaviour (fake adapters)

Method: a throw-away script imported `forgejo-runner/tests/_harness.py`, called `build_runtime()` and
drove `Runtime.tick()` on the fake clock in one-second steps. Where needed the fixed probe and the
stubbed trust result of the harness were replaced by scripted ones. These results describe the
controller logic with fakes, not behaviour against Docker.

| Scenario | Observed | Finding |
|---|---|---|
| Runner waiting, then trust gate forced red for 600 s | `gates_groen=False`; child still running; signals sent to child: none; state `WAITING` | AUDIT-003 |
| First probe fails, all later probes succeed | `fence_set` at t=0, state `DRAINING`, deadline alarm "fence-deadline bereikt" at t=60, runner starts at t=120. Control run with all probes good: runner starts at t=30 | AUDIT-007 |
| Runner exits 1 every time, 300 s | 5 runner starts; states seen `QUARANTINED`, `SCRUBBING`, `SOURCE_WAIT`, `WAITING` | AUDIT-006 |
| One pre-pull returns 1, then an hour of healthy conditions | `_blocked=True`; 1 pull attempt in total; 0 runner starts | AUDIT-005 |
| Scrub whose `poll()` never returns, 7200 s | operation still `scrub`; 0 runner starts; 0 alarm events | AUDIT-004 |

### Secret scan (throw-away git repository, dummy values of repeated characters)

| Case | Exit code | Finding |
|---|---|---|
| File renamed with `git mv`, token-like line added, staged (`R096`), hook run in staged mode | 0 (not scanned) | AUDIT-002 |
| Same file passed explicitly | 70 (blocked) | control |
| Staged mode under `/bin/bash` 3.2.57 | 0, with `mapfile: command not found` | AUDIT-002 |
| JSON line with a UUID and a 40-character token value | 0 | AUDIT-002 |
| `-----BEGIN PRIVATE KEY-----` (PKCS#8 header) | 0 | AUDIT-002 |
| Single-quoted 40-character value after `token:` | 0 | AUDIT-002 |
| `API_KEY=` with a 40-character value | 0 | AUDIT-002 |
| Files named `prod.env`, `.env.local`, `x.token` staged | 0 | AUDIT-002 |
| `docs/forgejo-runner-pool/implementatieplan-stap-a-b.md` passed explicitly | 70 (a quoted fixture trips the private-key rule) | noted in security.md SEC-9 |

One attempted case (secret staged, then removed from the working file) was set up incorrectly and is
not counted; that the scan reads the working file follows from `secret-scan.sh:17,28,43`.

### Configuration check

| Command | Exit code | Finding |
|---|---|---|
| `python3 forgejo-runner/scripts/cycle_runtime.py --config /nonexistent/controller.toml --check` | 0, no output | AUDIT-019 |
| `python3 forgejo-runner/scripts/forgejo_runner_cycle.py --config /nonexistent/controller.toml --check` | 2, `config-fout: … No such file or directory` | control |

## Live measurements (after the first report, at the owner's request)

Read-only, 2026-09-30. API calls used the operator's own token from a curl config file or stdin, never
argv. The trust-scan token on max2 was only used for GET requests inside a `sudo sh -c` on the host;
its database record was found by the last eight characters, compared on the fly and never displayed.
The database query selected token names and scopes only.

| What | How | Result |
|---|---|---|
| API paging limits | `GET /api/v1/settings/api` | `max_response_items` 50, `default_paging_num` 30 |
| Repository count visible to an admin token | `GET /repos/search?limit=100`, header `X-Total-Count` | 22, all owned by user `janpeter` |
| Teams endpoint on a user-owned repository | `GET /repos/janpeter/scrum4me-server/teams` | 405 |
| Tags per repository | `GET /repos/{r}/tags?limit=50` per repository | maximum 10 |
| Repository names outside `[A-Za-z0-9_-]` | from the repository list | none |
| Trust-scan token on max2: accessible endpoints | GETs with the token | `/user` 403 (missing `read:user`); `/admin/users`, `/repos/search`, collaborators, branch protections 200 |
| Trust-scan token on max2: record | `access_token` table in the `forgejo` database, name and scope columns | `FREX_RUNNER` of the site administrator; `read:activitypub, read:admin, write:misc, write:notification, write:organization, write:package, write:issue, write:repository` |
| `/opt/forgejo-runner` ownership | `stat` and `find` over SSH | max2: directory, `scripts/` and bundle files `janpeter:janpeter`; `credentials/` `root:root 700`; `trust-verdict.json` and `controller.toml` `root:root 644`. scrum4me-server: directory absent |
| Units on max2 | `systemctl is-active` | `forgejo-runner-cycle.service` active, `forgejo-runner-trust.timer` active; verdict `ok: true` |
| Containers on scrum4me-server | `docker ps` | Forgejo `codeberg.org/forgejo/forgejo:15.0.9`; legacy runner `code.forgejo.org/forgejo/runner:12` and `docker:dind` (tags, not digests) |
