# Receptproef — compose-hashbewijs en hostregel-commit (30 september 2026)

Bewijs bij de delta van [implementatieplan-forgejo-15.0.9.md](../../implementatieplan-forgejo-15.0.9.md)
(stappen 2.4, 4.2, R4 stap 5, 0.13 en 6.2). Alles is uitgevoerd met proefwaarden in tijdelijke
mappen; er is geen host en geen live compose-bestand geraakt.

## 1. Tagwissel met sha256-bewijs (4.2) en terugzetten (R4 stap 5)

Omgeving: `docker run --rm ubuntu:24.04` op de mac — GNU sed 4.9 en bash 5.2, dezelfde
gereedschapsfamilie als op `scrum4me-server`. `sed -i` draaide als root op een bestand van
uid 1000, mode 664, zoals `sudo sed -i` op de host.

Script:

```sh
#!/usr/bin/env bash
# Proef van het compose-hashrecept (plan 15.0.9: 2.4, 4.2, R4.5) met proefwaarden.
fixture() {
  mkdir -p /tmp/t && cat > /tmp/t/docker-compose.yml <<'Y'
services:
  forgejo:
    image: codeberg.org/forgejo/forgejo:15.0.2
    container_name: scrum4me-forgejo
  runner:
    image: code.forgejo.org/forgejo/runner:12.10.1
    depends_on: [forgejo, dind]
  dind:
    image: docker:dind
Y
  chown 1000:1000 /tmp/t/docker-compose.yml; chmod 664 /tmp/t/docker-compose.yml
}
CF=/tmp/t/docker-compose.yml
stap24() { PRE_CF=$(sha256sum "$CF" | cut -d' ' -f1); }
stap42() {
  sed -i 's|image: codeberg.org/forgejo/forgejo:15.0.2$|image: codeberg.org/forgejo/forgejo:15.0.9|' "$CF"
  ( set -e
    [ "$(grep -c 'image: codeberg.org/forgejo/forgejo:15.0.9$' "$CF")" = 1 ]
    [ "$(grep -c 'forgejo/forgejo:' "$CF")" = 1 ]
    [ "$(sed 's|image: codeberg.org/forgejo/forgejo:15.0.9$|image: codeberg.org/forgejo/forgejo:15.0.2|' "$CF" | sha256sum | cut -d' ' -f1)" = "$PRE_CF" ]
  )
  rc=$?
  [ "$rc" -eq 0 ] && echo "TAGWISSEL OK (alleen de forge-imageregel gewijzigd)" || { echo "TAGWISSEL NIET EENDUIDIG (exit $rc) — STOP, ga NIET naar 4.3"; false; }
}
r45() {
  sed -i 's|image: codeberg.org/forgejo/forgejo:15.0.9$|image: codeberg.org/forgejo/forgejo:15.0.2|' "$CF"
  [ "$(sha256sum "$CF" | cut -d' ' -f1)" = "$PRE_CF" ] && echo "COMPOSE TERUG OP PRE_CF" || { echo "COMPOSE WIJKT AF VAN PRE_CF — STOP, JP"; false; }
}
echo "sed: $(sed --version | head -1) | bash: $BASH_VERSION"
echo "--- a. normaal";            fixture; stap24; stap42; echo "exit=$?"; stat -c '%u:%g %a' "$CF"; r45; echo "exit=$?"
echo "--- b. vreemde wijziging tussen 2.4 en 4.2"; fixture; stap24; echo "# x" >> "$CF"; stap42; echo "exit=$?"
echo "--- c. imageregel met spatie erachter (sed matcht niet)"; fixture; sed -i 's|forgejo:15.0.2$|forgejo:15.0.2 |' "$CF"; stap24; stap42; echo "exit=$?"
echo "--- d. twee forge-imageregels"; fixture; echo "    image: codeberg.org/forgejo/forgejo:15.0.2" >> "$CF"; stap24; stap42; echo "exit=$?"
echo "--- e. R4.5 na een vreemde wijziging"; fixture; stap24; stap42 >/dev/null; echo "# y" >> "$CF"; r45; echo "exit=$?"
```

Uitvoer:

```text
sed: sed (GNU sed) 4.9 | bash: 5.2.21(1)-release
--- a. normaal
TAGWISSEL OK (alleen de forge-imageregel gewijzigd)
exit=0
1000:1000 664
COMPOSE TERUG OP PRE_CF
exit=0
--- b. vreemde wijziging tussen 2.4 en 4.2
TAGWISSEL NIET EENDUIDIG (exit 1) — STOP, ga NIET naar 4.3
exit=1
--- c. imageregel met spatie erachter (sed matcht niet)
TAGWISSEL NIET EENDUIDIG (exit 1) — STOP, ga NIET naar 4.3
exit=1
--- d. twee forge-imageregels
TAGWISSEL NIET EENDUIDIG (exit 1) — STOP, ga NIET naar 4.3
exit=1
--- e. R4.5 na een vreemde wijziging
COMPOSE WIJKT AF VAN PRE_CF — STOP, JP
exit=1
```

Lezing: (a) de wissel slaagt, eigenaar en mode blijven `1000:1000 664`, en terugzetten levert
exact de hash van 2.4; (b) een vreemde wijziging tussen 2.4 en 4.2, (c) een imageregel die de
`sed` niet matcht en (d) een tweede forge-imageregel geven alle drie `TAGWISSEL NIET EENDUIDIG`
met exit 1; (e) een vreemde wijziging vóór R4 stap 5 geeft `COMPOSE WIJKT AF VAN PRE_CF`.

## 2. Compose-map onder git (0.13) en de hostregel-commit (6.2)

Omgeving: tijdelijke map op de mac, onder git gezet met `scripts/compose-git-init <map>
docker-compose.yml runner-config.yaml` uit deze repo (allowlist en hook zoals op de host);
daarnaast een `.env` die buiten de allowlist valt. De tagwissel zelf gebruikt hier `sed -i ''`
(BSD-sed op de mac); het GNU-recept is in §1 beproefd.

```text
## compose-git-init
repo gemaakt in <tijdelijke map>/forgejo, eerste commit cae0121
  87b5e3aa65299dd406d59611e8c5e9f808e0e45fc1b164e150efaa98905a93fd  docker-compose.yml
  6f66b0a7d818a8dbe79aa3d2b4ca0058e5df8d2a9956654a983eb189083420b2  runner-config.yaml
hook: 51d6eac0e0b98e649fb384c8db81aad48b1222c4909949d997201e7d7c86c5d6
## 0.13
GIT_CF=ja
(einde status)
## 4.2 tagwissel (mac: sed -i '')
 M docker-compose.yml
## 6.2 hostregel-commit
config-exit=0
-    image: codeberg.org/forgejo/forgejo:15.0.2
+    image: codeberg.org/forgejo/forgejo:15.0.9
commit-exit=0
(einde status)
89bd2d3 forgejo 15.0.2 -> 15.0.9 (onderhoudsvenster proef)
cae0121 Eerste commit: live compose-bestanden onder versiebeheer
## rollback-variant: tag terug vóór commit → schoon
COMPOSE TERUG OP PRE_CF
(einde status)
```

Lezing: een schone map geeft bij 0.13 `GIT_CF=ja` en een lege status; na de tagwissel is alleen
`docker-compose.yml` gewijzigd; `docker compose config -q` geeft exit 0; de gestagede diff bevat
alleen de imageregel; de commit slaagt door de hook en de status is daarna leeg. Wordt de tag
vóór een commit teruggezet, dan is de hash weer die van 2.4 en is de werkboom schoon.
