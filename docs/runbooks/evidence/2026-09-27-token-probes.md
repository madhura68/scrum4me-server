# Tokens: uitgifte en intrekking per uitgever — proeven (IDEA-221, T-104)

Datum: 2026-09-27 · uitgevoerd door mac:claude. **Geen waarden in dit document.** Waarden zijn
vergeleken in-process: via een salt die per run willekeurig is, via `token_last_eight` binnen
één proces, of via sha256 tegen `api_tokens.token_hash`.

## 1. Forgejo-PAT's (Forgejo 15.0.2, container `scrum4me-forgejo`, DB `forgejo` in `scrum4me-postgres`)

### Aanmaken: bewezen

```bash
ssh scrum4me-srv 'sudo docker exec -u git scrum4me-forgejo forgejo admin user generate-access-token \
  -u <account> -t <naam> --scopes <scope,scope> --raw' | <pipe naar de consument>
```

- Werkt voor elk account, ook voor een bot zonder bekend wachtwoord.
- `--raw` zet alleen de waarde (40 hex) op stdout, dus de waarde kan direct een pipe in.
- De proeftoken gaf `GET /api/v1/user` → 200 met de juiste login.
- **Let op:** een naam die al bestaat geeft een fout. Gebruik daarom altijd een datum in de naam.

### Intrekken

| Weg | Uitkomst |
|---|---|
| API `DELETE /users/{u}/tokens/{id}` met een admin-PAT plus `Sudo: {u}` | **401**: dit endpoint vereist basic-auth (het wachtwoord van het account). Ook de hulptoken kon zichzelf niet intrekken (401). |
| API `GET /users/{u}/tokens` met een admin-PAT met `write:user` plus `Sudo` | 200: **lijst en id's opvragen werkt wel** |
| forgejo-CLI | er is geen subcommando om een token in te trekken |
| **DB:** `DELETE FROM access_token WHERE id = <id>` (DB `forgejo`, via `docker exec -i scrum4me-postgres psql -U scrum4me -d forgejo`, SQL via stdin) | **bewezen:** 401 direct na de delete, en ook na 5, 30 en 90 s. De tokencache vertraagt de intrekking dus niet. |
| UI (Instellingen → Toepassingen) als de eigenaar | voor eigen tokens van janpeter; niet voor bot-accounts zonder bekend wachtwoord |

Alle proeftokens (ids 32–35: `idea221-probe*`, `idea221-revoke-helper`) zijn via de DB
verwijderd; daarna stonden er 0 `idea221-*`-rijen.

**Incident tijdens de proef:** een controle-aanroep probeerde een tweede token met dezelfde naam
aan te maken. Dat mislukte op de naam en maakte geen token aan (ids 32–35 zijn allemaal
verklaard).

### Inventaris: PAT per consumer (koppeling via `token_last_eight`, in-process)

| Consumer | Sleutel | Forgejo-token (id, account, naam) | Scope |
|---|---|---|---|
| srv + max2 `compose/worker-idea.env` | `FORGEJO_TOKEN` | 6 janpeter `FORGEJO_TOKEN_SERVER` | write:repository |
| srv `compose/worker-deploy.env` | `FORGEJO_TOKEN` | 13 janpeter `worker-deploy-proread` | read:repository |
| srv + max2 `compose/worker-codex.env` | `FORGEJO_TOKEN` | 11 s4m-codex-reviewer `CODEX_FORGEJO` | write:activitypub, misc, notification, organization, package, issue, repository, user |
| srv `secrets/workers.env` (max2: zelfde klasse volgens de salt-meting) | `FORGEJO_TOKEN` | 7 janpeter `janpeter-shell` | write:admin, repository, user |
| srv `repos/Scrum4Me/.env` | `FORGEJO_TOKEN` | 21 janpeter `ISSUE_TOKEN2` | all |
| srv `/etc/forgejo-mirror/forgejo.env` | `FORGEJO_TOKEN` | 2 janpeter `Sync-forgejo-github` | write:organization, write:repository, read:user |
| srv `/etc/ops-agent/forgejo-tag.token` | heel bestand | 29 mcp-release `ops-agent-deploy-tag` | write:repository |
| max2 `/opt/forgejo-runner/credentials/trust-scan.env` | `FORGEJO_TOKEN` | 26 janpeter `FREX_RUNNER` | read:activitypub, read:admin, write:misc, notification, organization, package, issue, repository |
| mac `~/.zshenv` | `FORGEJO_TOKEN` | 24 janpeter `s4m-queue-2026-08-29` | write:activitypub, admin, misc, notification, organization, package, issue, repository, read:user |

**Correctie op een eerdere meting.** Een eerste `/user`-controle met een regex zonder woordgrens
koppelde `Scrum4Me/.env` aan s4m-codex-reviewer. De meting per sleutel geeft id 21; dat klopt
met de salt-meting, die voor dat bestand een andere waarde vond dan voor `worker-codex`. De
PAT van `worker-codex` (id 11) staat dus **alleen** in `worker-codex.env` op srv en max2.

Forgejo heeft in totaal 26 PAT's. Voor 17 daarvan is in deze inventaris geen consumer gevonden
(onder andere `SCRUM4ME_FORGEJO`, `mac-Forgejo`, `JP_FORGEJO`, `TEMP_OPS`, `SCRUM4ME_MAX2`,
`ISSUE_TOKEN`). Dat zijn kandidaten om in te trekken, of om hun consumer te vinden, bijvoorbeeld
in mac-production-secrets of CI-secrets.

## 2. Scrum4Me API-tokens (`api_tokens`, scrum4me-workers-UI `/api-tokens`)

