# Executive summary

Audit of `scrum4me-server` at commit `4d9f873` (`main` on 2026-09-30). Read-only: nothing outside
`docs/repo-audit/` was changed, no host was contacted, no container was started, no credential was used.

## 1. What is this system?

Not an application. It is the operations repository for the host `scrum4me-server` and the canonical
source of a **Forgejo Actions runner pool** that runs on two machines (`scrum4me-server` and `max2`).
It contains about 4 700 lines of Python (standard library only) and Bash, about 5 200 lines of tests,
and a large body of design documents, review reports and captured evidence.

## 2. How is it structured?

- `forgejo-runner/` — the bundle copied by hand to `/opt/forgejo-runner/` on both hosts: a Compose
  stack (privileged Docker-in-Docker plus a one-job runner), a Python **cycle controller** that starts
  exactly one runner per job and scrubs DinD in between, a **trust scanner** that checks Forgejo
  repositories against an allow-list and publishes a verdict the controller gates on, and deploy and
  verification scripts.
- `scripts/` — six stand-alone host tools: credential rotation, compose-directory hygiene (three
  tools), the nightly Forgejo→GitHub mirror, and Docker rollback-tag retention.
- `docs/` — the approved design, implementation plans, review rounds, runbooks and evidence.

There is no package manifest, no build, no CI and no deployment automation; rollout is manual by design.
Details: [repository-map.md](repository-map.md), [architecture.md](architecture.md).

## 3. What was actually inspected?

All 167 tracked files were in scope. Every source file, test file, unit file and configuration file
was read in full by at least one of four specialist reviewers (architecture, code quality, testing and
reliability, security and dependencies). Of the documentation, the design documents were read where a
claim had to be checked; the 59 files under `docs/forgejo-runner-pool/` were not all read line by
line. Git history (all branches) and the seven tracked `.pyc` files were scanned for secrets.

The lead re-read the code behind every HIGH and most MEDIUM findings and reproduced seven of them.

## 4. What validation was executed?

On the audit workstation (macOS), see [verification.md](verification.md):

| Check | Result |
|---|---|
| Bats suite (`forgejo-runner/tests`, 137 tests) | pass, 1 skipped |
| Python unittest, bundle (238 tests) | pass |
| Python unittest, `scripts/tests` (95 tests) | 78 pass, **17 skipped** |
| shellcheck, bundle scripts | clean |
| shellcheck, mirror and retention scripts | 3 warnings |
| ruff default rules, production Python | clean |
| ruff default rules, test code | 82 findings, mostly statement-packing style |
| Syntax checks, all shell and Python files | pass |

No executed test failed.

In addition the lead reproduced findings with the repository's own fake-adapter harness and with a
throw-away git repository (dummy values only): five controller behaviours, three secret-scan
bypasses and the no-op configuration check.

## 5. What could not be verified?

- **Anything on the target platform.** All runs were on macOS; the hosts are Ubuntu. The 18 skipped
  tests are exactly the ones that need GNU tar, Linux ACLs, a Postgres container or the real runner
  image. `compose-inpak` had **zero** executed tests.
- **Most of the live state.** After the first report the owner answered three questions and asked the
  lead to measure two more (see "Measured on the hosts" below). Still unmeasured: who can reach the
  DinD bridge, how the systemd units are installed, and runtime behaviour against real Docker.
- **Exposure of the pinned images.** No registry or advisory database was consulted.
- **Type correctness.** The repository has no type checker.

## 6. The most consequential findings

33 findings: **0 critical, 1 high, 19 medium, 13 low.** Records are in [findings.json](findings.json).

The single HIGH is not a defect: **every CI job controls a privileged Docker-in-Docker on the host
that also runs Forgejo and Postgres (AUDIT-001).** The design accepts this explicitly for trusted
workflows and makes the trust gate the control. What matters is how much rests on that one control,
and the audit found it thinner than the design text suggests:

