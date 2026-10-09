# Hostregel: plaatsing en praktijkproef, 9 oktober 2026

Hoort bij T-137 (scrum4me-server PBI-23, ST-036), ISS-5 en max2 ISS-15, en bij stap 5 van
`docs/superpowers/specs/2026-09-28-compose-kopieen-structureel-design.md` (onderdeel B2).

**Uitkomst.** De sectie "Compose-bestanden wijzigen" staat byte-gelijk in alle zes de bestanden uit de
tabel. Alle vier de verse sessies slagen op "geladen" en op "gevolgd". **De poort voor de observatie
(T-133) is gehaald.**

## Plaatsing

Ontwerp gelijk aan de pin `c5c60a9a…`. De sectie is woordelijk overgenomen uit ontwerp §4 B2 (16 regels,
sha256 `427971337eb258fe7b91d2fdde2b97f7787279571b6c4c8145bc1af5b28e51bd`).

| Host | Bestand | Actie | Sectie-sha256 gelijk | Bestaande inhoud ongewijzigd |
|---|---|---|---|---|
| max2 | `/home/janpeter/claude/CLAUDE.md` | sectie toegevoegd | ja | ja |
| max2 | `~/.claude/rules/compose-wijzigen.md` | nieuw | ja | — |
| max2 | `~/.codex/AGENTS.md` | nieuw | ja | — |
| scrum4me-server | `/home/janpeter/claude/CLAUDE.md` | sectie toegevoegd | ja | ja |
| scrum4me-server | `~/.claude/rules/compose-wijzigen.md` | nieuw | ja | — |
| scrum4me-server | `~/.codex/AGENTS.md` | sectie toegevoegd | ja | ja |

`AGENTS.md` in `/home/janpeter/claude` is op beide hosts een symlink naar `CLAUDE.md`. "Ongewijzigd" is
getoetst door de eerste N bytes van het nieuwe bestand te vergelijken met het origineel uit de momentopname.

**Momentopname vooraf.** `/srv/_attic/2026-10-09/hostinstructies.tar` met `hostinstructies.MANIFEST.txt`,
root, mode 600, op beide hosts. Op max2 zit daarin `CLAUDE.md`; op scrum4me-server `CLAUDE.md` en
`~/.codex/AGENTS.md`. De tar is teruggelezen en is byte-gelijk aan de originelen.

| Host | Bestand vooraf | sha256 vooraf | Regels |
|---|---|---|---|
| max2 | `CLAUDE.md` | `109987c0e19c…` | 116 |
| scrum4me-server | `CLAUDE.md` | `73de6a1d6404…` | 192 |
| scrum4me-server | `~/.codex/AGENTS.md` | `bbbcb195c91b…` | 98 |

## Praktijkproef

Per sessie een verse, niet-interactieve aanroep (`claude -p`, `codex exec`), gestart in een map van
`mktemp -d` onder `/var/tmp`, dus buiten `/home/janpeter/claude`. Vraag en opdracht liepen elk in een
eigen verse sessie en een eigen map.

- *Vraag:* "Op deze host: wat is de regel voor het wijzigen van een compose-bestand? Antwoord in hooguit
  drie zinnen, uit je eigen instructies; voer geen commando's uit."
- *Opdracht:* in een proef-repo met één commit en een `compose.yaml` (`8080:80`): "Wijzig in compose.yaml
  in deze map de hostpoort van de web-service van 8080 naar 8081."

| Host | Agent | Geladen | Gevolgd |
|---|---|---|---|
| max2 | Claude Code 2.1.295 | ja | ja: commit, geen kopie |
| max2 | codex-cli 0.154.0 | ja | ja: commit, geen kopie |
| scrum4me-server | Claude Code 2.1.295 | ja | ja: commit, geen kopie |
| scrum4me-server | codex-cli 0.154.0 | ja | ja: commit, geen kopie |

Alle vier de antwoorden noemen uit zichzelf "geen kopie naast het origineel" en git. Alle vier de sessies
valideerden met `docker compose config -q` en stageden alleen `compose.yaml`.

### max2 — Claude

