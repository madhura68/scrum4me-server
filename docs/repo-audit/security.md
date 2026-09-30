# Security audit — scrum4me-server

Scope: read-only, defensive review of commit `4d9f873` (branch `claude/repo-engineering-audit-66e5a7`),
requested by the repository owner. Audit date 2026-09-30.

Method: full read of the ~5 000 source lines under `forgejo-runner/` and `scripts/`; pattern scan of
all 167 tracked files, of the seven tracked `.pyc` files and of the added lines of all 221 commits on
all local and remote branches; `shellcheck -x`; the secret-scanner regexes were exercised against
**synthetic** strings only. No repository script, test, container, SSH or network command was run and
no credential was used or validated. No host was inspected: everything about host state is either
quoted from tracked evidence or marked **inferred**.

Severity = impact if the condition is met. Confidence = how sure the observation is.
"Observed" = read in the code or evidence. "Inferred" = follows from the code plus general
Docker/git/systemd behaviour, not measured.

---

## 1. Secrets in the repository

**Result: no live secret found** in the working tree, in the `.pyc` files or in history.

| Check | Result |
|---|---|
| Key/value, URL-credential, JWT, PAT-prefix, private-key, SCRAM, hex-token patterns over all tracked files | Only placeholders, regexes, fixtures and redacted values |
| Same patterns over added lines of all 221 commits (all branches) | Only fixtures and paths |
| `git log --all --diff-filter=D` | No file was ever deleted |
| Seven tracked `.pyc` (`strings` + hex extraction) | Only synthetic test constants (single-character repeats and 16-character periodic patterns), identical to the test sources |
| `docs/**/evidence/*.json` key inventory | `token` is `<GEREDIGEERD>`; registration token in `Config.Env` and inside the entrypoint script is redacted |

Things that are present and are not secrets, but are worth knowing:

* Runner **UUIDs** of the legacy runner and of the spike record appear in
  `docs/forgejo-runner-pool/evidence/stap-a/scrum4me-server/runner-registration.json:10`,
  `.../forgejo*/runners-global.json:1`, `.../runners-summary.tsv` and `.../ephemeral-spike.md:10,25`
  (see SEC-12).
* LAN (`192.168.0.x`), Docker-bridge and Tailscale (`100.x`) addresses appear in
  `docs/runbooks/credential-rotation.md`, `docs/forgejo-runner-pool/implementatieplan-stap-a-b.md`
  and the step-A evidence. Topology information only.
* A documented incident: on 2026-09-09 the values of two Forgejo JWT secrets reached an agent
  transcript (`docs/forgejo-runner-pool/forgejo-upgrade-onderzoek-2026-09.md:78-80`). The document
  states the values are not in this repo; the scans agree. Whether the rotation happened cannot be
  verified on this branch; the owner states it happened (Q1).
* `docs/forgejo-runner-pool/evidence/stap-a/scrum4me-server/runner-registration-stat.txt:1` records the
  legacy `.runner` file (which holds the runner token) as mode `644`. It lives under
  `/var/lib/docker/volumes/`, which is normally root-only, so this is mitigated (inferred); the legacy
  installation is scheduled for removal in step G.

---

## 2. Findings

### SEC-1 — Mirror: Forgejo token is persisted in a bare clone's git config and both tokens travel in git URLs

* **Category:** secret handling
* **Severity:** MEDIUM · **Confidence:** HIGH (code path) / MEDIUM (host exposure)
* **Observation:** `tags_fallback` clones with
  `https://${FORGEJO_USERNAME}:${FORGEJO_TOKEN}@…` and pushes with
  `https://${GH_USERNAME}:${GH_TOKEN}@github.com/…`. A `git clone --bare <url>` stores the URL,
  including the credential, as `remote.origin.url` in `<clonedir>/config`; the later
  `git fetch … origin` (line 398) relies on exactly that stored URL. Both URLs are also process
  arguments.
* **Evidence:** `scripts/forgejo-mirror/forgejo-mirror-lib.sh:381-391`, `:398`, `:404-405`.
  Token scope: `docs/runbooks/credential-rotation.md:578` lists this token as
  `write:organization, write:repository, read:user`, location "`/etc/forgejo-mirror/forgejo.env`" only.
* **Impact:** a write-scoped Forgejo token sits in plain text under
  `/srv/scrum4me/repos/mirrors/*.git/config` with default umask permissions (inferred: `0644`), outside
  the documented credential inventory, so a rotation that follows the runbook card does not know this
  copy exists. Reachability: only when `verify_tags` fails (`forgejo-mirror-sync.sh:95-96`). Whether a
  clone currently exists: per the owner, none does (Q2).
