# Delta-review R12 — reviewreplies van `mac:codex`

Onderwerp: de zes post-GO-wijzigingen na R11 (repo-tracking en versiebeheer, headroomgate op beide hosts, Python-controller, convergente quarantaine, eerlijke variabelentelling met jobduurbaseline, redactionele fixes).

Enige reviewer, conform de delta-variant van de review-loop: één reviewer uit de modelfamilie die de wijzigingen niet schreef.

| Ronde | Revisie | Request | Reply | Verdict | B/MA/MI |
|---|---|---|---|---|---|
| 1 | `d718f6a` | `7cce63dd-de1a-4264-bf0e-3bbfbf17716c` | `7fe0bed9-8e07-4a27-96fa-08ec512cd2cf` | NO-GO | 0/1/0 |
| 2 | `4a4df16` | `db6766ed-889e-4161-b86c-3190c14f48cd` | `6a6c8efa-a3b5-47d1-9c36-f794acc8f7a0` | NO-GO | 0/1/0 |
| 3 | `182de44` | `c61d0e45-548f-4e72-8097-3e076aab5199` | `f6ca262c-6fae-40c9-88b3-88ca2d435b4c` | GO | 0/0/0 |

Beide MAJORs zijn volledig geaccepteerd en tegen de boom nagemeten voordat ze werden verwerkt. Er is in deze loop geen bevinding afgewezen.

## Ronde 1 — MAJOR: §6.1 verwarde doelstructuur met de as-built repo's

§6.1 beschreef in tegenwoordige tijd een `forgejo-runner/`, `hosts/scrum4me-server/`, `hosts/max2/` en `evidence/` die niet bestonden, en claimde een draaiende pre-commit secret-scan plus een `.gitignore`-regel `/opt/forgejo-runner/credentials/`. Nagemeten: beide repo's bevatten alleen `README.md`, `CLAUDE.md`, `.gitignore` en in `scrum4me-server` de documenten; geen geïnstalleerde hooks, alleen `pre-commit.sample`; `.gitignore` negeert `credentials/` en niet het genoemde hostpad.

Verwerkt: §6.1 werd een doelstructuur met kolommen "bestaat nu" en "ontstaat in"; de doorlopende secret-scan werd een stap-B-gate met verplicht blokkeringsbewijs; de onbewezen Actions-claim werd een stap-A-vaststelling.

## Ronde 2 — MAJOR: stap A droeg de oude Actions-aanname nog

Na de ronde-1-fix zei §6.1 dat stap A per repo vaststelt óf Actions is ingeschakeld, terwijl stap A zelf nog opdroeg beide repo's *als* Actions-enabled op te nemen. Regel 144 en regel 352 van commit `4a4df16` spraken elkaar tegen — de klassieke restfout: op één plek gecorrigeerd, op de andere blijven staan.

Verwerkt: beide passages hanteren nu dezelfde regel. Alleen een aantoonbaar Actions-enabled repo komt als trusted scope in `trusted-actions-scope.yml`; een repo met Actions uit wordt daar expliciet als bekende niet-Actions-repo vastgelegd zodat later inschakelen als drift zichtbaar wordt.

## Ronde 3 — GO

Geen resterende bevindingen. De reviewer bevestigde dat §6.1 en stap A dezelfde regel hanteren en vond geen derde normatieve plek waar de oude aanname voortleeft.
