# Compose-git — proef van het herstelrecept, 28 september 2026

Hoort bij onderdeel B1 van
`docs/superpowers/specs/2026-09-28-compose-kopieen-structureel-design.md`.

**Aanleiding.** In reviewronde 2 en 3 bleek het herstelrecept tweemaal fout: eerst zette
`git rm --cached` het verwijderen van een gevolgd bestand klaar, daarna schreef het recept
voor om een werkbestand te wijzigen, wat bij een live `.env` de credential zou breken. Het
recept is daarom eerst beproefd en pas daarna opnieuw beschreven.

**Methode.** Uitgevoerd op `mac` in een map van `mktemp -d`, met git 2.53.0. Beide hosts
hebben dezelfde git-versie (meetbewijs §3 en §4). De proef gebruikt alleen proefwaarden en
raakt geen host en geen live bestand. De proefwaarde is korter dan 20 tekens, zoals
`forgejo-runner/scripts/secret-scan.sh` van proefwaarden vraagt. `GIT_CONFIG_GLOBAL` en `GIT_CONFIG_SYSTEM` staan op
`/dev/null`, zodat lokale instellingen de uitkomst niet kleuren.

## Uitkomst

| Proef | Verwacht | Gemeten |
|---|---|---|
| Gewone `git add .env` bij een allowlist-`.gitignore` | geweigerd | geweigerd, exit 1 |
| Nieuw pad geforceerd gestaged, daarna `git restore --staged` | uit de index, werkbestand gelijk, blob weg na prune | zo gemeten |
| Gevolgd bestand met proefwaarde gestaged, daarna `git restore --staged` | index gelijk aan HEAD, bestand nog gevolgd, werkbestand gelijk, blob weg na prune | zo gemeten |
| Tegenproef: `git rm --cached` op het gevolgde bestand | zet een verwijdering klaar | `D  docker-compose.yml` |
| Repo zonder commit: `git restore --staged` | faalt, want er is geen HEAD | `fatal: could not resolve 'HEAD'`, exit 128 |
| Repo zonder commit: `git rm --cached` | haalt het pad uit de index, werkbestand blijft | zo gemeten |

Eén commando, `git restore --staged -- <pad>`, herstelt dus beide gevallen en raakt het
werkbestand niet. Na geval 2 toont `git status` nog ` M docker-compose.yml`: de letterlijke
waarde staat nog in het werkbestand. Dat is een gewone wijziging voor de editor, geen
onderdeel van het herstel.

## Uitvoer

```text
git 2.53.0
eerste commit: .gitignore docker-compose.yml 

== allowlist: gewone add van .env ==
The following paths are ignored by one of your .gitignore files:
.env
exit=1  index: .gitignore docker-compose.yml 

== geval 1: nieuw pad, geforceerd gestaged (.env) ==
blob vastgelegd: ec3ee188e9bc  bestaat: ja
restore exit=0
index na herstel: .gitignore docker-compose.yml 
werkbestand ongewijzigd: ja
blob na prune: weg

== geval 2: gevolgd bestand met letterlijke proefwaarde gestaged ==
blob vastgelegd: 561f66cd7d1a
restore exit=0
index gelijk aan HEAD: ja
bestand nog gevolgd: ja
werkbestand ongewijzigd: ja
blob na prune: weg
git status:  M docker-compose.yml;

== tegenproef: git rm --cached op het gevolgde bestand (het foute recept uit ronde 1) ==
git status: D  docker-compose.yml;?? docker-compose.yml;

== randgeval: repo zonder commit ==
fatal: could not resolve 'HEAD'
restore exit=128
rm --cached exit=0  index: []  werkbestand bestaat: ja
```

## Script

