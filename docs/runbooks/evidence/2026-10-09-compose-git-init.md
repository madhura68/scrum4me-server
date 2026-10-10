# Compose-git — de twee resterende mappen, 9 oktober 2026

Hoort bij T-135 (scrum4me-server PBI-23, ST-036), ISS-5 en max2 ISS-15, en bij stap 4 van
`docs/superpowers/specs/2026-09-28-compose-kopieen-structureel-design.md`. Vervolg op
[2026-09-28-compose-git-init.md](2026-09-28-compose-git-init.md).

**Stand.** Alle drie de mappen staan nu onder git.

| Host | Map | Uitkomst |
|---|---|---|
| scrum4me-server | `/srv/scrum4me/compose` | sinds 2026-09-28, eerste commit `67c1c43` |
| scrum4me-server | `/srv/scrum4me/forgejo` | repo gemaakt op 2026-10-09, eerste commit `89a1b4a` |
| max2 | `/srv/scrum4me/compose` | repo gemaakt op 2026-10-09, eerste commit `93e4137` |

**Voorwaarden.** Op max2 is de opruiming (T-134) klaar: zie
[2026-10-09-compose-opruiming-max2.md](2026-10-09-compose-opruiming-max2.md). De forgejo-map werd op
28 september overgeslagen omdat een andere sessie hem toen wijzigde. Op 9 oktober is `docker-compose.yml`
daar sinds 2026-09-30 ongewijzigd (de upgrade naar Forgejo 15.0.9 is afgerond). De kopie
`docker-compose.yml.bak-throttle-…` bestaat niet meer, en onder `/srv` op scrum4me-server staat geen
losse compose-kopie. Vlak vóór de installatie zijn de hashes opnieuw getoetst.

**Gereedschap.** `scripts/compose-git-init` en `scripts/compose-git-pre-commit` uit `main@c318e50`, sha256
`5d1e70633a0e…` en `51d6eac0e0b9…`. Ze zijn byte-gelijk aan de versie van 28 september, en de kopieën in
de tijdelijke map op beide hosts waren dat ook. Het ontwerp is gelijk aan de pin `c5c60a9a…`. De
tijdelijke mappen zijn na afloop verwijderd.

Dit bestand bevat alleen namen, hashes en aantallen.

## Natoets

| Natoets | forgejo (scrum4me-server) | compose (max2) |
|---|---|---|
| Droogloop noemt alleen de allowlist | ja | ja |
| `git ls-files` = allowlist + `.gitignore` | `docker-compose.yml`, `runner-config.yaml` | `docker-compose.yml`, `docker-compose.override.yml`, `docker-compose.codex.yml` |
| `git status --porcelain` leeg | ja | ja |
| `.git` mode 700, `janpeter:janpeter` | ja | ja |
| Hook byte-gelijk aan de bron en uitvoerbaar | ja | ja |
| sha256 van de live bestanden voor en na gelijk | ja | ja |
| `docker compose … config -q` slaagt | ja | ja (alle drie de bestanden, met `sudo` voor de `.env`) |
| `docker compose ls --all` voor en na gelijk | ja | ja |
| Een gewone `git add .env` wordt geweigerd, index blijft leeg | ja | ja |
| Geen remote | ja | ja |
| Containers | `scrum4me-forgejo` healthy, runner en dind Up | ongewijzigd |

sha256 van de live bestanden, voor en na gelijk:

```text
360dbe9d91afb4acece76022bdb4368954c2929cf640acab9a7f2acf4717a637  scrum4me-server /srv/scrum4me/forgejo/docker-compose.yml
873a480089b4075f64ac7fbfbd548983ccbe450e46c1836945668e517bc0e69a  scrum4me-server /srv/scrum4me/forgejo/runner-config.yaml
7885614b3faad3656c4faea08bb8f774721e5a478e569aaebbcd90fc3ac8f79b  max2 /srv/scrum4me/compose/docker-compose.yml
1ff8ee24d6c65c10d2e8caba5d7c6368258711a87a583c746a18d1e816469320  max2 /srv/scrum4me/compose/docker-compose.override.yml
96bc7e9bee5d34457c45a3c4a03e06107c7e1b7059deb72cd7497e65e751cba9  max2 /srv/scrum4me/compose/docker-compose.codex.yml
```

