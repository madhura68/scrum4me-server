# DinD-API: bereikbaarheid vanaf de host (T-178, PBI-40, AUDIT-009/010)

Gemeten 30 september 2026, ca. 20:55 UTC, read-only over SSH vanaf `mac`. Er is niets gewijzigd:
alleen `docker ps/inspect/port`, `ss`, `iptables -S`, een TCP-connect via `/dev/tcp` en één
`GET /_ping`. Geen credential gebruikt of getoond.

## max2 — bundel (cyclecontroller)

| Wat | Gemeten |
|---|---|
| Container | `forgejo-runner-dind-1`, image op digest |
| Netwerk | `forgejo-runner_runner-control`, subnet `172.22.0.0/16`, DinD op `172.22.0.2` |
| Gepubliceerde poorten | geen |
| Daemon | `dockerd --host=tcp://0.0.0.0:2375 --tls=false`, `DOCKER_TLS_CERTDIR` leeg |
| Luisteraar in de host-netns op 2375/2376 | geen (de gate in `verify-stack.sh` kijkt alleen hiernaar) |
| TCP-connect `172.22.0.2:2375` als `janpeter` (uid 1000) | **open**; `GET /_ping` → **200** |
| TCP-connect `172.22.0.2:2375` als `nobody` | **open** |
| `OUTPUT`-policy / `DOCKER-USER` | `ACCEPT`, `DOCKER-USER` leeg |
| Leden groep `docker` | `ops-agent`, `janpeter` |
| Andere niet-root-accounts met draaiende processen | o.a. `videoeditor`, `owui-web-bridge`, uid `10001` (`socat`), `dsh-*` (`socat`), `gdm-greeter`, `avahi`, `colord`, `cups-browsed` |

**Conclusie max2.** Iedere lokale gebruiker, ook zonder lidmaatschap van `docker`, bereikt de
ongeauthenticeerde API van een **privileged** DinD. Via die API start je een privileged container,
en daarmee heb je root op max2. De grens "alleen root en de groep `docker` besturen containers" geldt
voor de host-Docker, niet voor deze DinD. Dat de gate geen luisteraar in de host-netns ziet, bewijst
alleen dat er geen gepubliceerde poort is; een bridge-adres is vanuit de host-netns altijd bereikbaar.

## scrum4me-server — legacy runner (vóór stap G)

| Wat | Gemeten |
|---|---|
| Container | `scrum4me-forgejo-dind`, image `docker:dind` (tag) |
| Netwerk | `forgejo_forgejo-internal`, DinD op `172.19.0.3` |
| Gepubliceerde poorten | geen |
| Daemon | standaard-entrypoint met `DOCKER_TLS_CERTDIR` gezet: TLS op 2376 |
| 2375 als `janpeter` / `nobody` | closed |
| 2376 als `janpeter` / `nobody` | TCP open; `curl -k https://…:2376/_ping` zonder clientcertificaat → handshake geweigerd (curl rc 56) |

**Conclusie scrum4me-server.** De legacy-DinD eist een clientcertificaat; een lokale gebruiker zonder
certificaat komt niet binnen. Stap G zou op deze host dezelfde open 2375 invoeren als op max2, op de
host waar Forgejo en Postgres draaien.

## Gevolg

Dit is de meting achter AUDIT-010 ("TLS verdwenen zonder vastgelegd besluit"). Het besluit en de
maatregel horen in ontwerpdelta R16; zie T-179.