* **Mitigating:** requires local read access to the host; the old value becomes useless once revoked.
* **Recommendation:** keep credentials out of URLs (credential helper, `http.extraHeader` from a
  0600 file, or `GIT_ASKPASS`); add the clone directory to the rotation card; check existing clones.
* **Verification:** on the host, `git -C <clonedir> config --get remote.origin.url` must show no
  userinfo; `rotate-env-credential scan`-style search over the mirror directory returns nothing.

### SEC-2 — Mirror: tokens in process arguments beyond what the README admits

* **Category:** secret handling
* **Severity:** MEDIUM · **Confidence:** HIGH
* **Observation:** the README documents the `-H "Authorization: …"` exposure as an open improvement.
  Two further paths are not mentioned: the GitHub token is passed to `jq --arg pw "$GH_TOKEN"` and the
  resulting JSON (containing `remote_password`) is passed to `curl --data "$data"`.
* **Evidence:** `scripts/forgejo-mirror/forgejo-mirror-lib.sh:39-46`, `:59-60`, `:67-75`, `:98-114`
  (header); `:277-282` with `:42` (payload); `scripts/forgejo-mirror/README.md:30-31` (admission).
* **Impact:** any local account can read both tokens from `ps`/`/proc/*/cmdline` during the nightly
  run unless `hidepid` is set (the runbook references ISS-43 for that). Contradicts the repo's own
  principle A.1 (`docs/runbooks/credential-rotation.md:30-33`).
* **Documented/intentional:** partially (header only); acknowledged as not yet fixed.
* **Recommendation:** `curl --config <(…)` as already used in
  `forgejo-runner/scripts/capture-forgejo-records.sh:29`, and `--data @file`/stdin for the payload.
* **Verification:** while a run is active, `ps -eo args | grep -c -E 'token |Bearer '` is 0.

### SEC-3 — DinD API is unauthenticated plain TCP; TLS of the legacy setup was dropped without recorded rationale

* **Category:** container/host isolation
* **Severity:** MEDIUM · **Confidence:** MEDIUM (network reachability inferred, not tested)
* **Observation:** `dockerd --host=tcp://0.0.0.0:2375 --tls=false` in a `privileged: true` container
  on a user-defined bridge with `internal: false`. The legacy stack captured in step A used
  `DOCKER_TLS_VERIFY=1`, `DOCKER_HOST=tcp://dind:2376` and client certificates. The design's
  accepted-risk section covers co-location of a privileged DinD for trusted workflows; it does not
  discuss who on the host can reach the endpoint, nor the removal of TLS. `verify-stack.sh` checks
  only that nothing listens on 2375/2376 in the **host** network namespace.
* **Evidence:** `forgejo-runner/compose.yaml:10-13`, `:63-66`;
  `docs/forgejo-runner-pool/evidence/stap-a/scrum4me-server/containers.json:21-23`;
  `docs/forgejo-runner-pool/migratieontwerp.md:193-235`; `forgejo-runner/scripts/verify-stack.sh:28-32`.
  A search for "tls" in the design, plans and reviews returns only the compose line itself.
* **Impact (inferred):** the host can route to a bridge container's IP, so any local process — an
  unprivileged account, or a container in host network mode — can drive the Docker API of a
  privileged container and from there reach host devices: local privilege escalation to root on the
  production host. Containers on other bridge networks are normally blocked by Docker's inter-bridge
  isolation rules.
* **Mitigating:** no published port; requires local code execution; accounts already in the `docker`
  group gain nothing new.
* **Recommendation:** record the decision explicitly (why TLS went away, who may reach the bridge);
  consider host firewall rules limiting the bridge port to the runner container, or TLS with client
  certificates for the runner while job containers keep a separate path.
* **Verification:** from an unprivileged host account, `curl http://<dind-bridge-ip>:2375/_ping`
  must fail.

### SEC-4 — Every CI job has full control of a privileged container (documented, accepted risk)

* **Category:** container/host isolation — **intentional and documented**
* **Severity:** HIGH (impact) · **Confidence:** HIGH
* **Observation:** job and step containers receive `DOCKER_HOST=tcp://dind.internal:2375` by policy,
  so any workflow can run `docker run --privileged …` inside DinD. The job-level restrictions
  (`privileged: false`, `valid_volumes: []`) therefore constrain the job container itself, not what
  the job can ask DinD to do.
