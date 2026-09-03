# Dekking van het testharnas tegenover §8 stap A

Stap A eist dat het stub-/testharnas iedere readinessuitkomst, de bevestigingsregel,
de fence, de latchclassificatie, de deadlinewatchdog, het maintenance-record en het
assignment-nulbewijs afzonderlijk bewijst. §7.9 maakt deze suite de stap-A-gate:
zolang hij niet groen is, is stap A niet afgerond.

**Stand:** 99 tests over vijf bestanden, 0 failures.

| Bestand | Tests |
|---|---|
| `test_cycle_readiness.py` | 20 |
| `test_cycle_eventloop.py` | 18 |
| `test_cycle_fence.py` | 24 |
| `test_cycle_maintenance.py` | 16 |
| `test_cycle_lifecycle.py` | 21 |

## Eis uit stap A → bewijzende test

| Eis uit §8 stap A | Test |
|---|---|
| transport/5xx → `SOURCE_WAIT` | `test_cycle_readiness.TestVierwegclassificatie.test_transportfout_is_source_wait`, `…test_5xx_is_source_wait` |
| authprobe 401/403 → `CREDENTIAL_ERROR` | `…test_401_en_403_op_de_authprobe_is_credential_error` |
| overige status/schemafout → `QUARANTINED` | `…test_overige_status_is_protocol`, `…test_2xx_met_verkeerd_schema_is_protocol` |
| geldige 2xx → inhoudelijke trustgate | `…test_2xx_met_geldig_schema_is_ready` plus `test_cycle_eventloop.TestToestandsmachine.test_rode_gates_houden_de_controller_uit_waiting` |
| eerste afwijking zet alleen informatief event plus fence | `test_cycle_fence.TestFenceZetten.test_eerste_afwijking_logt_fence_set_en_alarmeert_niet` |
| eerste afwijking stopt een `WAITING` child | `…test_eerste_afwijking_haalt_waiting_direct_uit_de_lucht` |
| twee gelijke afwijkingen bevestigen | `test_cycle_readiness.TestBevestiging.test_twee_gelijke_waarnemingen_bevestigen` |
| klassesprong herstart bevestiging | `…test_klassesprong_herstart_de_bevestiging` |
| automatisch herstel zonder directe runnerstart | `test_cycle_fence.TestFenceWissen.test_een_geldige_probe_wist_de_fence_niet`, `…test_twee_geldige_probes_zonder_nulbewijs_wissen_de_fence_niet`, `…test_twee_geldige_probes_met_nulbewijs_en_groene_gates_wissen_de_fence` |
| alleen `event_seq < fence_seq` is vóór-latch | `test_cycle_fence.TestLatchclassificatie` (vijf tests) |
| remote/Forgejo-tijden beslissen nooit | `…test_late_wandklok_verandert_het_oordeel_niet`, `test_cycle_eventloop.TestEventSeq.test_event_seq_loopt_op_ook_als_de_wandklok_terugspringt` |
| unknown/late gaat naar cancel/scrub/redispatch | `test_cycle_lifecycle.TestOpNaLatchJob.test_job_na_de_fence_leidt_tot_cancel_en_scrub` |
| blijvende klassesprong bereikt de deadline | `test_cycle_fence.TestDeadlinewatchdog.test_zwaarste_klasse_wint_bij_een_blijvende_klassesprong` |
| blijvende valid/error-flap bereikt de deadline | `…test_valid_error_flap_bereikt_alsnog_de_deadline` |
| deadline kiest de zwaarste klasse en alarmeert | `…test_deadline_commit_gaat_naar_de_zwaarste_klasse`, `…test_deadline_commit_alarmeert` |
| gemengde startupklassen committen alleen `SOURCE_WAIT` | `test_cycle_maintenance.TestVensterGedrag.test_gemengde_startupklassen_committen_alleen_source_wait` |
| na algemene readiness gelden 401/protocol normaal | `…test_na_tweemaal_geldige_algemene_readiness_vervalt_de_uitzondering` |
| na de harde eindtijd bestaat geen uitzondering | `…test_na_de_harde_eindtijd_geldt_de_normale_regel` |
| assignment-nulbewijs vereist twee snapshots | `test_cycle_lifecycle.TestNulbewijs` (zeven tests) |

Alle rijen uit het plan zijn gedekt; er ontbreekt geen enkele.

## Aanvullend gedekt — gaten die het plan niet noemde

Deze eisen staan wél in §7.7 of §7.9 maar hadden geen test in het plan. Ze zijn
alsnog gedekt omdat het zonder uitzondering fail-open-paden waren.

