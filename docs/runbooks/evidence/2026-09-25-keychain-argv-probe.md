# Keychain vullen zonder argv — proef (IDEA-221, T-81)

Datum: 2026-09-25 · host: mac · macOS 27.0 · uitgevoerd door mac:claude. Alleen wegwerp-items
(`s4m-db-probe/*`), achteraf verwijderd. Geen waarden in dit document.

## Uitkomst

`security add-generic-password … -w` met `-w` als **laatste argument zonder waarde** leest het
wachtwoord van **stdin**, maar vraagt twee keer ("password data for new item", "retype password
for new item"). Eén regel op stdin geeft `passwords don't match` en maakt **geen** item aan,
terwijl de exitcode 0 is — controleer daarom altijd achteraf.

Bewezen methode (geen shellvariabele, waarde alleen door pipes):

```bash
openssl rand -hex 32 | awk '{print; print}' \
  | security add-generic-password -U -s s4m-db-<rol> -a new -w >/dev/null 2>&1
security find-generic-password -s s4m-db-<rol> -a new -w \
  | awk '{print length($0), ($0 ~ /^[0-9a-f]{64}$/ ? "hex-ok" : "BAD")}'   # verwacht: 64 hex-ok
```

## Metingen

| Proef | Resultaat |
|---|---|
| Eén regel via stdin | prompt twee keer, `passwords don't match`, rc=0, geen item (len=0) |
| Twee identieke regels via stdin | item aangemaakt, uitgelezen waarde gelijk aan invoer (len=64) |
| `ps -axww` tijdens een vertraagde aanroep | argv = `security add-generic-password -U -s s4m-db-probe -a new3 -w` — geen waarde |
| awk-verdubbeling uit `openssl rand` | rc=0, `64 hex-ok` |

## Les voor het runbook

- Zet een secret nooit letterlijk in een commandoregel, ook niet in een `zsh -c '…'`-string: de
  commandostring van de aanroepende shell is zelf zichtbaar in `ps`. Tijdens deze proef stond
  alleen `$V` (de variabelenaam) in die string, niet de waarde — maar de pipe-methode hierboven
  heeft geen variabele meer nodig.
- Proef A (interactieve prompt + plakken) is niet meer nodig: de pipe-methode is volledig en
  vermijdt het klembord.
