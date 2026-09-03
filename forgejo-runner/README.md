# forgejo-runner — gedeelde bundel

Deze map is de **canonieke bron** van de Forgejo-Runner-poolbundel. Beide hosts
(`scrum4me-server` en `max2`) rollen uit vanaf dezelfde commit-SHA van deze repo.
De `max2`-repo bevat geen kopie; zie §6.1 van het migratieontwerp
(`docs/forgejo-runner-pool/migratieontwerp.md`).

## Wat erin zit

| Bestand | Rol |
|---|---|
| `compose.yaml` | DinD (privileged, `restart: always`) en runner (profiel `cycle`, `restart: "no"`) |
| `.env.example` | imagepins als `repo@sha256:…` en de caps uit `evidence/stap-a/caps.env`; nooit tokens of UUID's |
| `labels.txt` | canonieke, digest-gepinde labellijst (§7.4) |
| `allowed-job-images.txt` | digests die de scrub mag behouden, met grootte in bytes |
| `runner-config.policy.yml` | gedeelde runnerpolicy; `render-config.sh` voegt de hostspecifieke UUID en `token_url` toe |
| `trusted-actions-scope.yml` | trust-allowlist voor global scope (§7.7) |
| `forgejo-runner-cycle.service` | systemd-unit die de Python-cyclecontroller draait |
| `scripts/` | preflight, render-config, resolve-digests, scrub-dind, bundle-hash, verify-stack, secret-scan, de cyclecontroller en de read-only inventarisatiescripts |
| `tests/` | bats- en unittest-suite; draait niet mee op de hosts en telt niet mee in de bundelhash |

## Uitrollen

1. `bash scripts/preflight.sh --facts … --caps … --images allowed-job-images.txt`
   moet exit 0 geven. Faalt hij, dan wordt er niets uitgerold. De gate wordt niet
   versoepeld om verder te kunnen (§7.8).
2. Kopieer de bundel naar `/opt/forgejo-runner/` op de host.
3. Schrijf de commit-SHA naar `/opt/forgejo-runner/BUNDLE_COMMIT`.
4. Render de hostconfig: `bash scripts/render-config.sh --uuid <host-uuid>
   --labels labels.txt --policy runner-config.policy.yml --out runner-config.yml`.
5. Zet het token als `/opt/forgejo-runner/credentials/forgejo-token`, mode `0600`,
   eigendom van de effectieve runner-UID:GID, **zonder afsluitende newline** (de
   runner weigert een token met een newline). Het token komt nooit uit deze repo.
6. `cp .env.example .env` en `docker compose up -d`: dat start uitsluitend DinD; de
   runner staat onder het profiel `cycle` en wordt alleen door de cyclecontroller
   gestart.
7. `systemctl enable --now forgejo-runner-cycle.service`.
8. `bash scripts/verify-stack.sh <commit> <bundelhash>` moet exit 0 geven; de
   bundelhash komt van `bash scripts/bundle-hash.sh .` op dezelfde commit.

## Terugdraaien

Zet de unit eerst in `DRAINING`, wacht tot een geaccepteerde job terminaal is en
leg het Forgejo-side nulbewijs voor assigned/running jobs vast. Stop en disable
daarna de unit en verwijder alleen de runner- en DinD-containers. Laat het volume
`forgejo-runner-dind-data` staan voor onderzoek. Herstart nooit de host-Dockerdaemon.

## Wat hier bewust niet gebeurt

- Geen deployment via Forgejo Actions: jobcontainers draaien in DinD zonder
  host-Docker-socket en zonder hostpadvolumes en kunnen deze stack niet wijzigen.
- Geen wijziging aan `/etc/docker/daemon.json`, geen herstart van de Docker-daemon,
  geen hostbrede `docker system prune`.
- Geen gedeeld DinD-volume of gedeelde DinD tussen de hosts.

## Verifiëren

```bash
bats tests/*.bats
for f in tests/test_*.py; do python3 "$f"; done
shellcheck -x scripts/*.sh
```