- **Aanmaken:** in de workers-UI (alleen admin). De token is `randomBytes(32).hex` en wordt één keer
  getoond. De DB bewaart `sha256(raw)`. Er zijn soorten `IMPLEMENTATION`/`PLANNING`/`WORKERS_UI`/`COPILOT`,
  een optionele vervaldatum en maximaal **10 actieve** tokens per gebruiker. Oud en nieuw kunnen
  dus tegelijk bestaan.
- **Intrekken:** met de knop in dezelfde UI (`revoked_at = now()`). Als admin kun je elke token
  intrekken.
- Er bestaat oudere tokens met base64url-vorm (43 tekens); die worden op dezelfde manier gehasht.

| Consumer | Token (id, label, soort) |
|---|---|
| srv + max2 `worker-idea.env`, `worker-codex.env`; max2 `~/.claude.json` | `cmp40ivm…` "Srum4Me server" IMPLEMENTATION |
| srv `worker-docs.env`, `worker-deploy.env` | `cmr6gdat…` "worker-deploy" IMPLEMENTATION |
| srv `~/.claude.json`, `~/.codex/config.toml` | `cmp8u3vh…` "scrum4me-server" IMPLEMENTATION |
| mac `~/.zshenv`, `~/.claude.json`, `~/.codex/config.toml` | `cmrq0hrk…` "S4M_MCP_MAC" IMPLEMENTATION |
| srv `Scrum4Me/.env`, srv + max2 `ops-dashboard/.env` | **geen DB-rij**: geen geldige API-token; waarvoor hij dient, moet nog uitgezocht worden |

Er zijn 9 actieve tokens. Zonder gevonden consumer: "voor mcp-tester", "Janpeter",
"agent-harness-local-llm-max2" en de twee COPILOT-tokens (digiplein, mediaorganizer; hun
consumers staan buiten deze inventaris).

**Incident:** bij een vormcontrole toonde mac:claude de eerste 6 tekens van de token "worker-deploy",
omdat de maskering alleen kleine hex-tekens verving. Er blijven ruim 220 bits onbekend. Het
advies is die token bij de eerste Scrum4Me-rotatie mee te nemen. Voortaan toon je bij
vormcontroles alleen de lengte en de tekenklasse.

## 3. Claude

| Soort | Waar | Aanmaken | Intrekken / vervangen |
|---|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` (2 waarden: srv-workers A, max2 `worker-idea` B) | compose-env | `claude setup-token` (interactief, browser, vereist abonnement), op de mac, uitvoer via een pipe naar de Keychain | Volgens de docs: nieuwe token maken en de consumer herstarten. **Hoe je de oude intrekt, is niet bewezen**; JP controleert dat in de instellingen van claude.ai. Tot dan blijft de oude token geldig tot hij verloopt. |
| `ANTHROPIC_API_KEY` (1 waarde) | `copilot.env`, `ops-dashboard/.env` (srv+max2); leeg in sommige worker-env's | Anthropic Console → API Keys | Console: sleutel uitschakelen of verwijderen (direct) |
| Interactieve login | srv/max2 `~/.claude/.credentials.json` (access en refresh token, vernieuwt zichzelf); mac: Keychain "Claude Code-credentials" | `claude auth login` / `/login` | `/logout`, of de sessie beëindigen in claude.ai |

Docs (ctx7 `/websites/code_claude`): `CLAUDE_CODE_OAUTH_TOKEN` gaat vóór de Keychain-credentials.
Een token van `setup-token` mag alleen model-aanroepen doen. Een aanwezige `ANTHROPIC_API_KEY`
wint in `-p`-modus altijd.

## 4. ChatGPT / Codex (codex-cli 0.154.0)

- Alle `auth.json`-bestanden hebben `auth_mode=chatgpt`. Het gaat om **één ChatGPT-account**
  (gelijke `account_id`), maar met **vijf eigen sessies**: elke refresh-token is anders.
  - srv `~/.codex`
  - srv `worker-codex-home`
  - max2 `~/.codex`
  - max2 `worker-codex-home`
  - mac `~/.codex`
  
  Vernieuwen op de ene plek raakt de andere dus niet.
- **Aanmaken:** `codex login --device-auth` op een host zonder browser, of `codex login` met een
  browser. De ChatGPT-OAuth-tokens komen in `$CODEX_HOME/auth.json`. Voor `worker-codex-home`
  zet je `CODEX_HOME=/srv/scrum4me/worker-codex-home`. Er zijn ook `--with-api-key` en
  `--with-access-token`, die de waarde van stdin lezen.
- **Intrekken:** `codex logout` per plek verwijdert de lokale credentials. Alle sessies tegelijk
  intrekken gaat via het ChatGPT-account (uitloggen op alle apparaten). Daarna moeten alle vijf
  plekken opnieuw inloggen.

## Samengevat per uitgever

| Uitgever | Aanmaken | Intrekken | Bewezen |
|---|---|---|---|
| Forgejo | CLI `generate-access-token --raw` in een pipe | DB-delete op id (id via de lijst-API of de DB) | ja, 200 → delete → 401 (0–90 s) |
| Scrum4Me | workers-UI `/api-tokens` | workers-UI intrekken | code gelezen; niet uitgevoerd |
| Anthropic API-key | Console | Console | gedocumenteerd |
| Claude OAuth-token | `claude setup-token` | open (claude.ai-instellingen) | gedeeltelijk |
| Claude/Codex-login | `/login`, `codex login --device-auth` | `/logout`, `codex logout`, account-breed via de uitgever | gedocumenteerd |
