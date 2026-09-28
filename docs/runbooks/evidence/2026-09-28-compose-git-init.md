# Compose-git — installatie op scrum4me-server, 28 september 2026

Hoort bij T-135 (scrum4me-server PBI-23, ST-036) en bij stap 4 van
`docs/superpowers/specs/2026-09-28-compose-kopieen-structureel-design.md`.

**Stand.** Eén van de drie mappen staat onder git. De andere twee zijn bewust niet aangeraakt.

| Host | Map | Uitkomst |
|---|---|---|
| scrum4me-server | `/srv/scrum4me/compose` | repo gemaakt, eerste commit `67c1c43` |
| scrum4me-server | `/srv/scrum4me/forgejo` | niet aangeraakt: een andere sessie was er op dat moment bezig |
| max2 | `/srv/scrum4me/compose` | niet aangeraakt: de opruiming (T-134) is daar nog niet gedaan |

**Gereedschap.** `scripts/compose-git-init` en `scripts/compose-git-pre-commit` op
`main@147d1d29e8ad4dc2ab3b6a1017738639c6d234cb`, sha256 `5d1e70633a0e…` en `51d6eac0e0b9…`. De kopieën
op de host waren byte-gelijk. Het ontwerp is vooraf gecontroleerd tegen de pin `c5c60a9a…`.

Dit bestand bevat alleen namen, hashes en aantallen.

## `/srv/scrum4me/compose` op scrum4me-server

| Natoets | Uitkomst |
|---|---|
| `git ls-files` toont precies de allowlist en `.gitignore` | ja |
| `git status --porcelain` is leeg | ja |
| `.git` heeft mode 700 | ja |
| De hook is byte-gelijk aan de bron en uitvoerbaar | ja |
| sha256 van `docker-compose.yml` voor en na gelijk | ja, `8e82fa13…` |
| `docker compose -f <bestand> config -q` slaagt | ja (met `sudo`, want de `.env` is van `ops-agent`) |
| `docker compose ls --all` voor en na gelijk | ja |
| Zelfde 22 containers, alle `Up` | ja |
| Een gewone `git add .env` wordt geweigerd | ja |
| Geen remote | ja |

Git negeert in deze map dertien bestanden: de `.env`, de vier `worker-*.env` en hun backups.

## Waarom de forgejo-map is overgeslagen

Tussen de eerste meting (17:23:12Z) en de droogloop (17:24:22Z) veranderde de map:

| Tijd (UTC) | Wat |
|---|---|
| 17:13:31 | `.env` gewijzigd |
| 17:23:38 | `docker-compose.yml` gewijzigd; sha256 van `6702bd8a…` naar `52cbca21…` |
| 17:23:38 | nieuwe kopie `docker-compose.yml.bak-throttle-20260928T172338Z`, sha256 `6702bd8a…` |

De kopie is de inhoud van vóór de wijziging. Een sessie op de host was dus op dat moment met de
forgejo-stack bezig. Een repo aanmaken midden in andermans wijziging zou een tussenstand als
eerste commit vastleggen. De map is daarom niet aangeraakt, en de kopie ook niet: de andere
sessie kan hem nodig hebben om terug te draaien, en verwijderen vraagt een goedgekeurde lijst.

**Gevolg voor de scanner.** De droogloop geeft nu 1 destructieve bevinding: deze kopie. Na de
opruiming van 16:40Z stond de teller op 0. De opruiming hield dus 43 minuten. Dat komt niet door
de installatie van git; het is de oorzaak waar stap 5 (de hostregel) voor bedoeld is.

## Waarom max2 is overgeslagen

Het plan van T-135 vraagt dat de opruiming op de host klaar is. Op max2 staan nog 24 losse
kopieën in `/srv/scrum4me/compose`; T-134 is niet uitgevoerd.

## Raakt dit een bestaande flow?

Read-only nagegaan in `/etc/ops-agent/commands.yml` op beide hosts: 16 commando's op
scrum4me-server en 14 op max2 noemen een live compose-map. Geen ervan draait git in die map. De
commando's met die map als werkmap zijn `docker` en `sh`. Geen enkele build-context wijst naar
de compose-map zelf, dus `.git` komt niet in een build terecht.

