# Repository audit — scrum4me-server

Evidence-based engineering audit of this repository at commit `4d9f873` (`main`, 2026-09-30).
The audit was read-only: only files under `docs/repo-audit/` were created. No production code, test,
configuration, host, database or external system was changed.

## Start here

| Document | Content |
|---|---|
| [executive-summary.md](executive-summary.md) | What the system is, what was checked, the consequential findings, evidence gaps, open questions |
| [findings.json](findings.json) | **Authoritative finding records** (33), machine-readable |
| [pbi-candidates.md](pbi-candidates.md) | 18 backlog candidates traced to findings; no priority, no estimates |

## Detail reports

| Document | Content |
|---|---|
| [repository-map.md](repository-map.md) | Inventory: layout, components, external systems, tooling |
| [architecture.md](architecture.md) | Architecture as implemented, with diagrams; design conformance |
| [verification.md](verification.md) | Every command that was run, its result, and what could not be run |
| [code-quality.md](code-quality.md) | Correctness, error handling, duplication, dead code, static-tool output |
| [testing.md](testing.md) | Test inventory, coverage matrix, proven versus assumed, reliability mechanisms |
| [security.md](security.md) | Secrets, isolation, trust gate error paths, scanners, hardening |
| [dependencies.md](dependencies.md) | Pinned images, implicit tool-chain, update process |
| [technical-debt.md](technical-debt.md) | Debt separated from defects and from deliberate choices |

## How the audit was done

One lead and four specialist reviewers (architecture, code quality, testing and reliability, security
and dependencies). The specialists read the code and wrote the detail reports; the lead ran the test
suites and linters, re-read the code behind the important findings, reproduced seven of them, merged
duplicates and set the final ratings.

**Ratings.** The detail reports carry the specialists' own IDs and severities. Where they differ from
`findings.json`, `findings.json` is the verdict. Severity is impact, not effort. Confidence HIGH means
the behaviour was reproduced or is directly visible in the cited lines.

**Reading a finding.** Each record separates `observation` (what the code does), `impact` (what could
follow — inferred unless stated otherwise), `recommendation` (a direction, not implemented) and
`verification` (how to prove or disprove it). Extra fields beyond the requested schema:
`sourceIds` (specialist IDs merged into the record), `leadVerified` (what the lead checked) and, where
the owner has decided, `status` (`accepted-risk`).

## Findings by severity

| Severity | Count |
|---|---|
| CRITICAL | 0 |
| HIGH | 1 (a documented, accepted risk) |
| MEDIUM | 19 |
| LOW | 13 |

## Mapping: consolidated ID → specialist IDs

