# Dependencies and supply chain — scrum4me-server

Scope: commit `4d9f873`, audit date 2026-09-30. Read-only; no registry, advisory database or network
source was consulted. Version and date facts are quoted from tracked files. **No CVE is asserted from
memory**; where the repository's own documents cite an advisory, that citation is reported as such.
Everything else is "not verified against an advisory database".

## 1. Shape of the dependency surface

There is no package manifest and no lockfile (`package.json`, `pyproject.toml`, `requirements*.txt`
absent). All Python is standard library. The dependency surface therefore consists of:

1. three container images pinned by digest,
2. one mutable image tag used as a CLI default,
3. an undeclared set of host tools and interpreter versions,
4. the Forgejo server the bundle talks to (deployed outside this repo, discussed in its docs).

## 2. Container images

| Role | Reference | Pin | Known version / age (from repo) | Evidence |
|---|---|---|---|---|
| Runner | `code.forgejo.org/forgejo/runner@sha256:3d49…8533` | digest | v12.10.1, image created 2026-05-05 | `forgejo-runner/.env.example:8`; `docs/forgejo-runner-pool/evidence/stap-a/scrum4me-server/images.json` |
| DinD | `docker@sha256:685b…2495` | digest | Docker 29.4.3, image created 2026-05-08 | `.env.example:9`; same evidence file |
| Job image | `catthehacker/ubuntu@sha256:c58e…ff43` | digest | tag `act-latest` resolved 2026-09-02 | `.env.example:10`; `forgejo-runner/labels.txt:5`; `forgejo-runner/allowed-job-images.txt:7`; `evidence/stap-a/resolved-digests.tsv:3` |
| Probe client | `postgres:17` | **mutable tag** | default of `--image`, run with `--pull never` | `scripts/rotate-env-credential:426`, `:534` |

Observed: `resolved-digests.tsv:1-2` shows that on 2026-09-02 the tags `runner:12` and `docker:dind`
already resolved to digests different from the pinned ones; `.env.example:3-6` states the runner tag
had moved to v12.13.2. The pins deliberately reproduce "what demonstrably runs", not the newest build.

## 3. Findings

### DEP-1 — Pinned runner is several releases behind; a security fix is recorded as unverified

