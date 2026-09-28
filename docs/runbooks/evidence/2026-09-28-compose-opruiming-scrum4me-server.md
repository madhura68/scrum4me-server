# Compose-opruiming scrum4me-server — 28 september 2026

Hoort bij T-130 (scrum4me-server PBI-23, ST-035) en bij stap 1 van
`docs/superpowers/specs/2026-09-28-compose-kopieen-structureel-design.md`.

**Wat er is gedaan.** De zes losse compose-kopieën op scrum4me-server zijn ingepakt volgens het
inpakrecept (onderdeel E) en daarna verwijderd. De drie bestanden van de opruiming van 25 september
hebben mode 600 gekregen. Er is geen container herstart en geen compose-bestand gewijzigd.

**Akkoord.** JP keurde op 2026-09-28 lijst A en lijst B goed en bevestigde het onderhoudsvenster:
geen deploy bezig, niemand anders schrijft in de compose-, forgejo- en backupmap.

**Gereedschap.** `scripts/compose-inpak` op commit `a940e2687c786a1e1e7e7ebdb27f9ef6ec28b4aa`, sha256
`e6d6308c3598359cebca2d9ce55c525d2a96e99acace5ac56b7e524a24c39dc9`. Het script en de lijsten op de
host waren byte-gelijk aan de lokale versie. De proef van het recept staat in
[2026-09-28-inpakrecept-proef.md](2026-09-28-inpakrecept-proef.md).

Dit bestand bevat alleen namen, hashes en aantallen.

## Uitkomst

| Toets | Uitkomst |
|---|---|
| Ontwerp gelijk aan de pin `c5c60a9a…` | ja |
| Lijst goedgekeurd en venster bevestigd vóór de tar | ja |
| Tar teruggelezen en gelijk aan de lijst, vóór het verwijderen | ja, door het script en daarna onafhankelijk |
| sha256 van de tars gelijk aan het MANIFEST | ja |
| sha256 van de live configbestanden voor en na gelijk | ja |
| `docker compose ls --all` voor en na gelijk | ja |
| Zelfde 22 containers, alle `Up` | ja |
| Losse compose-kopieën onder `/srv` | 6 → 0 |
| Scanner, droogloop | exitcode 0, geen destructieve bevinding, 1 waarschuwing |
| Mode van tar, MANIFEST en SHA256SUMS | 600, ook die van 25 september |

De ene waarschuwing is het project `scrum4us-dev`, dat geregistreerd staat op een scratchpad-pad
onder `/tmp`. Die valt buiten deze taak.

## Waar de bestanden nu staan

| Tar | Inhoud | Terugzetten |
|---|---|---|
| `/srv/_attic/2026-09-28/compose-history.tar` | 5 kopieën uit `/srv/scrum4me/forgejo` en `/srv/scrum4me/compose` | per bestand in `compose-history.MANIFEST.txt` |
| `/srv/scrum4me/backups/forgejo-pre-v15-2026-05-16/compose.tar` | `docker-compose.yml.bak` | in `compose.MANIFEST.txt` |

Beide tars vervallen op 2026-12-27 (bewaartermijn 90 dagen, besluit JP).

## Lijst A — goedgekeurd

```text
a602231bd00fdc3912ec143f48d2303ac2b99b1042167e9ec728b61e98c25368  /srv/scrum4me/forgejo/docker-compose.yml.bak.20260607-174910
7eb25caa7741ef7699df17b50372f0ea9db50869f9ac4cc00908c6983b8764b8  /srv/scrum4me/forgejo/docker-compose.yml.bak.20260926T071930Z
d6dc59feedca94a56fbed7cb469aad3cc35e465b336534dca5e3038a3a8bd76b  /srv/scrum4me/forgejo/docker-compose.yml.iss8.bak
0bb1ed305c8912ee4157c24841a9c58bd6f3fdee935405e36d8c2bfe85f66c43  /srv/scrum4me/compose/docker-compose.yml.bak.20260928T005811-workerdb
fac38ea10501fc2d67aae3d3234605e486a79b750285f53695ae6cc6e3ffc097  /srv/scrum4me/compose/docker-compose.yml.bak.clipins-20260927T114046Z
```

## Lijst B — goedgekeurd

```text
fa170b1a570c262aa84c6460b2941615e2ba37977b2b1e5a9a3f6c354271d8a8  /srv/scrum4me/backups/forgejo-pre-v15-2026-05-16/docker-compose.yml.bak
```

## Stand vooraf