* **Evidence:** `forgejo-runner/runner-config.policy.yml:13-14`, `:19-24`;
  `docs/forgejo-runner-pool/migratieontwerp.md:203-218` (endpoint matrix), `:220-224` (explicit
  acceptance: an escape "kan … de host en de productiecontainers raken"), `:272-279`;
  `forgejo-runner/trusted-actions-scope.yml:12-27` and 13 repositories carrying
  `risky_triggers_acknowledged: [pull_request]`.
* **Impact:** whoever can get a workflow to run on the `ubuntu-latest` label is effectively root on a
  host that also runs Forgejo and Postgres. The trust gate (section 3) is the only control.
* **Assessment:** this is a recorded risk acceptance by the owner, not a defect. It is listed because
  SEC-3, SEC-5, SEC-6, SEC-7 and SEC-8 each widen or weaken the boundary that acceptance relies on.
* **Recommendation:** none beyond the design's own phase-2 intent (rootless/unprivileged DinD);
  keep the acceptance text in sync with the findings below.
* **Verification:** n/a (design decision).

### SEC-5 — A repository-admin API token is stored on the hosts that execute CI jobs

* **Category:** secret handling / blast radius
* **Severity:** MEDIUM · **Confidence:** HIGH (requirement) / MEDIUM (effective token scope unknown)
* **Observation:** the trust scan needs "een account met admin-recht op iedere Actions-enabled
  repository"; the token is kept in `/opt/forgejo-runner/credentials/trust-scan.env` (0600, root) on
  both hosts and loaded through `EnvironmentFile=`. The README does not require a read-only token
  scope. The same document shows a verification command with the token inline
  (`FORGEJO_TOKEN=<waarde> … python3 …`), which puts it in shell history.
* **Evidence:** `forgejo-runner/README.md:41-56`; `forgejo-runner/forgejo-runner-trust.service:16-19`;
  `forgejo-runner/scripts/trust_scope_cli.py:43`, `:188-193`.
* **Impact:** combined with SEC-4, a container escape on either host yields a token with admin rights
  on every Actions-enabled repository — including this one, which holds the allow-list the gate
  enforces.
* **Recommendation:** issue the token with read scopes only (the scan only performs GETs), state that
  in the README, and replace the inline example by an env-file or stdin form.
* **Verification:** the token answers 403 on a write endpoint; README example contains no inline value.

### SEC-6 — A waiting runner is not stopped when the trust verdict turns red or a fence is set

* **Category:** trust gate (fail-open window)
* **Severity:** MEDIUM · **Confidence:** HIGH
* **Observation:** the gate result only feeds `controller.gates_groen`, which is consulted before a
  **new** runner start. The only call that stops a running `one-job --wait` child is the SIGTERM
  handler. The state machine moves to `DRAINING` on a fence, but the runtime never acts on that state.
  So a runner that is already waiting stays online and accepts one more job after the verdict became
  red, expired or unbound. No test covers "gate turns red while waiting".
* **Evidence:** `forgejo-runner/scripts/cycle_runtime.py:181-192` (sets the flag),
  `:197-207` (start precondition), `:319-325` (only stop path);
  `forgejo-runner/scripts/forgejo_runner_cycle.py:302-303`;
  design requirement `docs/forgejo-runner-pool/migratieontwerp.md:258` and `:270`.
* **Documented:** partly. `docs/forgejo-runner-pool/controller-entrypoint-ontwerp.md` §2 and §6.3
  call the deploy-verdict a "zwakkere, tijdgebonden garantie" and defer the live gate, the
  authenticated probe, `DRAINING` and cancel/redispatch; §7.4 says only "geen runnerstart". The
  specific consequence above is not written down.
* **Impact:** after a hard trust deviation is detected, up to one job per host can still run on the
  privileged DinD. Detection itself lags by up to the timer interval (6 h) and a verdict stays valid
  for 24 h if the timer stops (`forgejo-runner/forgejo-runner-trust.timer:12`,
  `forgejo-runner/controller.toml.example:25`).
* **Recommendation:** either stop the waiting child when `gates_groen` flips to false, or record the
  one-job leak explicitly as part of the accepted thin-slice limitation.
* **Verification:** a unit test that flips the verdict while `rt.child` is set and asserts
  `runner.request_stop` was called.

### SEC-7 — "No state between jobs" holds only against non-malicious jobs

