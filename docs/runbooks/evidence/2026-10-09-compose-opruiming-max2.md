# Compose-opruiming max2 — 9 oktober 2026

Hoort bij T-134 (scrum4me-server PBI-23, ST-035), max2 ISS-15 en stap 3 van
`docs/superpowers/specs/2026-09-28-compose-kopieen-structureel-design.md`.

**Wat er is gedaan.** De 32 losse compose-kopieën onder `/srv` op max2 zijn ingepakt volgens het
inpakrecept (onderdeel E) en daarna verwijderd. Van de 15 When2Watch-releases die niet `current` zijn
is `compose.yaml` per release ingepakt in `release-compose.tar` (D1). Er is geen container herstart en
geen live compose-bestand gewijzigd.

**Akkoord.** JP keurde op 2026-10-09 de lijsten goed en bevestigde het onderhoudsvenster: geen
When2Watch-deploy, geen andere schrijver.

**Gereedschap.** `scripts/compose-inpak`, sha256
`e6d6308c3598359cebca2d9ce55c525d2a96e99acace5ac56b7e524a24c39dc9` (gelijk aan de pin), uit
`main@bc7b7ab`. De tests draaiden op max2 groen: 14 van 14, Python 3.14.4, GNU tar 1.35. Het ontwerp
was gelijk aan de pin `c5c60a9a…`. De When2Watch-procedure stond op When2Watch `main@3c7b9ec`.

Dit bestand bevat alleen namen, hashes en aantallen.

## Uitkomst

| Toets | Uitkomst |
|---|---|
| Ontwerp en script gelijk aan de pins | ja |
| Lijsten goedgekeurd en venster bevestigd vóór de eerste `run` | ja |
| Tar teruggelezen en gelijk aan de lijst, vóór het verwijderen | ja, door het script; de tar met losse kopieën ook onafhankelijk (32 van 32) |
| sha256 van de live configbestanden voor en na gelijk | ja (4 bestanden) |
| `docker compose ls --all` voor en na gelijk | ja |
| `compose.yaml` alleen nog in de release van `current` (`3c7b9ec`) | ja |
| `when2watch-web-1` en `when2watch-db-1` | beide healthy |
| `https://when2watch.jp-visser.nl/api/health` | 200 |
| Uitpakblok uit When2Watch `deploy/README.md`, beproefd op `dfc39bb` | geslaagd; hash gelijk aan de lijst; daarna opnieuw ingepakt |
| Losse compose-kopieën onder `/srv` | 32 → 0 |
| When2Watch-releases met een los `compose.yaml` naast `current` | 15 → 0 |
| Scanner, droogloop | exitcode 0, geen destructieve bevinding, 1 waarschuwing (was 22 destructief, 22 waarschuwingen) |
| Mode van tar, MANIFEST en SHA256SUMS | 600 |

## Stand vóór de opruiming

- Losse kopieën: 32 (op 28 september 30). `/srv/scrum4me/compose` 26, `/srv/immich` 2,
  `/srv/apps/media-organizer/repo/deploy` 2, `/srv/apps/tei` 1,
  `/srv/scrum4me/backups/forgejo-pre-v15-2026-05-16` 1. Nieuw sinds 28 september: de twee kopieën
  `.bak.cli-202610022033` in `/srv/scrum4me/compose`.
- De twee kopieën in `media-organizer/repo/deploy` worden niet door git gevolgd, getoetst met
  `git ls-files --error-unmatch` als `ops-agent`.
- When2Watch: `current` → `releases/3c7b9ec` (deploy van 8 oktober). De deploys van `5dd8b3f` en
  `c35cd1a` hadden hun `compose.yaml` al zelf ingepakt volgens `deploy/README.md`: `release-compose.tar`
  plus `.SHA256SUMS`, zonder `.MANIFEST.txt`. Er resteerden 15 releases met een los `compose.yaml`.

**Afwijking, buiten deze taak.** `when2watch-db-1` draagt als `config_files` nog
`releases/5dd8b3f/compose.yaml`. De db-container is bij de deploy van `3c7b9ec` niet opnieuw aangemaakt.
Dat bestand bestond vóór deze taak al niet meer als los bestand. `docker compose ls` noemt voor `when2watch`
daarom twee configbestanden, vóór en na gelijk.

