# Forgejo → GitHub nightly mirror

`forgejo-mirror-sync.sh` (+ `forgejo-mirror-lib.sh`) runs nightly as `forgejo-mirror.service`
(user `forgejo-mirror`, timer ~02:30, env from `/etc/forgejo-mirror/{forgejo,github}.env`).
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

Note: `fj`/`gh` put the token in curl's argv (`-H "Authorization: …"`), which `ps` can see while
it runs. Compare ISS-41/ISS-43; moving to `-H @file` is an open improvement.