* **Category:** container isolation (cross-job integrity)
* **Severity:** MEDIUM · **Confidence:** MEDIUM (inferred, not tested)
* **Observation:** the scrub runs **inside** the long-lived DinD container, using that container's
  `docker` CLI against its own daemon, and the DinD container (`restart: always`) and its data volume
  are never recreated between jobs. A job that uses the DinD API to start a privileged container can
  modify the DinD container's filesystem or the image store on `dind-data` directly; the scrub's proof
  is then produced by tooling the previous job could alter.
* **Evidence:** `forgejo-runner/compose.yaml:9`, `:16-18`;
  `forgejo-runner/scripts/cycle_adapters.py:120-143`; `forgejo-runner/scripts/scrub-dind.sh:25`,
  `:60-87`; requirement `docs/forgejo-runner-pool/migratieontwerp.md:313`.
* **Impact:** a compromised or hostile workflow in one repository could influence later jobs of other
  repositories on the same host. Falls inside the "trusted workflows only" premise of SEC-4, but the
  13 acknowledged `pull_request` paths make that premise weaker than "trusted writers only".
* **Recommendation:** recreate the DinD container (and ideally the volume, re-pulling the pinned job
  image) per cycle, or state in §7.9 that the scrub is hygiene and not a security boundary.
* **Verification:** design text updated, or a cycle test showing a fresh container ID per job.

### SEC-8 — Trust scan: under-detection paths

* **Category:** trust gate
* **Severity:** MEDIUM · **Confidence:** MEDIUM
* **Observation (each item observed in code; consequences inferred):**
  1. Only the default branch is scanned — `contents()` is called without a ref
     (`trust_scope.py:39`, `trust_scope_cli.py:93-96`). Documented in `forgejo-runner/README.md:87`.
     A `pull_request` workflow normally comes from the PR head, so a repository without an
     acknowledged trigger on its default branch is not thereby proven closed to fork PRs. Not verified
     against Forgejo's source (Q4).
  2. Shared-label use is a substring test on the workflow text (`trust_scope.py:126`); a `runs-on`
     built from an expression or matrix does not contain the label, which downgrades a risky trigger
     from hard to soft (`trust_scope.py:352-365`).
  3. Writers = owner, collaborators, team members (`trust_scope.py:133-198`). Deploy keys with write
     access and instance administrators are not inventoried, although branch-protection data already
     exposes `push_whitelist_deploy_keys` in the captured inventory.
  4. Pagination stops when a page has fewer than 50 items (`trust_scope_cli.py:65-73`, `:82-91`). If
     the instance's maximum page size is below 50, the first page already terminates the loop and the
     result is silently truncated — the exact failure the docstring warns about. The total-count
     header is not checked. `/repos/{…}/teams` is not paginated at all (`:106-112`).
  5. Repositories are those **visible to the token** (`/repos/search`), so an under-privileged token
     shrinks the measured set without an error.
* **Impact:** the gate can be green while a path for unapproved code exists.
* **Mitigating:** everything unreadable is fail-closed; registration is closed on the instance
  (`trusted-actions-scope.yml:18`); items 2 and 3 require an already-trusted writer or admin.
* **Recommendation:** compare the collected count with `X-Total-Count`; treat a label-less risky
  trigger as hard unless acknowledged; add deploy keys to the writer inventory; document item 1 in
  §7.7 next to the existing acknowledgement text.
* **Verification:** unit tests for a 30-item page size, for an expression-based `runs-on`, and for a
  write-enabled deploy key.

### SEC-9 — `secret-scan.sh`: false negatives and a fail-open path

