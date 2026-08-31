# Eindrapport review-loop — Forgejo Runner-tweemachinepool

**Datum:** 31 augustus 2026  
**Reviewers:** `mac:codex` en `scrum4me-server:claude`  
**Uitgevoerde rondes:** 10 van maximaal 10  
**Eindstatus:** **NO-GO — geen dubbele GO bij de rondecap**

## Conclusie

Het migratieontwerp is in tien onafhankelijke adversarial rondes substantieel aangescherpt, maar is nog niet goedgekeurd voor implementatie. In de finale ronde gaf Mac-Codex GO zonder findings; Claude gaf NO-GO met één MAJOR en één MINOR. Volgens het review-loopcontract is dubbele GO vereist en stopt de loop na ronde 10.

De productiehosts zijn niet gewijzigd. Er wordt nog geen implementatieplan uitgevoerd.

## Finale verdicts

| Reviewer | BLOCKER | MAJOR | MINOR | Verdict |
|---|---:|---:|---:|---|
| `mac:codex` | 0 | 0 | 0 | GO |
| `scrum4me-server:claude` | 0 | 1 | 1 | NO-GO |

De exact in ronde 10 beoordeelde revisie telde 578 regels en had SHA-256 `a9e2639738b96e475eb5e2978686b1b2c605ade8aff47264fb610c79c5469f5f`.

Het ontwerp inclusief het daarna toegevoegde finale reviewrecord telt 598 regels en heeft SHA-256 `58f3d8d7f30396b484811954ed8bcc3d4fba5d032d9554b01bab60a7959ae79c`.

## Resterende bevindingen

### MAJOR — boot-SLA botst met geldig maintenance-record

De boot-SLA reset na vijf minuten onverkort de zevendaagse stabiliteitsperiode. Het formele control-plane-maintenance-record staat echter tot maximaal dertig minuten `SOURCE_WAIT` toe. Daardoor kan correct uitgevoerd, gepland onderhoud toch als stabiliteitsbreuk tellen.

Vereiste deltawijziging:

- binnen een geldig en op beide hosts identiek gearmd `maintenance_id`-venster is boot-SLA-overschrijding informatief en reset zij de stabiliteitsperiode niet;
- buiten het venster en na de harde eindtijd blijven alarm en reset ongewijzigd;
- §6 en §9 moeten exact dezelfde regel gebruiken.

### MINOR — eerste 121-GB-scrub gebruikt nog een los prozavenster

De eenmalige scrub van het oude anonieme DinD-volume kan aantoonbaar langer dan de reguliere grenzen duren, maar gebruikt nog niet het formele maintenance-record.

Vereiste deltawijziging:

- arm een afzonderlijk `maintenance_id`-record voor deze scrub;
- bepaal de harde eindtijd op basis van opnieuw gemeten dataomvang en een proefmeting;
- benoem expliciet welke stabiliteitscriteria gedurende dit venster tijdelijk niet gelden;
- de-arm expliciet en laat na expiry normale alarmen gelden.

## Rondehistorie

| Ronde | Mac-Codex | Scrum4Me-Claude | Resultaat |
|---:|---|---|---|
| 1 | 1 B / 3 M / 1 m — NO-GO | 1 B / 2 M / 3 m — NO-GO | herzien |
| 2 | 0 B / 2 M / 1 m — NO-GO | 1 B / 1 M / 2 m — NO-GO | herzien |
| 3 | 1 B / 1 M / 1 m — NO-GO | 0 B / 2 M / 2 m — NO-GO | herzien |
| 4 | 0 B / 0 M / 1 m — GO | 0 B / 2 M / 2 m — NO-GO | herzien |
| 5 | 0 B / 0 M / 0 m — GO | 0 B / 1 M / 1 m — NO-GO | herzien |
| 6 | 0 B / 0 M / 0 m — GO | 0 B / 1 M / 1 m — NO-GO | herzien |
| 7 | 0 B / 0 M / 0 m — GO | 0 B / 1 M / 0 m — NO-GO | herzien |
| 8 | 1 B / 1 M / 1 m — NO-GO | 0 B / 1 M / 1 m — NO-GO | herzien |
| 9 | 0 B / 0 M / 0 m — GO | 0 B / 2 M / 0 m — NO-GO | herzien |
| 10 | 0 B / 0 M / 0 m — GO | 0 B / 1 M / 1 m — NO-GO | cap bereikt |

`B` = BLOCKER, `M` = MAJOR, `m` = MINOR.

## Belangrijkste bereikte verbeteringen

- Eerst een stabiele pool met Runner 12.10.1; Runner 13 blijft een afzonderlijke rolling canaryfase.
- Twee onafhankelijke runnerrecords met exact dezelfde productielabels en exclusieve hostlokale DinD.
- Per-job `one-job --wait`-cyclus, zodat geen volgende job vóór een bewezen scrub kan starten.
- Declaratieve connectionconfig zonder actieve legacy `.runner`; token via read-only `token_url`-bestand mode `0600`.
- Expliciete privileged-DinD-risicoacceptatie en mechanische trustscope voor global runners.
- Fail-closed workflowdiscovery met `.forgejo/workflows` en Forgejo's `.github/workflows`-fallback.
- Digest-gepinde jobimages, beperkte allowlist en volledige verwijdering van jobstate/buildcache.
- Benoemd DinD-volume, resourceheadroom op gemeten `MemAvailable`, concrete endpointmatrix en productiegezondheidschecks.
- Racevrije schedulingfence met lokale geserialiseerde eventordering, assignmentnulbewijs, scrub en bounded recovery.
- Expliciete bootcontroller, sequentiële reboottests en eerlijk onderscheid tussen runnerpool en het co-located Forgejo/Postgres-control-plane.

## Vervolg

Maak geen implementatieplan op basis van de huidige NO-GO-status. De kortste vervolgstap is een kleine revisie met de MAJOR en MINOR hierboven, gevolgd door een nieuwe **delta-review** met beide reviewers. Pas bij dubbele GO mag het uitvoerbare implementatieplan worden opgesteld en daarna afzonderlijk worden goedgekeurd vóór productieaanpassingen.
