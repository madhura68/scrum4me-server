# Delta-review R11 — Forgejo Runner tweemachinepool

Beoordeeld document: `outputs/forgejo-runner-tweemachinepool-migratieontwerp.md`  
Beoordeelde revisie: 605 regels, SHA-256 `5f91b8c1030276d8263a0bbeaa05eb84156fc077db654a9d1b0350c6654c6a79`

## Severity counts

- BLOCKER: 0
- MAJOR: 0
- MINOR: 0

## Findings

Geen findings.

## Delta-controle

- Ronde-10 MAJOR over boot-SLA versus maintenance-record is opgelost. §6 maakt de vijfminuten-SLA conditioneel: buiten een geldig, identiek gearmd control-plane-maintenance-record alarmeert en reset overschrijding; binnen zo'n niet-verlopen record is de overschrijding alleen informatief zolang de controller de verwachte control-plane-`SOURCE_WAIT` observeert. §9 spiegelt dit als stabiliteitscriterium: `SOURCE_WAIT` is alleen binnen een gelijk gearmd, niet verlopen control-plane-record toegestaan zonder reset; buiten dat venster en na harde eindtijd volgt availability-incident plus reset. §10 monitort `maintenance_id`, armingsgelijkheid, eindtijd en de exacte alarm/reset-grenzen.
- Ronde-10 MINOR over de eerste oude DinD-volume-scrub is opgelost. Stap G eist een afzonderlijk scrub-maintenance-record met eigen `maintenance_id`, UTC-start en harde UTC-eindtijd op basis van actuele dataomvang plus proefmeting. De tijdelijk opgeschorte §9-criteria zijn begrensd tot maximale `SCRUBBING`-duur en tijd-tot-`WAITING` voor alleen `scrum4me-server`; trustgate, credential/protocolclassificatie, assignment-nulbewijs, geen-nieuwe-runner-tijdens-scrub en alle `max2`-criteria blijven gelden. §10 alarmeert weer zodra dit aparte scrubrecord ontbreekt, ongeldig is of verlopen is.
- Bestaande Runner 12-poolcontracten zijn niet geregressed in de gecontroleerde secties. De one-job/scrub-fence, exact één connection, DinD-isolatie, event-sequence fence, readinessclassificatie, trustgate-grenzen, `SOURCE_WAIT` versus quarantaine en Runner 13-uitstel blijven intact. §14 houdt de productieblokkade correct staan totdat deze delta-review door beide reviewers GO krijgt.

VERDICT: GO
