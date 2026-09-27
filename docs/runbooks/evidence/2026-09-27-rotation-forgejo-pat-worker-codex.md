# Rotatie Forgejo-PAT `worker-codex` — 2026-09-27 (T-107, IDEA-221)

Uitgevoerd door mac:claude met GO van JP. Script `rotate-env-credential` op main `36e6007`
(sha256-prefix `343cc1f1c8ae8d75`, gelijk op srv en max2). Keychain-item `s4m-tok-forgejo-codex`.
**Geen waarden in dit document.**

| Fase | Tijd (UTC) | Uitkomst |
|---|---|---|
| 0 | 14:1x | `check_queue_empty` 0; `agent-codex` zonder lopende codex-processen (srv en max2). `old` = Forgejo-token 11 `CODEX_FORGEJO` (s4m-codex-reviewer; `/user` 200; `token_last_eight` klopt). `rewrite-key --dry-run`: 1 treffer in `compose/worker-codex.env` op srv en op max2, 0 in `worker-idea.env` |
| 1 | 14:2x | Nieuwe PAT id 36 `CODEX_FORGEJO-2026-09-27` via `forgejo admin user generate-access-token --raw`, direct in de Keychain; scope gelijk aan id 11; `/user` 200 s4m-codex-reviewer |
| 2 | 14:23:38–14:23:41 | `rewrite-key` srv stamp `20260927T142338_878504Z`, max2 `20260927T142339_163873Z` (elk 1 vervanging); `agent-codex` gerecreate op beide hosts |
| 3 | 14:24–14:26 | environ-canary: nieuw `treffers=1`, oud 0 op beide containers; `/user` vanuit de containers (header via stdin) 200; health `healthy` op beide; 0 auth-fouten in de containerlogs; Forgejo `updated_unix` van id 36 = 14:24:01 |
| 4 | 14:2x | id 11 verwijderd via DB-delete (met naam, account en id als voorwaarde); oud `/user` **401**; nieuw 200; beide containers 200 |

Faalvenster: geen. De oude token bleef geldig tot na het bewijs in fase 3.

**Voorval (zonder gevolg):** de eerste extractie van de oude token naar de Keychain gebruikte
een regex waarin `\x27` letterlijk werd, waardoor de waarde bij het eerste `2` of `7`
afgekapt werd. Er is niets geprint. De dry-runs weigerden terecht (0 treffers) en het item is
vervangen. Voor een PAT haal je de waarde op met het patroon `^FORGEJO_TOKEN=[0-9a-f]{40}$`
(kaart C.4).

Opgeruimd na JP-akkoord (2026-09-27): de back-ups `worker-codex.env.bak-<stamp>` op srv en max2, en het Keychain-item `old`.