```bash
#!/usr/bin/env bash
# Proef van het herstelrecept uit B1 in een tijdelijke repo. Alleen proefwaarden, geen echte secrets.
set -u
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null
R=$(mktemp -d); trap 'rm -rf "$R"' EXIT
cd "$R" || exit 2
sha() { shasum -a 256 "$1" | cut -d' ' -f1; }
blob_id() {  # exact één stage-0-regel, veld 2; anders stoppen
  local out n
  out=$(git ls-files -s -- "$1"); n=$(printf '%s' "$out" | grep -c .)
  [ "$n" -eq 1 ] || { echo "STOP: $n indexregels voor $1" >&2; return 1; }
  [ "$(printf '%s' "$out" | awk '{print $3}')" = "0" ] || { echo "STOP: stage is niet 0" >&2; return 1; }
  printf '%s' "$out" | awk '{print $2}'
}
echo "git $(git --version | awk '{print $3}')"
git init -q . && git config user.name proef && git config user.email proef@example.invalid
printf '/*\n!/.gitignore\n!/docker-compose.yml\n' > .gitignore
printf 'services:\n  db:\n    environment:\n      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?}\n' > docker-compose.yml
printf 'POSTGRES_PASSWORD=proefwaarde\n' > .env
git add .gitignore docker-compose.yml && git commit -q -m "eerste commit" && echo "eerste commit: $(git ls-files | tr '\n' ' ')"

echo; echo "== allowlist: gewone add van .env =="
git add .env 2>&1 | head -2; echo "exit=${PIPESTATUS[0]}  index: $(git ls-files | tr '\n' ' ')"

echo; echo "== geval 1: nieuw pad, geforceerd gestaged (.env) =="
before=$(sha .env); git add -f .env; b=$(blob_id .env) || exit 1
echo "blob vastgelegd: ${b:0:12}  bestaat: $(git cat-file -e "$b" && echo ja || echo nee)"
git restore --staged -- .env; echo "restore exit=$?"
echo "index na herstel: $(git ls-files | tr '\n' ' ')"
echo "werkbestand ongewijzigd: $([ "$(sha .env)" = "$before" ] && echo ja || echo NEE)"
git gc -q --prune=now; echo "blob na prune: $(git cat-file -e "$b" 2>/dev/null && echo BESTAAT-NOG || echo weg)"

echo; echo "== geval 2: gevolgd bestand met letterlijke proefwaarde gestaged =="
printf 'services:\n  db:\n    environment:\n      POSTGRES_PASSWORD: proefwaarde\n' > docker-compose.yml
before=$(sha docker-compose.yml); git add docker-compose.yml; b=$(blob_id docker-compose.yml) || exit 1
echo "blob vastgelegd: ${b:0:12}"
git restore --staged -- docker-compose.yml; echo "restore exit=$?"
echo "index gelijk aan HEAD: $(git diff --cached --quiet && echo ja || echo NEE)"
echo "bestand nog gevolgd: $(git ls-files --error-unmatch docker-compose.yml >/dev/null 2>&1 && echo ja || echo NEE)"
echo "werkbestand ongewijzigd: $([ "$(sha docker-compose.yml)" = "$before" ] && echo ja || echo NEE)"
git gc -q --prune=now; echo "blob na prune: $(git cat-file -e "$b" 2>/dev/null && echo BESTAAT-NOG || echo weg)"
echo "git status: $(git status --porcelain | tr '\n' ';')"

echo; echo "== tegenproef: git rm --cached op het gevolgde bestand (het foute recept uit ronde 1) =="
git add docker-compose.yml; git rm -q --cached -- docker-compose.yml; echo "git status: $(git status --porcelain | tr '\n' ';')"
git restore --staged -- docker-compose.yml

echo; echo "== randgeval: repo zonder commit =="
R2=$(mktemp -d); cd "$R2" && git init -q . && printf 'X=proef\n' > .env && git add -f .env
git restore --staged -- .env 2>&1 | head -1; echo "restore exit=${PIPESTATUS[0]}"
git rm -q --cached -- .env; echo "rm --cached exit=$?  index: [$(git ls-files | tr '\n' ' ')]  werkbestand bestaat: $([ -f .env ] && echo ja || echo nee)"
cd /; rm -rf "$R2"
```
