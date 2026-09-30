# Image-pins: vergelijking met de registry op 30 september 2026

Onderzoek voor AUDIT-024 (`docs/repo-audit/findings.json`). Alleen-lezen: anonieme registry-API's en publieke releasenotes. Er is niets op `max2` of `scrum4me-server` gemeten en geen pin gewijzigd; de fase-1-freeze blijft zoals ontworpen. Meetdatum 30 september 2026.

Methode: manifest-HEAD/GET via de anonieme token-flow van `code.forgejo.org` en Docker Hub (`docker buildx imagetools inspect` is niet nodig; `resolve-digests.sh` levert de **index-digest** en dat is ook wat hier is vergeleken). Alle drie de pins in de repo zijn index-digests (mediaType `application/vnd.oci.image.index.v1+json`, voor runner en DinD bevestigd via een GET op de gepinde digest; de jobimage-digest werd eveneens als index teruggegeven).

## 1. Beveiligingsfix die bij Runner 13.0.0 wordt aangehaald

| Onderdeel | Bevinding |
|---|---|
| Repo-tekst | Upgradeonderzoek §4: *"prevent commit impersonation via refs/replace/* during action checkout"*; in de 12.x-notes tot 12.13.2 staat die fix niet, teruggeporteerd niet gecontroleerd |
| Wat het is | PR [#1635](https://code.forgejo.org/forgejo/runner/pulls/1635) "fix: prevent commit impersonation via `refs/replace/*` during action checkout". Beschrijving: voorkomt dat `git replace` een ref aanmaakt die een andere commit overschaduwt, "similar to previous fixes for tags and branches". Commit `a863a4b9ea`, merge-commit `b5a3bf90d1`, gemerged op `main` op 2026-07-19 |
| Release | Eerste release met de fix: [v13.0.0](https://code.forgejo.org/forgejo/runner/releases) (2026-08-03), vermeld onder "bug fixes". De [v13.0.0-blog](https://forgejo.org/2026-08-runner-release-v13/) noemt deze fix niet; de blog beschrijft de breaking changes |
| CVE / advisory | Geen CVE-ID of security-announcement gevonden; de fix staat alleen als bug fix in de releasenotes |
| Terugport naar 12.x | **Niet gevonden.** De onderhoudsbranch [`support-v12.13.x`](https://code.forgejo.org/forgejo/runner/src/branch/support-v12.13.x) eindigt op tag v12.13.2 (`4140a19a2e`, 2026-07-23); de commitlijst van die branch sinds v12.9.0 (70 commits) bevat #1635 niet. v12.13.2 bevat volgens de releasenotes uitsluitend #1643 (reusable-workflow-invoer). v12.13.2 is de laatste 12.x-release (geen v12.13.3 of v12.14 in de taglijst). De fix is dus in geen enkele 12.x-release aanwezig, ook niet in de gepinde 12.10.1 |

Tagoverzicht 12.x na de pin (bron: Forgejo-API `code.forgejo.org/api/v1/repos/forgejo/runner/releases`): 12.10.2 (2026-05-26), 12.11.0 (06-11), 12.11.1 (06-12), 12.12.0 (06-20), 12.13.0 (07-08), 12.13.1 (07-18), 12.13.2 (07-23). De fix van 2026-07-19 kwam dus vier dagen vóór de laatste 12.x-release op `main` en is niet meegenomen.

Go-toolchain- en dependency-updates met het label `[SECURITY]` (Renovate) in de 12.x-lijn na 12.10.1: `golang.org/x/sys` v0.44.0 in 12.10.2 (#1529); Go toolchain 1.25.11 in 12.11.0 (#1548); Go 1.25.12 staat op `support-v12.13.x` (#1597, zonder `[SECURITY]`-label). Wat die bijwerkingen concreet dichten is niet uitgezocht (zie "Niet vastgesteld").

## 2. Pins tegenover de registry

### 2.1 Runner

| Veld | Waarde |
|---|---|
| Bron-tag | `code.forgejo.org/forgejo/runner:12` (gemeten op de host op 15 mei 2026; image-label `org.opencontainers.image.version=12.10.1`, created 2026-05-05) |
| Gepinde digest (index) | `sha256:3d49075f9115054ae2485d8cea2819296a904dfd4f00017285168028615d8533` |
| Tag `12.10.1` nu | `sha256:3d49075f...8533`, **gelijk** aan de pin. De pin is dus nog steeds een geldige, bestaande image |
| Tag `12` nu | `sha256:eb6e7bc21973382d261e6eb883dbd27b8cb56939d33a3bfd79a1352b7f9a33a0` (= `12.13.2`), **verplaatst** ten opzichte van de pin; gelijk aan de waarde in `resolved-digests.tsv` (2 sep), dus sinds 2 sep niet meer verplaatst |
| Tag `13` nu | `sha256:ca3d5eea46004789a175d1369eec6829d3ea9bfbe2011a06625b4bdaa55f7552` (ter oriëntatie; 13.2.0 is van 2026-09-18) |
| Nieuwste 12.x | v12.13.2 (2026-07-23). Nieuwste patch binnen 12.10: v12.10.2 |
| amd64-manifest van de pin | `sha256:2526722b27436a097ae884479ec44309634d5ec34e4090bf19fd54bf8beee14d` (ter vergelijking; de repo pint de index) |

### 2.2 DinD

| Veld | Waarde |
|---|---|
| Bron-tag | `docker:dind`, op de host op 8 mei 2026 gebouwd; dit is tag `29.4.3-dind` (env `DOCKER_VERSION=29.4.3`, created 2026-05-08) |
| Gepinde digest (index) | `sha256:685b91dca8eab7de1dce1c303dbb7a763e4082d6a60db10968adf3295fbd2495` |
| Tags `29.4.3-dind` en `29.4-dind` nu | `sha256:685b91dc...2495`, **gelijk** aan de pin (tag is niet verplaatst; de pin bestaat nog) |
| Tag `dind` / `29-dind` nu | `sha256:3f3c01aaaebf7cce837356b688b7c059a4749f10bd7660dec7c58fc454a283f0`, Docker 29.8.1 (created 2026-09-17), **verplaatst** |
| `resolved-digests.tsv` (2 sep) | `docker:dind` = `sha256:3ef33f2e...4cb6` (Docker 29.7.2, created 2026-08-31). Dat is een andere digest dan de pin. Dat is bedoeld: de pin is de draaiende 29.4.3, de tsv-regel is alleen de toenmalige tagstand. Niet verwarren als drift in de bundel |
| Nieuwste dind-tag | `29.8.1-dind` in de taglijst; Docker Engine 29.8.2 is volgens de releasenotes vandaag (2026-09-30) verschenen, nog geen `29.8.2-dind`-tag gezien |
| amd64-manifest | pin `sha256:f67b1b3e59ec7db970a5c905fc97904e31ee16534c0241bd7f372b18ca53e7e2`; `dind` nu `sha256:754ce04dd9dee9ef015680b8529fc49608efb75f30322a54780e7aab32698a47` |

### 2.3 Jobimage

| Veld | Waarde |
|---|---|
| Bron-tag | `catthehacker/ubuntu:act-latest` (opgelost 2 sep 2026, `resolved-digests.tsv`) |
| Gepinde digest (index) | `sha256:c58e2b364da03b0c804c7d660f2ecbedf2f221a382b9baa0b344b0144780ff43` |
| Tag nu | `sha256:c58e2b364da03b0c804c7d660f2ecbedf2f221a382b9baa0b344b0144780ff43`, **gelijk**. Docker Hub meldt `last_pushed` 2026-08-15, dus de tag is sinds vóór de pin niet bewogen |
| Index-inhoud | amd64 `sha256:4f2d5083a9d1...`, arm64, arm (volledige digests niet vastgelegd; repo pint de index, amd64 is de vergelijkingsmaat voor `allowed-job-images.txt` alleen qua grootte) |

Samenvatting: pins 1 en 3 (runner `12.10.1`, jobimage) zijn index-tegen-index gelijk aan de bronregistry; de DinD-pin bestaat nog op zijn eigen versietag maar de zwevende tag `dind` staat drie minor-versies verder. De tag `12` is verplaatst naar 12.13.2.

## 3. Bekende advisories sinds de pin

### 3.1 Runner 12.10.1

- De in §1 beschreven `refs/replace/*`-fix ontbreekt in 12.10.1 en in alle 12.x-releases. Geen CVE-ID gevonden. Blootstelling: een actie-checkout in een job kan via `git replace` een commit overschaduwen. Of dat voor onze workflows (14 workflows in 12 repositories volgens het upgradeonderzoek) een praktisch risico is, is niet beoordeeld.
- Geen Forgejo Runner-advisory met CVE-ID gevonden voor 12.10.1 (zie "Niet vastgesteld" voor wat is nagekeken).
- Serverzijde (niet de runner): Forgejo 15.0.8/16.0.4 op 2026-09-10 voor CVE-2026-89094 (RCE via template-repository). Onze server draait 15.0.9 (zie het upgradeonderzoek). Bron: [GitHub Advisory GHSA-q873-4w8p-m645](https://github.com/advisories/GHSA-q873-4w8p-m645). Buiten de scope van de pins, hier genoteerd omdat het de triggerbron voor een vergelijkingsritme is.

### 3.2 DinD (Docker Engine 29.4.3 in de pin)

Docker Engine 29.4.3 is van 2026-05-06. Volgens de [Docker Engine 29 releasenotes](https://docs.docker.com/engine/release-notes/29/) bevatten latere 29.x-releases beveiligingsfixes die 29.4.3 niet heeft:

| Fix in | Datum | Advisory | Kern |
|---|---|---|---|
| 29.5.1 | 2026-05-18 | CVE-2026-41567, CVE-2026-41568, CVE-2026-42306 | Kwetsbaarheden in `docker cp`: decompressiebinaries (`xz`, `unpigz`) uit het containerfilesystem als host-root; TOCTOU die bestanden op willekeurige hostlocaties laat aanmaken; racecondition die een bind mount naar een willekeurig hostpad omleidt. [GHSA-rg2x-37c3-w2rh](https://github.com/moby/moby/security/advisories/GHSA-rg2x-37c3-w2rh) |
| 29.6.2 | 2026-07-16 | CVE-2026-15793, -15792, -15791, -15789, -15788 | BuildKit: command injection bij Git-checkout uit een bundle, panics, LLB-bestandsoperatie die /tmp leegt, bypass van bestemmingsvalidatie, WCOW-cache-mount (alleen Windows) |
| 29.7.0 | 2026-07-30 | CVE-2026-17106 / GHSA-hfg8-hc9c-6c3h | `moby/go-archive` naar v0.3.0 |
| 29.8.2 | 2026-09-30 | CVE-2026-53493, -92543, -92542, BuildKit CVE-2026-93315 t/m -93326 | Onder meer: DoS door gemanipuleerde OCI-index bij pull, TLS-verificatie overslaan of HTTP-fallback na kwaadaardig DNS-antwoord (registry-credentials/image-substitutie), Swarm-overlay (niet van toepassing zonder Swarm) |

Relevantie voor onze DinD is **niet beoordeeld**: de runner draait jobs in DinD zonder host-socket (zie `CLAUDE.md`), dus `docker cp`-fixes raken alleen de DinD-daemon en de jobcontainers daarin, niet de hostdaemon. Dat is een afweging voor de eigenaar, geen conclusie van dit onderzoek. De advisories zijn bij de bron gelezen op de releasenotes-pagina; de individuele GHSA-pagina's zijn, behalve GHSA-rg2x-37c3-w2rh (GitHub API), niet apart geopend.

### 3.3 Jobimage

Geen advisory onderzocht: `catthehacker/ubuntu:act-latest` is een communityimage zonder eigen advisorykanaal. Er is geen scanner- of SBOM-uitvoer beschikbaar (AUDIT-024 noemt dat ook).

## 4. Niet vastgesteld

- Of Forgejo een **niet-openbare** terugport van #1635 naar 12.x overweegt. Gecontroleerd: releasenotes 12.10.2 t/m 12.13.2, PR-lijst en commits van `support-v12.13.x`. Er is geen terugport-PR gevonden, maar dat bewijst niet dat er geen komt.
- Of de fix een CVE of een security-announcement kreeg. Gezocht: de Forgejo-blog en een webzoekopdracht; `codeberg.org/forgejo/security-announcements` is niet direct doorzocht.
- Wat de `[SECURITY]`-dependencyupdates in 12.10.2 en 12.11.0 concreet dichten (welke CVE's in `x/sys` en de Go-standaardbibliotheek) en of die de runner raken.
- De inhoud van de docker-image-lagen (OS-pakketten, CVE-scan): geen scanner gedraaid. Alleen de Docker Engine-versie is uit de imageconfig gelezen.
- Of `data.forgejo.org/forgejo/runner` (de in de docs genoemde nieuwe registry) dezelfde digests geeft als `code.forgejo.org`; niet vergeleken.
- De volledige digests van het jobimage-amd64-manifest en de runner-13-images; niet nodig voor de vergelijking.
- `docker buildx imagetools inspect` is niet gebruikt; de digests komen rechtstreeks uit de registry-API. Op deze Mac waren `crane` en `skopeo` niet geïnstalleerd.

## 5. Voorstel vergelijkingsritme (voor de eigenaar; geen wijziging van pins)

Voorstel, niet besloten: een vergelijking zonder wijziging, dus passend binnen de fase-1-freeze.

- **Periodiek:** maandelijks, bijvoorbeeld in de eerste week, `resolve-digests.sh` draaien voor de drie bronnen (`runner:12`, `docker:dind`, `catthehacker/ubuntu:act-latest`) plus de lijst van nieuwe 12.x-releases, en het verschil vastleggen onder `evidence/` met datum.
- **Op een trigger:** direct bij een Forgejo security-release (server of runner), een Docker Engine-release met een security-kop in de releasenotes, of een nieuwe 12.x-runnerrelease.
- **Vraag per vergelijking:** staat er een fix in de nieuwere versie die bij ons geldt (ja/nee/niet beoordeeld), en heeft iemand het terugportstatus gecontroleerd op `support-v*`-branches van de runner?
- **Uitkomst is informatie:** een afwijking opent een afweging voor de eigenaar; het pinbesluit en de fasevolgorde blijven bij de eigenaar, en het upgradebesluit volgt het ontwerp (fase 2).

## Bronnen

- Runner-PR #1635: https://code.forgejo.org/forgejo/runner/pulls/1635
- Runner-releases: https://code.forgejo.org/forgejo/runner/releases (API: `/api/v1/repos/forgejo/runner/releases`)
- Runner v13.0.0-blog: https://forgejo.org/2026-08-runner-release-v13/
- Onderhoudsbranch: https://code.forgejo.org/forgejo/runner/src/branch/support-v12.13.x
- Registry: `https://code.forgejo.org/v2/forgejo/runner/manifests/<tag>` (anonieme token), Docker Hub `library/docker` en `catthehacker/ubuntu`
- Docker Engine 29 releasenotes: https://docs.docker.com/engine/release-notes/29/
- moby-advisory: https://github.com/moby/moby/security/advisories/GHSA-rg2x-37c3-w2rh
- Forgejo CVE-2026-89094: https://github.com/advisories/GHSA-q873-4w8p-m645
- Repo: `forgejo-runner/.env.example`, `forgejo-runner/labels.txt`, `forgejo-runner/allowed-job-images.txt`, `docs/forgejo-runner-pool/evidence/stap-a/resolved-digests.tsv`, `docs/forgejo-runner-pool/evidence/stap-a/scrum4me-server/images.json`, `forgejo-runner/scripts/resolve-digests.sh`