De drift-checker leest alleen `/etc/ops-agent` en de baseline. Hij kijkt niet in de compose-map.

**Nog niet bewezen.** Het plan vraagt de eerstvolgende run van `ops-agent-drift` en van de
deploy-flows te volgen. Die run is vannacht rond 00:01 CEST. Een handmatige droogloop van de
drift-checker gaf 5 bestanden met drift in `/etc/ops-agent`; vannacht meldde hij 3 rijen van een
andere soort. Dat verschil komt door wijzigingen van vandaag aan de ops-agent-configuratie en
zegt niets over git. De vergelijking "wijkt niet af van de vorige run" is daardoor niet zuiver
te maken.

Bijvangst: `commands.yml` regel 224 op scrum4me-server zegt in commentaar dat het
compose-bestand niet in git staat. Dat klopt sinds vandaag niet meer. Het commentaar staat ook
in de baseline en is niet gewijzigd.

## Stand vooraf, scrum4me-server

```text
=== scrum4me-server 2026-09-28T17:23:12Z ===
git: git version 2.53.0  python3: Python 3.14.4  gebruiker: janpeter
--- map /srv/scrum4me/compose ---
janpeter:janpeter 755 /srv/scrum4me/compose
git-werkboom: fatal: not a git repository (or any of the parent directories): .git
.git aanwezig: nee
.gitignore aanwezig: nee
inhoud (namen, eigenaar, mode):
  -rw------- ops-agent:ops-agent .env  
  -rw------- ops-agent:ops-agent .env.bak-pre-m38  
  -rw------- root:root .env.bak.20260527T033500Z  
  -rw------- root:root .env.bak.20260527T081846Z  
  -rw------- ops-agent:ops-agent .env.bak.mcppin-20260925T103218Z  
  -rw-rw-r-- janpeter:janpeter docker-compose.yml  
  -rw------- ops-agent:ops-agent worker-codex.env  
  -rw------- ops-agent:ops-agent worker-codex.env.bak.20260924T155947Z  
  -rw------- ops-agent:ops-agent worker-deploy.env  
  -rw------- ops-agent:ops-agent worker-deploy.env.bak.20260924T155947Z  
  -rw------- ops-agent:ops-agent worker-docs.env  
  -rw------- ops-agent:ops-agent worker-docs.env.bak.20260924T155947Z  
  -rw------- ops-agent:ops-agent worker-idea.env  
  -rw------- ops-agent:ops-agent worker-idea.env.bak.20260924T155947Z  
--- map /srv/scrum4me/forgejo ---
janpeter:janpeter 775 /srv/scrum4me/forgejo
git-werkboom: fatal: not a git repository (or any of the parent directories): .git
.git aanwezig: nee
.gitignore aanwezig: nee
inhoud (namen, eigenaar, mode):
  -rw------- janpeter:janpeter .env  
  -rw-rw-r-- janpeter:janpeter docker-compose.yml  
  -rw-rw-r-- janpeter:janpeter runner-config.yaml  
  drwxrwxr-x janpeter:janpeter test  
  drwxrwxr-x janpeter:janpeter workflow-templates  
  -rw------- janpeter:janpeter ~\forgejo.txt  
  -rw-r--r-- janpeter:janpeter ~\forgejo.txt.pub  
  -rw------- janpeter:janpeter ~forgejo.txt  
  -rw-r--r-- janpeter:janpeter ~forgejo.txt.pub  
--- docker compose ls --all ---
NAME                STATUS              CONFIG FILES
compose             running(13)         /srv/scrum4me/compose/docker-compose.yml
forgejo             running(3)          /srv/scrum4me/forgejo/docker-compose.yml
scrum4us            running(6)          /srv/scrum4us/checkout/infra/compose/docker-compose.srv.yml
scrum4us-dev        exited(1)           /tmp/claude-1000/-home-janpeter-claude/8201fb25-3e30-472e-8135-91402e36345d/scratchpad/s4u/infra/compose/docker-compose.dev.yml
--- losse compose-kopieen met suffix onder /srv ---
--- ops-agent: commando's en flows die deze mappen noemen (alleen regelnummers en sleutels) ---
  /etc/ops-agent/commands.yml: 17 regel(s)
  /etc/ops-agent/flows/redeploy_all.yml: 1 regel(s)
  git-commando's met een van deze mappen als werkmap:
34:136-        merge_subject="$(git -C "$repo" log --merges -1 --pretty=%s)" &&
46:161-        commit="$(git -C "$repo" rev-parse HEAD)" &&
47:162-        epoch="$(git -C "$repo" show -s --format=%ct HEAD)" &&
57:172-    description: "Pin MCP_GIT_REF forward to the current scrum4me-mcp main tip (reuses an existing deploy/* tag on that commit; never moves one)"
98:224:        # (/srv/scrum4me/compose/docker-compose.yml) staat NIET in git — hij wordt
--- ops-agent-drift: laatste run ---
NEXT                             LEFT LAST                          PASSED UNIT                          ACTIVATES
Tue 2026-09-29 00:01:29 CEST 4h 38min Mon 2026-09-28 00:01:47 CEST 19h ago ops-agent-drift.timer         ops-agent-drift.service
Tue 2026-09-29 00:45:36 CEST 5h 22min Mon 2026-09-28 00:39:48 CEST 18h ago compose-collision-check.timer compose-collision-check.service
```

