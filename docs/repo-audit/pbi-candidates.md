# PBI candidates

Eighteen candidates, derived from 26 of the 33 findings in [findings.json](findings.json). Six
findings produce no candidate: AUDIT-001 (accepted risk), AUDIT-027, -028, -032 (debt without a
concrete trigger, see [technical-debt.md](technical-debt.md)), AUDIT-030, -031 and -033 (low-impact
hardening and defence-in-depth; AUDIT-033 fits naturally into step G's normalisation).

No story points and no priority are given; the order below is by topic, not by importance.
Several candidates touch the approved pool design. Per the repository's hard-stop rules, a post-GO
change to that design needs a delta review with GO before its status changes; that is listed as a
dependency where it applies.

---

## PBI-01 — Close the bypasses in the pre-commit secret scan

- **Source finding:** AUDIT-002
- **Type:** SECURITY
- **Problem:** `secret-scan.sh` passes renamed-and-edited files, exits 0 without scanning under bash 3.2, drops any line that also contains a UUID or `sha256:`, and misses PKCS#8 keys, single-quoted values and names such as `API_KEY`, `.env.local`, `*.token`. It reads the working tree, not the staged content.
- **Desired outcome:** the hook judges what is actually being committed and fails closed when it cannot.
- **Why it matters:** it is the only automated guard behind the "no secrets in Git" hard-stop, and the repository records an earlier token leak (ISS-8) as its reason for existing.
- **Suggested acceptance criteria:**
  - A staged rename with an added token line is blocked.
  - Run with `/bin/bash` 3.2, the hook either scans or exits non-zero.
  - A JSON line carrying both a UUID and a token value is blocked.
  - PKCS#8 private-key headers, single-quoted values and `API_KEY=`-style names are blocked.
  - A secret staged with `git add -p` while the working file is clean is blocked.
  - The file-name rule matches the list in `scripts/compose-git-pre-commit`.
  - Each case is a test in `forgejo-runner/tests/test_secret_scan.bats`.
- **Dependencies:** none. Note that `docs/forgejo-runner-pool/implementatieplan-stap-a-b.md` currently trips the private-key rule and will need a decision.
- **Suggested verification:** the new bats cases; repeat the lead's throw-away-repository reproduction and see exit 70.

## PBI-02 — Make controller stalls visible and recoverable

- **Source finding:** AUDIT-004, AUDIT-005, AUDIT-020, AUDIT-021
- **Type:** BUG
- **Problem:** the controller can stop offering runners while the unit stays `active` and the journal stays quiet: an operation without a deadline, a blocked latch that never clears, an unexpected exception followed by the latch, and a red DinD-health gate that logs nothing.
- **Desired outcome:** every state in which no runner is offered has a log line with a reason, a bounded duration or an explicit "needs operator" marker, and a way for monitoring to see it.
- **Why it matters:** the pool's stability definition (design §9) depends on noticing these states; the same failure shape already caused two outages for the trust gate.
- **Suggested acceptance criteria:**
  - A scrub or pre-pull that does not finish within its budget is terminated, logged and leaves the controller in a defined state.
  - A single failed pre-pull is retried with backoff; the latch remains only for causes that need a person, and the cause is logged on every retry interval.
  - An exception in probe, verdict read or runner start is logged and classified instead of ending the process.
  - Every gate transition (trust, DinD health, blocked) produces one journal line.
- **Dependencies:** the five-minute scrub rule already exists in design §7.9; changes to state semantics need a delta review.
- **Suggested verification:** harness scenarios equivalent to the lead's reproductions D and E (one failed pull; a scrub that never returns) turn from "stalled forever" into a logged, bounded outcome.

## PBI-03 — Record the accepted one-job window in the design

- **Source finding:** AUDIT-003
- **Type:** DOCUMENTATION
- **Problem:** a runner that is already waiting accepts one more job after the trust verdict turns red, expires or loses its binding, or after a fence is set. The owner accepted this window on 2026-09-30, but `migratieontwerp.md:115` still says a WAITING runner is stopped gracefully.
- **Desired outcome:** the design states the accepted window, its bound (one job per host) and its rationale, next to the other thin-slice limitations.
- **Why it matters:** the design is the reference for reviews; a protection described there but not implemented misleads the next reviewer.
- **Suggested acceptance criteria:**
  - `migratieontwerp.md` and `controller-entrypoint-ontwerp.md` describe the same behaviour.
  - The acceptance names the owner and the date.
  - A test documents the current behaviour (gate turns red while a child waits; no stop is sent), so a later change is deliberate.
- **Dependencies:** delta review with GO, because it changes an approved design.
- **Suggested verification:** grep of both design documents; the new test.

## PBI-04 — Reconcile quarantine and fence-recovery semantics between the two designs

- **Source finding:** AUDIT-006, AUDIT-007
- **Type:** TECHNICAL_IMPROVEMENT
- **Problem:** quarantine after a runner failure re-opens within about a minute (a start-fail loop), and one failed readiness probe produces an alarm and a 90-second delay because fence recovery depends on a flag nothing sets.
- **Desired outcome:** one authoritative description of quarantine and fence recovery for the thin-slice controller, with code and tests matching it.
- **Why it matters:** quarantine cannot currently be relied on as a stop, and the alarm channel carries noise on every transient blip.
- **Suggested acceptance criteria:**
  - The two design documents no longer contradict each other on re-opening after a runner failure.
  - A runner that fails repeatedly does not restart more often than a stated backoff allows.
  - A single failed probe followed by confirmed good probes does not raise a deadline alarm.
- **Dependencies:** delta review.
- **Suggested verification:** harness scenarios equivalent to the lead's reproductions A and C.

## PBI-05 — Make the scrub proof require a live daemon

- **Source finding:** AUDIT-008
- **Type:** BUG
- **Problem:** `scrub-dind.sh` reports all five proofs OK when the DinD daemon does not answer, because every proof tests for empty output.
- **Desired outcome:** "proven clean" is only reported after a positive answer from the daemon.
- **Why it matters:** `clean_proven` is the precondition for offering the next job.
- **Suggested acceptance criteria:** with a docker stub that fails every call, the script exits non-zero; existing scrub tests still pass.
- **Dependencies:** none.
- **Suggested verification:** a new case in `forgejo-runner/tests/test_scrub_dind.bats`.

## PBI-06 — Record the DinD boundary decisions: API transport and what the scrub guarantees

- **Source finding:** AUDIT-009, AUDIT-010
- **Type:** RESEARCH
- **Problem:** the DinD API went from TLS with client certificates to plain TCP without a recorded decision, and the between-job scrub runs inside a container the previous job could modify while the design presents it as proof of "no state between jobs".
- **Desired outcome:** a measured answer to "who on each host can reach the DinD API" and an explicit statement of whether the scrub is a security boundary or hygiene.
- **Why it matters:** both shape how much the accepted risk of design §7.6 actually covers.
- **Suggested acceptance criteria:**
  - Reachability of the bridge address from an unprivileged host account is measured on both hosts and recorded as evidence.
  - The design states the transport decision and its rationale.
  - The design states what the scrub does and does not guarantee against a hostile job.
- **Dependencies:** read-only access to both hosts; delta review for the design text.
- **Suggested verification:** the evidence files and the updated design sections.

## PBI-07 — Keep mirror credentials out of URLs, clone configuration and argv

- **Source finding:** AUDIT-011
- **Type:** SECURITY
- **Problem:** the tag fallback clones and pushes with tokens embedded in URLs; the clone stores the URL; tokens also travel through `curl -H`, `jq --arg` and `curl --data`. The rotation runbook does not list the clone directory.
- **Desired outcome:** no token in any process argument or persisted git configuration, and a rotation card that covers every place the token is used.
- **Why it matters:** a write-scoped Forgejo token may be stored where the rotation procedure does not look, and would keep being used after a rotation.
- **Suggested acceptance criteria:**
  - During a run, no process argument contains a token.
  - An existing clone's `remote.origin.url` carries no user information.
  - The rotation runbook card for this token lists every storage location.
  - Existing clones on the host are checked once. (Owner, 2026-09-30: the clone directory is currently empty.)
- **Dependencies:** ISS-41 / ISS-43 (argv hygiene) named in the mirror README; PBI-11 for a test harness.
- **Suggested verification:** a bats test with a fake `git` and `curl` that records argv; on the host, inspect the clone configuration without printing the value.

## PBI-08 — Reduce under-detection in the trust scan

- **Source finding:** AUDIT-012
- **Type:** SECURITY
- **Problem:** the scan can report green while it has not seen everything: pagination assumes a page size of 50 and never checks a total, the teams list is not paginated, the shared label is detected by substring, and deploy keys are not counted as writers.
- **Desired outcome:** a truncated or partial inventory is detected and fails closed; the known blind spots are either closed or written next to the existing acknowledgement text.
- **Why it matters:** the comment in the code itself says a truncated writer set makes the gate "silently green".
- **Suggested acceptance criteria:**
  - A server page size below 50 does not truncate the result (test with a fake client). Measured 2026-09-30: the instance cap is 50, so this guards against a future configuration change.
  - A risky trigger whose `runs-on` cannot be resolved to a label is not downgraded to soft unless acknowledged.
  - Write-enabled deploy keys are either inventoried or listed as an explicit non-goal in design §7.7.
- **Dependencies:** delta review for §7.7 text. (Page-size cap measured on 2026-09-30: 50.)
- **Suggested verification:** new cases in `forgejo-runner/tests/test_trust_scope.py`.

## PBI-09 — Limit the trust-scan token and remove inline-token examples

- **Source finding:** AUDIT-013
- **Type:** SECURITY
- **Problem:** the scan token must belong to an account with admin rights on every Actions-enabled repository and lives on both CI hosts; the README does not ask for read-only scopes; two documents show `FORGEJO_TOKEN=<value> command`.
- **Desired outcome:** the token stored on the runner hosts can read but not write, and no document shows a token on a command line.
- **Why it matters:** a compromise of a runner host would otherwise yield write access to every repository that can run jobs, including the one holding the allow-list.
- **Suggested acceptance criteria:**
  - The README states the required scopes.
  - A write call with the deployed token is refused (checked once per host).
  - No tracked document contains the `VAR=value command` form for a secret.
- **Dependencies:** whether a read-scoped admin token can read branch protections must be confirmed. Measured 2026-09-30: the current token is the site administrator's `FREX_RUNNER` with write scopes; before rotating it, find what else uses it.
- **Suggested verification:** grep of tracked documents; a recorded probe on each host.

## PBI-10 — One verification entry point that reports failures and skips

- **Source finding:** AUDIT-014, AUDIT-015
- **Type:** TESTING
- **Problem:** verification is three hand-run commands in one README; the Python loop loses all but the last exit status; `scripts/tests` has no documented command; 18 tests skip off Linux while the suites print OK.
- **Desired outcome:** one committed command that runs every suite and linter in the repository, fails if any part fails, and prints which tests were skipped and why.
- **Why it matters:** the bundle is rolled out by hand to two production hosts; today nothing ensures the tests ran, or ran where they mean something.
- **Suggested acceptance criteria:**
  - A deliberately failing test in any suite makes the command exit non-zero.
  - The summary lists skipped tests by name.
  - Mirror and retention scripts are included in the shell lint.
  - `CLAUDE.md` / `AGENTS.md` name the command under "Verify".
  - It is decided and recorded where the Linux-only tests must run before a rollout.
- **Dependencies:** a decision on whether a read-only Forgejo Actions job may run it (the hard-stop forbids deploying through Actions, not checking).
- **Suggested verification:** run on the workstation and on a host; compare skip lists.

## PBI-11 — Tests for the mirror and retention scripts

- **Source finding:** AUDIT-016
- **Type:** TESTING
- **Problem:** 616 lines that force-push tags, change push-mirror configuration and remove image tags have no tests.
- **Desired outcome:** the main paths and the safety guards are covered with fakes in the style already used for the bundle scripts.
- **Why it matters:** both scripts act on production data and were changed on the day of this audit.
- **Suggested acceptance criteria:** tests cover per-repository failure isolation, `DRY_RUN`, the default-branch check, keep-N ordering, the in-use guard and the refusal path; breaking any of these in the script makes a test fail.
- **Dependencies:** none; enables PBI-07 and PBI-12.
- **Suggested verification:** mutation by hand of each guarded line.

## PBI-12 — Fix the mirror and retention logic defects

- **Source finding:** AUDIT-017, AUDIT-018
- **Type:** BUG
- **Problem:** a state-file error aborts the whole mirror run; any non-200 answer counts as "no workflows"; tag comparison reads one page; a repository name with a dot breaks the token lookup; the retention script's in-use set can be silently empty and the run can abort before its summary.
- **Desired outcome:** each failure is confined to the repository or image it concerns and is reported.
- **Why it matters:** silent partial mirroring and a weakened retention guard.
- **Suggested acceptance criteria:**
  - A corrupt state file does not stop the remaining repositories.
  - Only 404 means "no workflows"; other statuses are an error for that repository.
  - Tag lists are compared in full (optional; latent today).
  - If container enumeration fails, `--apply` refuses to remove anything.
- **Dependencies:** PBI-11. Measured 2026-09-30: no repository has more than 10 tags and none has a non-identifier name, so the tag-pagination and token-lookup items can be dropped or kept as guards.
- **Suggested verification:** the tests from PBI-11.

## PBI-13 — Make the documented controller configuration check real

- **Source finding:** AUDIT-019
- **Type:** BUG
- **Problem:** the documented command `cycle_runtime.py --config … --check` exits 0 for any input, including a missing file; the real entry point checks key presence only.
- **Desired outcome:** the documented command validates the configuration, including that the configured files exist and values are in range.
- **Why it matters:** it is a rollout step in the bring-up runbook.
- **Suggested acceptance criteria:** the documented command exits non-zero for a missing file, a missing key, a non-existent path and a zero poll interval; `controller.toml.example` and the runbook name the right command.
- **Dependencies:** none.
- **Suggested verification:** the lead's reproduction (missing config) returns exit 2.

## PBI-14 — Bring top-level documents and repository hygiene in line with the tree

- **Source finding:** AUDIT-022, AUDIT-026
- **Type:** DOCUMENTATION
- **Problem:** `CLAUDE.md`, `AGENTS.md` and `README.md` describe a repository without code, without `forgejo-runner/`, without `scripts/` and without verify commands; two comments contradict the code; seven `.pyc` files are tracked.
- **Desired outcome:** the three files describe what exists, name the verification command and the host-ops scripts; stale comments are corrected; bytecode is untracked and ignored.
- **Why it matters:** these files are the starting context of every agent session, and the repository's own rule is to claim nothing about the tree that was not measured.
- **Suggested acceptance criteria:**
  - Every path in the "Rol van deze repo" table matches `git ls-files`.
  - The Forgejo and Runner versions named are dated or point to evidence (owner, 2026-09-30: Forgejo runs 15.0.9; `main` says 15.0.2).
  - The unit comment and README step 10 match the code.
  - `git ls-files '*.pyc'` is empty and a fresh test run leaves `git status` clean.
- **Dependencies:** PBI-10 for the verify command. Doc-only, so no ceremony under the product's own rules.
- **Suggested verification:** grep after the change, as the hard-stop rule prescribes.

## PBI-15 — Extend the drift gate to what it claims to cover

- **Source finding:** AUDIT-023
- **Type:** TECHNICAL_IMPROVEMENT
- **Problem:** `verify-stack.sh` reports isolation OK when `ss` is missing, and does not compare installed unit files or the rendered runner configuration; the mirror unit, the retention schedule and the unit-installation step are not in the repository.
- **Desired outcome:** the gate fails closed on a missing tool and covers every artefact that comes from the bundle; remaining host units are tracked or explicitly listed as host-local.
- **Why it matters:** "byte-identical on both hosts" is a stated design requirement.
- **Suggested acceptance criteria:** without `ss` the script exits non-zero; a modified installed unit file is reported as drift; the rollout steps say how units are installed.
- **Dependencies:** delta review if §6.1 of the design changes.
- **Suggested verification:** new cases in `forgejo-runner/tests/test_verify_stack.bats`.

## PBI-16 — Decide a refresh cadence for the pinned images and close the open back-port question

- **Source finding:** AUDIT-024
- **Type:** RESEARCH
- **Problem:** the runner, DinD and job images are frozen at digests from May and September 2026; the repository records that a Runner 13.0.0 security fix may or may not exist in 12.x and that this was not checked; nothing prompts a review.
- **Desired outcome:** a dated answer to the back-port question and a recorded cadence (or trigger) for comparing pins with upstream.
- **Why it matters:** the DinD image is the only privileged component; the runner fetches and executes repository code.
- **Suggested acceptance criteria:** the research document states the 12.x status of the cited fix with a source; a dated comparison of the three pins with their tags exists; the cadence is written next to the pins.
- **Dependencies:** phase-1 freeze in the design (§12 upgrade is phase 2).
- **Suggested verification:** the dated record.

## PBI-17 — Scenario tests for the runtime layer

- **Source finding:** AUDIT-025
- **Type:** TESTING
- **Problem:** the layer that connects the state machine to Docker, the trust verdict and signals is tested with the trust gate stubbed, a fixed probe result and without ever running its main loop.
- **Desired outcome:** the scenarios this audit reproduced by hand exist as tests, plus one bounded run of the main loop with a stop signal.
- **Why it matters:** five production-relevant behaviours were found in minutes with the existing harness; they should be found by the suite.
- **Suggested acceptance criteria:** the harness accepts a scripted probe sequence and a scripted trust result; tests exist for gate-turns-red-while-waiting, probe-fails-then-recovers, runner-fails-repeatedly, pull-fails-once and operation-never-finishes; `Runtime.run` is executed once with a short grace period.
- **Dependencies:** expected outcomes depend on PBI-02, PBI-03 and PBI-04.
- **Suggested verification:** each test fails against today's code where the finding says so, and passes after the corresponding change.

## PBI-18 — Close the residual gaps in `rotate-env-credential`

- **Source finding:** AUDIT-029
- **Type:** TECHNICAL_IMPROVEMENT
- **Problem:** a signal during `probe` can leave a temporary password file; a signal between replace and bookkeeping leaves one file outside the restore list; subprocesses have no timeout; no lock prevents two runs.
- **Desired outcome:** no interruption point leaves a secret on disk or a file outside the rollback set.
- **Why it matters:** the tool's purpose is that a rotation never leaks or half-applies.
- **Suggested acceptance criteria:** SIGTERM during `probe` leaves no temporary file; an interrupt at any point in the batch is fully rolled back; a second concurrent run is refused.
- **Dependencies:** none.
- **Suggested verification:** new cases in `scripts/tests/test_alter_probe.py` and `test_rewrite.py`.
