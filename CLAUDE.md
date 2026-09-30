# CLAUDE.md — scrum4me-server

Host-repo voor de Ubuntu-machine `scrum4me-server` én **canonieke bron** van de gedeelde Forgejo-Runner-poolbundel die op zowel `scrum4me-server` als `max2` draait. Op deze host draaien Forgejo 15.0.9 en Postgres zelf; een reboot hier is daarom ook control-plane-onderhoud voor de runnerpool.

## Scrum4Me-product

- **Naam:** scrum4me-server
- **product_id:** `cmsx8zbdh0002hk7rcgxxr00k`
- **Code:** `PRODUCTION`
- **Definition of Done:** nog niet geregistreerd in Scrum4Me (veld is leeg, gecontroleerd 2026-08-31). Tot JP er een vastlegt geldt voor het runnerpool-werk §9 "Definitie van een stabiele pool" uit [docs/forgejo-runner-pool/migratieontwerp.md](docs/forgejo-runner-pool/migratieontwerp.md): zeven aaneengesloten dagen waarin alle daar genoemde criteria groen zijn.
- **Lopend werk:** Forgejo Runner tweemachinepool. Fase 1 is een stabiele pool op Runner 12.10.1 over `scrum4me-server` en `max2`; fase 2 is pas daarna een rolling upgrade naar Runner 13. Het ontwerp heeft GO (delta-review R12, ronde 3); het uitvoerbare implementatieplan bestaat nog niet.

- **Verify:** deze repo bevat nog geen code. De verificatiecommando's worden vastgelegd in stap B van het migratieontwerp, samen met de bundel zelf.

<!-- BEGIN scrum4me-agent-workflow v1 -->
## Scrum4Me-methodiek en MCP-queue

Volgt de globale Scrum4Me-methodiek (`~/.claude/rules/scrum4me-methodiek.md` voor Claude; de "Scrum4Me-methodiek"-sectie in `~/.codex/AGENTS.md` voor Codex). Niet-triviaal werk: plan → Sprint/PBI/Story/Taak via de `scrum4me` MCP → `update_task_status` per laag → docs in de DB. Volg de bestaande goedkeuring en hardstop na materialisatie; voor alleen documentatie/instructies geldt de doc-only-uitzondering.

**Context.** Lees `product_id` uit het Scrum4Me-productblok in de repo-`CLAUDE.md`/`AGENTS.md`. Ontbreekt het, werk normaal zonder een product-ID te raden.
`mcp__scrum4me__get_context({ product_id })` → product, alle `active_sprints` en `agent_guide`. Kies de sprint binnen de actuele opdracht; lees `get_sprint_context({ sprint_id })` voor stories/taken en voeg `task_id` alleen toe voor het volledige taakplan. Gebruik `get_ideas_context({ product_id })` alleen voor ideeën. Geef expliciet bekende `agent.runtime` en `agent.model_id` mee (CLAUDE/CODEX + exact model-ID); laat onbekende gegevens weg. Ontbreekt de guide, gebruik `get_agent_guide` met dezelfde agentinvoer. Context autoriseert geen volgende story.

**Queue gebruiken.** Volg de `s4m-queue`-skill bij queue-handelingen. Gebruik de `mcp__scrum4me__queue_*`-tools met je eigen identiteit; de CLI is fallback bij ontbrekende MCP-toegang of identiteit.
- Stuur een geautoriseerde opdracht/vraag met `queue_push({ to, type, body, ... })`: `task`, `info` of `review_request`. Voor `task`/`review_request`: `cwd` op de ontvangende host en `meta.task: { objective, verification, response_format }`; geef `meta.task.repo` expliciet mee als die niet uit `cwd` kan worden afgeleid.
- Koppel bestaand werk met het meest specifieke `task_id`, `story_id` of `sprint_id` als toolparameter. Gebruik echte IDs uit de context, geen zichtbare codes. De tool leidt `product_id` en bovenliggende IDs af naar `meta.work_item`; geef geen losse `product_id`-parameter aan `queue_push`. Zonder bestaand werkitem geen ID verzinnen.
- Bewaar `message_id`; lees antwoorden met `queue_wait_reply({ message_ids: [...] })`. Ontvang werk via `queue_next`, lees body én metadata en werk binnen `meta.task.cwd`. Rond af via `queue_done`/`queue_fail` met `message_id` en `claim_token`; sluit CLI-claims via de CLI af.

**Reviewdocumenten via metadata.** Voeg bij `review_request` de beoordeelde bronnen toe als `meta.review_documents: { version: 1, items: [...] }`, naast `meta.task`.
- Iedere referentie bevat `key`, `title`, `product_id` en `sha256` van de exacte documentinhoud. Gebruik `source: "product_doc"` met `doc_id` + `revision_id`, of `source: "git"` met relatief `.md`-`path` + volledige gepubliceerde `commit_sha`.
- Lees als reviewer de gekoppelde exacte revisie/commit en controleer de SHA-256; alleen de body of de nieuwste versie lezen volstaat niet. Ontbreekt de gepinde bron of wijkt de hash af, voer de review niet uit: meld de fout en rond een geclaimd verzoek af met `queue_fail`.
- Rapporteer tegen deze pins en antwoord via `queue_done`; het `reviewed`-antwoord blijft via `in_reply_to` gekoppeld aan de reviewdocumenten van het verzoek.
<!-- END scrum4me-agent-workflow v1 -->

## Rol van deze repo

Canonieke bron van de gedeelde bundel plus de host-overlay voor `scrum4me-server`. De `max2`-repo is bewust géén tweede kopie van de bundel: twee kopieën zijn twee bronnen van waarheid en maken de byte-identiek-eis onbewijsbaar.

