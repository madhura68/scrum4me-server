# Backup-manifest — rollbackpunt Forgejo 15.0.9-venster

Map op `scrum4me-server`: `/srv/backups/manual/forgejo-pre-15.0.9` (`0700 root:root`). Geen inhoud in dit bestand, alleen paden, groottes, hashes en tijden.

| Bestand | Grootte (bytes) | sha256 | Genomen (UTC) | Rol |
|---|---|---|---|---|
| `app.ini.pre` | 2 134 | `792f2102f4cdcbccad2256c4060f3f3e083981f1e9972b9c731c0f5d8eb285fd` | 13:25:47 | configuratie vóór 2.5 (bevat de oude, gelekte secrets) |
| `forgejo-pre-15.0.9.dump` | 39 721 045 | `bbfcb717d86e0259b6857a0f226a89aff5e933fa696d1a396e268b510de25adb` | 13:25:52 | koud punt 2.7 (Gate-2-bewijs; geen R4-bron) |
| `forgejo-pre-image.dump` | 39 491 297 | `f3cdea1b0b637a38a29648d822a4a42e2a31e4bc0e7f55c44d9c0d0a5f0a3956` | 13:31:09 | vers punt 4.1, hoort bij `data/` |
| `data/` | 1 037 075 652 | — | 13:31:1x (rsync 1,3 s) | volumekopie van 4.1, op 15.0.2, met de geroteerde secrets |

Warme kopie (1.2): 13 s, 2 245 444 035 bytes; koude delta (2.7): 2,0 s. Het volume kromp tussen 2.7 en 4.1 doordat Forgejo bij de start in Fase 3 oude repo-archieven opruimde.

Het R4-paar (`forgejo-pre-image.dump` + `data/`) herstelt naar 15.0.2 met de nieuwe configuratie. R4 is niet gebruikt.

**Retentie (6.4).** Gate 5 was groen op 30 september 2026; de map blijft zeven dagen staan. **Vernietigingsdatum: 7 oktober 2026**, door JP (`sudo rm -rf /srv/backups/manual/forgejo-pre-15.0.9`). De map gaat vanaf de nacht van 30 september mee in de restic-snapshots (NAS en B2); verwijderen haalt haar daar niet uit (besluit JP, zie `venster.md`).