```text
host:
e6d6308c3598359cebca2d9ce55c525d2a96e99acace5ac56b7e524a24c39dc9  compose-inpak
af9317d254101a1402f749e809b24ecb0730e80ca579523a523e0cbea1b5ad4a  lijst-live.txt
58be099e7b197572d8a39fb2c30a8948d71a0e21da5b6a1b5003d537e01face3  lijst-backup.txt
--- python onder sudo ---
Python 3.14.4
--- stand vooraf ---
2026-09-28T16:40:32Z
NAME                STATUS              CONFIG FILES
compose             running(13)         /srv/scrum4me/compose/docker-compose.yml
forgejo             running(3)          /srv/scrum4me/forgejo/docker-compose.yml
scrum4us            running(6)          /srv/scrum4us/checkout/infra/compose/docker-compose.srv.yml
scrum4us-dev        exited(1)           /tmp/claude-1000/-home-janpeter-claude/8201fb25-3e30-472e-8135-91402e36345d/scratchpad/s4u/infra/compose/docker-compose.dev.yml
8e82fa13ada08c87fead137d7e5e71ae1d6244527a4524aa4b1cfe54fbf413e5  /srv/scrum4me/compose/docker-compose.yml
6702bd8aaf1cce922056941fe9dafb79e7734c091195ccec844d9ca6b431a8d2  /srv/scrum4me/forgejo/docker-compose.yml
9f8da6dcdef9d6ea329066b39cc42e63f5aca5bf283e8e4cbd3d03a6e13ab2f7  /srv/scrum4us/checkout/infra/compose/docker-compose.srv.yml
draaiende containers: 22
```

## Uitvoering lijst A

```text
2026-09-28T16:40:40Z
toets vooraf geslaagd: 5 bestand(en)
tar gemaakt: /srv/_attic/2026-09-28/compose-history.tar
teruggelezen: 5 bestand(en) gelijk aan de lijst
verwijderd: /srv/scrum4me/forgejo/docker-compose.yml.bak.20260607-174910
verwijderd: /srv/scrum4me/forgejo/docker-compose.yml.bak.20260926T071930Z
verwijderd: /srv/scrum4me/forgejo/docker-compose.yml.iss8.bak
verwijderd: /srv/scrum4me/compose/docker-compose.yml.bak.20260928T005811-workerdb
verwijderd: /srv/scrum4me/compose/docker-compose.yml.bak.clipins-20260927T114046Z
natoets geslaagd: projecten, statussen en configbestanden zijn gelijk
exit=0
```

## Uitvoering lijst B en chmod

```text
2026-09-28T16:40:50Z
--- lijst B ---
toets vooraf geslaagd: 1 bestand(en)
tar gemaakt: /srv/scrum4me/backups/forgejo-pre-v15-2026-05-16/compose.tar
teruggelezen: 1 bestand(en) gelijk aan de lijst
verwijderd: /srv/scrum4me/backups/forgejo-pre-v15-2026-05-16/docker-compose.yml.bak
natoets geslaagd: projecten, statussen en configbestanden zijn gelijk
exit=0
--- chmod 600 op de tar van 25 september ---
exit=0
```

## Natoets

De onafhankelijke controle in dit blok mislukte op de proefopstelling, niet op de tar: de
tijdelijke map was van root en de `cd` draaide als `janpeter`. De controle is daarna als root
herhaald; zie het volgende blok. De regel "herstart sinds de meting vooraf: 1" telt containers met
een looptijd korter dan een uur en is dus te ruim; het volgende blok laat zien dat het om
`scrum4me-forgejo-runner` gaat, gestart om 16:20:38Z, twintig minuten vóór de opruiming.