## Stand vooraf, max2 (de 24 losse kopieën zijn weggelaten)

```text
=== max2 2026-09-28T17:23:15Z ===
git: git version 2.53.0  python3: Python 3.14.4  gebruiker: janpeter
--- map /srv/scrum4me/compose ---
janpeter:janpeter 755 /srv/scrum4me/compose
git-werkboom: fatal: not a git repository (or any of the parent directories): .git
.git aanwezig: nee
.gitignore aanwezig: nee
inhoud (namen, eigenaar, mode):
  -rw------- ops-agent:sambashare .env  
  -rw------- root:root .env.bak.20260527T033500Z  
  -rw------- root:root .env.bak.20260527T081846Z  
  -rw------- ops-agent:sambashare .env.bak.20260909-211140  
  -rw-r--r-- janpeter:janpeter docker-compose.codex.yml  
  -rw-r----- janpeter:ops-agent docker-compose.override.yml  
  -rw-rw-r-- janpeter:janpeter docker-compose.yml  
  -rw------- ops-agent:ops-agent worker-codex.env  
  -rw------- ops-agent:ops-agent worker-codex.env.bak.20260924T155954Z  
  -rw------- ops-agent:sambashare worker-idea.env  
  -rw------- ops-agent:sambashare worker-idea.env.bak.20260924T155954Z  
--- docker compose ls --all ---
NAME                           STATUS                  CONFIG FILES
deepseek-harness               running(1)              /home/janpeter/Development/max2/deepseek-harness/docker-compose.yml
forgejo-runner                 running(2)              /opt/forgejo-runner/compose.yaml
media-organizer                exited(1), running(4)   /srv/apps/media-organizer/.media-deploy.ZjIcgmGa/source/deploy/docker-compose.yml,/srv/apps/media-organizer/.media-deploy.mc2gXMZi/source/deploy/docker-compose.yml
media-organizer-idea211-test   exited(3)               /srv/apps/media-organizer/idea211-test/artifacts/test-stack.compose.yml,/srv/apps/media-organizer/idea211-test/secrets/private-media.override.json,/srv/apps/media-organizer/idea211-test/artifacts/test-stack.worker-direct.override.yml,/srv/apps/media-organizer/idea211-test/evidence/web-image-542d9cf-20260912T183812Z/web-image.override.yml,/srv/apps/media-organizer/idea211-test/evidence/web-image-28721e5-20260912T191309Z/web-image.override.yml,/srv/apps/media-organizer/idea211-test/evidence/web-image-bcc20b3-20260912T195719Z/web-image.override.yml
open-webui                     running(1)              /home/janpeter/Development/max2/open-webui/docker-compose.yml
scrum4me                       running(5)              /srv/scrum4me/compose/docker-compose.yml,/srv/scrum4me/compose/docker-compose.override.yml,/srv/scrum4me/compose/docker-compose.codex.yml
tei-gpu                        exited(1)               /srv/apps/tei/docker-compose.yml
video-editor                   exited(6)               /var/tmp/ve-3e13074/compose.yaml,/var/tmp/ve-ecb97f1/compose.yaml
when2watch                     running(2)              /srv/apps/when2watch/releases/5dd8b3f/compose.yaml
--- losse compose-kopieen met suffix onder /srv ---
  /srv/apps/media-organizer/repo/deploy/docker-compose.override.yml.retired.20260605-220404
  /srv/apps/media-organizer/repo/deploy/docker-compose.yml.bak.20260710T011238
  /srv/apps/tei/docker-compose.yml.bak.lanswitch.20260919T232455Z
  /srv/immich/docker-compose.override.yml.bak.20260531
  /srv/immich/docker-compose.yml.bak.20260531
  /srv/scrum4me/backups/forgejo-pre-v15-2026-05-16/docker-compose.yml.bak
  /srv/scrum4me/compose/docker-compose.codex.yml.bak.20260928T002106-workerdb
  /srv/scrum4me/compose/docker-compose.codex.yml.bak.clipins-20260927T114828Z
  /srv/scrum4me/compose/docker-compose.codex.yml.bak.pre-clibump-20260711T213336
  /srv/scrum4me/compose/docker-compose.codex.yml.bak.pre-rename-20260711T063757
  /srv/scrum4me/compose/docker-compose.override.yml.bak.1780161296
  /srv/scrum4me/compose/docker-compose.override.yml.bak.iss1-20260925T173506Z
  /srv/scrum4me/compose/docker-compose.override.yml.bak.lanswitch.20260919T232455Z
  /srv/scrum4me/compose/docker-compose.override.yml.bak.pre-rename-20260711T063757
  /srv/scrum4me/compose/docker-compose.yml.bak.20260522-234028
  /srv/scrum4me/compose/docker-compose.yml.bak.20260525-195132
  /srv/scrum4me/compose/docker-compose.yml.bak.20260526-202520
  /srv/scrum4me/compose/docker-compose.yml.bak.20260526-213957
  /srv/scrum4me/compose/docker-compose.yml.bak.20260526-223242
  /srv/scrum4me/compose/docker-compose.yml.bak.20260527-110826
  /srv/scrum4me/compose/docker-compose.yml.bak.20260527T032419Z
  /srv/scrum4me/compose/docker-compose.yml.bak.20260527T051630Z
  /srv/scrum4me/compose/docker-compose.yml.bak.20260527T082707Z
  /srv/scrum4me/compose/docker-compose.yml.bak.20260528-213943
  /srv/scrum4me/compose/docker-compose.yml.bak.20260928T002106-workerdb
  /srv/scrum4me/compose/docker-compose.yml.bak.clipins-20260927T114828Z
  /srv/scrum4me/compose/docker-compose.yml.bak.iss35-20260927T133213Z
  /srv/scrum4me/compose/docker-compose.yml.bak.pre-clibump-20260711T213336
  /srv/scrum4me/compose/docker-compose.yml.bak.pre-pgbind-fix-20260601
  /srv/scrum4me/compose/docker-compose.yml.bak.pre-rename-20260711T063757
--- ops-agent: commando's en flows die deze mappen noemen (alleen regelnummers en sleutels) ---
  /etc/ops-agent/commands.yml: 21 regel(s)
  git-commando's met een van deze mappen als werkmap:
71:559-        commit="$(git -C "$repo" rev-parse HEAD)" &&
72:560-        epoch="$(git -C "$repo" show -s --format=%ct HEAD)" &&
91:586-    description: "Pin MCP_GIT_REF forward to the current scrum4me-mcp main tip (reuses an existing deploy/* tag on that commit; never moves one)"
--- ops-agent-drift: laatste run ---
NEXT                             LEFT LAST                          PASSED UNIT                          ACTIVATES
Tue 2026-09-29 00:08:16 CEST 4h 45min Mon 2026-09-28 00:13:55 CEST 19h ago ops-agent-drift.timer         ops-agent-drift.service
Tue 2026-09-29 00:37:25 CEST 5h 14min Mon 2026-09-28 00:35:20 CEST 18h ago compose-collision-check.timer compose-collision-check.service
```

