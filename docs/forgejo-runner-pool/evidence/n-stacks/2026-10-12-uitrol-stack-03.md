# Uitrol stack `-03` op `max2` — fase 2, 2b, 3a t/m 3f (M52 stap I, R17)

Datum 2026-10-12. Uitgevoerd door `max2:claude` op de host `max2`, aangestuurd en beoordeeld door `mac:claude`, op de opdrachten van JP van 2026-10-12 ("extra runner toevoegen", "ja, fase 3d", "ja, doe fase 3f"). Besluiten vooraf (U4, 2026-10-12): D1 N = 2, D7 waiver van §7.8, P5 aanvaarding van het co-locatierisico, P6-drempels. Dit document legt de uitkomst vast; het wijzigt geen host.

**Geen secrets, tokens of UUID's** staan in dit document. De runnerrecords zijn aangeduid met hun numerieke ID in Forgejo. De jobrun-URL's verwijzen naar publieke runs in `janpeter/scrum4me-shared`.

## Identiteit van de uitgerolde bundel

| | |
|---|---|
| bundelcommit (`BUNDLE_COMMIT` op `max2`) | `cbc7c26d4061bc0438d59475ad00b1b4a057e428` |
| canonieke bundelhash (`bundle-hash.sh /opt/forgejo-runner`) | `5dbbe158b02faf5768fac0ea2770545b9573f0b5c7913d254cf99b2c0b108a4d` |
| vorige bundel op `max2` | `bc7b7ab9196653db7d2c69c95d9c84598768ecbd`, hash `baebcc7b9337e3b7863004ece5d54aba286809d089634fe7725275ce075012fc` |
| stackset | `02` (bestaand, projectmap = bundelmap) en `03` (nieuw, `/opt/forgejo-runner-stacks/03/`) |
| runnerrecords (global, label `ubuntu-latest`) | ID 3 `scrum4me-srv-runner` (srv), ID 5 `max2-forgejo-runner-02`, ID 6 `max2-forgejo-runner-03` |
| Forgejo / runner | Forgejo 15.0.9, forgejo-runner 12.10.1 |

Het verschil tussen beide bundels is precies 13 bestanden (`.env.example`, `README.md`, `compose.yaml`, `controller.toml.example`, `forgejo-runner-cycle@.service` (nieuw), `forgejo-runner-dind-guard.service`, `scripts/cycle_adapters.py`, `cycle_runtime.py`, `dind-guard.sh`, `preflight.sh`, `stack_invariants.py` (nieuw), `trust_scope.py`, `verify-stack.sh`). `labels.txt`, `trusted-actions-scope.yml`, `allowed-job-images.txt` en `runner-config.policy.yml` zijn byte-gelijk gebleven, dus het hostverdict bleef geldig. De trustscan van beide versies gaf tegen live Forgejo dezelfde uitkomst (exit 10: alleen zachte afwijkingen, alle risky triggers bevestigd).

## Fase 2 — metingen (alleen lezen)