| Pad | Inhoud | Bestaat nu |
|---|---|---|
| `docs/forgejo-runner-pool/` | Ontwerp, reviewrapporten en runbook van de tweemachinepool | ja |
| `forgejo-runner/` | De volledige gedeelde bundel | nee — ontstaat in stap B |
| `hosts/scrum4me-server/` | Host-overlay en bewijsmateriaal voor deze host | nee — ontstaat in stap G |

## Oriëntatie

| Bestand | Waarvoor |
|---|---|
| [docs/forgejo-runner-pool/migratieontwerp.md](docs/forgejo-runner-pool/migratieontwerp.md) | **Begin hier.** Het goedgekeurde ontwerp: doelarchitectuur, trustgate, cyclecontroller, migratievolgorde stap A–H, stabiliteitsdefinitie, monitoring en rollback |
| §6.1 van dat ontwerp | Versiebeheer, distributie en driftgate — waarom deze repo canoniek is en hoe `BUNDLE_COMMIT` en de bundelhash werken |
| §7.7 van dat ontwerp | Trustscope voor global runners; wat een harde versus zachte trustafwijking is |
| §9 van dat ontwerp | Definitie van een stabiele pool — de facto DoD zolang Scrum4Me er geen heeft |
| [docs/forgejo-runner-pool/reviews/](docs/forgejo-runner-pool/reviews/) | Alle reviewrondes: R1–R10, delta-review R11 en delta-review R12 |
| [docs/forgejo-runner-pool/forgejo-upgrade-onderzoek-2026-09.md](docs/forgejo-runner-pool/forgejo-upgrade-onderzoek-2026-09.md) | Wat een Forgejo-upgrade op deze host betekent: gemeten uitgangssituatie, de LTS-lijn 15.0 tegenover nieuwere versies, het secretlek van 9 september |
| [docs/forgejo-runner-pool/implementatieplan-forgejo-15.0.9.md](docs/forgejo-runner-pool/implementatieplan-forgejo-15.0.9.md) | Het uitgevoerde plan voor 15.0.2 → 15.0.9 (30 september 2026), met drain, rollbackpunten en de doctor-functies; bewijs onder `evidence/forgejo-15.0.9/` |

## Infra-issues melden

Deze repo hoort bij een **host-product**. De agent-guide van Scrum4Me is hierover bindend: loopt er op deze host iets mis dat niet bij één taak hoort — een service die omvalt, een claim die verdwijnt, een timer die stopt — registreer dat dan met `create_issue` op het product van díe host (`max2` of `scrum4me-server`). Zonder die stap wordt er niets vastgelegd en ontdekt de volgende agent het opnieuw vanaf nul.

- **Fingerprint verplicht**, in de vorm `host:component:kern` — bijvoorbeeld `max2:mcp:claim-lost` of `scrum4me-server:caddy:cert-renewal-failed`. Dezelfde fingerprint bij herhaling telt op bij het bestaande issue in plaats van een kopie te maken, en heropent het automatisch als het als opgelost was gesloten. Zonder fingerprint krijg je elke keer een nieuw issue.
- **`reported_by`** is je eigen queue-adres, in de vorm `host:model`.
- Bevindingen en de oplossing gaan via `update_issue` (`append_research` / `append_resolution`, met `authored_by` op je eigen adres). Die velden appenden, dus je wist het werk van een voorganger niet. Sluiten kan alleen samen met een resolution.
- **Geen secrets in issues.** De inhoud wordt naar Forgejo gespiegeld en is daar leesbaar voor iedereen met repositorytoegang.

## Hardstop-regels

- **Geen secrets in Git.** Tokens, UUID-credentials, private sleutels en `.env` met echte waarden komen hier nooit in. Het actieve runnertoken leeft uitsluitend op de host als `/opt/forgejo-runner/credentials/forgejo-token`, mode `0600`, en dus nooit binnen een repo-werkboom.
- **Eén bron van waarheid.** Wijzigingen aan de gedeelde bundel gebeuren hier, in één commit. Beide hosts rollen uit vanaf dezelfde commit-SHA; `verify-stack.sh` vergelijkt `/opt/forgejo-runner/BUNDLE_COMMIT` en de canonieke bundelhash tussen de hosts. Kopieer de bundel nooit naar de `max2`-repo.
- **Niet deployen via Forgejo Actions.** Runnerjobs draaien in DinD zonder host-Docker-socket en zonder hostpadvolumes en kunnen de hoststack fysiek niet wijzigen. Uitrol gaat handmatig of via SSH vanaf `mac`. Bouw geen deployworkflow die per ontwerp niet kan werken.
- **Post-GO-wijzigingen aan het ontwerp vereisen een delta-review met GO** voordat de status verandert. Voeg iedere ronde toe aan het Review record in het ontwerp zelf. Zie de `review-loop`-skill.
- **Beweer niets over de boom dat je niet hebt gemeten.** Dit ontwerp is tweemaal NO-GO gegaan op precies die fout: doelstructuur beschreven als bestaand, en een bewering op één plek gecorrigeerd terwijl hij elders bleef staan. Grep na iedere fix.
- **Forge:** Forgejo (`git.jp-visser.nl`) is leidend. Push alleen naar `origin`; PR's uitsluitend op Forgejo via de compare-URL, de API of `tea` — nooit `gh pr create`.
- **Productiecontext.** Forgejo en Postgres draaien op deze host. Herstart de host-Dockerdaemon niet, wijzig `/etc/docker/daemon.json` niet en voer geen hostbrede `docker system prune` uit. Een reboot van deze host vereist een vooraf gearmd maintenance-record op beide hosts.
