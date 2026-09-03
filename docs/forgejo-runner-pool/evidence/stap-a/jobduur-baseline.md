# Jobduur-baseline (warme DinD-cache)

Gemeten in stap A (Task 7) op 2026-09-01. §9 zet de cacheloze pool tegen deze
waarde af met een grens van 200%; zonder deze baseline is dat criterium niet toetsbaar.

## Gemeten run

- Repository/workflow: `janpeter/scrum4me-workers` `.forgejo/workflows/ci.yml` (job `verify`: npm ci + npm run verify)
- Reden voor deze keuze: de historisch zwaarste workflow (Scrum4Me ci.yml, ~59 min) deployt bij
  workflow_dispatch (vercel + prisma migrate) en is dus niet veilig te dispatchen; scrum4me-workers
  ci.yml is de zwaarste deploy-vrije, dispatchbare kandidaat (JP-keuze). Zie ephemeral/trust-bewijs.
- run_id: 2521 (workflow_dispatch)
- started: 2026-09-01T00:28:32+02:00
- stopped: 2026-09-01T00:30:42+02:00
- **wandkloktijd (warme cache): 130 s**
- Historische max succesvolle duur van dezelfde workflow: 203 s (72 runs); deze run was korter door warme cache.

## Commando

```bash
source ~/.zshenv
curl --config <(printf 'header = "Authorization: token %s"\n' "$FORGEJO_TOKEN") \
  "https://git.jp-visser.nl/api/v1/repos/janpeter/scrum4me-workers/actions/runs?limit=2"
# started/stopped uit run 2521; duration wordt door Forgejo als int64-nanoseconden geleverd.
```

## Belangrijke kanttekening

Deze baseline (130 s / historisch max 203 s) is die van de zwaarste DEPLOY-VRIJE workflow, niet van
de absoluut zwaarste (Scrum4Me ci.yml, ~59 min, niet dispatchbaar). Voor de §9-regressiecheck
(cacheloze pool < 200% van de warme baseline) moet dezelfde workflow (scrum4me-workers ci.yml)
worden hergebruikt, niet Scrum4Me ci.yml.