| Poort | Uitkomst |
|---|---|
| G2 `preflight.sh --stacks N` met live facts | N=1 exit 0 (12,5 vCPU en 6 GiB tegen budget 14 vCPU en 13,4 GB); N=2 exit 40: vCPU rood (25 > 14), geheugen **groen** op het live-moment (12,88 GB ≤ 13,38 GB); N=3 exit 40: vCPU en geheugen rood |
| U2 (24 uur, 1405 steekproeven) | laagste MemAvailable 21,67 GiB (budget 50% = 10,83 GiB); load1 maximaal 15,51 op 28 cores; CPU-busy maximaal 45%; swap 2,5 tot 4,8 GiB; §7.8: N=1 groen, N=2 (25 vCPU, 12 GiB) rood op beide, N=3 rood op beide |
| G4 | niets luistert op 2375/2376; geen hostsocket in de mounts |
| G5 | hostverdict `ok=true`, 438 s oud tegenover maximaal 86400 s; beide bindinghashes gelijk |
| G6 | alleen record 3 en 5 boden `ubuntu-latest` aan; 0 org-, 0 user-, 0 repo-runners (23 repo's) |
| G7 | guardregels alleen `-o fr-dind0`; `.env` zonder `STACK_*`; alles root-eigendom en niet groep-/wereldschrijfbaar; `[dind]` van `controller.toml` zoals verwacht; geen compose-aanroepers buiten de bundel |

**Afwijking van de plantekst:** G2 verwachtte rood op vCPU én geheugen; het geheugen was op het live-moment groen. Op het U2-minimum is het geheugen wel rood (12 GiB tegen 10,83 GiB). Exit 40 is bereikt en N=2 was niet groen, dus de stopvoorwaarde ging niet af. D7 (de waiver) dekt beide assen.

## Fase 2b — overgang van `-02` naar de R17-bundel

Poging 1 stopte terecht in stap 3b (rsync-droogloop met ~30 alleen-modusverschillen): de staging was gemaakt onder `umask 0002`. Dat was een stagingartefact in de taaktekst, geen hostdrift. Uit die poging is alleen de `.env`-toevoeging gewijzigd (back-up onder `/srv/_attic/2026-10-12/`). Poging 2 (`umask 022`, `tar --no-same-permissions`): droogloop toonde precies de 13 bestanden; installatie, `BUNDLE_COMMIT`, `dind-guard.sh apply`, unitinstallatie en één `daemon-reload` zonder enable of start van de template.

| Controle | Uitkomst |
|---|---|
| G1: render van de nieuwe `compose.yaml` tegen de bijgewerkte `.env` tegenover de huidige, **met en zonder `--profile cycle`** | beide diffs leeg |
| `verify-stack.sh cbc7c26… 5dbbe158…` zonder `--stacks` | exit 0 |
| G3a: TCP vanaf de host naar het DinD-adres op 2375 en 2376 | geblokkeerd; tellers van de wildcardregels liepen op |
| `-02` onaangeroerd | DinD-02 StartedAt `2026-10-09T01:52:47Z`, cycle-unit ActiveEnter `2026-10-09 03:52:49 CEST` met NRestarts 0 en MainPID 5372, guard-unit `03:52:41 CEST` met NRestarts 0: voor en na gelijk |

## Fase 3a t/m 3c — stack `-03` voorbereiden en isoleren

- Per-stack-map `/opt/forgejo-runner-stacks/03/` (map, `.env`, `controller.toml`, `runner-config.yml`, `state/` root 644/755; `credentials/` root 700). `.env`: de niet-`STACK_*`-regels byte-gelijk aan die van `-02`; `STACK_BRIDGE=fr-dind1`, `STACK_VOLUME=forgejo-runner-03-dind-data`, `STACK_CONFIG` en `STACK_TOKEN` onder de per-stack-map. `controller.toml`: alleen `project = "forgejo-runner-03"`, `marker_path` onder de per-stack-`state/` en `env_file` wijken af van `-02`. `cycle_runtime.py --check` exit 0.
- Het token is door JP geplaatst (600, uid 1000, 40 bytes, gelijk aan het tokenbestand van `-02`).
- `verify-stack.sh … --stacks "02 03" --pre-start` exit 0. Alleen de DinD van `-03` gestart (`up -d dind`, project `forgejo-runner-03`): healthy binnen 10 s, caps gelijk aan DinD-02 (5 GiB, 2048 PID, privileged, CPU-quota 1.150.000 per 100.000), bridge `fr-dind1` UP, volume `forgejo-runner-03-dind-data`.
- Runtime-deel `verify-stack.sh … --stacks "02 03"` exit 0. G4: geen luisteraar, geen hostsocket in de mounts van DinD-03.
- **G3b:** vanaf de host naar `172.22.0.2:2375` en `:2376` geblokkeerd; wildcardtellers 5 → 6 pakketten, de oude `fr-dind0`-regels op 0.
- **Cross-stackproef** met wegwerpcontainers op de host-Docker (digest-gepind `docker`-image dat al op de host stond, `--pull never`, alleen TCP-connect): positieve controle op het eigen `-03`-netwerk naar DinD-03 verbonden; richting 1 (netwerk van `-02` naar DinD-03, poort 2375 en 2376) geblokkeerd; richting 2 (netwerk van `-03` naar DinD-02) geblokkeerd; geen testcontainers achtergebleven.

## Fase 3d — controller van `-03` ingeschakeld

`systemctl enable --now forgejo-runner-cycle@03.service` om 2026-10-12T10:47:10Z: trustgate groen, scrub ok, pre-pull ("up to date"), runner gestart, `labels: [ubuntu-latest] … declared successfully`, WAITING. **T0 van de P6-meting: 2026-10-12T10:47:43Z.** `verify-stack.sh … --stacks "02 03"` met draaiende controller exit 0; geen token in Env, Cmd of Entrypoint van runner of DinD (0 treffers van de tokenpatroon-grep); guard-unit niet herstart.

**Exact-labelgelijkheid:** (i) de geordende connectielabels in de `runner-config.yml` van `-02` én `-03` zijn gelijk aan de niet-commentaarregels van `labels.txt` (één label: `ubuntu-latest:docker://catthehacker/ubuntu@sha256:c58e2b364da03b0c804c7d660f2ecbedf2f221a382b9baa0b344b0144780ff43`); (ii) het Forgejo-record van `-03` (ID 6) toont de labelnaam `ubuntu-latest`, gelijk aan de naamprojectie van die lijst.

**Drie gelijktijdige jobs verdeeld over drie runners, groene en rode job:**

| Run | Workflow | Jobs | Verdeling | Uitkomst |
|---|---|---|---|---|
| [126](https://git.jp-visser.nl/janpeter/scrum4me-shared/actions/runs/126) | `m52-probe-green` | p1 p2 p3, 75 s, exit 0 | p1 srv; p2 `-03`; p3 `-02` | alle drie geslaagd |
| [127](https://git.jp-visser.nl/janpeter/scrum4me-shared/actions/runs/127) | `m52-probe-red` | p1 p2 p3, 75 s, exit 1 | p1 srv; p2 `-03`; p3 `-02` | alle drie mislukt, zoals bedoeld |

Journals (controller van `-03`: taak 12614 groen en 12617 rood; `-02`: taak 12615 en 12618): procesexit van de runner 0, scrub ok (0 tot 1 s), nieuwe runner en WAITING binnen 5 s, geen quarantaine of herstart; DinD-03 leeg na afloop. Een rode job is geen runnerfout.

**Afwijking:** `janpeter/scrum4me-server` heeft Forgejo Actions uitgeschakeld (`has_actions=false`); de eerste probe aldaar maakte geen run. De probes draaiden daarom in de publieke repo `scrum4me-shared`, met tijdelijke branches `m52/probe-green` en `m52/probe-red` die alleen de probe-workflow bevatten (bestaande workflow op de branch verwijderd); alle probebranches zijn verwijderd. De runs 126 tot en met 129 staan nog in de Actions-historie van die repo.

## Fase 3e — failovertest (vereenvoudigd)

**Bevinding:** Forgejo 15.0.9 (API 1.22) kent geen pauze of disable van een runnerrecord: in de UI kan een runner alleen worden bewerkt (naam, beschrijving, token vernieuwen) of verwijderd; de API biedt `get`, `post` en `delete`. De stap "JP pauzeert het runnerrecord" uit plan, ontwerp (§9, rollback) en README is daarom niet uitvoerbaar. Op JP's keuze is de test teruggebracht tot het gecontroleerd stoppen en starten van alleen de controller van `-03`; `-02` is niet gestopt en de omgekeerde richting is niet getest.

| Moment (UTC) | Gebeurtenis |
|---|---|
| 11:11:03 en 11:11:13 | Forgejo-kant (nulbewijs): alle drie de records idle, geen wachtende jobs |
| 11:11:44 | README-controles 1 en 2 groen; `systemctl stop forgejo-runner-cycle@03.service`: runner-exit rc=130 (SIGINT), geen job, geen timeout; DinD-03 ongewijzigd, unit nog `enabled` |
| 11:12:05 | [run 128](https://git.jp-visser.nl/janpeter/scrum4me-shared/actions/runs/128) (drie jobs): p1 srv en p2 `-02` tegelijk; p3 wacht (er is geen derde runner) tot 11:13:26 en loopt dan op srv; maximaal twee gelijktijdige jobs, geen enkele op `-03` |
| 11:13:16 | `systemctl start forgejo-runner-cycle@03.service`: trustgate groen, scrub ok, pre-pull, runner gestart, WAITING om 11:13:48 (~32 s) |
| 11:16:10 | [run 129](https://git.jp-visser.nl/janpeter/scrum4me-shared/actions/runs/129) met `-03` terug: p1 en p3 op max2 (twee gelijktijdige max2-jobs kunnen alleen op `-02` en `-03` draaien) en p2 op srv; alle drie geslaagd |

`-02` en de guard bleven onaangeroerd (voor en na gelijk, NRestarts 0).

## Fase 3f — eindstand (opgenomen 2026-10-12T11:39Z)

```
commit: cbc7c26d4061bc0438d59475ad00b1b4a057e428
bundel_hash: 5dbbe158b02faf5768fac0ea2770545b9573f0b5c7913d254cf99b2c0b108a4d
isolatie: OK
guard: OK
exit=0            (verify-stack.sh zonder --stacks)

commit: cbc7c26d4061bc0438d59475ad00b1b4a057e428
bundel_hash: 5dbbe158b02faf5768fac0ea2770545b9573f0b5c7913d254cf99b2c0b108a4d
isolatie: OK
guard: OK
stacks: 02 03 (runtime)
stackinvarianten: OK
exit=0            (verify-stack.sh --stacks "02 03")
```

| Eenheid | enabled | active | ActiveEnter | NRestarts |
|---|---|---|---|---|
| `forgejo-runner-cycle.service` (`-02`) | ja | ja | 2026-10-09 03:52:49 CEST | 0 |
| `forgejo-runner-cycle@03.service` | ja | ja | 2026-10-12 13:13:16 CEST (de geplande herstart van 3e; eerste start 12:47:11 CEST) | 0 |
| `forgejo-runner-dind-guard.service` | ja | ja (oneshot, exited) | 2026-10-09 03:52:41 CEST | 0 |
| `forgejo-runner-trust.timer` | ja | ja | 2026-10-09 03:52:41 CEST | n.v.t. |

Alle geïnstalleerde `forgejo-runner*`-units zijn byte-gelijk aan de bundelkopie (`cmp`). Guardregels in `OUTPUT`: twee wildcardregels `-o fr-dind+` (poort 2376 en 2375, `REJECT --reject-with tcp-reset`) vóór de twee oude regels `-o fr-dind0`; geen luisteraar op 2375/2376; bridges `fr-dind0` en `fr-dind1` UP. Containers: `forgejo-runner-dind-1` en `forgejo-runner-03-dind-1` healthy, elk met één runnercontainer; DinD-03 leeg. Caps van beide DinD's en beide runners gelijk (DinD: 5.368.709.120 bytes, 2048 PID, privileged, CPU-quota 1.150.000/100.000; runner: 1.073.741.824 bytes, 256 PID, 1 CPU, niet privileged). Mounts: geen `docker.sock` of ander hostsocket. Tokenbestanden: `janpeter:janpeter` (uid 1000) mode 600, in een root-map met mode 700; de rest van de per-stack-bestanden `root:root` 644/755, niets groep- of wereldschrijfbaar.

Het hostverdict (`ok=true`) bindt alleen `labels.txt` en `trusted-actions-scope.yml`; `allowed-job-images.txt` zit niet in de binding.

## Open: acceptatiepoort P6 (T-212) en fase 4

De P6-meting loopt van T0 (2026-10-12T10:47:43Z) tot 2026-10-13T10:47:43Z; de sampler op `max2` (`~/m52-p6/`) loopt tot 12:46Z. Drempels (U4): rood bij een MemAvailable onder 10,8 GiB in één steekproef, bij een mediane wachttijd van Scrum4Me of Ops-dashboard boven 440 s, of bij een host-OOM of throttling van productie. De uitkomst komt in een aanvulling op dit document. Daarna volgt fase 4 (zeven dagen stabiliteit).

## Voor het volgende bundelwijzigingsmoment

`forgejo-runner/README.md` (onder "Terugdraaien van één stack" en "Uitrolvolgorde van een extra stack") en de hoofdtekst van `migratieontwerp.md` §13 noemen nog het pauzeren van een runnerrecord in Forgejo. Dat kan in deze Forgejo-versie niet; de gecontroleerde stop (README-controles 1 en 2, en het Forgejo-nulbewijs van twee snapshots) is de werkbare vorm. Het README maakt deel uit van de bundelhash: een wijziging verandert de hash en vraagt een nieuwe uitrol, dus die aanpassing wacht op de eerstvolgende bundelwijziging (zie het issue met fingerprint `scrum4me-server:forgejo-runner-readme:no-runner-pause`).