Wat git negeert, alleen namen:

- forgejo (scrum4me-server): `.env`, `test/`, `workflow-templates/` en vier bestanden `~forgejo.txt*` en
  `~\forgejo.txt*` die op sleutelparen lijken.
- compose (max2): `.env`, drie `.env.bak.*`, `worker-codex.env`, `worker-idea.env` en hun backups (8 in totaal).

## Scanner

Ops-dashboard `deploy/ops-agent/check-compose-collision.sh` op `main@c9b6722`, sha256 `4b2f739bea75…`,
droogloop met `DRIFT_NO_NOTIFY=1`, na de installatie:

| Host | Bestanden | Destructief | Waarschuwingen | Exitcode |
|---|---|---|---|---|
| scrum4me-server | 11 | 0 | 2 | 0 |
| max2 | 11 | 0 | 1 | 0 |

Het aantal destructieve bevindingen is niet gestegen: 0 op beide hosts.

## Stap 9: nachtelijke runs van 10 oktober

**Uitkomst: groen.** Geen rapport noemt iets wat met de git-repo's in de compose-mappen te maken heeft.

| Host | `ops-agent-drift`, 2026-10-09 | `ops-agent-drift`, 2026-10-10 | Verschil |
|---|---|---|---|
| max2 (00:14 / 00:08) | 1 bestand, 2 hunks (`commands.yml`) | 1 bestand, 2 hunks (`commands.yml`) | geen; ook 2026-10-08 gelijk |
| scrum4me-server (00:01 / 00:10) | 14 bestanden, 17 hunks: 5 config, 5 repo-vs-runtime, 4 installed-build | 5 bestanden, 5 hunks: 0 config, 0 repo-vs-runtime, 5 installed-build | verklaard, zie hieronder |

**scrum4me-server.** Op 2026-10-09 rond 09:36 CEST is de runtime-baseline gesynchroniseerd met
`apply-drift-runtime.sh` (opdracht JP; momentopname `/srv/_attic/2026-10-09/drift-baseline-voor-sync.tar`, 600).
Rond 09:40 kwam het ontbrekende commentaarblok van 4 regels in de live `/etc/ops-agent/commands.yml`. Inode,
eigenaar en mode bleven gelijk en de geparste YAML is identiek, dus zonder restart (momentopname
`/srv/_attic/2026-10-09/ops-agent-commands-voor-commentaar.tar`, 600). Daardoor gingen config en repo-vs-runtime
naar 0. De overgebleven vijf rijen zijn allemaal `build:`: de installatie onder `/opt/ops-agent` loopt achter op de
bron. Die laag stond er de nachten ervoor al (4 rijen). De vijfde rij (`wrappers/skills/verify-worker-skills.sh`)
komt doordat de bron-checkout naar `main@c9b6722` is gegaan. Oplossen vraagt een herinstallatie via
`deploy/ops-agent/setup.sh` met een eigen restartvenster; dat valt buiten deze taak. De handmatige controle van
2026-10-09 meldde "no drift" omdat `OPS_AGENT_SRC_DIR` niet gezet was en de build-laag dus werd overgeslagen.

**Werkbomen, 2026-10-10 ochtend.**

| Host | Map | `git status --porcelain` | HEAD |
|---|---|---|---|
| scrum4me-server | `/srv/scrum4me/compose` | leeg | `939fcf8` "Bump CLI-pins: Claude Code 2.1.287, Codex 0.160.0" (2026-10-09 12:01, 1 bestand) |
| scrum4me-server | `/srv/scrum4me/forgejo` | leeg | `89a1b4a` (eerste commit) |
| max2 | `/srv/scrum4me/compose` | leeg | `93e4137` (eerste commit) |

De commit `939fcf8` is de eerste gewone wijziging via de nieuwe route: een commit, en geen kopie ernaast.
Onder `/srv` staat op beide hosts geen losse compose-kopie.

**Deploy-flows.** Sinds de installatie (FlowRun in `ops_dashboard` op scrum4me-server, laatste 30 uur):
`update_scrum4me_workers` op `srv` om 2026-10-09 08:18 en 18:28 CEST, beide `success`, exit 0. Ze draaiden in
`/srv/scrum4me/compose` met `.git` aanwezig. Op max2 liep in dat venster geen flow.