## Waar de bestanden nu staan

Alle tars vervallen op 2027-01-07 (bewaartermijn 90 dagen, besluit JP).

| Tar | Inhoud | Eigenaar |
|---|---|---|
| `/srv/_attic/2026-10-09/compose-history.tar` | de 32 losse kopieën, basismap `/` | root, 600 |
| `/srv/apps/when2watch/releases/<commit>/release-compose.tar` | `compose.yaml` van die release | janpeter, 600 |

Terugzetten per bestand staat in het `MANIFEST.txt` naast elke tar. Voor When2Watch geldt het
uitpakblok in When2Watch `deploy/README.md`.

sha256 van `compose-history.tar`: `6b8cee5b4e6b8bf080f8def8c05c2b8bbde1a0dda704373fb81fafeda9853c21`.

## Lijst losse kopieën — goedgekeurd

```text
f362b558bd76aa3518f549d4f310228b1e8246336171a5a1b875fab67a7c37d6  /srv/apps/media-organizer/repo/deploy/docker-compose.override.yml.retired.20260605-220404
99e6d79e836f1a77c30297527d83502990739af24fb2c0fec679d30fe4d03245  /srv/apps/media-organizer/repo/deploy/docker-compose.yml.bak.20260710T011238
f8610a09ed589a1f48d98ef4eb0ced27fa6da66c67691f10efdde5eb834bfc62  /srv/apps/tei/docker-compose.yml.bak.lanswitch.20260919T232455Z
36b9791fff6d33982ca3990fceed7e19ae631069c61daea4608033270c45e268  /srv/immich/docker-compose.override.yml.bak.20260531
641ba2bb3658264f63abcf90df4164677c3a72e06b2904254be52a04bf29234c  /srv/immich/docker-compose.yml.bak.20260531
fa170b1a570c262aa84c6460b2941615e2ba37977b2b1e5a9a3f6c354271d8a8  /srv/scrum4me/backups/forgejo-pre-v15-2026-05-16/docker-compose.yml.bak
762995b6e544c5f1636a0a08a8e0ed00d09939fe793777446d8cfa6ad053b72e  /srv/scrum4me/compose/docker-compose.codex.yml.bak.20260928T002106-workerdb
5e9e03aa2821a3c7159faa84def7d5f7b3276c744139eb59e3fd53eb8d14a33a  /srv/scrum4me/compose/docker-compose.codex.yml.bak.cli-202610022033
4575bcf8df9bc429bedf5218339a0ca35ce1cf76342b3c05e2e9440bb01c22a5  /srv/scrum4me/compose/docker-compose.codex.yml.bak.clipins-20260927T114828Z
96ab1df045bdc9e99b3ad34bb11a4dddcab4ce6b0c6348f228522998e6c8d5dd  /srv/scrum4me/compose/docker-compose.codex.yml.bak.pre-clibump-20260711T213336
9981506733ccceb1784c12162c60578a6f2739f535a1637f23955a3d2d90f9df  /srv/scrum4me/compose/docker-compose.codex.yml.bak.pre-rename-20260711T063757
515f0b26e08056b0609154956803421c443d12f6bdd49c7a561a066a55cd69f7  /srv/scrum4me/compose/docker-compose.override.yml.bak.1780161296
7822e569642d7a26adde7c7a1d5c3f9d1a94900f6d4edf63df1b7ad577a193bb  /srv/scrum4me/compose/docker-compose.override.yml.bak.iss1-20260925T173506Z
d8609f84fed0d595e58648c63f56330f7cd6e1fb4e57eede2bf7e5ba44504d42  /srv/scrum4me/compose/docker-compose.override.yml.bak.lanswitch.20260919T232455Z
64868da970fd4a6befe274059fec8b359567a4cf891fa68425b35192bcb88ecb  /srv/scrum4me/compose/docker-compose.override.yml.bak.pre-rename-20260711T063757
fca1fa5f431048e697c80c688b15305ac47fb2689ad840ffd28e517965bb4763  /srv/scrum4me/compose/docker-compose.yml.bak.20260522-234028
e59dea14cb9a4153ebce1db0550077456dfe98d7469be2e17443139e2ab29774  /srv/scrum4me/compose/docker-compose.yml.bak.20260525-195132
ce35e128e6bb4c59c2e8fa656fa4a65f6e591c6dc785516a6f958394fa2f76bd  /srv/scrum4me/compose/docker-compose.yml.bak.20260526-202520
a8ac94cd6b986f577362a47d67357cbf280f2f77783d19aeeb6c3e037695b4a2  /srv/scrum4me/compose/docker-compose.yml.bak.20260526-213957
2409824125c38ac89efa8b3ff18ffc41fbf6407869d2fb0462ea6a6ac85240b4  /srv/scrum4me/compose/docker-compose.yml.bak.20260526-223242
7c462b42687418d54639d867954bc41e4bfd4707c467c8bf38cd7ef1dcb17f26  /srv/scrum4me/compose/docker-compose.yml.bak.20260527-110826
aa55d38f752a8bf9bee17abc3bfeaa32cb6daaad29968a8e3ee10c322bdc292d  /srv/scrum4me/compose/docker-compose.yml.bak.20260527T032419Z
9efdc0908bd99c93977dacd1bb1c22f6ae588c93d2c412b4fb7b1106cf955f44  /srv/scrum4me/compose/docker-compose.yml.bak.20260527T051630Z
38be4fa9016771af5b21cd671a186f803e3e6ecd41f279aaf0be05bd19ab7f0d  /srv/scrum4me/compose/docker-compose.yml.bak.20260527T082707Z
dad1cc74214bffb0c9bcda82b2cbb394b5ee375f2ae4486f7ef74a82320e5fa8  /srv/scrum4me/compose/docker-compose.yml.bak.20260528-213943
a42035825836b97b0270992c00ba9667c78026c61ec5f6a7da377613a111dfff  /srv/scrum4me/compose/docker-compose.yml.bak.20260928T002106-workerdb
d1e91d7d271b6ffd171f35890ea0dfafa80b6d928b88551dba4bd7a1682bbd1f  /srv/scrum4me/compose/docker-compose.yml.bak.cli-202610022033
c798b8758e9869811ea4cd20e6786af6da314078bd8659f0ca1521a2e51151f8  /srv/scrum4me/compose/docker-compose.yml.bak.clipins-20260927T114828Z
91751cc226a4bcefd7b04ee0e1371c14e384994df15eaa0ffb53bebf3dd3acf7  /srv/scrum4me/compose/docker-compose.yml.bak.iss35-20260927T133213Z
40e59ade448911a29c5d9b34b79ef7a604f188ef2378bd8281e5c1ca81f3ecb4  /srv/scrum4me/compose/docker-compose.yml.bak.pre-clibump-20260711T213336
cbe1c9dacb02248c2e27d6daf02cc2fca5172c41b26919b8153cea37f849ba03  /srv/scrum4me/compose/docker-compose.yml.bak.pre-pgbind-fix-20260601
5fae06838a79b093c271e5841289a36e705ee73fef9974afb8898ce56b24435b  /srv/scrum4me/compose/docker-compose.yml.bak.pre-rename-20260711T063757
```

