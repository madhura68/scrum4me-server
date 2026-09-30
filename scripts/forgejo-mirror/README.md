# Forgejo → GitHub nightly mirror

`forgejo-mirror-sync.sh` (+ `forgejo-mirror-lib.sh`) runs nightly as `forgejo-mirror-sync.service`
(user `forgejo-mirror`, timer 02:30 UTC ±5 min, env from `/etc/forgejo-mirror/{forgejo,github}.env`).
Per repository: check that a GitHub counterpart exists, check the GitHub default branch,
ensure a Forgejo push mirror, trigger a sync, then verify SHA and tags. Installed copies live in
`/srv/scrum4me/scripts/`; this directory is the source (imported 2026-09-30, until then only on
the host).

## Install

    install -m 755 forgejo-mirror-sync.sh forgejo-mirror-lib.sh /srv/scrum4me/scripts/
    sha256sum /srv/scrum4me/scripts/forgejo-mirror-*.sh forgejo-mirror-*.sh

## Test without side effects

    sudo -u forgejo-mirror env REPOS_FILTER=<repo> DRY_RUN=1 /srv/scrum4me/scripts/forgejo-mirror-sync.sh

Run it as `forgejo-mirror`: the lock file `/var/lock/forgejo-mirror-sync.lock` belongs to that user,
and root gets `Permission denied` on it (protected_regular).

## Known failures

| Symptom | Cause | Fix |
|---|---|---|
| `ERROR … default branch '<x>' ≠ Forgejo '<y>'`; before 2026-09-30 this showed as `trigger_sync … http=500` ×3 | The GitHub default branch points to a branch that no longer exists in Forgejo; the mirror wants to delete it and GitHub refuses (`refusing to delete the current branch`) | On GitHub: Settings → Default branch → `<y>`, then run again and `systemctl reset-failed forgejo-mirror-sync` |
| `SKIP … bevat .github/workflows` | The default PAT lacks the Workflows scope | Set `GH_TOKEN_<REPO>` in `github.env` with workflow scope |
| `GitHub counterpart ontbreekt` | No GitHub repo | Create it on GitHub (empty, same visibility) |

## Token hygiene

No token appears in any process argv or URL (compare ISS-41/ISS-43):

- `fj`/`gh` pass the `Authorization` header to curl through `-K <(…)` (a process-substitution
  pipe, never `-H` in argv).
- The push-mirror payload (which contains the GitHub token as `remote_password`) is built by `jq`
  from the environment (`$ENV.GH_TOKEN`) and sent on curl's stdin (`--data-binary @-`).
- `tags_fallback` clones/fetches/pushes with URLs without userinfo; credentials come from a
  `GIT_ASKPASS` helper in a 0700 `mktemp -d` that is removed on exit. The bare clone's
  `remote.origin.url` never holds a credential; an existing clone that still has one from an older
  version is rewritten with `git remote set-url` on the next run.

Tests: `bats scripts/tests/test_forgejo_mirror.bats` (fake curl/git/flock, no network).
