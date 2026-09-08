# Stap D — bring-up-resultaat (max2)

**Datum:** 8 september 2026. **Host:** `max2` (via `ssh janpeter@max2`). **Uitvoerder:** mac:claude, op instructie van JP.
**Runner:** `max2-forgejo-runner-02`, type global, labels `[ubuntu-latest]`. (De host-UUID staat bewust NIET in Git — CLAUDE.md-hardstop; die leeft alleen in `runner-config.yml` op de host.)
**Bundel-commit:** `85153f2` (`/opt/forgejo-runner/BUNDLE_COMMIT`). Procedure: `bring-up-runbook.md`.

## §1 preflight (§7.8-headroomgate) — exit 0
Verse hostfeiten op max2 (caveat: video-editor-stack lag plat, ISS-7 → dit is de favorabele kant van de productielast; JP heeft "preflight as-is met caveat" bewust aanvaard):
```
vcpu: OK — som 12.5 binnen 50% van 28
geheugen: OK — som 6442450944 binnen 50% van 21843079168
schijf: OK — 25% vrij en 242513588224 bytes >= 23203885056 nodig
inodes: OK — 92% vrij
```

## §4 argv-sanity (§6.2) — binary-pad + config-load
`docker inspect` op de gepinde runnerimage: `Entrypoint=null Cmd=["/bin/forgejo-runner"]`.
De config-loze `one-job --wait` gaf zoals verwacht `Error: … 0 connections are configured`, exit 1 (bewijst enkel dat het binary-pad klopt). **Bug gevonden (ISS-15):** het compose-`command` miste `-c`, dus de runner laadde `runner-config.yml` niet → 0 connections → nooit online. Gefixt (PR #18, `-c /etc/forgejo-runner/config.yml`); daarna laadt de config aantoonbaar (zie §5).

## §2 trust-verdict (§6.3) — ok:true, gebonden
`trust-verdict-published.json` (deze map): `ok:true`, `measured_at 1788869447`, target `https://git.jp-visser.nl`, `labels_sha256`/`allowlist_sha256` gevuld. De gedeployde `labels.txt`/`trusted-actions-scope.yml` hashten identiek → binding matcht → de controller-`TrustVerdict` accepteert het. Om groen te krijgen ruimde JP 3 HARD-repos op (o.a. `s4us-smoke-bot/s4us-smoke` verwijderd) + branch-protection/Actions-uit op de rest (de deploy-wrapper publiceert alleen bij CLI-exit 0 = 0 hard + 0 soft).

## §5 runner online — declared successfully
Controllerjournal bij koude start: `SOURCE_WAIT` → 2× `READY` → `scrub ok=True` → `cyclus: runner gestart` →
```
runner: max2-forgejo-runner-02, with version: v12.10.1, with labels: [ubuntu-latest], ephemeral: false, declared successfully
single task poller launched
```
Forgejo Site-Admin → Runners: `max2-forgejo-runner-02` online/idle (door JP bevestigd). Beide runners delen nu de pool (runner-01 blijft tot stap G).

## §5.1 C1 fail-closed (de Critical uit de final review) — bewezen
1. Vóór de crash zag de **label-filtered** `docker ps -a` de one-off runnercontainer; `docker compose -p forgejo-runner ps -q runner` was er **blind** voor (precies het lek).
2. `systemctl kill -s SIGKILL` → `code=killed, status=9/KILL`, `Failed with result 'signal'`.
3. De runnercontainer **overleefde** (geen `--rm`), zelfde container-id.
4. Auto-restart (Restart=on-failure) → startup-reconciliatie logde `WARNING startup: achtergebleven runner — fail-closed` en startte **geen 2e** runner (count bleef 1).
5. Na `docker rm -f` van de leftover + schone restart: reconciliatie clean → runner weer online.

## §7 nette SIGTERM-stop (§9) — schoon
`systemctl stop` (idle): `ExecMainStatus=0`, `Result=success`, `ActiveState=inactive`; geen leftover-runnercontainer (count 0); geen operatie-marker (`/opt/forgejo-runner/state/cycle-op.marker` afwezig). Daarna herstart → weer online.

## verify-stack (§6.1/§7.5) — groen (als root)
```
commit: 85153f2c34477ce047bbdbeee6e013677bf1ec2c
bundel_hash: b50df893e1ae9ed6c74f19b2c1a332d2182c75379d56287492d697ac1b6cca26
isolatie: OK
```
Geen hostlistener op 2375/2376 (`ss -ltn` leeg). **Klein restpunt:** `bundle-hash.sh` gebruikt `! -path` i.p.v. `-prune`, dus het faalt als non-root op de `0700 credentials/`-dir (find: Permission denied → pipefail); als root werkt het. Aparte follow-up (excluded dirs prunen).

## Slot
Stap D bereikt: eigen runner op max2 online en bewezen (zie ook `../stap-e/smoke-resultaat.md`). Controller-unit `enabled` (start bij boot).