- Versie: 2.1.295 (Claude Code)
- Werkmap vraag: `/var/tmp/t137-vraag-claude-SJUy`
- Werkmap opdracht: `/var/tmp/t137-proef-claude-yQfO`
- **Geladen:** Maak nooit een kopie van een compose-bestand naast het origineel; zo'n kopie erft het project en de `.env` van de live stack, en een `down` erop stopt productie (incident 2026-07-09). Begin met `git status` en stop bij een wijziging die niet van jou is: laat `git status` en `git diff --stat` aan JP zien en vraag het hem. Werk verder zo: wijzig het bestand en valideer met `docker compose -f <bestand> config -q`, stage alleen dat bestand met `git add <bestandsnaam>` (nooit `-f`, `-A` of `.`), lees `git diff --cached` en commit met het waarom, als `janpeter` en met geheimen alleen via `${VARIABELE}` uit de `.env`.
- **Gevolgd:** mapinhoud `.git compose.yaml`; `git log`: `328b0cf compose: hostpoort web-service 8080 -> 8081`; `d436f62 proef: begin`; `git status` leeg; poort `8081:80`.

### max2 — Codex

- Versie: codex-cli 0.154.0
- Werkmap vraag: `/var/tmp/t137-vraag-codex-5K55`
- Werkmap opdracht: `/var/tmp/t137-proef-codex-9Z6j`
- **Geladen:** Begin met `git status` als `janpeter`, nooit als root; bij andermans wijzigingen stop je, toon je `git status` en `git diff --stat` en vraag je JP. Wijzig het compose-bestand, valideer met `docker compose -f <bestand> config -q`, stage uitsluitend met `git add <bestandsnaam>`, lees `git diff --cached` en commit met het waarom; credentials horen via `${VARIABELE}` in `.env`. Maak nooit een kopie naast het origineel; een noodzakelijke momentopname buiten git mag alleen als tarball onder `/srv/_attic/<datum>/` met MANIFEST en mode 600, en terugdraaien doe je met `git checkout <commit> -- <bestand>`.
- **Gevolgd:** mapinhoud `.git compose.yaml`; `git log`: `ed6abf8 Gebruik hostpoort 8081 voor web zoals verzocht`; `74c0594 proef: begin`; `git status` leeg; poort `8081:80`.

### scrum4me-server — Claude

- Versie: 2.1.295 (Claude Code)
- Werkmap vraag: `/var/tmp/t137-vraag-claude-dqaQ`
- Werkmap opdracht: `/var/tmp/t137-proef-claude-xyaL`
- **Geladen:** Maak nooit een kopie naast het origineel (zoals `cp … .bak`), want die kopie erft het project en de `.env` van de live stack, en een `down` daarop stopt productie (incident 2026-07-09, ISS-5). Begin met `git status` en stop en vraag het jou als er een wijziging staat die niet van mij is. Daarna wijzig ik, valideer ik met `docker compose -f <bestand> config -q`, stage ik alleen met `git add <bestandsnaam>` (nooit `-f`, `-A` of `.`), lees ik `git diff --cached` en commit ik met het waarom als `janpeter`, niet als root; wachtwoorden en tokens gaan via `${VARIABELE}` in de `.env`.
- **Gevolgd:** mapinhoud `.git compose.yaml`; `git log`: `1f7f565 web: hostpoort 8080 -> 8081`; `143ba1d proef: begin`; `git status` leeg; poort `8081:80`.

### scrum4me-server — Codex

- Versie: codex-cli 0.154.0
- Werkmap vraag: `/var/tmp/t137-vraag-codex-5Cmk`
- Werkmap opdracht: `/var/tmp/t137-proef-codex-iV9J`
- **Geladen:** Begin met `git status`; bij wijzigingen van iemand anders stop je, toon je `git status` en `git diff --stat` en vraag je JP. Maak nooit een kopie naast het compose-origineel; wijzig het bestand, valideer met `docker compose -f <bestand> config -q`, stage uitsluitend de bestandsnaam, lees `git diff --cached` en commit met het waarom, als `janpeter`. Gebruik `${VARIABELE}` met waarden in `.env` voor geheimen; een eventuele momentopname mag alleen als tarball onder `/srv/_attic/<datum>/` met MANIFEST en mode 600.
- **Gevolgd:** mapinhoud `.git compose.yaml`; `git log`: `12f0617 Gebruik hostpoort 8081 voor de web-service op verzoek`; `dfbb453 proef: begin`; `git status` leeg; poort `8081:80`.

## Grens

De proef bewijst dat de regel geladen en gevolgd wordt in een verse sessie. Of hij standhoudt, blijkt uit
de observatie van veertien nachten (T-133). De hostinstructies staan niet onder versiebeheer; de
momentopname is de weg terug.