* **Category:** secret scanner
* **Severity:** MEDIUM · **Confidence:** HIGH (regexes exercised with synthetic input)
* **Observation:**
  * Fail-open on bash < 4: the script has `set -uo pipefail` without `-e` and fills the file list
    with `mapfile`. Where `bash` resolves to 3.2 (stock macOS), `mapfile` is not a builtin, the array
    stays empty and line 13 exits 0 (`secret-scan.sh:7`, `:11-13`).
  * Not matched by rule 2: `-----BEGIN PRIVATE KEY-----` (PKCS#8) and
    `BEGIN ENCRYPTED PRIVATE KEY` (`:28`).
  * Not matched by rule 3 (`:43`): single-quoted values, key names without
    `token|secret|password` (`API_KEY`, `DB_PASSWD`, `PGPASS`), `Authorization: Bearer …`, DSNs with
    inline credentials, values containing `.`, values shorter than 20 characters.
  * Line-level exclusion (`:44`): any line that also contains `sha256:`, `token_url` or a
    UUID-shaped string is dropped. A single-line JSON object with both `uuid` and `token` — the shape
    `capture-forgejo-records.sh` writes — passes. This contradicts the script's own comment
    "GEEN inhoud-gebaseerde uitzondering" (`:39-42`).
  * It greps the working-tree file, not the staged blob (`:17`, `:28`, `:43`), and lists only
    `--diff-filter=ACM`, so renames are skipped (`:11`).
  * File-name rule covers `forgejo-token`, `*.key`, `*.pem`, `.env` only; `trust-scan.env`,
    `github.env`, `.env.production` pass by name (`:21-25`).
* **Installation:** manual and per clone (`install-git-hooks.sh:28-33`); it is installed in the
  main checkout on this workstation (`.git/hooks/pre-commit`). There is no server-side hook and no CI,
  so other clones and `--no-verify` are unprotected.
* **Would the repo pass its own scanner?** Rule 3 and the name rule: yes for all 167 files. Rule 2
  flags `docs/forgejo-runner-pool/implementatieplan-stap-a-b.md:5428` (a quoted test fixture), so any
  commit touching that document is blocked.
* **Impact:** the gate that backs the "no secrets in Git" hard-stop misses common secret shapes.
* **Recommendation:** add `-e` or an explicit `mapfile` guard; scan `git show :path`; match
  `BEGIN [A-Z ]*PRIVATE KEY`; strip allowed tokens from a line instead of dropping the line; widen key
  names; consider a maintained scanner in addition.
* **Verification:** extend `forgejo-runner/tests/test_secret_scan.bats` with the shapes above.

### SEC-10 — `compose-git-pre-commit`: heuristic gaps

* **Category:** secret scanner
* **Severity:** LOW · **Confidence:** HIGH
* **Observation:** comment lines are skipped, so a commented-out credential passes (`:44`); any value
  containing `$` followed by a letter counts as interpolated (`:28`, `:53`); key list lacks e.g.
  `*_KEY`, `CREDENTIALS`, `AUTH`, `PASS` (`:22-26`); private-key blocks are not detected.
* **Documented:** yes — "Een patroontoets, geen volledige scan" (`:38`). The repos it guards are
  local-only with `.git` at 0700 (`scripts/compose-git-init:92`) and an allow-list `.gitignore`.
* **Recommendation:** treat comments like other lines; require the whole value to be an interpolation.
* **Verification:** new cases in `scripts/tests/test_compose_git.py`.

### SEC-11 — Evidence redaction is narrow; one capture script writes the raw API response

* **Category:** secret handling in evidence
* **Severity:** LOW · **Confidence:** HIGH
* **Observation:** `redact_inspect.py` redacts `Config.Env`, `Config.Cmd`, `Config.Entrypoint` and
  `Args` only (`:91-98`); health-check commands, labels and bind paths are untouched. Env keys are
  matched on `TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|PRIVATE|APIKEY|API_KEY|ACCESS_KEY` (`:26-28`), so
  `DATABASE_URL`, `*_DSN`, `DB_PASS`, `ENCRYPTION_KEY` would pass. Values shorter than four characters
  are not replaced globally (`:40`). `capture-forgejo-records.sh:29-31` stores the unfiltered
  `/admin/actions/runners` response.
* **Current evidence:** verified clean — the two captured containers carry only
  `RUNNER_REGISTRATION_TOKEN`, redacted in `Env` and inside the entrypoint script
  (`evidence/stap-a/scrum4me-server/containers.json:6`, `:13`, `:22`); the runner list has no `token`
  key.
* **Impact:** the tool is safe for the two containers it was written for; pointing it at a production
  container with a DSN in its environment would leak. SEC-9's UUID exclusion would not catch a token in
  the raw runner list.
* **Recommendation:** add URL-credential detection and broader key names; drop `token` fields in
  `capture-forgejo-records.sh` as `spike-ephemeral.sh:77-83` already does.
* **Verification:** tests with a `DATABASE_URL=postgres://u:p@h/db` env entry.

### SEC-12 — Runner UUIDs are committed although the repo rules forbid it

* **Category:** policy consistency
* **Severity:** LOW · **Confidence:** HIGH
* **Observation:** `CLAUDE.md:65`, `forgejo-runner/.env.example:2` and
  `runner-config.policy.yml:2-3` exclude UUIDs from Git; step-A evidence contains them (locations in
  section 1). Already noted in `docs/forgejo-runner-pool/implementatieplan-forgejo-15.0.7.md:297`.
* **Impact:** a UUID is an identifier; authentication also needs the token, which is redacted. Low.
* **Recommendation:** decide whether UUIDs are secret; align either the rule or the evidence.
* **Verification:** grep for UUID-shaped strings under `docs/**/evidence/`.

### SEC-13 — `rotate-env-credential`: residual exposure paths

* **Category:** secret handling
* **Severity:** LOW · **Confidence:** HIGH
* **Observation:** the headline claim holds (section 4). Residuals:
  * `probe` writes `PGPASSWORD` to a `mkstemp` file (0600) and removes it in `finally`
    (`:416-432`), but installs no signal handler — the rollback handler exists only in
    `_write_batch` (`:205`, `:240-261`). SIGTERM/SIGHUP leaves the file in the temp directory.
  * The password is URL-unquoted (`:63`) before being written as an env-file line (`:419-422`);
    an encoded newline would inject a further variable. Source is the operator's own `.env`.
  * `alter-role` sends only the SCRAM verifier (`:385-395`), but a server with statement logging
    would record that verifier; stderr filtering drops lines containing the verifier (`:374-379`).
  * `.bak-<stamp>` files are full copies of the `.env`, i.e. they hold every other secret in that
    file until phase 4 of the runbook removes them (`:109-119`;
    `docs/runbooks/credential-rotation.md:196-198`).
* **Recommendation:** reuse the signal-to-exception wrapper around `probe`; reject control characters
  after unquoting.
* **Verification:** unit test sending SIGTERM during `probe` and asserting no `rec-probe-*` remains.

### SEC-14 — systemd units run as root with partial sandboxing

* **Category:** hardening
* **Severity:** LOW · **Confidence:** HIGH
* **Observation:** neither service sets `User=`. The controller unit has `NoNewPrivileges` and
  `ProtectHome` only, with `PrivateTmp=false` and no `ProtectSystem`
  (`forgejo-runner-cycle.service:19-21`). The trust unit adds `ProtectSystem=strict` and `PrivateTmp`,
  but `ReadWritePaths=/opt/forgejo-runner` makes the scripts and `credentials/` writable to a process
  that only needs to replace `trust-verdict.json` (`forgejo-runner-trust.service:34-40`). Neither sets
  `CapabilityBoundingSet=`, `RestrictAddressFamilies=`, `ProtectKernel*`, `PrivateDevices`.
* **Context:** the controller needs the Docker socket, which is root-equivalent regardless. The trust
  unit needs only outbound HTTPS and one writable file.
* **Recommendation:** move the verdict to a dedicated state directory and narrow `ReadWritePaths`;
  run the trust unit as a dedicated user with read access to the env file.
* **Verification:** `systemd-analyze security <unit>` before/after.

### SEC-15 — `preflight.sh` executes file content as shell and as Python

* **Category:** input validation
* **Severity:** LOW · **Confidence:** HIGH
* **Observation:** `source "$CAPS"` (`:24`) and `python3 -c "print(${RUNNER_CPU} + ${DIND_CPU})"` /
  `${VCPU}` from the facts TSV (`:39-41`) interpolate file content into code.
* **Impact:** the inputs are evidence files the operator produces; an altered file would run code with
  the operator's rights. No remote input reaches this.
* **Recommendation:** parse the two files and pass numbers as arguments (`sys.argv`).
* **Verification:** a bats case with a caps value of `1; import os` exits 2.

### SEC-16 — Documentation that contradicts the repo's own secret-handling rule

* **Category:** process
* **Severity:** LOW · **Confidence:** HIGH
* **Observation:** rule A.1 forbids `VAR=value command` (`docs/runbooks/credential-rotation.md:30-33`).
  `forgejo-runner/README.md:53` and
  `docs/forgejo-runner-pool/implementatieplan-forgejo-15.0.7.md:49` show exactly that form;
  the same plan interpolates a freshly generated secret into a `sed` argument (`:119-120`). The
  install recipe stages the script at the fixed path `/tmp/rec` before `sudo install`
  (`credential-rotation.md:72-73`); the subsequent hash comparison detects tampering after the fact.
* **Recommendation:** align the examples with A.1; stage via `mktemp`.
* **Verification:** grep for `_TOKEN=<` / `_TOKEN=…` in docs returns nothing.

### SEC-17 — Compiled bytecode is tracked

* **Category:** repository hygiene
* **Severity:** LOW · **Confidence:** HIGH
* **Observation:** seven `.pyc` files under `scripts/__pycache__/` and `scripts/tests/__pycache__/`
  are tracked; the root `.gitignore` has no `__pycache__` rule (the bundle's own
  `forgejo-runner/.gitignore:1-2` does). They embed a local developer path.
* **Impact:** no secret; bytecode cannot be reviewed and can drift from the source.
* **Recommendation:** untrack and ignore.
* **Verification:** `git ls-files '*.pyc'` is empty.

### SEC-18 — Job containers have unrestricted network egress

* **Category:** container isolation
* **Severity:** LOW · **Confidence:** MEDIUM (inferred)
* **Observation:** `runner-control` is `internal: false` so DinD can pull images
  (`compose.yaml:63-66`); nothing restricts what job containers may reach through DinD's NAT: the
  runner container, host services bound to non-loopback addresses, LAN and tailnet.
* **Context:** subsumed by SEC-4 for a hostile job; relevant for a merely buggy or dependency-poisoned
  job. Forgejo's web port is bound to loopback per
  `docs/forgejo-runner-pool/forgejo-upgrade-onderzoek-2026-09.md:53`.
* **Recommendation:** record the intended egress policy; consider an egress allow-list on the bridge.
* **Verification:** from a job, a connection to a LAN address outside the allow-list fails.

---

## 3. Trust gate — error-path table (observed)

| Condition | Behaviour | Closed? | Evidence |
|---|---|---|---|
| Token missing | CLI exit 30 → verdict invalidated | yes | `trust_scope_cli.py:188-191`, `publish-trust-verdict.sh:53-54` |
| HTTP error other than the two whitelisted cases | `Unreadable` → exit 30 | yes | `trust_scope_cli.py:47-52` |
| Timeout / URL error / bad JSON | `Unreadable`, or caught by the broad handler → exit 30 | yes | `:53-54`, `:203-208` |
| Response of wrong shape | `Unreadable` | yes | `trust_scope.py:51-83`, `trust_scope_cli.py:68-69`, `:85-86` |
| 404 on a workflow directory | treated as "absent", falls back | intended | `trust_scope_cli.py:93-96` |
| 405 on `/teams` (user-owned repo) | treated as "not applicable" | intended | `:106-112` |
| Page size < 50 on the server | loop ends after page 1 | **no** (SEC-8.4) | `:65-73`, `:82-91` |
| Labels or allow-list file missing | exit 30 → invalidated | yes | `publish-trust-verdict.sh:24-29` |
| Allow-list not approved | exit 30 | yes | `trust_scope_cli.py:231-234` |
| CLI crashes / Python missing | shell fallback writes `ok:false` | yes | `publish-trust-verdict.sh:83-93` |
| Exit code and JSON disagree, duplicate keys, NaN | invalidated | yes | `:40-64` |
| Verdict file missing or not JSON | gate red | yes | `cycle_adapters.py:217-223` |
| Verdict file unreadable (other `OSError`) | exception → controller crash → unit restart | closed, noisy | `cycle_adapters.py:221` |
| `measured_at` in the future / NaN / bool | gate red | yes | `cycle_runtime.py:95-100` |
| Verdict older than 24 h | gate red | yes | `:101-102` |
| Labels / allow-list / target changed since measurement | gate red (hash binding) | yes | `:103-108` |
| Labels file missing **and** verdict carries an empty hash | would match (`""`) | theoretical; verdict writer is root | `cycle_adapters.py:226-231` |
| Verdict turns red while a runner is waiting | runner keeps waiting | **no** (SEC-6) | `cycle_runtime.py:181-207` |
| Forgejo state changes between scans | unseen for up to 6 h | documented window | `forgejo-runner-trust.timer:12` |
| TLS | `urllib` default verification; target hard-coded `https://` in the unit | yes | `forgejo-runner-trust.service:27` |
| Readiness probe | unauthenticated `/api/v1/version`; `CREDENTIAL_ERROR` unreachable | documented deferral | `cycle_adapters.py:18-25`, `controller-entrypoint-ontwerp.md` §2 |

---

## 4. What is done well (with evidence)

* **`rotate-env-credential` keeps its promise in code.** Secrets are read from stdin only and
  validated (`:39-47`); the role name is whitelisted before it is placed in SQL (`:21`, `:28-31`);
  the SQL travels on stdin, never argv (`:392-395`); Postgres receives a SCRAM verifier, not the
  password (`:68-77`, `:385`); error output is restricted to type and `strerror`, never `str(exc)`
  (`:85-87`); `.env` rewrites are atomic, preserve mode/owner/ACL and refuse concurrent modification
  (`:133-156`); backups are `O_EXCL`, 0600 (`:109-119`); interruption rolls the whole batch back
  (`:199-229`). Output shows paths, counts and classes, never values (`:354-371`, `:470-509`).
* **The scanner is fail-closed on nearly every error path** (table above), with explicit reasoning in
  the code for each exception (`trust_scope_cli.py:23-39`) and defensive JSON parsing in the publisher
  (`publish-trust-verdict.sh:40-64`).
* **Verdict binding**: freshness is judged on `measured_at`, not mtime, and bound to the hashes of the
  labels and allow-list files and to the measured target (`cycle_runtime.py:90-109`).
* **Image pinning by digest** for runner, DinD and job image, enforced by `render-config.sh:33-40`,
  `cycle_runtime.py:74-87` and contract tests (`forgejo-runner/tests/test_compose_contract.bats`).
* **No host Docker socket, no published ports, no host namespaces, token mounted read-only into the
  runner only** (`compose.yaml:16-18`, `:51-53`), with a drift gate (`verify-stack.sh`, `bundle-hash.sh`).
* **Capture scripts avoid argv for the token** (`capture-forgejo-records.sh:29`,
  `spike-ephemeral.sh:33-34`) and the step-A evidence is correctly redacted.
* **`compose-inpak`** refuses globs, relative paths and registered config files, re-hashes before
  every deletion, reads the archive back before removing anything, and creates the archive 0600
  (`:37-58`, `:87-104`, `:176-181`, `:200-226`). `compose-git-init` refuses to run as root and keeps
  an allow-list `.gitignore` (`:47-48`, `:79-83`).
* **Shell quality:** `shellcheck -x` reports nothing on `forgejo-runner/scripts/*.sh`; no `eval`,
  no `curl | sh`, `jq --arg` used for JSON construction in the mirror (`forgejo-mirror-lib.sh:277-281`).
* **Risk acceptance is written down**, including its limits (`migratieontwerp.md:220-224`, `:272-279`),
  and a past leak was recorded rather than hidden (`forgejo-upgrade-onderzoek-2026-09.md:78-80`).
* **History is clean:** no secret-shaped value in 221 commits, no deleted files.

---

## 5. Open questions

* **Q1.** Were `JWT_SECRET` and `LFS_JWT_SECRET` rotated after the 2026-09-09 transcript leak?
  **Answered by the owner on 2026-09-30 (stated, not measured by the audit): yes, rotated.**
* **Q2.** Does `/srv/scrum4me/repos/mirrors/` exist on `scrum4me-server`, and does any `config` there
  hold a token (SEC-1)? **Answered by the owner on 2026-09-30 (stated, not measured by the audit): the directory exists and is empty**, so no token is persisted
  today; SEC-1's persistence path is latent until the first tag fallback.
* **Q3.** Which local accounts and host-network containers exist on the two hosts, and is `hidepid`
  active (relevant to SEC-2 and SEC-3)?
* **Q4.** For Forgejo 15, is a `pull_request` workflow taken from the PR head, and is the fork-PR
  approval gate enabled on the 13 acknowledged repositories? The design itself says the effective
  setting is not recorded (`migratieontwerp.md:277`).
* **Q5.** What is the instance's maximum API page size (SEC-8.4)? **Measured by the lead on 2026-09-30, read-only: `max_response_items` = 50**, equal to the scanner's page size; pagination is complete today and SEC-8.4 is latent.
* **Q6.** Who owns `/opt/forgejo-runner/` on the hosts? If a non-root deploy account can write there,
  it controls scripts that root executes. **Measured by the lead on 2026-09-30, read-only:** on max2 the directory, `scripts/` and all bundle files are owned by `janpeter`; `credentials/` is `root:root 700`; on scrum4me-server the directory does not exist (bundle not yet deployed). See findings.json AUDIT-033.
* **Q7.** What scope does the trust-scan token actually have (SEC-5)? **Measured by the lead on 2026-09-30, read-only:** on max2 it is the site administrator's token `FREX_RUNNER` with `read:admin` plus `write:repository`, `write:organization`, `write:package`, `write:issue`, `write:notification`, `write:misc`. SEC-5 is confirmed.