| Eis uit de spec | Test |
|---|---|
| een antwoord zonder status is niet interpreteerbaar → `PROTOCOL` | `test_cycle_readiness.TestVierwegclassificatie.test_ontbrekende_status_is_protocol` |
| een transportfout verzwaart niet tot `CREDENTIAL_ERROR` door een meegestuurde status | `…test_transportfout_wint_van_een_meegestuurde_status` |
| `SEVERITY` dekt precies de drie foutklassen; `READY` hoort er niet in | `test_cycle_readiness.TestSeverity.test_severity_dekt_precies_de_drie_foutklassen` |
| na een bevestiging zijn er weer twee waarnemingen nodig | `test_cycle_readiness.TestBevestiging.test_na_een_bevestiging_zijn_er_weer_twee_waarnemingen_nodig` |
| de bevestigingsdrempel loopt op monotone tijd, niet op de wandklok | `test_cycle_eventloop.TestToestandsmachine.test_de_bevestiging_loopt_op_monotone_tijd_niet_op_de_wandklok` |
| het auditspoor is compleet en op volgorde | `test_cycle_eventloop.TestEventSeq.test_de_loop_bewaart_ieder_event_in_volgorde_van_ontvangst` |
| een bevestigde foutklasse haalt de controller uit `WAITING` | `test_cycle_eventloop.TestToestandsmachine.test_een_bevestigde_foutklasse_haalt_de_controller_uit_waiting` |
| een jobacceptatie buiten `WAITING` legitimeert geen `RUNNING` | `…test_job_accepted_buiten_waiting_verandert_niets` |
| §7.9: een vóór-latch `RUNNING` job wordt niet afgebroken | `test_cycle_fence.TestJobInUitvoering.test_bevestigde_foutklasse_laat_de_lopende_job_staan`, `…test_fence_zetten_breekt_een_lopende_job_niet_af`, `…test_deadline_tijdens_een_lopende_job_breekt_hem_ook_niet_af` |
| na die job geldt de vastgelegde volgende toestand, niet `WAITING` | `…test_na_de_job_landt_de_controller_in_de_vastgelegde_toestand` |
| de scrubroute omzeilt een onopgeloste fence niet | `…test_scrub_heropent_niet_terwijl_een_onopgeloste_fence_staat` |
| een koude start vraagt geen nulbewijs (§7.7 "eventueel uitgesteld") | `test_cycle_fence.TestFenceWissen.test_koude_start_zonder_fence_vraagt_geen_nulbewijs` |
| de startupuitzondering geldt alleen voor de watchdog, niet voor de bevestiging | `test_cycle_maintenance.TestVensterGedrag.test_de_uitzondering_geldt_alleen_voor_de_watchdog_niet_voor_bevestiging` |
| venster is wandklok, fencedeadline is monotoon — nooit door elkaar | `…test_de_fencedeadline_blijft_monotoon_terwijl_het_venster_wandklok_is` |
| het alarm draagt het `maintenance_id` dat §10 monitort | `…test_het_alarm_draagt_het_maintenance_id` |
| een record met niet-positieve duur of een lege/witruimte-id wordt geweigerd | `test_cycle_maintenance.TestRecordvalidatie.test_niet_positieve_duur_wordt_geweigerd`, `…test_id_van_alleen_witruimte_wordt_geweigerd` |
| een vóór-latch job wordt níet gecanceld — daar dient het latchverdict voor | `test_cycle_lifecycle.TestOpNaLatchJob.test_een_voor_latch_job_wordt_niet_gecanceld` |
| §7.9: een geplande stop overleeft bronherstel | `test_cycle_lifecycle.TestDrain.test_een_drain_overleeft_bronherstel` |
| een drain heft een quarantaine niet op | `…test_drain_vanuit_een_fouttoestand_heropent_niets` |
| het nulbewijs kijkt naar twee opeenvolgende snapshots, niet naar de historie | `test_cycle_lifecycle.TestNulbewijs.test_het_bewijs_kijkt_naar_de_laatste_twee_opeenvolgende_snapshots` |
| de imagecontrole komt vóór de runnerstart (§7.9 stap 2 vóór 3) | `test_cycle_lifecycle.TestCyclusvolgorde.test_de_imagecontrole_komt_voor_de_runnerstart` |

## Afwijkingen van de letterlijke plancode

Het plan bevat volledige codeblokken; die zijn illustratief, terwijl het
migratieontwerp normatief is. Op drie punten week de code van de spec af en is de
spec gevolgd. Alle drie waren fail-open.

1. **Het nulbewijs geldt alleen bij herstel na een fence, niet bij een koude
   start.** De plancode eiste `nulbewijs_ok` voor iedere bevestigde `READY`,
   waardoor een verse host nooit uit `SOURCE_WAIT` kwam. Het nulbewijs weerlegt
   dat er nog een job aan een *gestopte* runner is toegewezen; bij een koude start
   is er niets te weerleggen. §7.7 spreekt daarom van het "eventueel uitgestelde"
   nulbewijs. Het plan schreef expliciet voor deze breuk te repareren in plaats van
   de oudere test aan te passen.

2. **Een lopende job wordt niet afgebroken, en de scrub omzeilt de fence niet.**
   §7.9 wil dat de controller bij een al vóór de latch `RUNNING` job de
   geselecteerde volgende toestand *vastlegt* zonder de job af te breken. De
   plancode overschreef `state` ook tijdens `RUNNING`, en `_on_scrub_done` kwam
   daarna weer bij `WAITING` uit op alleen `gates_groen` — zonder ooit naar de
   fence te kijken. Toegevoegd: `volgende_state` met `_commit_of_onthoud()`, en
   `_on_scrub_done` honoreert `volgende_state`, een gevraagde drain én een
   onopgeloste fence.

3. **Een gevraagde drain blokkeert een nieuwe runner.** `mag_child_starten` keek
   alleen naar de fence, de gates en de toestand. Een drain vanuit `SOURCE_WAIT`
   liet de toestand ongemoeid, zodat bronherstel de geplande stop stilzwijgend
   vergat en er weer een runner klaarstond. §7.9: een geplande stop verhindert dat
   de controller opnieuw een runner start.

Twee latere planstappen herschrijven `tick()` respectievelijk `_on_scrub_done()`
volledig (Task 14 en 15). Die herschrijvingen zouden de fixes hierboven ongedaan
maken; de takken zijn daarom samengevoegd in plaats van vervangen.

## Reproduceren

```bash
cd forgejo-runner
for f in tests/test_cycle_*.py; do python3 "$f"; done
```
