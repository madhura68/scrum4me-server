# Plan-review — implementatieplan stap A + B

Adversarial reviewloop over het implementatieplan voor stap A en B van de Forgejo-Runner-tweemachinepool. Twee onafhankelijke reviewers uit verschillende modelfamilies, die elkaars uitvoer niet zien.

| Ronde | Revisie | Codex | Claude | Uitkomst |
|---|---|---|---|---|
| 1 | `c386825` | 1 BLOCKER / 2 MAJOR / 0 MINOR | 0 / 1 MAJOR / 2 MINOR | NO-GO |
| 2 | `b959789` | 1 BLOCKER / 0 / 1 MINOR | 0 / 1 MAJOR / 1 MINOR | NO-GO |
| 3 | `3aee497` | 0 / 1 MAJOR / 0 | **GO** | NO-GO |
| 4 | `171b79e` | 0 / 1 MAJOR / 0 | **GO** | NO-GO |
| 5 | `8909ae0` | 0 / 1 MAJOR / 0 | **GO** (2 MINOR) | NO-GO |
| 6 | `61c9fc3` | 0 / 1 MAJOR / 0 | 1 BLOCKER / 1 MAJOR / 0 | NO-GO |
| 7 | `0352d49` | **GO** | **GO** | **GO** |

Twaalf bevindingen, elf volledig geaccepteerd en één deels verworpen. De verwerping — codex' stelling dat `/collaborators/{c}/permission` het `Permission`-schema met booleans levert — is in ronde 3 door beide reviewers als terecht geadjudiceerd: het endpoint levert `RepoCollaboratorPermission` met `permission` als string. De valide kern van die bevinding is wel verwerkt en bleek zwaarder te wegen dan gemeld: de repository-eigenaar zat helemaal niet in `writers`, en beide repo's in scope hebben nul collaborators, dus de schrijversverzameling was leeg.

## Waar de bevindingen zaten

Vanaf ronde 3 zaten alle bevindingen in één artefact: de trustscope-gate van Task 6. De overige 21 taken zijn na ronde 1 niet meer geraakt. Die gate is het enige onderdeel van stap A en B dat een externe, niet door ons beheerste API interpreteert.

Elke ronde legde een dieper niveau van dezelfde fail-openfamilie bloot:

1. **Respons aanwezig** — een 404 werd stil "leeg" in plaats van onleesbaar.
2. **Respons van de juiste vorm** — een onverwacht lichaam werd stil een lege lijst; bij `repos()` betekende dat "niets te toetsen" en dus een groene gate zonder één gemeten repository.
3. **Velden aanwezig** — een ontbrekende `has_actions` werd `False` en sloeg de hele inspectie over; een ontbrekende `owner.login` liet de meest bevoorrechte identiteit wegvallen.
4. **Geneste collectie- en itemvorm** — een dict waar een lijst hoorde gaf een `AttributeError` in plaats van een auditeerbare `Unreadable`.

## De keerzijde, en de les

Ronde 6 liet zien wat fail-closed doorvoeren kost zonder de gedocumenteerde uitzonderingen te kennen: `/repos/{owner}/{repo}/teams` antwoordt met HTTP 405 `repo is not owned by an organization` voor iedere repository van een gebruiker, en beide repo's in scope zijn dat. De verscherping uit ronde 3 maakte daar `Unreadable` van, waardoor de gate voor precies de doelrepo's nooit groen kon worden.

Dat was alleen te vinden door de endpoints daadwerkelijk aan te roepen. Drie rondes statische analyse — inclusief een verticale trace door de volledige foutketen — misten het. De reviewer noteerde de les zelf: een verticale trace door één pad bewijst niets over de andere aanroepplekken, en mechanisch zoeken op de vórm vindt wat het verhaal mist.

De volledige per-ronde-verantwoording staat in de sectie **Review record** van [het plan zelf](../implementatieplan-stap-a-b.md).