## ops-agent-commando's die een live compose-map noemen

```text
=== scrum4me-srv ===
  docker_compose_restart: programma=docker cwd="/srv/scrum4me/compose" git-in-de-tekst=nee git-op-de-compose-map=nee
  docker_compose_stop: programma=docker cwd="/srv/scrum4me/compose" git-in-de-tekst=nee git-op-de-compose-map=nee
  docker_compose_build: programma=docker cwd="/srv/scrum4me/compose" git-in-de-tekst=nee git-op-de-compose-map=nee
  docker_compose_build_scrum4me_workers_with_metadata: programma=sh cwd=- git-in-de-tekst=ja git-op-de-compose-map=nee
  docker_compose_build_ops_dashboard_with_metadata: programma=sh cwd=- git-in-de-tekst=ja git-op-de-compose-map=nee
  cut_mcp_release_tag: programma=bash cwd=- git-in-de-tekst=nee git-op-de-compose-map=nee
  verify_mcp_release_ref: programma=bash cwd=- git-in-de-tekst=nee git-op-de-compose-map=nee
  docker_compose_build_worker_fresh: programma=sh cwd="/srv/scrum4me/compose" git-in-de-tekst=nee git-op-de-compose-map=nee
  docker_compose_up: programma=docker cwd="/srv/scrum4me/compose" git-in-de-tekst=nee git-op-de-compose-map=nee
  docker_compose_up_recreate: programma=docker cwd="/srv/scrum4me/compose" git-in-de-tekst=nee git-op-de-compose-map=nee
  docker_compose_ps_worker: programma=docker cwd="/srv/scrum4me/compose" git-in-de-tekst=nee git-op-de-compose-map=nee
  wait_for_health_worker: programma=sh cwd="/srv/scrum4me/compose" git-in-de-tekst=nee git-op-de-compose-map=nee
  docker_compose_scale_worker_idea: programma=docker cwd="/srv/scrum4me/compose" git-in-de-tekst=nee git-op-de-compose-map=nee
  docker_compose_build_codex_fresh: programma=sh cwd="/srv/scrum4me/compose" git-in-de-tekst=nee git-op-de-compose-map=nee
  docker_compose_recreate_agent_codex: programma=docker cwd="/srv/scrum4me/compose" git-in-de-tekst=nee git-op-de-compose-map=nee
  docker_compose_scale_agent_codex: programma=docker cwd="/srv/scrum4me/compose" git-in-de-tekst=nee git-op-de-compose-map=nee
  totaal: 16 commando('s) noemen een live compose-map
=== max2 ===
  docker_compose_restart: programma=docker cwd="/srv/scrum4me/compose" git-in-de-tekst=nee git-op-de-compose-map=nee
  docker_compose_stop: programma=docker cwd="/srv/scrum4me/compose" git-in-de-tekst=nee git-op-de-compose-map=nee
  docker_compose_build: programma=docker cwd="/srv/scrum4me/compose" git-in-de-tekst=nee git-op-de-compose-map=nee
  docker_compose_build_worker_fresh: programma=sh cwd="/srv/scrum4me/compose" git-in-de-tekst=nee git-op-de-compose-map=nee
  docker_compose_up: programma=docker cwd="/srv/scrum4me/compose" git-in-de-tekst=nee git-op-de-compose-map=nee
  docker_compose_up_recreate: programma=docker cwd="/srv/scrum4me/compose" git-in-de-tekst=nee git-op-de-compose-map=nee
  docker_compose_ps_worker: programma=docker cwd="/srv/scrum4me/compose" git-in-de-tekst=nee git-op-de-compose-map=nee
  compose_build_ops_dashboard_with_metadata: programma=sh cwd=- git-in-de-tekst=ja git-op-de-compose-map=nee
  verify_mcp_release_ref: programma=bash cwd=- git-in-de-tekst=nee git-op-de-compose-map=nee
  cut_mcp_release_tag: programma=bash cwd=- git-in-de-tekst=nee git-op-de-compose-map=nee
  build_worker_idea_fresh: programma=docker cwd=- git-in-de-tekst=nee git-op-de-compose-map=nee
  scale_worker_idea: programma=docker cwd=- git-in-de-tekst=nee git-op-de-compose-map=nee
  build_codex_worker: programma=docker cwd=- git-in-de-tekst=nee git-op-de-compose-map=nee
  recreate_agent_codex: programma=docker cwd=- git-in-de-tekst=nee git-op-de-compose-map=nee
  totaal: 14 commando('s) noemen een live compose-map
```

