# Werkinstructies — scrum4me-server

## Rol van deze repo

Deze repo is de **canonieke bron** van de gedeelde Forgejo-Runner-poolbundel voor
`scrum4me-server` en `max2`, plus de host-overlay voor `scrum4me-server` zelf.
De `max2`-repo is bewust géén tweede kopie van de bundel.

## Harde regels

1. **Geen secrets.** Tokens, UUID-credentials, private sleutels en `.env` met echte
   waarden komen hier nooit in. Het actieve token leeft alleen als
   `/opt/forgejo-runner/credentials/forgejo-token` op de host (mode `0600`).
   Draai de secret-scan vóór iedere commit die de bundel raakt.
2. **Eén bron van waarheid.** Wijzigingen aan de gedeelde bundel gebeuren hier.
   Beide hosts rollen uit vanaf dezelfde commit-SHA; `verify-stack.sh` vergelijkt de
   uitgerolde bundelhash met die commit op beide hosts.
3. **Niet zelf deployen via Actions.** Runnerjobs draaien in DinD zonder
   host-Docker-socket en zonder hostpadvolumes. Uitrol gaat handmatig/SSH vanaf `mac`.
4. **Post-GO-wijzigingen aan het ontwerp** vereisen een aparte delta-review met GO
   voordat de status verandert. Zie het Review record in
   `docs/forgejo-runner-pool/migratieontwerp.md`.

## Productiecontext

Op deze host draaien Forgejo 15.0.2 en Postgres zelf. Een reboot van deze host is
daarom óók control-plane-onderhoud voor de runnerpool en vereist een vooraf gearmd
maintenance-record op beide hosts.
