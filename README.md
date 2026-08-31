# scrum4me-server

Host-repo voor `scrum4me-server` én **canonieke bron** van de gedeelde
Forgejo-Runner-poolbundel die op zowel `scrum4me-server` als `max2` draait.

## Wat hier staat

| Pad | Inhoud |
|---|---|
| `docs/forgejo-runner-pool/` | Ontwerp, reviewrapporten en runbook van de tweemachinepool |
| `forgejo-runner/` | **Canonieke gedeelde bundel** (nog niet aangemaakt; volgt uit het implementatieplan) |
| `hosts/scrum4me-server/` | Host-overlay en bewijsmateriaal voor deze host (volgt) |

De tweede host heeft een eigen repo: `max2`. Die bevat **uitsluitend** host-overlay,
metingen en bewijs, en deployt vanaf een gepinde commit van de bundel hier.
De bundel wordt daar niet gekopieerd — zie `docs/forgejo-runner-pool/migratieontwerp.md`.

## Harde regels

- Secrets staan nooit in deze repo. Het runnertoken leeft alleen als
  `/opt/forgejo-runner/credentials/forgejo-token` op de host, mode `0600`.
- De bundel is byte-identiek op beide hosts. Wijzigen doe je hier, in één commit,
  en beide hosts worden vanaf diezelfde commit uitgerold.
- Deployment gebeurt handmatig/via SSH vanaf `mac`, nooit via een Forgejo
  Actions-workflow: runnerjobs draaien in DinD zonder host-Docker-socket en zonder
  hostpadvolumes en kunnen de hoststack fysiek niet aanraken.
