# Berekende caps (§7.8)

De caps zijn afgeleid uit de meetreeks van Task 7 op `scrum4me-server`
(`workload-scrum4me-server.tsv`, 84 samples à 5 s tijdens `vitest run` uit
scrum4me-workers `ci.yml`, run 2521), volgens de regel uit §7.8:
`limiet = max(ondergrens, 150% van de gemeten piek)`, afgerond op 0,5 vCPU,
256 MiB en 128 PID.

- laagste MemAvailable in die reeks (`scrum4me-server`, onder last): 9281085440 bytes (8,644 GiB)

| Service | CPU | Geheugen | PIDs |
|---|---|---|---|
| runner | 1.0 | 1073741824 | 256 |
| dind | 11.5 | 5368709120 | 2048 |

Som: **12,5 vCPU** en **6442450944 bytes (6,0 GiB)**.

Deze caps gelden gelijk op beide hosts (§7.8: hetzelfde label moet dezelfde
minimale uitvoeromgeving betekenen). Ze staan machineleesbaar in `caps.env`.

## Headroomgate per host

De gate toetst per host tegen de **eigen** resources van díe host. Uitgevoerd met
`forgejo-runner/scripts/preflight.sh` (Task 10); de volledige uitvoer staat in
`preflight-scrum4me-server.txt` en `preflight-max2.txt`.

| Host | vCPU-som vs 50% | geheugensom vs 50% | schijf | inodes | Uitkomst |
|---|---|---|---|---|---|
| `scrum4me-server` | 12,5 vs 4,0 | 6,0 GiB vs 4,322 GiB | OK | OK | **ROOD** (exit 40) |
| `max2` | 12,5 vs 14,0 | 6,0 GiB vs 9,793 GiB | OK | OK | **GROEN** (exit 0) |

`scrum4me-server` faalt op beide resources, en op geheugen ongeacht welke
meetwaarde je neemt: met de onder-last laagste (8,644 GiB → 4,322 GiB headroom)
en met de momentopname uit `host-facts-scrum4me-server.tsv` (9,865 GiB →
4,933 GiB headroom) blijft de som van 6,0 GiB erboven. Ook de ondergrenzen
alléén (runner 1 GiB + DinD 4 GiB = 5 GiB) passen daar niet: het knelpunt is
geheugen, niet de gekozen marge.

`max2` haalt de gate met 3,79 GiB geheugenmarge en 1,5 vCPU marge; de gate zou
daar pas ROOD worden onder 12,0 GiB `MemAvailable`.

## Correctie ten opzichte van de eerste versie van dit bestand

De eerste versie noemde `max2` ROOD. Dat was fout: de gate van `max2` werd daar
getoetst tegen de laagste `MemAvailable` van **`scrum4me-server`** (9281085440
bytes) in plaats van tegen die van `max2` zelf (21029359616 bytes). De fout zat
in een ad-hoc aanroep, niet in `compute_caps.py` — `headroom_ok()` neemt de
waarde als parameter en is met eigen tests gedekt. Dit bestand is daarom
opnieuw gegenereerd via `preflight.sh`, zodat het oordeel reproduceerbaar is.

## Openstaand meetpunt voor `max2`

§7.8 en stap A vragen om de **laagste** `MemAvailable` onder eigen productielast.
Voor `scrum4me-server` is dat een reeks van 84 samples. Voor `max2` is
`mem_available_bytes` in `host-facts-max2.tsv` één momentopname, genomen terwijl
de elf productiecontainers uit `host-load-context.md` draaiden — dus wél onder
productielast, maar niet als reeks. De marge is groot (7,59 GiB daling nodig
voor ROOD), maar dat blijft een gevolgtrekking en geen meting.

Dit wordt gesloten wanneer `preflight.sh` in stap D op `max2` zelf draait: die
gate loopt vóór iedere mutatie en beslist daar op de dan geldende waarde.

Aanvulling 2 september: de opname in `productiecontainers-voor.txt` laat zien
dat de video-editor-stack op `max2` ten tijde van de hostmeting níét draaide.
De 19,585 GiB is dus zonder die last gemeten; komt die stack terug, dan is de
marge kleiner dan hier berekend.
