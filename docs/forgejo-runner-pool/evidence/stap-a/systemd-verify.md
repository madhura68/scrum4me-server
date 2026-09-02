# systemd-analyze verify van forgejo-runner-cycle.service

Uitgevoerd op 2 september 2026 in een ubuntu:24.04-container (linux/amd64) met
`apt-get install systemd`, omdat de Mac geen systemd heeft en stap B de unit
niet installeert. Een eerste run zonder Docker in de container gaf uitsluitend
"Unit docker.service not found" (verwacht: de container heeft geen Docker);
met een stub-`docker.service` is de uitkomst exit 0 zonder enige melding over
onbekende directives.

```
systemd: systemd 255 (255.4-1ubuntu8.17)
--- verify met stub docker.service ---
exit=0
--- directives die systemd niet kent (moet leeg zijn) ---
(geen)
```