- **The gate only blocks the next runner start.** A runner that is already waiting keeps accepting
  one more job after the gate turns red (AUDIT-003, reproduced). The owner has accepted this window.
- **The scan can under-report** in narrower ways than first thought — substring matching on the
  label, deploy keys not counted; the pagination concern is latent because the instance's page cap
  equals the scanner's page size (AUDIT-012, downgraded to LOW).
- **The scrub between jobs runs inside the container the previous job controlled**, and reports
  "proven clean" if the daemon does not answer (AUDIT-009, AUDIT-008).
- **The DinD API lost TLS** relative to the legacy stack with no recorded decision (AUDIT-010).
- **The token on the CI host can write to every repository.** Measured on max2: the trust-scan token
  is a site-admin token with `write:repository` and `write:organization`, although the scan only
  reads (AUDIT-013). A compromise of max2 would therefore reach the forge itself.

The second cluster is operational: **the controller can stop offering runners while looking
healthy.** An operation without a deadline (AUDIT-004), a blocked latch that never clears
(AUDIT-005), an unguarded exception (AUDIT-020) and a silent health gate (AUDIT-021) all end in
"unit active, DinD healthy, no runner, nothing in the journal". The first two were reproduced. The
repository's own history records two outages of exactly this shape for the trust gate.

Third: **the guard behind "no secrets in Git" has real bypasses** (AUDIT-002, reproduced): a renamed
file, an old bash, or a line that also contains a UUID gets through. History is clean today.

Fourth: **the oldest script does not follow the newest script's standard.** The mirror passes tokens
in URLs and argv and may persist one in a clone's configuration, outside the rotation runbook's
inventory (AUDIT-011), and carries several logic defects (AUDIT-017) with no tests (AUDIT-016).

### Combined effects

| Combination | Why it is worse together |
|---|---|
| Accepted privileged-DinD risk + gate gaps (003, 012) + runtime tests that stub the gate (025) | The one control in front of the accepted risk is both leaky and the least-tested part of the controller. |
| Silent stall modes (004, 005, 020, 021) + no monitoring path in the repo + stability definition of seven clean days | The criterion for "stable pool" depends on noticing states that currently leave no trace. |
| Weak secret scan (002) + no CI or server-side hook (014) + documentation that shows tokens inline (013) + capture tools that write raw API output (030) | Each layer assumes another one catches the mistake. |
| Destructive scripts without tests (016) + logic defects (017, 018) + units outside the repository (023) | The scripts most likely to change production data are the least controlled. |
| Stale top-level documents (022) + manual, undocumented verification (014) + silent skips (015) | An agent or person following the instructions has no reason to run the tests, and a local green run over-states what was proven. |
| Two approved designs that disagree (006, 007) + deferred paths shipped as code (028) | Tests pass for protections production never exercises. |

## 7. What appears well protected?

- **The controller state machine.** 99 tests drive the real `Controller` with a fake clock and no
  mocks; the decision logic is the best-covered part of the repository.
- **The trust scanner's error handling.** Nearly every error path is fail-closed, with the reasoning
  written next to the code, and 73 tests. The publisher invalidates an old green verdict on any failure.
- **`rotate-env-credential`.** Its claim that a secret never reaches argv, logs or output holds in
  code; rewrites are atomic and roll back on interruption; 51 executed tests.
- **`compose-git-init` and its hook.** Tested against real git, including "staged content is judged,
  not the working file" — the property the repository's own scanner lacks.
- **Image pinning.** Runner, DinD and job image are pinned by digest, enforced in code and tests.
- **Deploy gates.** `preflight.sh`, `render-config.sh`, `bundle-hash.sh` and `verify-stack.sh` each
  have a bats suite with fakes; all bundle shell scripts are shellcheck-clean.
- **No secret in the tree or in history**, and captured evidence is correctly redacted.

## 8. Where are the largest evidence gaps?

1. The layer between the state machine and the real world (`Runtime.run`, adapters against real
   Docker, signal handling) — tested for argument lists only.