## When2Watch-releases — goedgekeurd

Per release één lijst met `compose.yaml`. Kolommen: release, sha256 van `compose.yaml`, sha256 van
`release-compose.tar`.

| Release | `compose.yaml` | `release-compose.tar` |
|---|---|---|
| `2153d94` | `a7e1a337663e50cc02aab6ee62786bda075a4c96a2d4f5bc43cf309d99b72574` | `57138df3a007ed4648a107684b6402db6b56a94aef0fee484b0daa0730d89f32` |
| `4379141` | `a7e1a337663e50cc02aab6ee62786bda075a4c96a2d4f5bc43cf309d99b72574` | `2b0f83128c350e449ae4255ab541b205b1c87bcd2d320275945b0737677ff438` |
| `4a50e76` | `a7e1a337663e50cc02aab6ee62786bda075a4c96a2d4f5bc43cf309d99b72574` | `4cf88785e180a067ecd13494cccd917dda4ef85ba0786cbc7dcc3158b8c2741c` |
| `4c290be` | `a7e1a337663e50cc02aab6ee62786bda075a4c96a2d4f5bc43cf309d99b72574` | `b053bcf0e8aa205cebded6b976d73b14fab806c3d47418954d2a2b7a91ab7635` |
| `790ed77` | `a7e1a337663e50cc02aab6ee62786bda075a4c96a2d4f5bc43cf309d99b72574` | `4f00978d1f8de90246a13bb0bc9e83a4cca030234e3815ee596fd0e77e1e504c` |
| `8b87838` | `223160662043818116db73528d1ee94884d782c5a47138398cafbbeb07ce0734` | `3b3c030c41d9eb5e40295b65d601fac2a4bf1ea2766eaf167e7f5b6b5a62b449` |
| `93bbaed` | `a7e1a337663e50cc02aab6ee62786bda075a4c96a2d4f5bc43cf309d99b72574` | `623fe920aeed4058887981f3be1ac9481e7d2c88e4434a3e9005b3153605193d` |
| `961fc09` | `a7e1a337663e50cc02aab6ee62786bda075a4c96a2d4f5bc43cf309d99b72574` | `f651b968918ff22730f6f2a10602bab2aba6e6e9a19bb14d3dabacdfd4362ae6` |
| `b2e4de9` | `a7e1a337663e50cc02aab6ee62786bda075a4c96a2d4f5bc43cf309d99b72574` | `05c120501b70a7631bec7ff21f258929486a9ea1014443e3d75439084038d54e` |
| `b31af05` | `a7e1a337663e50cc02aab6ee62786bda075a4c96a2d4f5bc43cf309d99b72574` | `7cb2eb782defa83aa27d5408ee7bf3a088fac8548652ff456f95dfd98a0200ab` |
| `c04812c` | `a7e1a337663e50cc02aab6ee62786bda075a4c96a2d4f5bc43cf309d99b72574` | `7907a8a942b94b521d8e8d9daa64157de4daa94da43a431e11938f56f23420ec` |
| `d13cad0` | `a7e1a337663e50cc02aab6ee62786bda075a4c96a2d4f5bc43cf309d99b72574` | `d5a03a90a592092d9013158fa89575285b353a7da378401e70865ad62af09ba8` |
| `dfc39bb` | `a7e1a337663e50cc02aab6ee62786bda075a4c96a2d4f5bc43cf309d99b72574` | `0e5e7d2328d5721ba33ab7fb5f99a23d2aea794a4d5b556f00ddc77876acefbd` |
| `e864397` | `a7e1a337663e50cc02aab6ee62786bda075a4c96a2d4f5bc43cf309d99b72574` | `7b5bde382f533c9ac427a69242444e8b27854cd6a85a884e203704e73c6accf4` |
| `fb7a690` | `a7e1a337663e50cc02aab6ee62786bda075a4c96a2d4f5bc43cf309d99b72574` | `67e0cd144f0a0af399f693dce564b0be1c882b32e095da7fe017760cbb7802f7` |

De tar van `dfc39bb` is van de herinpak na de uitpakproef.

## Droogloop van de scanner

Ops-dashboard `deploy/ops-agent/check-compose-collision.sh` op `main@c9b6722`, lokaal berekende sha256
`4b2f739bea7578f947c5178986f10b85436858d5c15d3b69487b6d47e339a233`. Lokaal op max2 gedraaid; de vorm is die uit
ontwerp §4 A, zonder SSH:

```bash
sudo COMPOSE_COLLISION_SCANNER_SHA=$H DRIFT_NO_NOTIFY=1 bash -s -- max2 /srv < check-compose-collision.sh
```

```text
[check-compose-collision] scanner sha256 (first 12 hex chars): 4b2f739bea75
[check-compose-collision] scanning 11 compose file(s) under /srv
[check-compose-collision] clean: no destructive finding (1 warning(s): duplicate container_name and/or non-runnable stray copies — not alerting)
```

Exitcode 0. Bij een schone uitkomst drukt de scanner de waarschuwing niet uit.
