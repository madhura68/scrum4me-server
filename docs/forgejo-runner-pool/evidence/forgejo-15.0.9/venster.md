# Onderhoudsvenster Forgejo 15.0.2 → 15.0.9 — 30 september 2026

Uitvoering van `implementatieplan-forgejo-15.0.9.md` op commit `f2ed635` (sha256 `6bae8663104ac74ff3d5455bfac7bff8a272803b37a7e2de64e8ab7d969ba4db`). Operator: `mac:claude` via SSH; `[JP]`-stappen door JP. Scrum4Me: sprint S-2026-09-30-2, ST-040, T-143 t/m T-147.

**Uitkomst: `upgraded`.** De forge draait `15.0.9+gitea-1.22.0`; er is niet teruggerold.

## Tijden (UTC; lokaal = UTC+2)

| Moment | Tijd | Bron |
|---|---|---|
| `T0` (na 2.1) | 13:25:02 | `venster/f2-max2.txt` |
| `TSTOP` (2.6, forge gestopt) | 13:25:52 | `venster/f2-host.txt` |
| Forge terug op 15.0.2 (3.1) | 13:29:43 | `venster/f3-host.txt` |
| Forge gestopt voor 4.1 | 13:31:09 | `venster/f4-host.txt` |
| Recreate op 15.0.9 (4.3) | 13:31:16 | `venster/f4-host.txt` |
| Listener op 15.0.9 (4.4) | 13:31:19 | `venster/f4-host.txt` |
| `TEND` (Gate 5) | 13:41:29 | — |

Totale duur `T0`→`TEND`: **16 min 27 s** (doel ≤ 30 min). Downtime in twee intervallen: 13:25:52–13:29:43 (3 min 51 s, waarvan ruim 3 min wachten op JP's antwoord over de afwijking bij Gate 2) en 13:31:09–13:31:19 (10 s). Gate 4 was groen op T+10, binnen de beslisgrens T+20.

## Besluiten van JP

| Stap | Besluit |
|---|---|
| 0.10 OAuth2 | Alleen de drie ingebouwde applicaties (`tea`, `git-credential-oauth`, `Git Credential Manager`), nul grants, nul LFS-objecten (`fase0/oauth2-hulpmeting.txt`); de rotatie raakt geen client |
| 0.14 schrijvers | Geaccepteerd onder het restrisico van Gate 4; niets gepauzeerd, dus in 5.4 niets te hervatten |
| 1.1 restic | Geaccepteerd: `$BK` gaat mee in de nachtelijke restic-run (NAS en B2) |
| 1.4 venster | Direct na Fase 1; geen andere sessie op de hosts ("vrij baan") |
| 2.5b rotatie | Uitgevoerd: `ROTATIE OK` |
| 3.3 tak | Routerlog aanwezig: het verzoek via Caddy logt het publieke client-IP, niet het container-IP van Caddy (`venster/f3-router.txt`; de regel met `172.18.0.1` is de lokale controle op poort 3010, niet via Caddy) |
| Gate 4 | Functioneel groen (4.6) en de doctor-regel hieronder geaccepteerd |

`GIT_CF=nee` (0.13 en opnieuw in 2.4): de compose-map staat niet onder git, dus 6.2 kent geen commit in die map. `PRE_CF` = `52cbca210efd9534c45949721848e8e5457c32bcbd7a830e658f5de516bd4a6b`; na de tagwissel `360dbe9d91afb4acece76022bdb4368954c2929cf640acab9a7f2acf4717a637` (`TAGWISSEL OK`: teruggerekend gelijk aan `PRE_CF`).

## Afwijkingen van het plan

1. **Gate 2 — legacy runnercontainer `exited` in plaats van `running`.** JP pauzeerde de legacy runner (2.1) door de container te stoppen (`docker stop`, 13:23:33Z, vóór `T0`, 0 lopende taken volgens het runnerlog) in plaats van via de beheerinterface. De container-ID's van runner en DinD bleven gelijk (2.6 → 4.3: `RID/DID ONGEWIJZIGD`). JP bevestigde dit vóór Fase 3 en startte de container in 5.1 zelf weer (13:37:31Z).
2. **4.5 — `DOCTOR ROOD` op één verklaarde regel.** Alle 28 checks hebben verdict `OK`. `doctortoets` meldt de bestaande waarschuwing over verweesde repo-archieven als nieuw omdat het aantal veranderde: 261 (1,3 GiB) → 32 (218 MiB). Oorzaak: de herstart in Fase 3 ruimde oude archieven op; de volumekopie van 4.1, genomen vóór de image-wissel, telt al 32 bestanden (`venster/f4-doctor-beoordeling.txt`). Geen gevolg van 15.0.9.
3. **Baseline (0.4) — één `ERROR` die na de upgrade verdween.** Op 15.0.2 meldde doctor dat `authorized_keys` en de git-hooks niet actueel waren: de bestanden noemen `/usr/local/bin/gitea`, doctor verwachtte `/usr/local/bin/forgejo`. In beide images is `forgejo` een symlink naar `gitea`. De doctor van 15.0.9 meldt dit niet meer; de bestanden zelf zijn ongewijzigd (mtime juli en augustus, `venster/f4-extra.txt`).
4. **Mac-paden.** De `[mac]`-stappen schreven naar de scratchmap van de sessie in plaats van `/tmp/fj-15.0.9`.
5. **Journaalregels 5.2.** De controller logt `trustgate groen` → `cyclus: scrub ok=True` → `cyclus: runner gestart`; de regels `SOURCE_WAIT` en `READY` uit het plan komen in dit journaal niet voor.
6. **Trust-service liep twee keer** (13:35:29Z door deze uitvoering, 13:37:27Z door een andere trigger); beide `success`, het verdict is `ok: true` met `measured_at` na `T0`.

## Buiten het plan gemeten

- De compose-hash van de forge-service was vóór het venster gelijk aan die van de draaiende container, dus de recreate wisselde alleen de image. De DinD-service heeft een nog niet toegepaste wijziging in het compose-bestand (de CI-rem van 28 sep, live gezet met `docker update`); `--no-deps` liet DinD ongemoeid.
- Git over SSH: poort 2222 luistert op het tailnet-adres na de recreate; een `ls-remote` vanaf de host strandde op de host-keycontrole van de testende gebruiker, niet op de forge. Niet verder getest.
- In `/srv/scrum4me/forgejo` staan vier bestanden met `~` in de naam (`~forgejo.txt`, `~\forgejo.txt` en de `.pub`-varianten, mei 2026), naar vorm een SSH-sleutelpaar. Niet aangeraakt; gemeld aan JP.

## Migratie

Eén migratie bij de start van 15.0.9: `v17a_add-action-run-workflow-source-commit` (`venster/f4-host.txt`). Geen `[E]`, `[F]` of `panic` in het startlog.