```text
=== scrum4me-server 2026-09-28T16:41:09Z ===
--- docker compose ls --all ---
NAME                STATUS              CONFIG FILES
compose             running(13)         /srv/scrum4me/compose/docker-compose.yml
forgejo             running(3)          /srv/scrum4me/forgejo/docker-compose.yml
scrum4us            running(6)          /srv/scrum4us/checkout/infra/compose/docker-compose.srv.yml
scrum4us-dev        exited(1)           /tmp/claude-1000/-home-janpeter-claude/8201fb25-3e30-472e-8135-91402e36345d/scratchpad/s4u/infra/compose/docker-compose.dev.yml
--- live configbestanden ---
8e82fa13ada08c87fead137d7e5e71ae1d6244527a4524aa4b1cfe54fbf413e5  /srv/scrum4me/compose/docker-compose.yml
6702bd8aaf1cce922056941fe9dafb79e7734c091195ccec844d9ca6b431a8d2  /srv/scrum4me/forgejo/docker-compose.yml
9f8da6dcdef9d6ea329066b39cc42e63f5aca5bf283e8e4cbd3d03a6e13ab2f7  /srv/scrum4us/checkout/infra/compose/docker-compose.srv.yml
--- containers: verschil met vooraf (alleen namen en gezond/niet) ---
zelfde 22 containers
herstart sinds de meting vooraf: 1
--- compose-bestanden met suffix na de extensie onder /srv ---
aantal: 0
--- /srv/_attic/2026-09-28 ---
drwxr-xr-x root:root 4096 .
drwxr-xr-x root:root 4096 ..
-rw------- root:root 1496 compose-history.MANIFEST.txt
-rw------- root:root 638 compose-history.SHA256SUMS
-rw------- root:root 61440 compose-history.tar
--- /srv/_attic/2026-09-25 ---
drwxr-xr-x root:root 4096 .
drwxr-xr-x root:root 4096 ..
-rw------- root:root 4504 MANIFEST.txt
-rw------- root:root 2593 SHA256SUMS.compose-history
-rw------- root:root 204800 compose-history.tar
--- backupmap ---
drwxrwxr-x janpeter:janpeter 4096 .
drwxr-xr-x janpeter:janpeter 4096 ..
-rw------- root:root 604 compose.MANIFEST.txt
-rw------- root:root 89 compose.SHA256SUMS
-rw------- root:root 10240 compose.tar
-rw-r--r-- root:root 4938504291 forgejo-data.tar.gz
-rw-rw-r-- janpeter:janpeter 1227681 forgejo-db.sql
--- inhoud van de tars (namen) ---
srv/scrum4me/forgejo/docker-compose.yml.bak.20260607-174910
srv/scrum4me/forgejo/docker-compose.yml.bak.20260926T071930Z
srv/scrum4me/forgejo/docker-compose.yml.iss8.bak
srv/scrum4me/compose/docker-compose.yml.bak.20260928T005811-workerdb
srv/scrum4me/compose/docker-compose.yml.bak.clipins-20260927T114046Z
docker-compose.yml.bak
--- MANIFEST lijst A ---
gemaakt: 2026-09-28T16:40:40Z
host: scrum4me-server
tar: /srv/_attic/2026-09-28/compose-history.tar
sha256 van de tar: 7de33e45e2b118170e32c07a488648a0613f6c45746c9d50081394374a8e59c3
basismap: /
verwijderen na: 2026-12-27

sha256  bron  terugzetcommando
a602231bd00fdc3912ec143f48d2303ac2b99b1042167e9ec728b61e98c25368  /srv/scrum4me/forgejo/docker-compose.yml.bak.20260607-174910  tar -xpf /srv/_attic/2026-09-28/compose-history.tar -C / srv/scrum4me/forgejo/docker-compose.yml.bak.20260607-174910
7eb25caa7741ef7699df17b50372f0ea9db50869f9ac4cc00908c6983b8764b8  /srv/scrum4me/forgejo/docker-compose.yml.bak.20260926T071930Z  tar -xpf /srv/_attic/2026-09-28/compose-history.tar -C / srv/scrum4me/forgejo/docker-compose.yml.bak.20260926T071930Z
d6dc59feedca94a56fbed7cb469aad3cc35e465b336534dca5e3038a3a8bd76b  /srv/scrum4me/forgejo/docker-compose.yml.iss8.bak  tar -xpf /srv/_attic/2026-09-28/compose-history.tar -C / srv/scrum4me/forgejo/docker-compose.yml.iss8.bak
0bb1ed305c8912ee4157c24841a9c58bd6f3fdee935405e36d8c2bfe85f66c43  /srv/scrum4me/compose/docker-compose.yml.bak.20260928T005811-workerdb  tar -xpf /srv/_attic/2026-09-28/compose-history.tar -C / srv/scrum4me/compose/docker-compose.yml.bak.20260928T005811-workerdb
fac38ea10501fc2d67aae3d3234605e486a79b750285f53695ae6cc6e3ffc097  /srv/scrum4me/compose/docker-compose.yml.bak.clipins-20260927T114046Z  tar -xpf /srv/_attic/2026-09-28/compose-history.tar -C / srv/scrum4me/compose/docker-compose.yml.bak.clipins-20260927T114046Z
--- onafhankelijke controle: tar uitpakken en vergelijken met SHA256SUMS ---
bash: line 23: cd: /tmp/tmp.RZaAhL131m: Permission denied
--- scanner, droogloop ---
[check-compose-collision] scanning 10 compose file(s) under /srv
[check-compose-collision] clean: no destructive finding (1 warning(s): duplicate container_name and/or non-runnable stray copies — not alerting)
exit=0
```

## Natoets, vervolg

```text
=== scrum4me-server 2026-09-28T16:41:40Z ===
--- onafhankelijke controle: tar uitpakken en vergelijken met SHA256SUMS ---
srv/scrum4me/forgejo/docker-compose.yml.bak.20260607-174910: OK
srv/scrum4me/forgejo/docker-compose.yml.bak.20260926T071930Z: OK
srv/scrum4me/forgejo/docker-compose.yml.iss8.bak: OK
srv/scrum4me/compose/docker-compose.yml.bak.20260928T005811-workerdb: OK
srv/scrum4me/compose/docker-compose.yml.bak.clipins-20260927T114046Z: OK
exit=0
docker-compose.yml.bak: OK
exit=0
--- sha256 van de tars tegen het MANIFEST ---
gelijk: /srv/_attic/2026-09-28/compose-history.tar
gelijk: /srv/scrum4me/backups/forgejo-pre-v15-2026-05-16/compose.tar
--- containers met een looptijd korter dan een uur: vooraf en nu ---
scrum4me-forgejo-runner | vooraf: Up 19 minutes | nu: Up 21 minutes | gestart: 2026-09-28T16:20:38Z
--- containers met een andere status dan 'Up' ---
geen
tijdelijke map opgeruimd: ja
```