| ID | Sev | Title (short) | Source IDs | Lead check |
|---|---|---|---|---|
| AUDIT-001 | HIGH | Jobs control a privileged DinD on the production host (accepted risk) | SEC-4 | read |
| AUDIT-002 | MEDIUM | Secret-scan bypasses | SEC-9, TEST-7, CQ-7 | **reproduced** |
| AUDIT-003 | MEDIUM | Waiting runner not stopped on red gate (accepted by owner) | ARCH-1, SEC-6 | **reproduced** |
| AUDIT-004 | MEDIUM | No deadline on scrub / pull / runner operations | ARCH-4, REL-1, CQ-5 | **reproduced** |
| AUDIT-005 | MEDIUM | Blocked latch never clears | ARCH-2 | **reproduced** |
| AUDIT-006 | MEDIUM | Quarantine re-opens, start-fail loop | ARCH-3 | **reproduced** |
| AUDIT-007 | LOW | One failed probe → spurious alarm and delay | REL-2, CQ-19 | **reproduced** |
| AUDIT-008 | MEDIUM | Scrub proof passes on a silent daemon | CQ-2 | read |
| AUDIT-009 | MEDIUM | Scrub runs inside the DinD the job controlled | SEC-7 | read (inferred impact) |
| AUDIT-010 | MEDIUM | DinD API: TLS dropped without recorded decision | SEC-3 | read (reachability untested) |
| AUDIT-011 | MEDIUM | Mirror tokens in URLs, clone config and argv | SEC-1, SEC-2, ARCH-7, CQ-12 | read |
| AUDIT-012 | LOW | Trust scan under-detection (pagination latent) | SEC-8, REL-8 | **measured** |
| AUDIT-013 | MEDIUM | Write-scoped admin token on the CI host; inline-token examples | SEC-5, SEC-16 | **measured** |
| AUDIT-014 | MEDIUM | No CI, no single verification entry point | TEST-3, DEP-4 | observed |
| AUDIT-015 | MEDIUM | Target-platform tests skip silently | TEST-1, TEST-9 | observed |
| AUDIT-016 | MEDIUM | Mirror and retention scripts untested | TEST-2 | confirmed |
| AUDIT-017 | LOW | Mirror logic defects (two items latent) | REL-4, CQ-8..CQ-11 | partly read, partly measured |
| AUDIT-018 | LOW | Retention guard can be silently empty | REL-6, CQ-13 | read |
| AUDIT-019 | MEDIUM | Documented `--check` is a no-op | CQ-1, CQ-22 | **reproduced** |
| AUDIT-020 | MEDIUM | Unguarded exceptions in the controller loop | CQ-3 | read |
| AUDIT-021 | MEDIUM | Red DinD-health gate is silent | CQ-4 | read |
| AUDIT-022 | MEDIUM | Top-level documents and comments contradict the tree | ARCH-5, ARCH-6, TEST-3 | confirmed |
| AUDIT-023 | LOW | Drift / isolation gate coverage gaps | REL-5, ARCH-8, CQ-24 | read |
| AUDIT-024 | MEDIUM | Frozen image pins without a refresh process | DEP-1..DEP-4 | read (exposure unverified) |
| AUDIT-025 | MEDIUM | Runtime wiring unproven by tests | TEST-4, TEST-5, TEST-8 | confirmed |
| AUDIT-026 | LOW | Tracked bytecode | CQ-20, SEC-17, DEP-7 | confirmed |
| AUDIT-027 | LOW | Duplicated rules and formats | CQ-16..CQ-18 | partly confirmed |
| AUDIT-028 | LOW | Unwired code and caller-less tools in the bundle | CQ-19, REL-2 | accepted |
| AUDIT-029 | LOW | `rotate-env-credential` residuals | SEC-13, REL-7 | accepted |
| AUDIT-030 | LOW | Evidence capture: narrow redaction, UUIDs, failures as data | SEC-11, SEC-12, TEST-5, CQ-6, CQ-14, CQ-15 | accepted |
| AUDIT-031 | LOW | Minor hardening gaps | SEC-14, SEC-15, SEC-18 | read |
| AUDIT-032 | LOW | Undeclared tool-chain | DEP-5, CQ-21, CQ-24 | observed |
| AUDIT-033 | LOW | Bundle on max2 owned by a non-root account | lead | **measured** |

Specialist findings not carried into `findings.json`, with the reason:

| Source ID | Reason |
|---|---|
| TEST-6 | Partly incorrect (three compose tests do render with `docker compose config`); remainder kept as a debt note |
| SEC-10 | Documented as a heuristic in the code itself; low impact |
| REL-3 | Marker without `fsync`: power-loss only; noted in testing.md |
| CQ-23, CQ-25 | Parser and complexity observations; kept as debt notes |
| DEP-6 | Forgejo server version: not measurable from the repository; listed as an open question |

## Limits

- All test execution happened on macOS; the target hosts are Ubuntu. After the first report a small set
  of read-only host and API measurements was made at the owner's request (see verification.md).
- Reproductions of controller behaviour used the repository's fake adapters, not Docker.
- No registry or advisory database was consulted; no CVE is asserted.
- The documents under `docs/forgejo-runner-pool/` were read selectively, where a claim needed checking.
- Line references are valid for commit `4d9f873`.