## Droogloop

```text
--- op de host ---
5d1e70633a0e232c0b019dbf40111476ffc1a85229bba248c7c5a145cf5cd782  compose-git-init
51d6eac0e0b98e649fb384c8db81aad48b1222c4909949d997201e7d7c86c5d6  compose-git-pre-commit
2026-09-28T17:24:22Z
--- sha256 van de allowlist-bestanden vooraf ---
8e82fa13ada08c87fead137d7e5e71ae1d6244527a4524aa4b1cfe54fbf413e5  /srv/scrum4me/compose/docker-compose.yml
52cbca210efd9534c45949721848e8e5457c32bcbd7a830e658f5de516bd4a6b  /srv/scrum4me/forgejo/docker-compose.yml
873a480089b4075f64ac7fbfbd548983ccbe450e46c1836945668e517bc0e69a  /srv/scrum4me/forgejo/runner-config.yaml
--- build-contexten in de compose-bestanden (alleen het pad) ---
/srv/scrum4me/compose/docker-compose.yml:58: context: /srv/scrum4me/ops-dashboard
/srv/scrum4me/compose/docker-compose.yml:81: context: /srv/scrum4me/repos/scrum4me-docker
/srv/scrum4me/compose/docker-compose.yml:157: context: /srv/scrum4me/repos/scrum4me-docker
/srv/scrum4me/compose/docker-compose.yml:207: context: /srv/scrum4me/repos/scrum4me-docker
/srv/scrum4me/compose/docker-compose.yml:261: context: /srv/scrum4me/repos/scrum4me-docker
/srv/scrum4me/compose/docker-compose.yml:328: context: /srv/scrum4me/repos/scrum4me-workers
/srv/scrum4me/compose/docker-compose.yml:357: context: /srv/scrum4me/repos/scrum4me-mcp
/srv/scrum4me/compose/docker-compose.yml:387: context: /srv/scrum4me/repos/scrum4me-copilot
/srv/scrum4me/compose/docker-compose.yml:409: context: /srv/apps/digiplein/repo
--- droogloop compose ---
droogloop: /srv/scrum4me/compose
  op de allowlist: docker-compose.yml
droogloop: alle toetsen geslaagd; er is niets gewijzigd
exit=0
--- droogloop forgejo ---
droogloop: /srv/scrum4me/forgejo
  op de allowlist: docker-compose.yml
  op de allowlist: runner-config.yaml
droogloop: alle toetsen geslaagd; er is niets gewijzigd
exit=0
--- niets gewijzigd? aantal .git-namen per map ---
0
0
```

