# ISS-18 publisher — codereview en sprintresultaat

Datum: 2026-09-09. Sprint S-2026-09-09-3 / PBI-7 / ST-014 / T-59.

## Uitkomst

De publisherreparatie is geïmplementeerd en onafhankelijk gereviewd met GO.
Reviewrange: `3be6e70084b24610301dc26dd984a67494726a46..442cc37dcb0a560e6466b797333065534ea0dbd5`.
Reviewer: onafhankelijke subagent `review_iss18_code`; Critical 0 / Important 0 / Minor 0.

- Geldige exit0/10 wordt pas groen na strikte JSON-validatie; zachte waarschuwingen blijven zichtbaar met 24-uursbeoordelingsplicht.
- Harde/onleesbare/ongeldige/tegenstrijdige metingen trekken oud groen in, evenals ontbrekende of niet-reguliere inputs.
- De shellfallback dekt ook uitval van Python; onmogelijke invalidatie door schrijffouten wordt expliciet gemeld.
- Groen behoudt tijd-, target-, labels- en allowlistbinding. Scanner en controller zijn niet gewijzigd.

## Verificatie

| Controle | Resultaat |
|---|---|
| RED: twee soft-only-tests tegen oorspronkelijke publisher | exit3 i.p.v.0, verwachte fout |
| RED: zes ontbrekende/niet-reguliere-inputgevallen | exit2 i.p.v.3, verwachte fout |
| Nieuwe publisher-unittests | 6 methoden groen, inclusief 62 exit/JSON-matrixgevallen en echte offline CLI |
| Gerichte Bats publisher/timer | 11 geslaagd |
| Volledige Python-suite | 229 geslaagd, geen skips |
| Volledige Bats-suite | 133 geslaagd, 1 bestaande skip wegens ontbrekende timeout/gtimeout voor runner-image--wait-test |
| ShellCheck scripts/*.sh | exit0 |
| git diff --check | exit0 |

De reviewer herhaalde zelfstandig de zes publisher-tests en diffcontrole, en controleerde het consumercontract en alle vier gewijzigde bestanden. De volledige suites zijn door de uitvoerende agent gedraaid, niet door de reviewer herhaald. Bestaande ResourceWarnings bij trust_scope_cli-tests zijn niet gewijzigd.

## Planafstemming

Vier geplande bestanden gewijzigd: publisher, nieuwe Python-tests, bestaande Bats-succesfixture en README. Enige gemotiveerde verbetering ten opzichte van het plan: fixtureherstel in `finally`, zodat een verwachte RED-assertie niet de volgende inputsubtest vervuilt. De eerste volledige RED-run had daardoor 4 vervolgerrors; na cleanup-correctie toonde de gerichte RED-run uitsluitend 8 verwachte failures. Testverwachtingen zijn niet versoepeld.

`verify_task_against_plan` is aangeroepen en gaf `divergent` met reden **geen plan-baseline aanwezig**, `job_id=null`. Deze interactieve uitvoering heeft geen geclaimde job met frozen snapshot. Daarom is geen automatische ALIGNED-claim gedaan. Handmatige vergelijking met het goedgekeurde plan én onafhankelijke codereview bevestigen de overeenstemming. De origin/main-diff bevat naast code ook de eerder goedgekeurde plan/reviewdocumenten.

## Overdracht en grenzen

Canonieke branch: `codex/iss-18-soft-trust` op `https://git.jp-visser.nl/janpeter/scrum4me-server`.
Werkboom: `/Users/janpetervisser/.config/superpowers/worktrees/scrum4me-server/iss-18-soft-trust`.

Geen merge, hostuitrol, serviceherstart, Actions-toggle of runnerproef uitgevoerd. ISS-18 blijft open totdat afzonderlijk goedgekeurde uitrol en live verificatie zijn afgerond. Een lokale code-GO bewijst geen zeven stabiele pooldagen en geen commitgebonden workflow-attestation.

Volgende stap vereist expliciet merge-/uitrolakkoord. Uitrol moet uit één canonieke commit komen; niet los op max2 patchen. Eventuele rollback wordt na akkoord voorbereid naar de voorgaande canonieke bundelcommit `29beecacfd1b424d34e997a2a3398b66b2153fbe`, met behoud van hostspecifieke credentials en configuratie. Dat is nog geen uitgevoerde rollback of volledig live-uitrolrunbook.

VERDICT: GO