2. The mirror and retention scripts — no tests at all.
3. `compose-inpak` and the end-to-end rotation — tested, but only on a platform the audit did not have.
4. Systemd units — text matches only, no `systemd-analyze`.
5. Everything on the hosts — this audit read code and evidence files, not machines.

## 9. What should be considered for the backlog?

Eighteen candidates in [pbi-candidates.md](pbi-candidates.md), without priority or estimate:

- **Security (4):** secret-scan bypasses; mirror credentials; trust-scan under-detection; trust-scan
  token scope.
- **Bugs (4):** controller stall visibility; scrub proof on a silent daemon; mirror and retention
  logic; the no-op configuration check.
- **Testing (3):** one verification entry point; mirror and retention tests; runtime scenario tests.
- **Research (2):** DinD boundary decisions; image refresh cadence and the open back-port question.
- **Technical improvement (3):** quarantine and fence semantics; drift-gate coverage;
  `rotate-env-credential` residuals.
- **Documentation (2):** recording the accepted one-job window in the design; top-level documents
  and repository hygiene.

Several touch the approved pool design and therefore need a delta review with GO under the
repository's own rules before the design changes.

## Answered by the owner

Answered by the owner on 2026-09-30 (stated, not measured by the audit):

| Question | Answer | Effect on the audit |
|---|---|---|
| Which Forgejo version runs today? | **15.0.9** | Confirms that `CLAUDE.md`, `AGENTS.md` and the research document on `main` (15.0.2) are stale; strengthens AUDIT-022. The Forgejo security-release gap in dependencies.md DEP-6 is closed on the host. |
| Were `JWT_SECRET` and `LFS_JWT_SECRET` rotated after the 2026-09-09 transcript leak? | **Yes** | No open action; the leak is closed. |
| Does a mirror clone exist under `/srv/scrum4me/repos/mirrors/`? | **Directory exists, empty** | No token is persisted today; the stored-token part of AUDIT-011 is latent and occurs on the first tag fallback. The argv exposure is unchanged. |

| Is the one-job window after a red gate acceptable? | **Yes, acceptable** | AUDIT-003 becomes an accepted risk; PBI-03 is reduced to recording the decision in the design. |

## Measured on the hosts

Measured by the lead on 2026-09-30, read-only (API GETs, `stat`/`find` over SSH, one `SELECT` of token names and scopes;
no token value was displayed or stored):

| Question | Measurement | Effect on the audit |
|---|---|---|
| Maximum API page size | `max_response_items` 50, `default_paging_num` 30; 22 repositories, all owned by the user `janpeter`; teams endpoint answers 405 on user repositories | The scanner's page size of 50 equals the cap, so pagination is complete today. AUDIT-012 downgraded to LOW. |
| Tag counts and repository names (for the mirror) | largest tag count 10; no name outside `[A-Za-z0-9_-]` | Two items of AUDIT-017 are latent; AUDIT-017 downgraded to LOW. |
| Scopes of the trust-scan token | On max2: the site administrator's token `FREX_RUNNER` with `read:admin` and `write:repository`, `write:organization`, `write:package`, `write:issue`, `write:notification`, `write:misc` | AUDIT-013 confirmed, confidence raised to HIGH. |
| Owner of `/opt/forgejo-runner/` | max2: directory, scripts and bundle files `janpeter:janpeter`; `credentials/` `root:root 700`; verdict `root:root 644` inside the janpeter-owned directory. scrum4me-server: directory absent; the legacy runner and DinD run from the tags `runner:12` and `docker:dind` | New finding AUDIT-033 (LOW). The bundle is only deployed on max2; step G is still open. |
| Forgejo image on scrum4me-server | `codeberg.org/forgejo/forgejo:15.0.9` | Confirms the owner's answer. |

## Open questions for the owner

1. Does `docker compose run --rm` forward SIGTERM to the runner container? The stop protocol depends
   on it and it could not be checked without Docker.
2. Is `docker-rollback-retention.sh` scheduled anywhere, and is the mirror unit on the host the one
   the README describes?