## Installatie

```text
2026-09-28T17:25:08Z
--- vlak vooraf ---
5d1e70633a0e232c0b019dbf40111476ffc1a85229bba248c7c5a145cf5cd782  compose-git-init
51d6eac0e0b98e649fb384c8db81aad48b1222c4909949d997201e7d7c86c5d6  compose-git-pre-commit
8e82fa13ada08c87fead137d7e5e71ae1d6244527a4524aa4b1cfe54fbf413e5  /srv/scrum4me/compose/docker-compose.yml
mtime 2026-09-28 00:58:23.389499775 +0200
--- installatie /srv/scrum4me/compose ---
repo gemaakt in /srv/scrum4me/compose, eerste commit 67c1c43
  8e82fa13ada08c87fead137d7e5e71ae1d6244527a4524aa4b1cfe54fbf413e5  docker-compose.yml
hook: 51d6eac0e0b98e649fb384c8db81aad48b1222c4909949d997201e7d7c86c5d6
exit=0
```

## Natoets

```text
=== scrum4me-server 2026-09-28T17:25:26Z ===
--- 1. git ls-files ---
.gitignore
docker-compose.yml
--- 2. git status --porcelain (leeg is goed) ---
regels: 0
--- 3. mode van .git ---
janpeter:janpeter 700 /srv/scrum4me/compose/.git
janpeter:janpeter 664 /srv/scrum4me/compose/.gitignore
--- 4. hook gelijk aan de bron ---
aantal verschillende hashes (1 is goed): 1
uitvoerbaar: ja
--- 5. sha256 van het live bestand, vooraf en nu ---
8e82fa13ada08c87fead137d7e5e71ae1d6244527a4524aa4b1cfe54fbf413e5  /srv/scrum4me/compose/docker-compose.yml
8e82fa13ada08c87fead137d7e5e71ae1d6244527a4524aa4b1cfe54fbf413e5  /srv/scrum4me/compose/docker-compose.yml
--- 6. docker compose config -q ---
slaagt
--- 7. docker compose ls --all gelijk aan vooraf ---
gelijk
--- eerste commit ---
67c1c43 compose-git op scrum4me-server <compose-git@scrum4me-server.invalid> Eerste commit: live compose-bestanden onder versiebeheer
   .gitignore         |   5 +
   docker-compose.yml | 433 +++++++++++++++++++++++++++++++++++++++++++++++++++++
   2 files changed, 438 insertions(+)
--- .gitignore ---
# Allowlist: alles is genegeerd, behalve wat hieronder staat.
# Stage alleen met `git add <bestandsnaam>`, nooit met -f, -A of een punt.
/*
!/.gitignore
!/docker-compose.yml
--- identiteit en remote ---
compose-git op scrum4me-server
remotes: 0
--- wat git negeert in deze map (namen) ---
  !! .env
  !! .env.bak-pre-m38
  !! .env.bak.20260527T033500Z
  !! .env.bak.20260527T081846Z
  !! .env.bak.mcppin-20260925T103218Z
  !! worker-codex.env
  !! worker-codex.env.bak.20260924T155947Z
  !! worker-deploy.env
  !! worker-deploy.env.bak.20260924T155947Z
  !! worker-docs.env
  !! worker-docs.env.bak.20260924T155947Z
  !! worker-idea.env
  !! worker-idea.env.bak.20260924T155947Z
--- gewone add van een .env wordt geweigerd (wijzigt niets) ---
The following paths are ignored by one of your .gitignore files:
.env
exit=1
index na de poging: 0 gestagede paden
--- containers ---
draaiend: 22
alle Up
--- scanner, droogloop ---
[check-compose-collision] scanning 11 compose file(s) under /srv
# compose project-name collisions — 154

Scanned `/srv` (11 compose files).

## (c) Stray file aimed at a project Compose already knows (LIVE FIRE)

**1 file(s) in `/srv/scrum4me/forgejo` aim at project `forgejo`** — DESTRUCTIVE — resolves, and the project is running(3)
  registered config for `forgejo`: `/srv/scrum4me/forgejo/docker-compose.yml`
  - `/srv/scrum4me/forgejo/docker-compose.yml.bak-throttle-20260928T172338Z`
[check-compose-collision] FINDINGS: 1 destructive, 4 warning(s)
**1 file(s) in `/srv/scrum4us/checkout/infra/compose` aim at project `scrum4us-dev`** — warning — resolves, but the project is exited(1)
  registered config for `scrum4us-dev`: `/tmp/claude-1000/-home-janpeter-claude/8201fb25-3e30-472e-8135-91402e36345d/scratchpad/s4u/infra/compose/docker-compose.dev.yml`
  - `/srv/scrum4us/checkout/infra/compose/docker-compose.dev.yml`

## (b) Same container_name across files — warning only, Docker refuses the create

**container_name `scrum4me-forgejo-runner`** — 2 files:
  - `/srv/scrum4me/forgejo/docker-compose.yml`
  - `/srv/scrum4me/forgejo/docker-compose.yml.bak-throttle-20260928T172338Z`
**container_name `scrum4me-forgejo`** — 2 files:
  - `/srv/scrum4me/forgejo/docker-compose.yml`
  - `/srv/scrum4me/forgejo/docker-compose.yml.bak-throttle-20260928T172338Z`
**container_name `scrum4me-forgejo-dind`** — 2 files:
  - `/srv/scrum4me/forgejo/docker-compose.yml`
  - `/srv/scrum4me/forgejo/docker-compose.yml.bak-throttle-20260928T172338Z`

1 destructive, 4 warning(s).

What actually removes this class, in order of effect:
  1. Keep no RUNNABLE copy of a live compose file. A `.bak`/`.orig`/`.broken`
     beside the live `.env` is the sharpest hazard on the host: it inherits the
     project from its directory and it interpolates. Put the history under version
     control, or move it to `_attic/` (excluded from this scan), or store it in a
     form Compose will not run.
  2. An explicit `name:` is a TRADE, not a fix: it stops a directory rename from
     colliding and makes every copy collide instead, wherever it lands. Worth
     having only once no stray copies exist.
  3. Distinct `name:` values for mutually exclusive stacks sharing one directory
     (dev/srv variants) — (a) counts directories and cannot see those.
See the 2026-07-09 incident in the compose-collision runbook.
exit=1
[check-compose-collision] DRIFT_NO_NOTIFY=1 — skipping queue push
```