* **Category:** outdated component
* **Severity:** MEDIUM · **Confidence:** HIGH (staleness) / LOW (exposure)
* **Observation:** the bundle pins Runner v12.10.1 (May 2026) while the repo notes v12.13.2 existed by
  2 September. The repo's own research cites a security item in Runner 13.0.0 — "prevent commit
  impersonation via refs/replace/* during action checkout" — and states that whether it was
  back-ported to 12.x "is niet gecontroleerd".
* **Evidence:** `forgejo-runner/.env.example:3-8`;
  `docs/forgejo-runner-pool/forgejo-upgrade-onderzoek-2026-09.md:63`.
* **Impact:** unknown exposure in the component that fetches and executes repository code. Not verified
  against an advisory database.
* **Intentional:** yes — phase 1 freezes the runner version; phase 2 upgrades to 13
  (`docs/forgejo-runner-pool/migratieontwerp.md:468`).
* **Recommendation:** settle the open back-port question; define a maximum age for the pin.
* **Verification:** a dated note in the research document stating the 12.x status of that fix.

### DEP-2 — Privileged DinD image has no update path

* **Category:** outdated component
* **Severity:** MEDIUM · **Confidence:** HIGH (staleness) / LOW (exposure)
* **Observation:** the only `privileged: true` component runs an image built 2026-05-08 (Docker
  29.4.3, buildx 0.33.0, compose 5.1.3). The floating tag had moved by 2 September. No document
  schedules a refresh.
* **Evidence:** `forgejo-runner/.env.example:9`; `forgejo-runner/compose.yaml:8-10`;
  `evidence/stap-a/scrum4me-server/images.json` (`Created`, `DOCKER_VERSION`);
  `evidence/stap-a/resolved-digests.tsv:2`.
* **Impact:** container-runtime fixes released after May 2026 are absent from the component whose
  compromise reaches the host (see `security.md` SEC-4). Not verified against an advisory database.
* **Recommendation:** add a periodic digest review (both hosts from one commit, as §6.1 requires).
* **Verification:** `.env.example` history shows a digest change with a recorded reason.

### DEP-3 — Job image is a third-party community image frozen at one digest

* **Category:** supply chain
* **Severity:** LOW · **Confidence:** HIGH
* **Observation:** every CI job runs in `catthehacker/ubuntu` (`act-latest` at resolution time). The
  digest pin gives integrity and reproducibility; it also freezes the OS packages and tool-chain at
  2 September 2026 for every repository on the instance.
* **Evidence:** `forgejo-runner/labels.txt:5`; `forgejo-runner/allowed-job-images.txt:7`;
  `docs/forgejo-runner-pool/migratieontwerp.md:189`.
* **Impact:** image content is not under the owner's control and ages silently.
* **Recommendation:** record provenance expectations and a refresh cadence alongside the pin.
* **Verification:** the pin file carries a resolution date and reviewer.

### DEP-4 — No automated dependency, update or vulnerability tooling

* **Category:** process
* **Severity:** MEDIUM · **Confidence:** HIGH
* **Observation:** no CI, no Renovate/Dependabot configuration, no image scanning, no SBOM. Digest
  resolution is a manual script (`forgejo-runner/scripts/resolve-digests.sh`). The secret scanner is a
  local hook only.
* **Evidence:** `docs/repo-audit/repository-map.md` (CI/CD: none); absence of `.forgejo/`, `.github/`,
  `renovate.json`, `.trivyignore` in `git ls-files`.
* **Impact:** staleness in DEP-1..3 is discovered only when someone looks. The hard-stop "do not
  deploy via Forgejo Actions" (`CLAUDE.md`) does not prevent read-only checks.
* **Recommendation:** a scheduled, read-only job or a documented monthly checklist that re-resolves
  the three tags and diffs them against the pins.
* **Verification:** a dated record of the last comparison exists in the repo.

### DEP-5 — Implicit tool-chain is undeclared and partly platform-specific

* **Category:** reproducibility
* **Severity:** LOW · **Confidence:** HIGH
* **Observation:** requirements inferred from the code:

  | Requirement | Used by | Note |
  |---|---|---|
  | Python ≥ 3.11 (`tomllib`) | `forgejo-runner/scripts/cycle_runtime.py:12` | measured 3.14.4 on `max2`; for `scrum4me-server` listed as an open point in `controller-entrypoint-ontwerp.md` §14 |
  | bash ≥ 4 (`mapfile`, `declare -A`, `${!var}`) | `secret-scan.sh:11`, `docker-rollback-retention.sh:32,38`, `forgejo-mirror-lib.sh:92` | stock macOS bash is 3.2; in `secret-scan.sh` this fails open (see `security.md` SEC-9) |
  | POSIX `sh` | `scrub-dind.sh`, `publish-trust-verdict.sh` | runs inside the Alpine DinD image |
  | GNU coreutils/util-linux (`date -d`, `stat -c`, `df --output`, `du -sb`, `flock`, `ss`, `nproc`) | capture scripts, mirror, `verify-stack.sh` | Linux-only |
  | GNU tar (`--format=posix --numeric-owner`) | `scripts/compose-inpak:179` | |
  | `jq`, `curl`, `git` | mirror, capture scripts | unversioned |
  | Docker Engine with Compose v2 and buildx | controller, `resolve-digests.sh:16` | |
  | `psql` inside `scrum4me-postgres` and a local `postgres:17` image | `rotate-env-credential:393`, `:426` | |
  | systemd, `sudo`, `timedatectl`, `chronyc` | units, capture scripts | |
  | `bats`, `shellcheck`, `ruff` | validation only | `ruff` is named in `controller-entrypoint-ontwerp.md` but no configuration is tracked |

* **Evidence:** files cited in the table; `docs/forgejo-runner-pool/controller-entrypoint-ontwerp.md` §3.
* **Impact:** behaviour differs between the workstation and the hosts; one difference is
  security-relevant (SEC-9).
* **Recommendation:** list minimum versions in `forgejo-runner/README.md`; have scripts assert them.
* **Verification:** a preflight that prints and checks interpreter versions.

### DEP-6 — Forgejo server version: security releases recorded as pending in repo docs

* **Category:** outdated component (outside this repo's code, inside its documentation)
* **Severity:** MEDIUM · **Confidence:** MEDIUM (status on the host not verifiable from this branch)
* **Observation:** the research document records the live forge as `15.0.2` with image
  `codeberg.org/forgejo/forgejo:15.0.2` (tag-pinned, not digest-pinned), lists security fixes in
  15.0.3–15.0.7 that 15.0.2 lacks, and cites CVE-2026-20896 with the assessment "niet exploitabel" in
  this setup. An upgrade plan to 15.0.7 is tracked; branches for 15.0.9 and 17.0 exist remotely.
* **Evidence:** `docs/forgejo-runner-pool/forgejo-upgrade-onderzoek-2026-09.md:14-17`, `:51-53`,
  `:72`; `docs/forgejo-runner-pool/implementatieplan-forgejo-15.0.7.md:5`.
* **Impact:** as stated in the repo's own document. Current host version is an open question here.
* **Recommendation:** once upgraded, update the "gemeten uitgangssituatie" table so `main` does not
  describe a superseded version.
* **Verification:** `GET /api/v1/version` recorded in evidence on `main`.

### DEP-7 — Tracked bytecode is tied to one interpreter version

* **Category:** repository hygiene
* **Severity:** LOW · **Confidence:** HIGH
* **Observation:** seven `*.cpython-314.pyc` files are tracked under `scripts/`; the root
  `.gitignore` lacks a `__pycache__` rule.
* **Evidence:** `git ls-files '*.pyc'`; `.gitignore`; `forgejo-runner/.gitignore:1-2`.
* **Impact:** none functionally; bytecode is an unreviewable artefact (see `security.md` SEC-17).
* **Recommendation:** untrack and ignore.
* **Verification:** `git ls-files '*.pyc'` is empty.

## 4. What is done well

* All three runtime images are referenced by digest, never by tag, and this is enforced in code and
  tests (`forgejo-runner/scripts/render-config.sh:33-40`, `cycle_runtime.py:74-87`,
  `forgejo-runner/tests/test_compose_contract.bats`).
* The reason for each pin and the divergence from the floating tag are written next to the pin
  (`forgejo-runner/.env.example:3-7`).
* Zero third-party Python packages: nothing to audit beyond the interpreter itself.
* A drift gate compares the deployed bundle with a commit and a content hash
  (`forgejo-runner/scripts/verify-stack.sh:19-26`, `bundle-hash.sh`).
* `rotate-env-credential probe` uses `--pull never`, so the mutable `postgres:17` default cannot pull
  an unexpected image at run time (`scripts/rotate-env-credential:426`).
* The Forgejo upgrade research separates server and runner upgrades and records what was and was not
  checked (`forgejo-upgrade-onderzoek-2026-09.md:61-63`).

## 5. Open questions

* Which Forgejo version runs today, and is that recorded on `main`? **Answered by the owner on 2026-09-30 (stated, not measured by the audit): 15.0.9.** Not yet recorded on `main`, where the research document and `CLAUDE.md` still say 15.0.2.
* Was the 12.x back-port status of the Runner 13.0.0 security item ever checked?
* Which Python version does `scrum4me-server` provide (needed before step G)?
* Is there an intended refresh cadence for the three digests during the phase-1 freeze?