## Drift-checker en de nieuwe kopie

```text
2026-09-28T17:25:51Z
--- ops-agent-drift: unit ---
Environment=S4M_QUEUE_ENV=/home/janpeter/.config/s4m-queue.env
Environment=OPS_AGENT_SRC_DIR=/srv/scrum4me/ops-dashboard/ops-agent
ExecStart=/srv/scrum4me/ops-agent-drift/check-ops-agent-drift.sh 154 /srv/scrum4me/ops-agent-drift/baseline
SuccessExitStatus=1
--- ops-agent-drift: droogloop nu ---
[check-ops-agent-drift] laag repo<->runtime: OVERGESLAGEN (OPS_AGENT_SRC_DIR niet gezet)
[check-ops-agent-drift] DRIFT: 5 file(s), 7 hunk(s)
# ops-agent config drift — 154
Baseline: `/srv/scrum4me/ops-agent-drift/baseline` (repo)
Live:     `/etc/ops-agent`
| file | hunks | reason |
|---|---|---|
| `commands.yml` | 3 | content differs |
| `flows/redeploy_all.yml` | 1 | content differs |
| `flows/refresh_worker_db_env.yml` | 1 | live-only, not in baseline |
| `flows/update_codex_worker.yml` | 1 | content differs |
| `flows/update_mcp_worker.yml` | 1 | content differs |
5 file(s) drift, 7 hunk(s) total — 5 config, 0 repo-vs-runtime, 0 installed-build.
CONFIG: the live config has diverged from the version-controlled baseline.
Re-sync the repo baseline (and review whether the live change was intended) per
the host-config-discipline runbook, then this detector goes quiet again.
[check-ops-agent-drift] DRIFT_NO_NOTIFY=1 — skipping queue push
exit=1
--- de kopie in de forgejo-map ---
janpeter:janpeter 664 ctime=2026-09-28 19:23:38 /srv/scrum4me/forgejo/docker-compose.yml.bak-throttle-20260928T172338Z
6702bd8aaf1cce922056941fe9dafb79e7734c091195ccec844d9ca6b431a8d2  /srv/scrum4me/forgejo/docker-compose.yml.bak-throttle-20260928T172338Z
52cbca210efd9534c45949721848e8e5457c32bcbd7a830e658f5de516bd4a6b  /srv/scrum4me/forgejo/docker-compose.yml
live bestand nu: mtime=2026-09-28 19:23:38
tijdelijke map opgeruimd: ja
```
