# Migratieontwerp — bestaande Forgejo Runner uitbreiden naar een tweemachinepool

**Datum:** 31 augustus 2026  
**Status:** ontwerp GO — delta-review R12 (repo-tracking en vier bevindingen) goedgekeurd in ronde 3; uitvoering nog niet gestart  
**Doelhosts:** `scrum4me-server` en `max2`  
**Fase 1:** stabiele pool met Forgejo Runner 12.10.1  
**Fase 2:** afzonderlijke rolling upgrade naar Forgejo Runner 13

## 1. Besluit

De bestaande werkende Forgejo Runner + DinD-installatie op `scrum4me-server` wordt gebruikt als functionele referentie. We kopiëren niet de draaiende container, het DinD-volume of de registratiegegevens. We reconstrueren de installatie als een gedeelde declaratieve bundel en gebruiken die voor een tweede, onafhankelijk geregistreerde runner op `max2`.

Tijdens de poolmigratie blijven Runner 12.10.1, de DinD-versie, labelnamen en jobsemantiek gelijk aan de huidige werkende installatie. De legacy registratie via `.runner` wordt wel vervangen door de al in Runner 12.10.1 ondersteunde Forgejo 15-connectionconfiguratie. De runner draait voortaan per job met `one-job --wait`; tussen twee runnerprocessen scrubt een hostcontroller de eigen DinD. Runner 13 wordt pas ingevoerd nadat de tweemachinepool zeven aaneengesloten dagen aan de stabiliteitscriteria heeft voldaan.

## 2. Waarom deze volgorde

Fase 1 houdt de Runnerversie vast op 12.10.1 en stelt Runner 13 uit. Dat isoleert de breaking changes van Runner 13 van alle overige wijzigingen.

Fase 1 is echter géén enkelvoudige wijziging. Naast poolvorming veranderen tegelijk: het registratiemodel (legacy `.runner` → `server.connections`), de levenscyclus (permanente `daemon` → `one-job --wait` onder een systemd-cyclecontroller), de stateretentie (bestaande DinD-cache → volledige scrub na iedere job), de resourcecaps, de digest-pinning van de jobimage en de trustgate. Foutlokalisatie berust daarom niet op "één variabele" maar op de gefaseerde volgorde uit §8: `max2` wordt afzonderlijk bewezen in stap D en E vóór poolgedrag in stap F, en pas daarna wordt `scrum4me-server` in stap G genormaliseerd. Iedere stap is afzonderlijk terug te draaien.

Eén van die gelijktijdige wijzigingen heeft een voorspelbaar prestatie-effect. De huidige installatie draagt circa 121 GB inner-DinD-data en leunt dus zwaar op layer- en buildcache; de scrub uit §7.9 verwijdert die cache na iedere job. Jobduur is daarom een expliciet meetpunt in stap A en §7.8 en een expliciet stabiliteitscriterium in §9, zodat een onaanvaardbare regressie een zichtbare beslissing wordt in plaats van een sluipend gevolg.

De route heeft bovendien een eenvoudige rollback: zolang de huidige runner op `scrum4me-server` niet is gewijzigd, kan de nieuwe runner op `max2` worden gestopt en is de beginsituatie direct terug.

## 3. Doelarchitectuur

```text
                         Forgejo 15.0.2
                    dezelfde scope en labels
                              │
                 ┌────────────┴────────────┐
                 │                         │
       scrum4me-server                   max2
       bestaande Docker                 bestaande Docker
                 │                         │
       systemd cyclecontroller          systemd cyclecontroller
       Runner 12 one-job --wait         Runner 12 one-job --wait
       capacity: 1                      capacity: 1
                 │                         │
       exclusieve DinD                  exclusieve DinD
       lokaal volume                    lokaal volume
```

Forgejo verdeelt een job over iedere online runner die binnen dezelfde scope het gevraagde label aanbiedt. Per host bestaat maar één runnerproces tegelijk en dat proces accepteert precies één job, rondt die af en stopt voordat de scrub begint. De runners delen geen UUID, token, configbestand, netwerk of DinD-volume.

## 4. Wat identiek blijft

De volgende onderdelen komen uit één gedeelde, versiebeheerde bundel en moeten byte-identiek zijn:

| Onderdeel | Vereiste |
|---|---|
| Runnerimage | exact dezelfde Runner 12.10.1-tag én registry-gevalideerde manifestdigest |
| DinD-image | exact dezelfde tag én manifestdigest als de werkende installatie |
| Compose-template | dezelfde services, netwerken, volumestructuur, healthchecks en logging |
| Labels | dezelfde geordende lijst uit één `labels.txt`; labelnaam gelijk, jobimage digest-gepind |
| Forgejo-scope | global; dit is bewust instancebreed en gelijk aan het bestaande runnerrecord |
| Connections | exact één `server.connections`-verbinding per runnerconfig; harde `one-job`-randvoorwaarde |
| Capaciteit | `capacity: 1` per runner |
| Jobpolicy | geen hostjobs, geen host-Docker-socket en geen privileged jobcontainers |
| Resourceprofiel | dezelfde caps op beide hosts: geheugen uit de gemeten piek (harde grens), CPU op het host-affordable budget (throttlebaar), jobduur als prestatie-gate (§7.8) |
| Verificatie | dezelfde health-, isolatie-, verdelings- en failoverchecks |

De huidige live images worden vóór het maken van de bundel via `docker image inspect` en `RepoDigests` vastgelegd. Iedere kandidaatpin moet daarna vanaf de registry slagen voor `docker manifest inspect <image>@<digest>`. Alleen een lokale image-ID of een tag zoals `runner:12` is niet voldoende reproduceerbaar.

## 5. Wat per host uniek is

| Onderdeel | `scrum4me-server` | `max2` |
|---|---|---|
| Runnerrecord | bestaand legacy record tot normalisatie; daarna een nieuw record | nieuw record aanmaken |
| Runnernaam | `scrum4me-srv-runner-01` | `max2-forgejo-runner-02` |
| UUID | nieuwe UUID bij normalisatie | nieuwe UUID |
| Token | nieuw token in apart credentialbestand | nieuw token in apart credentialbestand |
| Configuratie | lokaal `runner-config.yml` plus lokaal credentialbestand | eigen `runner-config.yml` plus eigen credentialbestand |
| DinD-volume | na normalisatie lokaal `forgejo-runner-dind-data` | lokaal `forgejo-runner-dind-data` |
| Containernetwerk | lokaal netwerk op deze host | lokaal netwerk op deze host |
| Logs en metrics | hostgebonden | hostgebonden |

De nieuwe `max2`-config wordt gegenereerd met de gepinde Runner 12.10.1-image. Daarna worden de gemeenschappelijke policy, het canonieke labelblok en de unieke UUID ingevoegd. Het token staat niet inline: `server.connections.forgejo.token_url` verwijst naar een afzonderlijk read-only credentialbestand. Het bestaande configbestand en de legacy `.runner` van `scrum4me-server` worden nooit naar `max2` gekopieerd.

## 6. Gedeelde bundel

De gereconstrueerde bundel krijgt deze verantwoordelijkheden:

```text
forgejo-runner/
├── compose.yaml                 gedeelde runner- en DinD-services
├── .env.example                 uitsluitend imagepins en niet-geheime waarden
├── labels.txt                   canonieke labels voor beide runners
├── runner-config.policy.yml     capacity, timeouts en DinD-policy
├── trusted-actions-scope.yml    expliciete trust-allowlist voor global scope
├── allowed-job-images.txt       registry-gevalideerde digests die scrub mag behouden
├── forgejo-runner-cycle.service hostcontroller; één job, scrub, opnieuw aanbieden
├── scripts/
│   ├── capture-current.sh       read-only inventarisatie van de live installatie
│   ├── render-config.sh         maakt hostconfig uit basisconfig + policy + UUID
│   ├── preflight.sh             stopt vóór mutaties als de host niet past
│   ├── verify-stack.sh          health, poorten, config, labels en isolatie
│   ├── verify-trust-scope.sh    controleert repos, schrijvers en PR/fork-policy
│   ├── forgejo_runner_cycle.py  lifecycle incl. drain, scrub en quarantaine
│   └── scrub-dind.sh            fenced cleanup terwijl geen runnerproces bestaat
└── README.md                    uitrol-, rollback- en upgradeprocedure

/opt/forgejo-runner/credentials/
└── forgejo-token                hostbron; lokaal, nooit in Git, mode 0600
```

Runner 12.10.1 ondersteunt `server.connections`, connection-labels en `token_url`. De UUID en labels staan in de lokale config. De runnerservice bindmount `/opt/forgejo-runner/credentials/forgejo-token` read-only naar het absolute containerpad `/run/forgejo-runner-credentials/forgejo-token`; de config gebruikt letterlijk `token_url: file:/run/forgejo-runner-credentials/forgejo-token`. Er is geen `$CREDENTIALS_DIRECTORY`-placeholder nodig.

Het tokenbestand is mode `0600`, eigendom van de effectieve runner-UID:GID. Secrets staan niet inline in `runner-config.yml`, `.env`, Compose `command`, Git, shellhistory of containermetadata. De legacy `.runner` wordt uit het actieve runnerpad gehaald, zodat uitsluitend `server.connections` de verbinding levert.

Compose geeft het DinD-datavolume expliciet de naam `forgejo-runner-dind-data` via `volumes.dind-data.name`. De naam mag op beide hosts gelijk zijn, omdat Docker-volumes hostlokaal zijn. De permanente DinD-service behoudt `restart: always`; de tijdelijke runnerservice heeft `restart: "no"`. Uitsluitend de systemd-cyclecontroller maakt een runnerproces aan en wacht op diens exit.

`forgejo-runner-cycle.service` wordt op iedere host met `systemctl enable --now` geactiveerd en bevat minimaal `Requires=docker.service`, `After=docker.service network-online.target`, `Wants=network-online.target` en `WantedBy=multi-user.target`. Bij boot start de unit eerst alleen DinD, wacht tot de healthcheck groen is en gaat daarna naar `SOURCE_WAIT`: er bestaat nog geen runnerproces. De controller toetst met begrensde exponential backoff — 2, 4, 8, 16 en daarna 30 seconden — zowel een algemene Forgejo-health/API-probe als een geauthenticeerde read-only trust-preflight. Pas wanneer beide bronnen aantoonbaar ready zijn, voert hij trust-, volume-, image- en scrubgates uit en mag hij een runner in `WAITING` zetten.

De boot-SLA is maximaal vijf minuten vanaf `docker.service=active` tot `WAITING`. Buiten een geldig, identiek op beide hosts gearmd maintenance-record alarmeert overschrijding en reset zij de stabiliteitsperiode. Binnen zo'n record is de overschrijding uitsluitend informatief zolang het record nog niet verlopen is en de controller alleen verwachte control-plane-`SOURCE_WAIT` observeert; zij reset de stabiliteitsperiode dan niet. Bij de harde UTC-eindtijd vervalt deze uitzondering direct en gelden de normale alarm- en resetregels. In alle gevallen blijft de lokale controller zonder runner in `SOURCE_WAIT` doorproberen; dit is geen bevestigde securityafwijking. Er bestaat geen commandokanaal tussen de hosts: poolbrede quarantaine is convergent en niet gecommandeerd (§7.7). Een opstartrace of tijdelijke API-/database-onbereikbaarheid op `scrum4me-server` kan `max2` daarom niet quarantainen. De andere host behoudt zijn laatst goedgekeurde truststate, laat een reeds `RUNNING` job zo ver mogelijk gecontroleerd eindigen en start geen nieuwe runnercyclus. Een `WAITING` runner wordt graceful gestopt; het serverzijdige nulbewijs wordt na bronherstel uitgevoerd vóór heropening. Daarna blijft ook die host in `SOURCE_WAIT` totdat readiness en de trustgate weer groen zijn. Pas een bereikbare, geauthenticeerde Forgejo-bron die de inhoudelijke trustgate hard laat falen mag beide controllers quarantainen. De controller blijft zelf actief in `SOURCE_WAIT`, `CREDENTIAL_ERROR` of `QUARANTINED`; een unit-restart omzeilt nooit de gates.

Omdat Forgejo en Postgres zelf op `scrum4me-server` draaien, is een hostreboot daar ook een tijdelijk control-plane-onderhoud: `max2` blijft als host/controller gezond maar gaat na drain naar `SOURCE_WAIT`, omdat Forgejo gedurende dat vooraf aangekondigde venster geen nieuwe jobs kan uitdelen. Dat is geen bewijsbaar runnerfailovervenster en wordt niet als zodanig gepresenteerd. De reboottest op `scrum4me-server` vereist daarom een goedgekeurd productie-onderhoudsvenster; jobs worden vooraf gedraind, nieuwe runs blijven tijdens de control-plane-uitval uit of queued en na API-readiness volgt op beide hosts de trustgate vóór een runner terugkeert. Ongeplande productie-uitval blijft niet toegestaan.

De gekozen vorm is rechtstreeks ondersteund door de [Forgejo Runner 12.10.1-configuratie](https://code.forgejo.org/forgejo/runner/src/tag/v12.10.1/internal/pkg/config/config.example.yaml), de [`one-job`-commandregistratie met `--wait/-w`](https://code.forgejo.org/forgejo/runner/src/tag/v12.10.1/internal/app/cmd/cmd.go), de [single-task-poller](https://code.forgejo.org/forgejo/runner/src/tag/v12.10.1/internal/app/poll/single.go) en de [Forgejo 15-registratiedocumentatie](https://forgejo.org/docs/v15.0/admin/actions/registration/).

### 6.1 Versiebeheer, distributie en driftgate

De bundel is niet alleen "versiebeheerd" maar heeft één benoemde canonieke bron. Twee losse kopieën zouden twee bronnen van waarheid zijn en maken de byte-identiek-eis uit §4 en §9 onbewijsbaar.

Beide repo's bestaan al op de Forgejo-instance, maar zijn gebootstrapt met uitsluitend `README.md`, `CLAUDE.md`, `.gitignore` en — in `scrum4me-server` — `docs/forgejo-runner-pool/`. De onderstaande tabel is daarom een **doelstructuur en geen beschrijving van de huidige boom**; de kolom "bestaat nu" scheidt belofte van werkelijkheid.

| Repository | Rol | Doelinhoud | Bestaat nu | Ontstaat in |
|---|---|---|---|---|
| `scrum4me-server` | canonieke bron | `docs/forgejo-runner-pool/` met dit ontwerp, de reviewrapporten en het runbook | ja | — |
| `scrum4me-server` | canonieke bron | `forgejo-runner/` met de volledige gedeelde bundel | nee | stap B |
| `scrum4me-server` | canonieke bron | `hosts/scrum4me-server/` met host-overlay en bewijs | nee | stap G |
| `max2` | host-overlay | `hosts/max2/` met `runner-config.yml` zonder secretwaarden, preflight-uitkomsten en inventarisatie | nee | stap D |
| `max2` | host-overlay | `evidence/` met metingen, testbewijs en maintenance-records | nee | stap A en E |

`max2` krijgt bewust geen kopie van de bundel. Beide hosts rollen uit vanaf exact dezelfde commit-SHA van de canonieke repo.

Bindend, met per regel de stap die het bewijst:

- iedere host houdt de uitgerolde bundelcommit-SHA vast in `/opt/forgejo-runner/BUNDLE_COMMIT`; `verify-stack.sh` faalt als die ontbreekt, niet in de canonieke repo bestaat of afwijkt van de andere host (stap D en G);
- `verify-stack.sh` berekent daarnaast een canonieke hash over de uitgerolde bundelbestanden en vergelijkt die met de hash van die commit; dit is de mechanische invulling van "byte-identiek" waarnaar §9 verwijst; stap B levert het script, stap D en G bewijzen de vergelijking;
- beide waarden staan in de monitoring van §10;
- secrets komen niet in Git. Vandaag bestaat alleen de eenmalige scan van stap B, en negeren de `.gitignore`-bestanden van beide repo's `credentials/`, `forgejo-token`, `*.token`, `*.key`, `*.pem`, `.env` en `.env.*`, met `.env.example` expliciet toegestaan. Een doorlopende scan is er nog niet: stap B levert `scripts/secret-scan.sh` plus `scripts/install-git-hooks.sh` in de canonieke repo, installeert die als pre-commit hook in beide werkbomen en bewijst met een wegwerptestbestand dat een commit met een tokenpatroon daadwerkelijk wordt geblokkeerd. Pas na dat bewijs mag dit ontwerp beweren dat de scan draait. Het actieve token leeft op de host in `/opt/forgejo-runner/credentials/` en bevindt zich dus nooit binnen een repo-werkboom;
- deployment gebeurt handmatig of via SSH vanaf `mac`, nooit via een Forgejo Actions-workflow. Jobcontainers draaien in DinD zonder host-Docker-socket en zonder hostpadvolumes (§7.6) en kunnen de hoststack fysiek niet wijzigen. Een deployworkflow op deze runners is per ontwerp onmogelijk en mag niet worden gebouwd;
- beide repo's staan op dezelfde Forgejo-instance en vallen daarmee binnen de trustgrens van §7.7. Stap A stelt per repo vast óf Actions is ingeschakeld. Alleen een aantoonbaar Actions-enabled repo wordt als trusted scope in `trusted-actions-scope.yml` opgenomen; een repo met Actions uit wordt daar expliciet als bekende niet-Actions-repo vastgelegd, zodat later inschakelen als drift zichtbaar wordt. Beide vastleggingen gebeuren vóór de eerste trustgate-run; anders alarmeert de eerste dagelijkse controle op deze repo's zelf als zachte trustafwijking.

## 7. Wijzigingen aan de bestaande installatie

### 7.1 Host-Docker blijft ongemoeid

Op beide machines is Docker 29.7.2 al aanwezig. De poolmigratie:

- voegt geen APT-repository toe;
- installeert of upgradet geen Docker- of containerd-pakket;
- wijzigt `/etc/docker/daemon.json` niet;
- herstart de Docker-daemon niet;
- voert geen hostbrede `docker system prune` uit.

Logging wordt per runner- en DinD-service ingesteld. Cleanup vindt alleen plaats binnen de eigen DinD-daemon.

### 7.2 Huidige runner blijft eerst onaangeraakt

De eerste deployment is de nieuwe runner op `max2`. Pas nadat die afzonderlijk jobs kan uitvoeren en de huidige runner kan vervangen bij uitval, wordt de bestaande `scrum4me-server`-installatie genormaliseerd.

Dit voorkomt dat een configuratiefout de enige werkende runner uitschakelt.

### 7.3 Legacy `.runner` en tokens veilig migreren

De live Runner 12.10.1-installatie gebruikt nog het oude registratiemodel: de registratieopdracht staat in `Config.Cmd`; identiteit, token en labels staan in het Docker-volume in `.runner`, momenteel mode `0644`. De doelinstallatie gebruikt het hierboven beschreven Forgejo 15-connectionmodel, dat dezelfde Runner 12.10.1 al ondersteunt.

Op `max2` wordt via Forgejo UI of API een nieuw record gemaakt. UUID gaat in `runner-config.yml`; token gaat in `credentials/forgejo-token`. Er wordt geen legacy `forgejo-runner register` als permanente containeropdracht gebruikt en er wordt geen `.runner` gemaakt.

Na bewezen ingebruikname van `max2` wordt `scrum4me-server` als volgt genormaliseerd:

1. inventariseer het bestaande record en wacht tot de runner idle is;
2. blokkeer nieuwe jobtoewijzing aan de oude runner;
3. maak een vervangend runnerrecord met nieuwe UUID en token op dezelfde global scope;
4. schrijf UUID in de connectionconfig, token in `/opt/forgejo-runner/credentials/forgejo-token` en gebruik in de containerconfig het absolute `file:/run/forgejo-runner-credentials/forgejo-token`;
5. stop alleen de oude runnercontainer;
6. verplaats de legacy `.runner` uit het gemounte runnerpad naar een root-only quarantainebestand `legacy-runner.revoked.json` met mode `0600`, zodat alleen `server.connections` actief is;
7. start de cyclecontroller, die de nieuwe runnercontainer per job met `one-job --wait` uitvoert, zonder registratieopdracht of secrets in command/environment;
8. bewijs via `stat`, `docker inspect` en een geschoonde configweergave dat alleen het credentialbestand het actieve token bevat;
9. verwijder of disable het oude Forgejo-runnerrecord en trek de oude credentials definitief in;
10. verwijder het quarantainebestand nadat de rollbackperiode is gesloten; de oude token wordt nooit opnieuw gebruikt.

### 7.4 Canoniek labelcontract invoeren

De huidige `runner-config.yaml` bevat een lege labelset; bij de legacy installatie is daarom het `labels`-veld in `.runner` de canonieke bron. Het Forgejo-record toont alleen labelnamen en niet de volledige `naam:docker://image`-vorm en is dus geen geldige bron voor de jobimage.

De volledige runnerzijdige labels uit `.runner` worden read-only geëxtraheerd en als canonieke geordende lijst in `labels.txt` vastgelegd. Het huidige live contract bevat `ubuntu-latest:docker://catthehacker/ubuntu:act-latest`. In de doelbundel blijft de labelnaam `ubuntu-latest` gelijk, maar de imageverwijzing wordt na registry-resolutie vastgezet op exact dezelfde inhoud als `docker://catthehacker/ubuntu:act-latest@sha256:<vastgelegde-digest>`. Beide nieuwe connectionconfiguraties krijgen exact deze lijst. De vergelijking gebruikt een YAML/JSON-parser en een canonieke JSON-representatie; niet een inspringingsgevoelige awk-extractie. De check faalt als de lijst leeg is, de digest niet vanaf de registry is bevestigd of een mutabele tag zonder digest resteert.

De bestaande scope is global (`owner_id=0`, `repo_id=0`). De nieuwe runner wordt bewust eveneens instancebreed. Voor iedere test wordt gecontroleerd welke andere global, owner- of repositoryrunners hetzelfde label kunnen aanbieden.

### 7.5 Per runner een exclusieve DinD

Iedere runner gebruikt uitsluitend de DinD op dezelfde host. Er is:

- geen mount van `/var/run/docker.sock` van de host;
- geen publicatie van 2375 of 2376 op de host;
- geen gedeeld DinD-volume tussen de hosts;
- geen gedeelde DinD tussen de twee runners;
- een expliciet intern Docker-endpoint dat zowel de healthcheck als alle verificaties gebruiken.

De endpointmatrix is bindend:

| Uitvoercontext | Endpoint | Doel |
|---|---|---|
| DinD-container zelf | `tcp://127.0.0.1:2375` | healthcheck en interne beheerchecks |
| Runnercontainer | `tcp://dind:2375` | job- en servicecontainers in de eigen DinD maken |
| Job-/stepcontainer | `tcp://dind.internal:2375` | `docker build/run` vanuit de workflow; `dind.internal` wijst binnen DinD naar de gateway |

Iedere verificatie noemt zijn uitvoercontext en gebruikt expliciet het bijbehorende endpoint. Geen check valt terug op `/var/run/docker.sock`.

De Runner 12.10.1-configknoppen zijn eveneens bindend:

- Compose runner-environment: `DOCKER_HOST=tcp://dind:2375`;
- `container.docker_host: "-"`, zodat Runner het bovenstaande endpoint gebruikt zonder een socket te mounten;
- `runner.envs.DOCKER_HOST: tcp://dind.internal:2375`, zodat iedere job/step hetzelfde inner-DinD-endpoint krijgt;
- `container.options: --add-host=dind.internal:host-gateway`, zodat die naam vanuit DinD-gemaakte jobcontainers naar de DinD-gateway wijst.

### 7.6 Privileged DinD: expliciet geaccepteerde co-locatierisico's

Fase 1 behoudt de werkende baseline: de DinD-service draait `privileged: true`. Rootless DinD wordt niet tegelijk met de poolmigratie ingevoerd, omdat dat een tweede functionele variabele zou toevoegen. Jobcontainers zelf krijgen geen privileged-modus en zien de host-Dockerdaemon niet.

Dit betekent dat de DinD-service ondanks netwerk- en socketisolatie op dezelfde hostkernel als productie draait. Een containerescape of misbruik van de privileged DinD kan daardoor de host en de productiecontainers raken. Directe co-locatie is een bindende gebruikerskeuze; goedkeuring van dit ontwerp geldt als expliciete acceptatie van dit restrisico voor uitsluitend vertrouwde workflows en vertrouwde gebruikers met workflow-schrijfrechten. Onvertrouwde fork- of pull-requestworkflows mogen niet op deze global runners worden uitgevoerd.

De outer Compose-service krijgt exact deze grenzen:

- `privileged: true` alleen op DinD; runner en jobpolicy blijven niet-privileged;
- geen host-Docker-socket, host-PID-, host-IPC- of host-netwerkmode;
- geen hostpadvolumes, behalve expliciet goedgekeurde lokale runnerconfig/credentials voor de runnercontainer;
- geen gepubliceerde DinD-poort;
- alleen runner en DinD delen het private controlenetwerk;
- CPU-, geheugen- en PID-limieten op runner en DinD;
- read-only mount van het tokenbestand alleen in de runnercontainer;
- acceptatietests bewijzen dat een job de hostcontainers niet kan zien.

### 7.7 Trustscope voor global runners

Omdat beide runnerrecords global zijn, omvat hun vertrouwensgrens de hele Forgejo-instance. `trusted-actions-scope.yml` is een expliciete allowlist van iedere Actions-enabled repository en iedere identiteit met write/admin-rechten op workflowbestanden. Een identiteit is alleen trusted als JP haar bij naam heeft goedgekeurd; onbekende accounts, externe collaborators en ongecontroleerde teams zijn niet trusted.

De trustscope-gate inventariseert vóór deployment:

- alle repositories waarvoor Actions is ingeschakeld;
- zichtbaarheid en eigenaar/organisatie per repository;
- users, teams en externe collaborators met write/admin;
- branch-protection- en reviewregels voor de default branch;
- de effectieve workflowbron per repository: `.forgejo/workflows/*.{yml,yaml}` als die map bestaat en anders Forgejo's fallback `.github/workflows/*.{yml,yaml}`;
- alle effectieve workflows met `pull_request`, `pull_request_target`, `workflow_run` of een gedeeld runnerlabel; de gate behandelt het verwijderen van `.forgejo/workflows` als een relevante wijziging omdat daarmee de `.github/workflows`-fallback actief kan worden;
- fork- en PR-beleid dat onbetrouwbare code kan laten uitvoeren.

De gate bepaalt de effectieve workflowbron mechanisch en faalt gesloten als het bestaan, de inhoud of de fallback niet ondubbelzinnig uitleesbaar is. De readinesslaag onderscheidt eerst bronbeschikbaarheid, authenticatie/protocol en inhoudelijke trust. Iedere uitkomst valt verplicht in precies één van vier takken; er bestaat geen default-fallback:

1. netwerkfout, time-out, connection refused of HTTP 5xx op een readinessprobe: na bevestiging `SOURCE_WAIT`, lokaal availability-alarm, geen cross-hostquarantaine;
2. HTTP 401/403 op de geauthenticeerde readinessprobe: na bevestiging lokaal `CREDENTIAL_ERROR` zonder runner, securityalarm met credential-/scope-oorzaak, nooit een cross-hostquarantaine omdat nog geen inhoudelijk trustoordeel bestaat; tokenwaarden worden niet gelogd;
3. iedere andere onverwachte HTTP-status, malformed antwoord of verkeerd readinessschema: na bevestiging lokale `QUARANTINED` protocol/configuratiefout zonder cross-hostquarantaine;
4. alleen HTTP 2xx met het verwachte algemene én geauthenticeerde readinessschema: bron ready; voer daarna de volledige inhoudelijke trustgate uit.

De bevestigingsregel is voor de eerste drie takken identiek. De controller verwerkt readinessresultaten, childstatus en lokaal ontvangen runnerlog-/taskacceptatie-events in één geserialiseerde eventloop. Ieder event krijgt op ontvangst één oplopend lokaal `event_seq`, een lokale monotone tijd voor deadlines en daarnaast lokale RFC3339Nano-wandkloktijd voor audit. De eerste afwijkende probe registreert een informatief `FENCE_SET`-event en diens `fence_seq`; er start geen nieuw child. Staat de host `WAITING`, dan gaat hij direct naar `DRAINING` en stopt het bestaande `one-job --wait`-child, zodat het niet nog vijf seconden online blijft pollen. Het bestaande FetchTask-ambiguïteitsbewijs uit §7.9 is verplicht vóór heropening; zolang de bron niet read-ready is, wordt dat bewijs uitgesteld en blijft de host zonder runner.

Alleen een lokaal `JOB_ACCEPTED`/`RUNNING`-event met `event_seq < fence_seq` geldt beslissend als vóór-latch en mag gecontroleerd eindigen. Ieder niet vóór de fence lokaal waargenomen, onbekend of pas erna ontvangen jobevent wordt fail-closed als op/na-latch behandeld: child stoppen, job cancel/requeue of cancel+redispatch vanaf dezelfde commit, daarna scrub en nulbewijs. Logbuffering kan zo hoogstens een legitieme job conservatief laten herdispatchen, nooit een post-fencejob doorlaten. Forgejo-tijdlijn en remote wandklokken zijn uitsluitend corroboratief/audit en beslissen deze classificatie nooit.

Vijf seconden na de eerste afwijking volgt een bevestigingsprobe. Alleen twee opeenvolgende uitkomsten van dezelfde klasse bevestigen de bijbehorende fouttoestand. Een andere foutklasse herstart de vijfsecondenbevestiging onder dezelfde fence. Een geldige 2xx-readiness wist de fence pas nadat een tweede geldige probe vijf seconden later, het eventueel uitgestelde assignment-nulbewijs én de volledige inhoudelijke trustgate groen zijn.

De fence heeft vanaf de eerste afwijking een harde maximale leeftijd van zestig seconden. Is hij dan noch bevestigd noch veilig gewist, dan commit de controller buiten een geldig gearmd maintenance-startupvenster deterministisch naar de zwaarste sinds latch waargenomen klasse: lokale readiness-protocol-`QUARANTINED` > `CREDENTIAL_ERROR` > `SOURCE_WAIT`; dit alarmeert. Een onopgeloste fence kan dus nooit onder een oude `WAITING`-status blijven hangen.

Voor de geplande Forgejo/Postgres-reboot geldt één expliciete, vooraf gearmde uitzondering. Het change-record bevat `maintenance_id`, UTC-start en harde UTC-eindtijd van maximaal dertig minuten; beide controllers krijgen exact dit record vóór de drain. Het venster kan niet automatisch worden aangemaakt of verlengd. Terwijl de algemene Forgejo-readiness nog niet tweemaal geldig is, worden alle startuptransport-, status- en schema-uitkomsten voor de zestigsecondenwatchdog als `SOURCE_WAIT` behandeld; zij veroorzaken geen credential- of protocolquarantaine. Deze deadlinecommit is een verwacht maintenance-event, geen operationeel security-/availabilityalarm. Zodra de algemene readiness tweemaal vijf seconden uiteen geldig is, vervalt deze startupuitzondering direct: de geauthenticeerde probe en inhoudelijke gate volgen de normale vierwegclassificatie, zodat een bevestigde 401/403 of protocolfout ook binnen het onderhoudsvenster correct wordt gemeld. Bij de harde eindtijd vervalt iedere uitzondering; een nog niet ready bron volgt de normale classificatie en alarmering. `SOURCE_WAIT` is alleen binnen het exact gearmde interval verwacht.

Als de ready en geauthenticeerde bron vervolgens een vereist bestaand object of relevante instelling 401/403 geeft, laat ontbreken, een ongeldig inhoudsschema terugstuurt of anders niet volledig laat inventariseren, is de inhoudelijke gate fail-closed. Controllers in `SOURCE_WAIT`, `CREDENTIAL_ERROR` of een lokale readiness-protocol-`QUARANTINED` blijven iedere dertig seconden automatisch readiness proberen. Herstel vereist geen kunstmatige handmatige state-reset: zodra de bestaande of aangepaste credentials/configuratie twee geldige probes vijf seconden uiteen geeft en de volledige trustgate groen is, mag de controller weer `WAITING` worden. Zolang die volledige reeks niet groen is, start nooit een runner; bij een blijvende fout is menselijk herstel van credential/configuratie uiteraard wel nodig.

Een **bevestigde harde trustafwijking** is: een onbekende of niet-goedgekeurde workflow-schrijver, een fork/PR-pad waarmee onbetrouwbare code op de gedeelde labels kan starten, of een na geslaagde bron-readiness inhoudelijk niet-uitleesbare relevante instelling. Alleen dan gaan de cyclecontrollers op beide hosts naar `QUARANTINED`, accepteert de pool geen nieuwe jobs en is global scope NO-GO; als het niet veilig kan worden hersteld, worden de runners beperkt tot organisatie- of repositoryscope voor uitsluitend goedgekeurde repositories.

Deze poolbrede quarantaine is **convergent, niet gecommandeerd**. Er bestaat geen commandokanaal, RPC of gedeelde state tussen de hosts en er wordt er ook geen gebouwd: beide controllers draaien dezelfde gate tegen dezelfde Forgejo-bron en bereiken daardoor onafhankelijk hetzelfde oordeel, elk binnen zijn eigen dertigsecondeninterval. Waar dit ontwerp "op beide hosts" schrijft, betekent dat convergentie en nooit een instructie van de ene host naar de andere. Een kanaal zou een nieuwe faalmodus, eigen authenticatie en een split-brainvraag toevoegen zonder iets op te lossen.

Het gevolg is expliciet en aanvaard: een trustafwijking in de gedeelde bron is een gemeenschappelijke faalmodus die beide hosts tegelijk stilzet. De tweemachinepool beschermt tegen host-, Docker-, DinD- en runnerfalen, niet tegen een instancebrede trustbevinding. Bij een securitybevinding is dat het bedoelde gedrag: doorgaan op de andere host zou onbetrouwbare code op een privileged DinD naast productie laten draaien.

Een **zachte trustafwijking** is een nieuwe repository waarop Actions uitstaat, een collaborator zonder recht om workflows te wijzigen of een strengere branch-protectionregel. Die afwijking alarmeert direct en moet binnen 24 uur worden beoordeeld en in de allowlist worden verwerkt, maar zet de pool niet automatisch stil. Dezelfde controle draait dagelijks en na iedere repository-, collaborator-, team-, Actions-, workflowmap- of policywijziging. Een bevestigde harde afwijking reset de stabiliteitsperiode als securityquarantaine; een zachte afwijking niet zolang zij binnen 24 uur is afgehandeld en niet tot een harde afwijking evolueert. Tijdelijke brononbereikbaarheid wordt als availability-event gelogd: een lopende job mag gecontroleerd eindigen, een wachtende runner stopt graceful, er start geen nieuwe runner en de host gaat naar `SOURCE_WAIT`. Zodra de bron herstelt, volgen het uitgestelde assignment-nulbewijs, beide readinessprobes en de volledige trustgate vóór de overgang naar `WAITING`. Dit is geen cross-hostquarantaine; bij een centrale Forgejo-uitval kunnen beide hosts wel onafhankelijk en terecht `SOURCE_WAIT` bereiken.

### 7.8 Productieworkload beschermen

Voor het vaststellen van caps draait vóór de uitrol op de bestaande runner minimaal één representatieve zwaarste workflow terwijl iedere vijf seconden CPU, geheugengebruik en PID-aantal van runner en DinD worden gemeten. Een enkele inventarisatiemomentopname is niet voldoende.

De limieten worden per service afgeleid, waarbij geheugen en CPU **bewust verschillend** worden behandeld omdat ze fysiek verschillen: geheugen is een harde grens — overschrijding is een OOM-kill — terwijl CPU throttlebaar is: overschrijding vertraagt de job maar breekt hem niet af. De oorspronkelijke regel — 150% van de gemeten piek voor beide — behandelde ze gelijk en leverde daardoor voor parallelle-test-CI een CPU-limiet groter dan de host: een representatieve `vitest run` (of `jest`) opent standaard een worker-pool ter grootte van alle cores en piekte op `scrum4me-server` gemeten 742% (7,4 van 8 cores), waardoor 150% × piek ≈ 11,5 vCPU de acht fysieke cores overschreed en de headroomgate structureel faalde. De meting staat in `docs/forgejo-runner-pool/evidence/stap-a/caps.md`; de herziening is delta-review R13 in het Review record.

Tijdens de representatieve workflow wordt iedere vijf seconden ook `MemAvailable` vastgelegd. De limieten volgen dan uit drie regels:

- **Geheugen — harde grens.** De DinD-geheugenlimiet is `max(4 GiB ondergrens, gemeten piek + 512 MiB variantiemarge)`, de runnerlimiet `max(1 GiB ondergrens, gemeten piek + 256 MiB)`. De som van beide mag op `scrum4me-server` niet meer bedragen dan 50% van de laagste tijdens de representatieve run gemeten `MemAvailable`. Overschrijdt de gemeten geheugenpiek plus marge zelf al die affordable helft, dan is dat een **echte NO-GO**: de job past niet zonder OOM-risico of headroomoverschrijding, en geen enkele cap-instelling lost dat op.
- **CPU — throttlebaar.** De CPU-limieten worden niet uit de piek afgeleid maar op het **host-affordable budget** gezet: de som van de runner- en DinD-CPU-limiet is ten hoogste 50% van de laagste over de pool aanwezige vCPU's, naar beneden afgerond op 0,5 vCPU. De runner krijgt zijn ondergrens (1 vCPU); DinD krijgt de rest van dat budget. Draait de job boven de DinD-CPU-limiet, dan knijpt de kernel hem af en draait hij langzamer, niet stuk. De cap is dus expliciet kleiner dan de onbegrensde piek — dat is de bedoeling. De DinD-CPU-limiet moet ten minste zijn ondergrens (2 vCPU) halen; is het affordable budget lager, dan is de host te klein en is dat een echte NO-GO.
- **PID's** volgen de oude regel: `max(ondergrens, 150% × gemeten piek)`, naar boven afgerond op 128; PID's zijn goedkoop en vormen geen knelpunt. Ondergrenzen: runner 256 PID, DinD 2048 PID.

**Jobduur vervangt de CPU-piek-gate.** Omdat de CPU bewust wordt afgeknepen, kan de CPU-piek geen NO-GO meer zijn — anders zou elke parallelle-test-CI de pool blokkeren. In plaats daarvan is de jobduur de prestatie-gate: in stap D en E draait dezelfde representatieve workflow met de gecapte DinD, en de gemeten wandkloktijd moet binnen 200% van de warme-cachebaseline uit stap A blijven (§9). Een structurele overschrijding is de echte prestatie-NO-GO — de host is dan te traag voor aanvaardbare uitvoering — en vereist een beperktere workload of een nieuw hardware- of architectuurbesluit. Een momentane CPU-piek boven de limiet is dat niet.

`capacity: 1` voorkomt meerdere gelijktijdige jobs binnen één DinD. De afgeleide limieten worden op beide hosts gelijk gehouden zodat hetzelfde label dezelfde minimale uitvoeromgeving betekent. Iedere latere wijziging geldt voor beide runners en reset de zevendaagse stabiliteitsperiode.

De caps worden op `scrum4me-server` gemeten maar gelden gelijk op **beide** hosts. De headroomgate moet daarom ook op beide hosts slagen. Stap A legt van `max2` het aantal vCPU's, het fysieke geheugen, de laagste `MemAvailable` onder de eigen productielast en de vrije ruimte plus inodes op `DockerRootDir` vast. `preflight.sh` faalt vóór iedere mutatie als op de betrokken host niet geldt:

- de som van de vCPU-limieten van runner en DinD is ten hoogste 50% van de aanwezige vCPU's;
- de som van beide geheugenlimieten is ten hoogste 50% van de laagste gemeten `MemAvailable`;
- de vrije ruimte op `DockerRootDir` is ten minste 20% én ten minste de som van de gepinde toegestane images uit `allowed-job-images.txt` plus 20 GB werkruimte;
- de vrije inodes op `DockerRootDir` zijn ten minste 20%.

Haalt `max2` deze grenzen niet bij de uit `scrum4me-server` afgeleide caps, dan is dat een NO-GO voor identieke caps: de pool is dan niet uitwisselbaar en er volgt eerst een beperktere workload of een nieuw hardware- of architectuurbesluit. Lagere caps op alleen `max2` zijn niet toegestaan, omdat hetzelfde label dan een andere minimale uitvoeromgeving zou betekenen.

Meet tijdens dezelfde representatieve run ook de wandkloktijd per job op de huidige, warme DinD-cache. Die waarde is de jobduurbaseline waartegen §9 de cacheloze pool afzet.

### 7.9 DinD-retentie en scrub tussen jobs

Fase 1 accepteert geen jobstate, lokaal gebouwde images of buildcache tussen opeenvolgende jobs of repositories. Runnercache staat uit. Een permanente `daemon` kan na een idle-meting nog een nieuwe job aannemen; daarom gebruikt iedere host de in Runner 12.10.1 ondersteunde opdracht [`one-job --wait`](https://code.forgejo.org/forgejo/runner/src/tag/v12.10.1/internal/app/cmd/job.go). De single-task-poller wacht op precies één job, laat die voltooien, sluit daarna af en accepteert geen tweede job.

De host-systemd-cyclecontroller is de enige eigenaar van de runnerlevenscyclus en kent zeven toestanden:

- `SOURCE_WAIT`: alleen DinD/controller bestaan; de Forgejo/trustbron is nog niet ready en er wordt geen runner gestart;
- `CREDENTIAL_ERROR`: de geauthenticeerde readinessprobe gaf 401/403; lokale securityfout zonder runner en zonder cross-hostquarantaine;
- `WAITING`: één runnercontainer met `one-job --wait` is online en wacht op één job;
- `RUNNING`: datzelfde proces voert de geaccepteerde job volledig uit;
- `DRAINING`: een geplande stop blokkeert een nieuwe cyclus en bewijst serverzijdig dat geen job meer aan deze runner is toegewezen of actief;
- `SCRUBBING`: het runnerproces is geëindigd en er bestaat geen runnercontainer die een volgende job kan aannemen;
- `QUARANTINED`: trust-, DinD-, image- of scrubbewijs faalde; er wordt geen runnerproces gestart.

De controller is een niet-triviale toestandsmachine: een geserialiseerde eventloop, oplopende `event_seq`, een schedulingfence, tweewaarnemingenbevestiging, een deadlinewatchdog en atomair gepersisteerde toestand. Hij wordt daarom in Python geïmplementeerd als `scripts/forgejo_runner_cycle.py` en niet in shell. Signal handling, de race tussen childexit en readinessprobe, monotone deadlines en atomaire statepersistentie zijn in shell niet betrouwbaar uit te drukken; een fragiele controller zou zelf een grotere storingsbron worden dan het probleem dat hij oplost. Het stub- en testharnas uit stap A is de unittestsuite van deze module en hoort bij de bundel; de gates uit stap A zijn pas groen als die suite groen is. De overige scripts uit §6 blijven shell.

De controller bewaakt het runner-childproces en de geauthenticeerde readinessprobe gelijktijdig; hij blokkeert dus niet uitsluitend op de `one-job`-exit. In normale toestand wordt readiness iedere dertig seconden getoetst. De eerste fout zet de schedulingfence, blokkeert iedere childstart en stopt een `WAITING` child direct via `DRAINING`; de vijfsecondenbevestiging uit §7.7 kiest pas daarna de foutklasse. Bij een al vóór de latch `RUNNING` job legt de controller de geselecteerde volgende toestand vast maar breekt hij die job niet abrupt af; na het gecontroleerde einde en scrub start geen nieuw childproces. Een op/na-latch geaccepteerde job volgt de cancel/scrub/redispatchroute uit §7.7. In iedere fouttoestand blijft de controller automatisch iedere dertig seconden herproberen; alleen twee geldige readinessprobes vijf seconden uiteen, assignment-nulbewijs en de volledige groene trustgate mogen opnieuw een runner starten. De zestigsecondenwatchdog commit iedere niet-opgeloste fence naar de zwaarste waargenomen klasse.

De cyclus is bindend en racevrij:

1. controleer vóór de eerste aanbieding de harde trustgate, DinD-health en de schone begintoestand;
2. controleer of iedere regel in `allowed-job-images.txt` een registry-gevalideerde digest is; pre-pull ontbrekende toegestane images uitsluitend per digest;
3. start exact één runnercontainer met de gepinde Runner 12.10.1-image, config met exact één connection, `one-job --wait` en zonder Docker restartpolicy;
4. wacht op de exit van dit proces; een reeds geaccepteerde job krijgt de normale shutdown-timeout en wordt vóór exit afgerond; de controller correleert runnerlog/jobhandle met een terminale Forgejo-jobstatus;
5. bewijs dat geen runnerproces of runnercontainer bestaat; scrub na iedere exit voor veilige containment, maar heropen na een runnerfout niet en eindig na de scrub in `QUARANTINED`;
6. verwijder binnen uitsluitend deze DinD alle containers, volumes, niet-standaardnetwerken, lokaal gebouwde of niet-toegestane images en de volledige BuildKit-cache;
7. behoud alleen jobimages waarvan de exacte digest in `allowed-job-images.txt` staat; de outer Runner- en DinD-images bevinden zich in de hostdaemon en worden door deze inner-DinD-scrub niet geraakt;
8. bewijs: geen containers of volumes, alleen `bridge`/`host`/`none` als netwerken, geen buildcache en geen images buiten de digest-allowlist;
9. start alleen als de vorige joblevenscyclus aantoonbaar terminaal én alle checks groen zijn opnieuw één `one-job --wait`-runner en ga naar `WAITING`; blijf anders `QUARANTINED`.

Het exitcodecontract is brongebonden: `runJob` retourneert het resultaat van de single-task-poller; bij een ontvangen taak roept die `runner.Run(...)` aan zonder jobresultaat als procesfout terug te geven en retourneert daarna `nil`. Een normaal afgeronde groene én rode workflow levert daarom procesexit `0`; de terminale Forgejo-jobstatus bepaalt het jobresultaat. Een non-zero exit duidt bij `--wait` op config-, initialisatie-, poller- of runtimefalen en is samen met een niet-correleerbare/niet-terminale job een runnerfout die na scrub tot `QUARANTINED` leidt. De max2-canary bewijst dit met zowel een bewust groene als een bewust rode testjob voordat de pool wordt geactiveerd.

Een geplande pause, rollback, reboot of service-stop gaat eerst naar `DRAINING` en verhindert dat de controller na de huidige cyclus opnieuw een runner start. Is de runner `RUNNING`, dan mag de job terminaal worden en volgt scrub. Is hij `WAITING`, dan stopt het proces graceful, wacht minimaal de geconfigureerde `fetch_timeout` plus tien seconden, bewijst dat het runnerrecord offline is en pollt Forgejo op runner-ID en recente jobstatus. Het nulbewijs vereist daarna twee opeenvolgende snapshots met tien seconden ertussen zonder assigned/running job. Dit sluit het FetchTask-ambiguïteitsvenster waarin de server een job kan hebben toegewezen voordat de runner het antwoord ontving.

Wordt toch een toegewezen job zonder lokaal proces gevonden, dan blijft de host gepauzeerd en `QUARANTINED`. Stap A legt de effectieve Forgejo Actions assignment-/requeue-timeout vast als `T_requeue`. De operator wacht maximaal `min(T_requeue + 30 seconden, 10 minuten)`. Kan `T_requeue` niet betrouwbaar worden vastgesteld, dan is de wachttak niet toegestaan. Is de job na de grens niet aantoonbaar gerequeued/terminaal, dan annuleert de operator de run en dispatcht dezelfde workflow vanaf dezelfde commit opnieuw volgens de vastgelegde migratiepolicy. Pas na een vastgelegd nulbewijs en scrub is de host veilig gepauzeerd of herstartbaar.

Een digest-gepinde canonieke jobimage is onveranderlijke uitvoerbasis en geen jobstate. Als pre-pull, scrub of bewijs faalt, blijft de host `QUARANTINED`; hij neemt geen job aan. Reguliere scrub duurt maximaal vijf minuten. Een overschrijding is een alert, quarantaint die host en reset de stabiliteitsperiode. Twee hosts kunnen na twee gelijktijdig voltooide jobs kort tegelijk scrubben; gedurende maximaal vijf minuten kan dan geen runner online zijn. Reeds gestarte jobs falen hierdoor niet en nieuwe jobs blijven in Forgejo in de wachtrij. Dit begrensde onderhoudsvenster is verwacht poolgedrag, geen onverwachte uitval.

De controller logt runner-ID, cyclusnummer, begin/eindtijd, toestand en geanonimiseerde tellingen, nooit namen of metadata die secrets kunnen bevatten. De eerste scrub van het bestaande `scrum4me-server`-volume is een expliciet onderhoudsvenster en mag langer duren wegens de huidige circa 121 GB inner-DinD-data; hij gebeurt pas als `max2` bewezen jobs kan overnemen en telt niet als een reguliere stabiliteitscyclus. Daarna krijgt de nieuwe stack een schoon, benoemd volume en pre-pullt de controller alleen de toegestane digest-images; de 121 GB ongecontroleerde state wordt niet naar het nieuwe actieve volume gekopieerd. Alle daaropvolgende scrubs vallen onder de vijfminutengrens.

## 8. Migratievolgorde

### Stap A — Bestaande installatie read-only vastleggen

Leg image-ID’s, manifestdigests, Compose-config, runnerconfig zonder secretwaarden, legacy `.runner`-metadata zonder tokenwaarde, volledige labels, global scope, netwerken, volumes en healthstatus vast. Noteer expliciet de huidige anonieme volume-ID en de omvang van de inner-DinD-data; die state wordt vóór uitfasering gescrubd maar niet naar het nieuwe benoemde volume gekopieerd. Inventariseer via Forgejo alle zichtbare runnerrecords met ID, naam, scope, versie, volledige labels voor zover beschikbaar, online/offline en busy/idle. Bepaal als eerste uit de effectieve Forgejo 15.0.2-configuratie en bijbehorende versiebron de Actions assignment-/requeue-timeout `T_requeue`, omdat die uitkomst de wachttak in §7.9 aan- of uitzet; als die niet aantoonbaar is, wordt de wachttak uit §7.9 uitgeschakeld. Leg op beide hosts NTP/chrony-synchronisatiestatus en de gemeten wandklokskew ten opzichte van de Forgejo-Date-header vast. Deze meting dient uitsluitend audit/corroboratie; `event_seq` blijft de enige vóór/na-fencebeslisser. Voer de trustscope-gate inclusief `.forgejo/workflows`/`.github/workflows`-fallback uit en leg de goedgekeurde allowlist vast.

Bewijs met een stub/testharnas alle vier readinessuitkomsten afzonderlijk: transport/5xx → `SOURCE_WAIT`; authprobe 401/403 → lokaal `CREDENTIAL_ERROR`; overige status/schemafout → lokale `QUARANTINED`; geldige 2xx-schema's → inhoudelijke trustgate. Test per foutklasse ook: de eerste afwijking zet alleen een informatief event plus schedulingfence en stopt een `WAITING` child; twee gelijke afwijkingen bevestigen de toestand; klassesprong herstart bevestiging; twee geldige probes plus nulbewijs en groene trustgate herstellen automatisch zonder directe runnerstart. Test met één geserialiseerde eventloop en kunstmatige logvertraging dat alleen `JOB_ACCEPTED/RUNNING.event_seq < fence_seq` vóór-latch is, dat remote/Forgejo-tijden nooit beslissen en dat unknown/late veilig naar cancel/scrub/redispatch gaat. Laat vervolgens een blijvende foutklassesprong en een blijvende valid/error-flap minimaal zestig seconden lopen en bewijs in beide gevallen de deadline, zwaarste-klassekeuze en het alarm. Test ook het gearmde onderhoudsrecord: gemengde startupklassen committen vóór algemene readiness alleen `SOURCE_WAIT`; na tweemaal geldige algemene readiness worden 401/protocol normaal bevestigd; na de harde eindtijd bestaat geen uitzondering. Bewijs daarnaast dat alleen een bevestigde harde inhoudelijke gatefailure een cross-hostquarantaine geeft. Verifieer dat de bestaande productiecontainers gezond zijn voordat iets wordt toegevoegd.

Draai een representatieve zwaarste workflow en meet iedere vijf seconden het piekgebruik van CPU, geheugen en PID's van runner en DinD plus `MemAvailable` van de host. Bereken daarna de caps volgens §7.8 en stop bij overschrijding van de hostheadroomgate. Leg tijdens diezelfde run de wandkloktijd per job vast als warme-cachebaseline voor §9.

Inventariseer daarnaast van `max2` het aantal vCPU's, het fysieke geheugen, de laagste `MemAvailable` onder eigen productielast en de vrije ruimte plus inodes op `DockerRootDir`, en voer de headroom- en preflightgates uit §7.8 op beide hosts uit. Stel ten slotte voor de repo's `scrum4me-server` en `max2` uit §6.1 per repo vast óf Actions is ingeschakeld. Neem alleen een aantoonbaar Actions-enabled repo als trusted scope op in `trusted-actions-scope.yml`; leg een repo met Actions uit daar expliciet vast als bekende niet-Actions-repo, zodat later inschakelen als drift zichtbaar wordt. Beide vastleggingen gebeuren vóór de eerste trustgate-run. Neem geen van beide repo's ongetoetst als Actions-enabled aan.

### Stap B — Gedeelde Runner 12-bundel maken

Maak de gedeelde bundel met Runner 12.10.1 en de exact werkende DinD-pin. Bevestig beide manifestdigests vanaf de registry, resolveer de canonieke jobimage naar de exacte registrydigest en leg die zowel in `labels.txt` als `allowed-job-images.txt` vast. Valideer Compose statisch, inclusief `restart: "no"` voor de runner, `restart: always` voor DinD en het expliciet benoemde volume `forgejo-runner-dind-data`, en scan de bundel op tokens, UUID’s, wachtwoorden en private sleutels. Valideer met de Runner 12.10.1-image dat exact één `server.connections`-verbinding, het absolute `token_url`, connection-labels en de letterlijke opdracht `one-job --wait` worden geaccepteerd zonder legacy `.runner`. Leg daarbij het hierboven beschreven broncontract voor de exitcode vast.

### Stap C — Tweede runner in Forgejo registreren

Maak `max2-forgejo-runner-02` aan op de bestaande global scope; dit is een bewust instancebreed besluit. Bewaar UUID in de lokale config en token uitsluitend in het lokale credentialbestand. Gebruik exact de canonieke labels.

### Stap D — Alleen `max2` uitrollen

Plaats de bundel, genereer een nieuwe Runner 12.10.1-connectionconfig zonder `.runner`, start de eigen DinD en activeer de cyclecontroller. Bewijs vóór de smoketest dat de `one-job --wait`-runner met het absolute tokenpad geauthenticeerd verbinding maakt en in Forgejo online staat. Wijzig of herstart geen bestaande productie-hostservice.

### Stap E — `max2` afzonderlijk bewijzen

Blokkeer eerst nieuwe jobtoewijzing aan de bestaande runner en wacht aantoonbaar tot deze idle is. Start pas daarna een uitsluitend voor deze test gemaakte smokeworkflow, zodat die aantoonbaar op `max2` landt. Timebox de onderbreking, herstel de bestaande runner direct en controleer zijn online-status. Bewijs Docker build/run, alle drie endpoints uit §7.5, DinD-isolatie, afwezigheid van hostlisteners en afwezigheid van toegang tot hostcontainers. Voer daarna op `max2` één bewust groene en één bewust rode testjob uit: beide moeten een terminale Forgejo-status, runnerprocesexit `0`, een groene scrub en terugkeer naar `WAITING` opleveren; alleen het workflowresultaat verschilt. Forceer tevens veilig vóór productieactivatie een ongeldige testconfig in een geïsoleerde validatieaanroep en bewijs dat non-zero niet heropent maar quarantaint. Laat na iedere test de fence uit §7.9 slagen voordat `max2` opnieuw jobs accepteert.

### Stap F — Poolgedrag bewijzen

Lees direct vóór de test opnieuw alle Forgejo-runnerrecords uit. De gate faalt tenzij uitsluitend de twee bedoelde records binnen de global scope online de relevante gedeelde labels aanbieden. Disable of herlabel ieder ander matchend runnerrecord vóór de test.

Met beide runners online en idle:

1. start twee identieke jobs gelijktijdig;
2. bewijs met runner-ID en job-URL dat iedere bedoelde runner één job krijgt;
3. drain runner 1 volgens §7.9 en leg het Forgejo-side nulbewijs voor assigned/running jobs vast;
4. pauzeer runner 1 en bewijs met een dedicated workflow uitvoering op runner 2;
5. herstel runner 1 en controleer online-status;
6. drain runner 2 volgens §7.9 en leg het Forgejo-side nulbewijs voor assigned/running jobs vast;
7. pauzeer runner 2 en bewijs met een dedicated workflow uitvoering op runner 1;
8. herstel runner 2 en controleer online-status;
9. laat na iedere testjob de fenced scrub op de uitvoerende runner slagen;
10. controleer dat productiecontainers en niet-testworkflows tijdens alle tests gezond blijven;
11. drain en reboot alleen `max2`; bewijs dat Docker en DinD terugkomen, `forgejo-runner-cycle.service` enabled/active wordt, `SOURCE_WAIT` en alle bootgates correct doorloopt en de controller zelfstandig `WAITING` bereikt terwijl `scrum4me-server` jobs blijft uitvoeren;
12. herstel en bewijs `max2` volledig; maak daarna het goedgekeurde change-record met unieke `maintenance_id`, UTC-start en harde UTC-eindtijd van maximaal dertig minuten en arm exact dit record op beide controllers. Drain alle jobs en reboot `scrum4me-server` uitsluitend binnen dat Forgejo/Postgres-onderhoudsvenster. Bewijs dat `max2` als host/controller gezond en niet-gequarantined blijft, zijn wachtende runner graceful stopt en zelfstandig naar `SOURCE_WAIT` gaat; claim geen nieuwe jobuitvoering zolang het Forgejo-control-plane onbereikbaar is. Na API-readiness moeten beide hosts hun readiness- en trustgates groen afronden, `scrum4me-server` en `max2` `WAITING` bereiken en een queued/nieuwe testjob moet op `max2` kunnen landen. Sluit/de-arm het maintenance-record expliciet; bij de harde eindtijd gebeurt dit automatisch en gelden normale alarmen.

### Stap G — Bestaande installatie normaliseren

Nu `max2` jobs kan overnemen, wordt `scrum4me-server` volgens §7.3 van legacy `.runner` naar dezelfde Runner 12.10.1-connectionconfig en cyclecontroller gebracht. Leg de oude anonieme DinD-volume-ID en de opnieuw gemeten dataomvang vast. Arm voor de eenmalige scrub een afzonderlijk maintenance-record met eigen `maintenance_id`, UTC-start en harde UTC-eindtijd; bepaal die eindtijd uit de actuele dataomvang plus een proefmeting op dezelfde storageklasse. Tijdens dit scrubrecord zijn alleen de §9-criteria voor maximale `SCRUBBING`-duur en tijd-tot-`WAITING` tijdelijk opgeschort voor `scrum4me-server`; trustgate, credential/protocol-classificatie, assignment-nulbewijs, geen-nieuwe-runner-tijdens-scrub en alle criteria voor `max2` blijven gelden. De-arm het scrubrecord expliciet na groen schoonbewijs; bij de harde eindtijd vervalt de uitzondering automatisch en gelden normale alarmen en stabiliteitsreset weer. Maak vervolgens een schoon benoemd `forgejo-runner-dind-data`-volume; kopieer de oude state niet en pre-pull alleen de toegestane digest-images. Roteer de credentials, verwijder secrets uit containermetadata en het actieve runnerpad, en voer dezelfde verificaties uit. De host-Dockerdaemon blijft draaien.

### Stap H — Stabilisatieperiode

Start een periode van zeven aaneengesloten dagen. De teller begint opnieuw na een poolgerelateerd incident of een configuratiewijziging.

## 9. Definitie van een stabiele pool

De pool is stabiel wanneer zeven aaneengesloten dagen aan alle criteria is voldaan:

- iedere hostcontroller bevindt zich in `WAITING`, `RUNNING`, een aantoonbaar geplande `DRAINING`, of een reguliere `SCRUBBING`-cyclus; `SOURCE_WAIT` is tijdens boot/bronuitval en uitsluitend binnen een op beide hosts gelijk gearmd, nog niet verlopen control-plane-maintenance-record toegestaan zonder stabiliteitsreset, maar telt daarbuiten en na de harde eindtijd na vijf minuten als availability-incident met reset van de stabiliteitsperiode; `CREDENTIAL_ERROR` en protocol-`QUARANTINED` zijn nooit onderhoudsuitzonderingen of stabiel; geen host blijft onverwacht langer dan vijf minuten zonder geldige toestand of in `SCRUBBING`;
- de normale per-job exit en herstart van de tijdelijke runnercontainer telt niet als restartincident; er zijn geen onverwachte runner-exits en de permanente DinD-container heeft niet meer dan twee onverwachte restarts binnen vijftien minuten;
- gelijktijdig `SCRUBBING` op beide hosts duurt maximaal vijf minuten; nieuwe jobs blijven dan aantoonbaar veilig queued en reeds geaccepteerde jobs zijn vóór de scrub voltooid;
- de een-host-tegelijk-reboottest is op beide hosts groen: DinD en de enabled controller komen automatisch terug; bij de centrale Forgejo/Postgres-uitval gaan beide hosts zonder cross-hostquarantaine naar `SOURCE_WAIT`; gates worden niet omzeild en beide bereiken na bronherstel `WAITING`;
- alle bestaande Forgejo-workflows die in de periode draaien zijn groen of hebben een aantoonbaar niet-runnergerelateerd falen;
- de tweevoudige paralleltest en failover in beide richtingen zijn groen;
- direct vóór iedere pooltest bieden uitsluitend de twee bedoelde runnerrecords de gedeelde labels online aan;
- er is geen bevestigde harde trustafwijking; zachte trustafwijkingen zijn gealarmeerd en binnen 24 uur beoordeeld; tijdelijke trustbron-onbeschikbaarheid is apart als availability-event geclassificeerd;
- geen jobcontainer is zichtbaar op de host-Dockerdaemon;
- geen hostlistener bestaat op TCP 2375 of 2376;
- geen actief token staat in Git, logs, `.runner` in het actieve runnerpad, `runner-config.yml`, `docker inspect` command of environment;
- het enige actieve tokenbestand is mode `0600`, eigendom van de effectieve runner-UID:GID en read-only gemount;
- `.runner` is afwezig uit het actieve runnerpad;
- het ingetrokken legacy quarantainebestand is `0600`, root-only, heeft een vastgelegde vernietigingsdatum en wordt uiterlijk na de rollbackperiode verwijderd;
- iedere voltooide job heeft vóór de volgende runnerstart een groene DinD-scrub; geen containers, volumes, niet-toegestane images, niet-standaardnetwerken of buildcache blijven achter en toegestane jobimages matchen exact de digest-allowlist;
- iedere geplande stop vanuit `WAITING` heeft vóór pause/reboot/rollback een vastgelegd Forgejo-side nulbewijs voor assigned/running jobs;
- geen host heeft een onopgeloste readiness-schedulingfence ouder dan zestig seconden; iedere deadline heeft buiten maintenance de zwaarste waargenomen foutklasse gecommit en gealarmeerd, of binnen het exact gearmde startupvenster uitsluitend `SOURCE_WAIT` gecommit;
- vrije ruimte op het Docker-datafilesystem blijft minimaal 20%;
- de productiecontainers op beide hosts ondervinden geen runnergerelateerde uitval;
- labels en gemeenschappelijke configuratie zijn byte- of canoniek-identiek: beide hosts draaien aantoonbaar dezelfde bundelcommit-SHA en dezelfde canonieke bundelhash volgens §6.1;
- de gemeten jobduur van de representatieve workflow blijft binnen 200% van de warme-cachebaseline uit stap A; een structurele overschrijding is geen storing, maar vereist vóór het stabiel verklaren van de pool een expliciet besluit over het cache- of CPU-throttlebeleid. Sinds delta-review R13 de CPU-limiet op het affordable budget zet in plaats van op 150% × piek (§7.8), is deze jobduurgrens tevens de prestatie-gate die bewijst dat de bewust afgeknepen CPU de job niet onaanvaardbaar vertraagt; die meting hoort daarom bij de max2-canary in stap D en E.

## 10. Monitoring

Meet op iedere host minimaal iedere vijf minuten:

- actuele controllerstaat `SOURCE_WAIT`, `CREDENTIAL_ERROR`, `WAITING`, `RUNNING`, `DRAINING`, `SCRUBBING` of `QUARANTINED`, plus leeftijd van die staat;
- status/leeftijd van de readiness-schedulingfence, eerste en zwaarste foutklasse, bevestigingsresultaat, deadlinekeuze en auto-recoverypogingen;
- laatste `event_seq`, `fence_seq`, lokaal geobserveerd jobacceptatie-sequence en eventuele conservatieve unknown/late-classificatie;
- actieve `maintenance_id`, UTC-start/eindtijd, armingsgelijkheid tussen hosts en resterende duur;
- onverwachte runner-exits, reguliere cycluscount en permanente DinD-restartcount; de normale `one-job`-exit wordt afzonderlijk geclassificeerd;
- duur van iedere scrub, aantal mislukte scrubs en tijd in `QUARANTINED`;
- DinD-health;
- CPU- en geheugengebruik tegen de ingestelde limieten;
- vrije bytes en inodes op DockerRootDir;
- runner online-status in Forgejo;
- volledige lijst van online runnerrecords die de gedeelde labels aanbieden;
- trustbron-readiness, lokale credential-/autorisatiefouten en lokale protocol/schemafouten afzonderlijk van bevestigde harde en zachte trustscope-drift voor repositories, effectieve workflowbron, workflowschrijvers, teams en PR/fork-policy;
- status en laatste succesvolle jobgebonden DinD-scrub;
- enabled/active-status van `forgejo-runner-cycle.service`, laatste bootgate-resultaat en tijd tot `WAITING` na host- of Dockerboot;
- laatste geplande drain en het bijbehorende Forgejo-side nulbewijs voor assigned/running jobs;
- jobwachttijd;
- jobduur per uitgevoerde job, afgezet tegen de warme-cachebaseline uit stap A;
- uitgerolde bundelcommit-SHA en canonieke bundelhash per host, plus de gelijkheid daarvan tussen beide hosts;
- gezondheid van de bestaande productiecontainers.

Registreer de eerste readinessafwijking alleen als informatief event met klasse en latchtijd. Waarschuw operationeel bij een bevestigde fouttoestand of een schedulingfence die buiten een geldig maintenance-startupvenster de zestigsecondenwatchdog bereikt, bij `SOURCE_WAIT` langer dan vijf minuten buiten een op beide hosts geldig gearmd control-plane-venster, bij `SOURCE_WAIT` na de harde UTC-eindtijd van dat venster, bij een ontbrekend/ongelijk/verlopen maintenance-record, iedere bevestigde `CREDENTIAL_ERROR` als lokale securitymelding, onbekende controllerstaat, ongeplande of te lange `DRAINING`, `SCRUBBING` langer dan vijf minuten buiten het afzonderlijke oude-volume-scrubrecord, ontbrekend post-stop-nulbewijs, een niet-enabled/inactieve cycle-unit buiten gepland onderhoud, iedere overgang naar `QUARANTINED`, een bevestigde harde trustafwijking, een zachte trustafwijking ouder dan 24 uur, DinD unhealthy, meer dan twee onverwachte DinD-restarts in vijftien minuten, minder dan 20% vrije ruimte of herhaalde resource throttling. Een normale `one-job`-exit, verwachte `SOURCE_WAIT` binnen een geldig control-plane-maintenance-record en een bewezen scrubvenster binnen het aparte oude-volume-scrubrecord geven geen restart- of offlinealarm en resetten de stabiliteitsperiode niet; na expiry doen ze dat wel volgens de normale criteria.

## 11. Rollback van fase 1

### Voor problemen op `max2`

Zet `forgejo-runner-cycle.service` eerst in `DRAINING`, wacht zo nodig tot een reeds geaccepteerde job is voltooid en leg het Forgejo-side nulbewijs voor assigned/running jobs vast. Stop en disable daarna de unit en verwijder alleen de nieuwe runner- en DinD-containers. Disable het nieuwe runnerrecord in Forgejo. Laat het expliciete volume `forgejo-runner-dind-data` staan voor onderzoek; verwijder het alleen later als afzonderlijk, goedgekeurd onderhoud. De oorspronkelijke runner blijft jobs uitvoeren.

### Voor problemen tijdens normalisatie van `scrum4me-server`

Laat `max2` online. Herstel de gepinde Runner 12.10.1-image, Compose-config, cyclecontroller en connectionconfig met het expliciete `forgejo-runner-dind-data`-volume. Gebruik nooit het ingetrokken oude token of de legacy `.runner`; maak een nieuw runnerrecord en credentialbestand aan als de vervangende registratie niet bruikbaar is. Het vastgelegde oude anonieme volume is alleen forensische rollbackdata en wordt niet opnieuw actief gekoppeld zonder een afzonderlijk herstelbesluit. Herstart alleen de runnerstack, niet de host-Dockerdaemon.

## 12. Fase 2 — rolling upgrade naar Runner 13

Fase 2 start alleen nadat fase 1 de stabiliteitsdefinitie haalt.

1. Vergelijk alle aangetroffen workflows met de breaking changes van Runner 13.
2. Maak een aparte Runner 13-config vanuit `generate-config`; hergebruik niet blind het Runner 12-schema, behoud exact één `server.connections`-verbinding en verifieer opnieuw dat de per-job `one-job --wait`-cyclus ondersteund is voordat Runner 13 een job mag aannemen.
3. Blokkeer nieuwe jobs op `max2`, wacht tot de Runner 12-instantie idle is en stop alleen die runner.
4. Vervang op `max2` de gedeelde labels tijdelijk door uitsluitend `runner13-canary`; het canaryrecord biedt geen enkel productielabel aan.
5. Controleer in Forgejo vóór de upgrade dat alleen `scrum4me-server` de gedeelde productielabels aanbiedt en alleen `max2` het canarylabel aanbiedt.
6. Upgrade alleen `max2` naar Runner 13, behoud de bewezen cycle/scrub-fence en voer alle representatieve workflows expliciet via `runs-on: runner13-canary` uit.
7. Observeer de canary minimaal 48 uur met herhaalde representatieve runs; gewone productiejobs kunnen in deze periode niet op `max2` landen.
8. Test rollback van `max2` naar de gepinde Runner 12.10.1-image en bijpassende config terwijl het record canary-only blijft; herstel daarna Runner 13 en herhaal de canarysmoke.
9. Zet pas na een groene canary de exact gedeelde labels terug, verwijder het canarylabel en bewijs in Forgejo dat beide runners opnieuw dezelfde labelset aanbieden.
10. Observeer Runner 13 op `max2` vervolgens 48 uur in de productiepool, terwijl Runner 12 op `scrum4me-server` de rollbackcapaciteit behoudt.
11. Drain `scrum4me-server`, upgrade die runner naar 13 en herstel hem met de gedeelde labels.
12. Herhaal parallelle verdeling, failover, DinD-isolatie en secretcontroles.
13. Behoud de gepinde Runner 12.10.1-image en config totdat beide Runner 13-instanties zeven dagen stabiel zijn.

Bij een Runner 13-regressie wordt alleen de betrokken host teruggezet op de gepinde Runner 12.10.1-image en bijpassende Runner 12.10.1-config. De andere runner blijft beschikbaar.

## 13. Review record

### Ronde 1 — 31 augustus 2026

**Reviewers:** `mac:codex` en `scrum4me-server:claude`  
**Verdicts:** Codex NO-GO; Claude NO-GO  
**Tellingen:** Codex 1 BLOCKER / 3 MAJOR / 1 MINOR; Claude 1 BLOCKER / 2 MAJOR / 3 MINOR

Geaccepteerd en verwerkt:

- Runner 13-canary is nu exclusief en biedt tijdens validatie geen gedeelde productielabels aan.
- Alle runnerrecords en matchende labels worden vóór registratie en vóór pooltests opnieuw geïnventariseerd.
- Pauze- en failovertests hebben nu een drain-, idle-, timebox- en herstelgate.
- Privileged DinD, de resterende hostkernel-blast-radius en de vereiste vertrouwensgrens zijn expliciet.
- Endpointgebruik is per netwerknamespace vastgelegd.
- De legacy `.runner`, zijn mode `0644`, zijn labelrol en de credentialblootstelling zijn expliciet opgenomen.
- De huidige volledige labels worden uit legacy `.runner` gehaald; het Forgejo-record met alleen bare labelnamen is geen imagebron.
- Resourcecaps volgen pas na representatieve piekmeting: geheugen als harde grens uit de gemeten piek plus marge, CPU op het host-affordable budget (throttlebaar) met de jobduur als prestatie-gate (§7.8, delta-review R13).
- Global scope is als bewust instancebreed besluit vastgelegd.
- Registry-digests worden vóór gebruik vanaf de registry gevalideerd.

Deels verworpen, met correctie van het onderliggende echte probleem:

- Claude stelde dat `server.connections.forgejo.{uuid,token}` uitsluitend een Runner 13-configvorm is en dat fase 1 daarom credentials in `.runner` moet bewaren. De officiële bron van de live versie weerspreekt dit: Runner 12.10.1 definieert `server.connections`, `uuid`, `token`, `token_url` en connection-labels in `internal/pkg/config/config.example.yaml` en `config.go`. `daemon.go` laadt deze config vóór legacy `.runner`; `registration.go` meldt terecht een conflict als beide verbindingen leveren. Ronde 2 moet dit bronbewijs adjudiceren. Het live defect zelf is wel bevestigd: de huidige installatie gebruikt legacy `.runner` mode `0644`. Revisie 2 migreert daarom expliciet naar Runner 12.10.1 `server.connections` met een afzonderlijk tokenbestand mode `0600` en verwijdert legacy `.runner` uit het actieve pad.

### Ronde 2 — 31 augustus 2026

**Reviewers:** `mac:codex` en `scrum4me-server:claude`  
**Verdicts:** Codex NO-GO; Claude NO-GO  
**Tellingen:** Codex 0 BLOCKER / 2 MAJOR / 1 MINOR; Claude 1 BLOCKER / 1 MAJOR / 2 MINOR

Adjudicatie:

- Beide reviewers bevestigen aan de hand van de officiële bron en de live v12.10.1-binary dat `server.connections`, `token_url` en connection-labels in Runner 12.10.1 werken. Claude trok zijn ronde-1-versieclaim expliciet in. De migratie weg van legacy `.runner` blijft staan.

Geaccepteerd en verwerkt in revisie 3:

- Het host- en containerpad voor het token zijn absoluut vastgelegd; `token_url` bevat geen ongedefinieerde `$CREDENTIALS_DIRECTORY` meer. Runtime-authenticatie is een gate vóór de smoketest.
- De geheugenheadroom gebruikt 50% van de laagste tijdens de representatieve run gemeten `MemAvailable`, niet 50% van fysiek RAM.
- De trustgrens van global privileged-DinD runners is een mechanische allowlist/gate geworden voor repos, workflow-schrijvers, teams, collaborators, Actions-, branch- en PR/fork-policy; drift zet de runners offline.
- Fase 1 staat geen persistente cross-job DinD-state toe. Iedere busy→idle-overgang voert een fenced volledige scrub uit; falen quarantaint de runner.
- De endpointmatrix noemt nu de exacte Runner 12.10.1- en Compose-configknoppen.
- De legacy quarantaine is niet langer `.runner` genaamd; stabiliteitscriteria onderscheiden actief token van een ingetrokken root-only rollbackbestand met vernietigingsdatum.
- De motivatie voor het verwijderen van `.runner` belooft geen specifieke foutmelding meer; alleen `server.connections` mag actief zijn.

### Ronde 3 — 31 augustus 2026

**Reviewers:** `mac:codex` en `scrum4me-server:claude`  
**Verdicts:** Codex NO-GO; Claude NO-GO  
**Tellingen:** Codex 1 BLOCKER / 1 MAJOR / 1 MINOR; Claude 0 BLOCKER / 2 MAJOR / 2 MINOR

Geaccepteerd en verwerkt in revisie 4:

- De busy→idle-meting en daaropvolgende stop hadden een assignmentrace. Een host-systemd-controller start nu per cyclus Runner 12.10.1 `one-job --wait`; na precies één volledig afgeronde job bestaat geen runnerproces tijdens de scrub en kan geen volgende job vóór groen schoonbewijs worden aangenomen.
- Workflowdiscovery verwerkt nu Forgejo's `.github/workflows`-fallback wanneer `.forgejo/workflows` ontbreekt, inclusief fail-closed gedrag bij ambiguïteit of onleesbaarheid.
- Monitoring en stabiliteit modelleren `WAITING`, `RUNNING`, `SCRUBBING` en `QUARANTINED`. Normale per-job procesexits zijn geen restartincident; scrubvensters zijn verwacht maar hard begrensd op vijf minuten.
- Het DinD-volume heet op iedere host expliciet `forgejo-runner-dind-data`; de bestaande anonieme volume-ID en de huidige circa 121 GB data worden vóór de eenmalige migratiescrub vastgelegd.
- Trustdrift is gesplitst in direct quarantainerende harde securityafwijkingen en zachte administratieve afwijkingen met een beoordelings-SLA van 24 uur.

Deels verworpen, met verwerking van de valide kern:

- Claude stelde dat een volledige inner-DinD-imagescrub ook de Runner- en DinD-images verwijdert en daarom onwerkbaar is. Die outer images staan in de hostdaemon en worden door de inner scrub niet geraakt. Het valide performancepunt voor de jobimage is wel verwerkt: de canonieke jobimage wordt registry-gevalideerd en op digest gepind; alleen exact toegestane jobimagedigests mogen de scrub overleven. Alle jobstate, lokaal gebouwde images en buildcache worden nog steeds verwijderd.

### Ronde 4 — 31 augustus 2026

**Reviewers:** `mac:codex` en `scrum4me-server:claude`  
**Verdicts:** Codex GO; Claude NO-GO  
**Tellingen:** Codex 0 BLOCKER / 0 MAJOR / 1 MINOR; Claude 0 BLOCKER / 2 MAJOR / 2 MINOR

Geaccepteerd en verwerkt in revisie 5:

- Boot-persistentie is nu een expliciet contract: DinD behoudt `restart: always`; de cyclecontroller is een enabled systemd-unit met Docker- en network-online-afhankelijkheden, bootgates en een boot-SLA van vijf minuten. Beide hosts krijgen na elkaar een echte rebootacceptatietest terwijl de andere host beschikbaar blijft.
- Een geplande stop vanuit `WAITING` gebruikt nu `DRAINING` en een Forgejo-side nulbewijs voor assigned/running jobs. Een ambigue FetchTask-toewijzing wordt niet als veilig gepauzeerd verklaard maar expliciet gequarantined, afgewacht of gecontroleerd geannuleerd en opnieuw gedispatcht.
- Exact één `server.connections`-verbinding is van een lokale cyclusstap naar een bindende architectuureis gepromoveerd en geldt ook voor Runner 13.
- De exacte `one-job --wait`-opdracht, groene/rode jobexit en non-zero-foutweg worden vóór poolactivatie getest.

Deels verworpen, met extra bewijs en testdekking:

- Claude classificeerde het exitcodecontract als onbekend en vreesde dat een rode workflow de host kan quarantainen. De officiële Runner 12.10.1-bron sluit dat normale pad: `runJob` retourneert `Poll()`; bij een ontvangen taak roept de single-task-poller `runner.Run(...)` aan zonder jobresultaat als procesfout terug te geven en retourneert daarna `nil`. Groen en rood eindigen dus beide met procesexit `0`; hun Forgejo-jobstatus verschilt. Revisie 5 legt dit broncontract vast en eist alsnog een bewust groene én rode canarytest. Non-zero blijft terecht een runner/config/poller/runtimefout.
- Claude kon `--wait` niet in tekenreeksen van de binary bevestigen. `internal/app/cmd/cmd.go` van tag v12.10.1 registreert de vlag letterlijk als `BoolVarP(..., "wait", "w", ..., "waits until task has been assigned")`. De exacte bron is nu naast de bestaande `job.go`-bron gelinkt en de letterlijke opdracht wordt gevalideerd.

### Ronde 5 — 31 augustus 2026

**Reviewers:** `mac:codex` en `scrum4me-server:claude`  
**Verdicts:** Codex GO; Claude NO-GO  
**Tellingen:** Codex 0 BLOCKER / 0 MAJOR / 0 MINOR; Claude 0 BLOCKER / 1 MAJOR / 1 MINOR

Geaccepteerd en verwerkt in revisie 6:

- Forgejo en Postgres draaien zelf op `scrum4me-server`; `docker.service=active` bewijst daarom nog geen bruikbare trustbron. De controller heeft nu `SOURCE_WAIT`, begrensde readinessbackoff en afzonderlijke algemene plus geauthenticeerde probes. Tijdelijke API-/database-onbereikbaarheid houdt alleen de opstartende host zonder runner en quarantaint `max2` nooit.
- Cross-hostquarantaine is beperkt tot een bereikbare, geauthenticeerde bron die de inhoudelijke trustgate bevestigd hard laat falen. Een transportfout, timeout of HTTP 5xx is een availability-event, geen gefingeerde securitybevinding.
- De sequentiële reboottest observeert expliciet Forgejo/Postgres-not-ready, bewijst dat `max2` zijn laatst goedgekeurde state behoudt en laat `scrum4me-server` pas na bron-readiness en een groene trustgate naar `WAITING` gaan.
- Stap A legt de effectieve Actions assignment-/requeue-timeout vast als `T_requeue`. Een ambigue assigned job wordt maximaal `min(T_requeue + 30 seconden, 10 minuten)` afgewacht; zonder aantoonbare `T_requeue` vervalt de wachttak en volgt gecontroleerde cancel+redispatch.

### Ronde 6 — 31 augustus 2026

**Reviewers:** `mac:codex` en `scrum4me-server:claude`  
**Verdicts:** Codex GO; Claude NO-GO  
**Tellingen:** Codex 0 BLOCKER / 0 MAJOR / 0 MINOR; Claude 0 BLOCKER / 1 MAJOR / 1 MINOR

Geaccepteerd en verwerkt in revisie 7:

- Readiness heeft nu een uitputtende vierwegclassificatie zonder defaultgat. Transport/5xx wordt `SOURCE_WAIT`; 401/403 op de authprobe wordt lokaal `CREDENTIAL_ERROR` met securityalarm; andere status/schemafouten worden lokaal `QUARANTINED`; alleen geldige 2xx-schema's openen de inhoudelijke trustgate. Alleen die laatste gate kan cross-hostquarantaine veroorzaken.
- `CREDENTIAL_ERROR` is een expliciete controllerstaat en staat afzonderlijk in stabiliteit en monitoring; herstel doorloopt altijd opnieuw readiness en de volledige trustgate. Credentials worden nooit gelogd.
- Bij centrale Forgejo-uitval maakt een reeds draaiende host zijn lopende job gecontroleerd af, stopt een wachtende runner graceful en start geen volgende runner. Beide hosts kunnen onafhankelijk naar `SOURCE_WAIT` gaan zonder elkaar te quarantainen en keren pas na bronherstel plus groene gates terug naar `WAITING`.
- De `scrum4me-server`-reboottest bewijst dit eenduidige gedrag; `SOURCE_WAIT` is gedurende het aangekondigde control-plane-venster verwacht en daarbuiten na vijf minuten een availability-incident.

### Ronde 7 — 31 augustus 2026

**Reviewers:** `mac:codex` en `scrum4me-server:claude`  
**Verdicts:** Codex GO; Claude NO-GO  
**Tellingen:** Codex 0 BLOCKER / 0 MAJOR / 0 MINOR; Claude 0 BLOCKER / 1 MAJOR / 0 MINOR

Geaccepteerd en verwerkt in revisie 8:

- Alle drie readinessfoutklassen hebben nu dezelfde tweewaarnemingendrempel. De eerste afwijking alarmeert en zet een `no-new-child`-latch; pas een tweede uitkomst van dezelfde klasse vijf seconden later bevestigt de fouttoestand. Een klassesprong herstart de bevestiging zonder de latch te openen.
- `SOURCE_WAIT`, `CREDENTIAL_ERROR` en lokale readiness-protocolquarantaine herproberen automatisch iedere dertig seconden. Herstel vereist twee geldige probes vijf seconden uiteen en daarna de volledig groene inhoudelijke trustgate; er is geen handmatige state-reset en er start nooit eerder een runner.
- Een blijvend werkelijk credential-/configuratieprobleem vraagt uiteraard een menselijke correctie, maar een tijdelijke 401/403 of malformed response kan aantoonbaar zelf herstellen zonder beide hosts permanent te parkeren.
- Het stub/testharnas verifieert per klasse de eerste latch, bevestiging, klassesprong, automatische recovery en de blijvende grens tussen lokale fout en cross-host inhoudelijke trustquarantaine.

### Ronde 8 — 31 augustus 2026

**Reviewers:** `mac:codex` en `scrum4me-server:claude`  
**Verdicts:** Codex NO-GO; Claude NO-GO  
**Tellingen:** Codex 1 BLOCKER / 1 MAJOR / 1 MINOR; Claude 0 BLOCKER / 1 MAJOR / 1 MINOR

Geaccepteerd en verwerkt in revisie 9:

- `no-new-child` was onvoldoende voor een reeds online `WAITING` child. De eerste afwijking zet nu een schedulingfence en gaat direct naar `DRAINING`; het wachtende child stopt meteen en moet het bestaande FetchTask-assignmentnulbewijs doorlopen. Alleen een aantoonbaar vóór-latch geaccepteerde job mag gecontroleerd eindigen; een op/na-latch assignment wordt gestopt, gecanceld/geredispatcht en gevolgd door scrub.
- De schedulingfence heeft een harde deadline van zestig seconden. Bij blijvende class-flap of valid/error-flap commit de controller deterministisch naar de zwaarste waargenomen klasse: lokale protocolquarantaine, daarna credentialfout, daarna availability.
- De stabiliteitsdefinitie verbiedt een onopgeloste fence ouder dan zestig seconden; monitoring bewaart leeftijd/zwaarste klasse/deadlinekeuze en alarmeert op bevestiging of deadline.
- De eerste afwijking is alleen een informatief event, geen operationeel alarm. Dit voorkomt ruis zonder de onmiddellijke schedulingfence los te laten.
- Het testharnas dekt nu blijvende foutklassesprong, blijvende valid/error-flap, deadline/klassekeuze en jobs die vóór versus op/na de latch zijn toegewezen.

### Ronde 9 — 31 augustus 2026

**Reviewers:** `mac:codex` en `scrum4me-server:claude`  
**Verdicts:** Codex GO; Claude NO-GO  
**Tellingen:** Codex 0 BLOCKER / 0 MAJOR / 0 MINOR; Claude 0 BLOCKER / 2 MAJOR / 0 MINOR

Geaccepteerd en verwerkt in revisie 10:

- Vóór/na-fence vergelijkt geen verschillende klokdomeinen meer. Eén lokale geserialiseerde controller-eventloop kent oplopende `event_seq` toe; alleen lokaal ontvangen `JOB_ACCEPTED/RUNNING.event_seq < fence_seq` geldt als vóór-latch. Unknown, buffered/late en remote-only bewijs gaat conservatief via cancel/scrub/redispatch.
- Monotone tijd blijft uitsluitend voor lokale deadlines; lokale wandklok plus gemeten NTP/skew zijn audit/corroboratie. De Forgejo-tijdlijn beslist nooit.
- Het geplande Forgejo/Postgres-venster wordt vooraf op beide hosts gearmd met unieke ID, UTC-start en harde eindtijd van maximaal dertig minuten. Het kan niet automatisch worden aangemaakt of verlengd.
- Zolang algemene readiness tijdens dit venster nog niet tweemaal geldig is, commit een deadline uitsluitend naar `SOURCE_WAIT`, ongeacht gemengde startupresponsen. Zodra algemene readiness terug is, gelden auth/protocolfouten weer normaal; na de harde eindtijd vervalt iedere uitzondering.
- Tests dekken geserialiseerde eventordering met logvertraging én mixed startupklassen, herstel, post-readiness auth/protocolfalen en maintenance-expiry.

### Ronde 10 (finale ronde) — 31 augustus 2026

**Reviewers:** `mac:codex` en `scrum4me-server:claude`  
**Verdicts:** Codex GO; Claude NO-GO  
**Tellingen:** Codex 0 BLOCKER / 0 MAJOR / 0 MINOR; Claude 0 BLOCKER / 1 MAJOR / 1 MINOR  
**Exact beoordeelde revisie:** 578 regels, SHA-256 `a9e2639738b96e475eb5e2978686b1b2c605ade8aff47264fb610c79c5469f5f`

Bevestigd gesloten:

- De vóór/na-fencebeslissing gebruikt uitsluitend lokaal geserialiseerde `event_seq`; klokskew en Forgejo-tijdlijn zijn niet beslissend.
- Het maintenance-record is vooraf gearmd, identiek op beide hosts, maximaal dertig minuten, niet automatisch verlengbaar en na algemene readiness niet langer een uitzondering voor auth/protocolfouten.
- Codex vond geen resterende BLOCKER, MAJOR of MINOR en beoordeelde alle eerdere remedies als behouden.

Resterend bij het bereiken van de harde rondecap:

- **MAJOR:** de algemene boot-SLA in §6 reset na vijf minuten nog onverkort de stabiliteitsperiode. Die regel verwijst niet naar het geldige maintenance-record en botst daardoor met het toegestane control-plane-venster van maximaal dertig minuten. Vereiste deltawijziging: binnen een geldig gearmd `maintenance_id`-venster mag boot-SLA-overschrijding informatief worden gelogd maar de stabiliteitsperiode niet resetten; buiten het venster en na hard expiry blijft de reset gelden. Spiegel dit in §9.
- **MINOR:** de eenmalige scrub van circa 121 GB oude DinD-data gebruikt nog een prozavenster in plaats van hetzelfde formele maintenance-record. Vereiste deltawijziging: apart vooraf gearmd record met een op de gemeten dataomvang gebaseerde harde eindtijd en expliciet benoemde tijdelijk opgeschorte §9-criteria.

Omdat ronde 10 de afgesproken bovengrens is en de finale verdicts niet beide GO zijn, is het ontwerp **niet goedgekeurd voor implementatie**. De twee deltawijzigingen mogen pas na een nieuwe, afzonderlijke delta-review met dubbele GO de status wijzigen.

### Revisie na rondecap 10 — verwerkt voor delta-review

Na het bereiken van de rondecap zijn uitsluitend de twee finale reviewfindings verwerkt:

- De boot-SLA in §6 en de stabiliteitsdefinitie in §9 gebruiken nu dezelfde regel: binnen een geldig, identiek gearmd en niet verlopen control-plane-maintenance-record is overschrijding informatief en reset zij de stabiliteitsperiode niet; buiten dat venster en na de harde UTC-eindtijd blijven availabilityalarm en stabiliteitsreset gelden.
- De eenmalige scrub van het oude anonieme DinD-volume in stap G gebruikt nu een afzonderlijk maintenance-record met eigen `maintenance_id`, UTC-start, harde UTC-eindtijd op basis van actuele dataomvang plus proefmeting, expliciet beperkte opschorting van §9-criteria en automatische terugval naar normale alarmen na expiry.

### Delta-review R11 — 31 augustus 2026

**Reviewers:** `mac:codex` en `scrum4me-server:claude`  
**Requests:** `e7fa0214-e4ac-447b-bda4-ecf2fdee30b0`, `60d9317f-36ee-49ec-9659-cc079a666ca9`  
**Replies:** `ecb01c04-b1fc-4a64-a1a9-d75b7d4b52ea`, `cc15265a-2ea4-4183-977e-d3e47005202c`  
**Beoordeelde revisie:** 605 regels, SHA-256 `5f91b8c1030276d8263a0bbeaa05eb84156fc077db654a9d1b0350c6654c6a79`  
**Verdicts:** Codex GO; Claude GO  
**Tellingen:** Codex 0 BLOCKER / 0 MAJOR / 0 MINOR; Claude 0 BLOCKER / 0 MAJOR / 0 MINOR

Beide reviewers bevestigden dat de ronde-10-MAJOR over boot-SLA versus maintenance-record en de ronde-10-MINOR over het oude DinD-volume-scrubrecord zijn opgelost. Beiden vonden geen regressie op de eerder gesloten Runner 12-poolcontracten.

### Revisie na R11 — verwerkt voor delta-review R12

Na de dubbele GO van R11 zijn zes post-GO-wijzigingen aangebracht. Zij wijzigen de status van het ontwerp pas na een nieuwe delta-review met GO.

1. **Versiebeheer en distributie (nieuw §6.1).** De "gedeelde, versiebeheerde bundel" had geen benoemde bron, geen distributiemechanisme en geen driftgate, terwijl §4 en §9 byte-identieke bundels eisen. De bundel is nu canoniek in de `scrum4me-server`-repo; `max2` is host-overlay zonder kopie. Beide hosts rollen uit vanaf dezelfde commit-SHA, `verify-stack.sh` vergelijkt commit-SHA en canonieke bundelhash tussen de hosts, en §9 en §10 verwijzen daarnaar. Ook vastgelegd: pre-commit secret-scan, geen deployment via Forgejo Actions (jobs kunnen de hoststack per ontwerp niet raken), en opname van beide repo's in `trusted-actions-scope.yml` vóór de eerste trustgate-run.
2. **Headroomgate op beide hosts (§7.8, stap A).** De caps waren afgeleid uit een meting op `scrum4me-server`, golden gelijk op beide hosts, maar werden alleen op `scrum4me-server` gegate't; `max2`-hardware werd nergens vastgelegd en `preflight.sh` had geen criteria. `max2` wordt nu geïnventariseerd en `preflight.sh` heeft expliciete drempels voor vCPU, geheugen, vrije ruimte en inodes. Lagere caps op alleen `max2` blijven verboden.
3. **Controller in Python (§6, §7.9).** De toestandsmachine met geserialiseerde eventloop, `event_seq`, schedulingfence, bevestigingsdrempel en deadlinewatchdog is als shellscript niet betrouwbaar te bouwen. De controller is nu `scripts/forgejo_runner_cycle.py`; het stub-/testharnas uit stap A is zijn unittestsuite en een stap-A-gate. Overige scripts blijven shell.
4. **Quarantaine is convergent, niet gecommandeerd (§6, §7.7).** De tekst impliceerde op één plek een quarantaineopdracht van host naar host terwijl geen kanaal, authenticatie of faalmodus was beschreven. Vastgelegd is nu dat er geen kanaal bestaat en er ook geen komt: beide controllers oordelen onafhankelijk over dezelfde bron. Het resterende gevolg — een instancebrede trustbevinding is een gemeenschappelijke faalmodus die de hele pool stilzet — is expliciet aanvaard.
5. **Eerlijke variabelentelling en cacheregressie (§2, §7.8, §9, §10, stap A).** De claim dat fase 1 "slechts één hoofdeigenschap" verandert klopte niet: registratiemodel, levenscyclus, stateretentie, caps, digest-pinning en trustgate wijzigen tegelijk. De onderbouwing verwijst nu naar de gefaseerde volgorde van §8. Omdat de scrub de cache verwijdert waarop de huidige circa 121 GB DinD-state wijst, is jobduur toegevoegd als baselinemeting in stap A, als stabiliteitscriterium in §9 en als monitoringmeetpunt in §10.
6. **Redactioneel.** De dubbele kop `## 14. Acceptatie van dit ontwerp` is opgelost; delta-review R11 staat nu waar hij hoort, in het Review record. `T_requeue` wordt in stap A expliciet als eerste bepaald omdat de uitkomst een hele tak in §7.9 aan- of uitzet.

### Delta-review R12 — ronde 1 van maximaal 5 — 31 augustus 2026

**Reviewer:** `mac:codex` — enige reviewer; de delta-variant gebruikt één reviewer uit de modelfamilie die de wijzigingen niet schreef.
**Request:** `7cce63dd-de1a-4264-bf0e-3bbfbf17716c` — **Reply:** `7fe0bed9-8e07-4a27-96fa-08ec512cd2cf`
**Beoordeelde revisie:** 677 regels, commit `d718f6a`, SHA-256 `610d0daaf30d64b2823e67f3f6f76f02bd26c993541dd0e8a95fe2edee9df529`
**Verdict:** NO-GO — 0 BLOCKER / 1 MAJOR / 0 MINOR

Wijziging 2 tot en met 6 hielden stand: headroomgate op beide hosts, Python-controller, convergente quarantaine, eerlijke variabelentelling met jobduurbaseline, en de redactionele fixes inclusief `T_requeue`.

**MAJOR, geaccepteerd en nagemeten tegen de boom:** §6.1 verwarde doelstructuur met de as-built repo's. De tabel beschreef in tegenwoordige tijd een `forgejo-runner/`, `hosts/scrum4me-server/`, `hosts/max2/` en `evidence/` die op respectievelijk commit `d718f6a` en `922e84c` niet bestaan, en de bullets claimden een draaiende pre-commit secret-scan plus een `.gitignore`-regel `/opt/forgejo-runner/credentials/`. Zelf nagemeten met `git ls-tree -r --name-only HEAD` en `ls .git/hooks`: beide repo's bevatten alleen `README.md`, `CLAUDE.md`, `.gitignore` en in `scrum4me-server` de documenten; in geen van beide staat een geïnstalleerde hook, alleen `pre-commit.sample`; de `.gitignore` negeert `credentials/` en niet het genoemde hostpad, dat in een repo-`.gitignore` ook niet thuishoort.

Verwerkt in revisie 12b: §6.1 is nu expliciet een doelstructuur met een kolom "bestaat nu" en de stap waarin ieder onderdeel ontstaat. De doorlopende secret-scan is een stap-B-gate geworden met een verplicht blokkeringsbewijs, en het ontwerp mag pas ná dat bewijs beweren dat de scan draait. De niet-geverifieerde bewering dat beide repo's Actions-enabled zijn is vervangen door een stap-A-vaststelling.

### Delta-review R12 — ronde 2 van maximaal 5 — 31 augustus 2026

**Reviewer:** `mac:codex`
**Request:** `db6766ed-889e-4161-b86c-3190c14f48cd` — **Reply:** `6a6c8efa-a3b5-47d1-9c36-f794acc8f7a0`
**Beoordeelde revisie:** 695 regels, commit `4a4df16`, SHA-256 `cf3a683e982dfac8fbb80b91ddd6b9f403cabb520ff47d8d376005ef357fcf22`
**Verdict:** NO-GO — 0 BLOCKER / 1 MAJOR / 0 MINOR
**Oordeel over de ronde-1-MAJOR:** partially held — de verwarring tussen doelstructuur en as-built boom en de niet-bestaande hookclaim zijn gesloten; de bijbehorende Actions-aanname niet.

**MAJOR, geaccepteerd en nagemeten:** §6.1 stelde na de ronde-1-fix dat stap A per repo vaststelt óf Actions is ingeschakeld, maar stap A zelf droeg de oude aanname nog: "Neem ten slotte de repo's `scrum4me-server` en `max2` uit §6.1 als Actions-enabled repositories op in `trusted-actions-scope.yml`." Zelf nagemeten op regel 144 tegenover regel 352 van commit `4a4df16`: de twee passages spraken elkaar tegen. Een implementator die stap A letterlijk volgt legt beide repo's als Actions-enabled vast zonder bewijs, wat juist het trustbewijs verzwakt dat global runner-activatie gate't. Dit is de klassieke restfout: de bewering was op één plek gecorrigeerd en op de andere blijven staan.

Verwerkt in revisie 12c: §6.1 en stap A gebruiken nu dezelfde regel. Stap A stelt per repo vast óf Actions is ingeschakeld; alleen een aantoonbaar Actions-enabled repo komt als trusted scope in `trusted-actions-scope.yml`, en een repo met Actions uit wordt daar expliciet als bekende niet-Actions-repo vastgelegd zodat later inschakelen als drift zichtbaar wordt. Stap A verbiedt expliciet het ongetoetst aannemen van Actions-enabled.

### Delta-review R12 — ronde 3 van maximaal 5 — 31 augustus 2026

**Reviewer:** `mac:codex`
**Request:** `c61d0e45-548f-4e72-8097-3e076aab5199` — **Reply:** `f6ca262c-6fae-40c9-88b3-88ca2d435b4c`
**Beoordeelde revisie:** 707 regels, commit `182de44`, SHA-256 `12e44b67e6be938cc67ef944d7f5c96d62826f905a31f3e3feef45f319dc4e13`
**Verdict:** GO — 0 BLOCKER / 0 MAJOR / 0 MINOR
**Oordeel over de ronde-2-MAJOR:** held.

Geen resterende bevindingen. De reviewer bevestigde dat §6.1 en stap A dezelfde Actions-regel hanteren en vond geen derde normatieve plek waar de oude aanname voortleeft. Daarmee is delta-review R12 gesloten met GO in ronde 3 van maximaal 5; beide MAJORs uit ronde 1 en 2 waren volledig geaccepteerd en er is in deze loop geen bevinding afgewezen.

### Delta-review R13 — caps-methodiek (§7.8, §9) — 1 september 2026

**Reviewer:** `mac:codex` (delta-variant: één reviewer, cross-model naar de auteur; de wijziging is claude-authored).
**Aanleiding:** de stap-A-meting (Task 7–9 van het implementatieplan) toonde dat §7.8's regel "150% van de gemeten piek" voor CPU structureel faalt bij parallelle-test-CI. Een representatieve `vitest run` (scrum4me-workers `ci.yml`, run 2521) piekte gemeten 742% (7,4 van 8 cores) op `scrum4me-server`, waardoor 150% × piek ≈ 11,5 vCPU de acht fysieke cores overschreed en de headroomgate op **beide** hosts ROOD ging. Bewijs: `docs/forgejo-runner-pool/evidence/stap-a/caps.md`, `caps.env`, `workload-scrum4me-server.tsv`, `host-facts-*.tsv`.
**Wijziging:** §7.8 behandelt geheugen en CPU voortaan gescheiden — geheugen is een harde grens (limiet = piek + marge, som binnen 50% van de laagste `MemAvailable`), CPU is throttlebaar (limiet op het host-affordable budget van 50% van de laagste vCPU's, niet 150% × piek). De jobduur (§9, binnen 200% van de warme baseline, gemeten in stap D/E met de gecapte DinD) wordt de CPU-prestatie-gate in plaats van de CPU-piek. PID's houden de 150%-regel. De samenvattingstabel (§Resourceprofiel) en de ontwerpbeslissing over resourcecaps zijn meegetrokken.
**Ronde 1 (`mac:codex`, request `3de16a33-6884-4b2d-bd50-3cdefc7a7140`, reply `0ec4e6b5-b1f9-4982-9b01-ac82d461364e`): NO-GO — 1 BLOCKER / 1 MAJOR / 0 MINOR.** Beide bevindingen zelf tegen de boom nagemeten en **bevestigd**:

- **BLOCKER — de nieuwe formule blijft ROOD op de eigen meting.** De ondergrenzen alléén overschrijden de headroom: DinD-mem = max(4 GiB floor, 3,174 GiB piek + 512 MiB) = 4 GiB (floor wint); runner-mem = max(1 GiB floor, 28,6 MiB + 256 MiB) = 1 GiB (floor wint); som = 5,000 GiB > 50% × 8,644 GiB = 4,322 GiB, over met 0,678 GiB. De CPU-throttle-delta lost de CPU-false-negative op, maar het echte knelpunt is **geheugen**, en dat blijft een NO-GO. De reviewer eist: markeer R13 als echte NO-GO die een hardware-/headroom-/workloadbesluit vergt, óf wijzig de geheugensemantiek (DinD-floor vs 50%-`MemAvailable`) met JP-akkoord — niet accepteren zolang de formule ROOD rekent.
- **MAJOR — het uitvoerpad codeert nog de oude 150%-regel.** `compute_caps.py`, `test_compute_caps.py`, `caps.md` en `caps.env` implementeren/exporteren nog `max(floor, 150% × piek)` (DIND_CPU=11,5, DIND_MEM=5 GiB); de reviewer draaide de 7 tests groen als bewijs dat de oude regel het actieve contract is. Zonder bijwerken óf een expliciete R13-hardstop dat die artefacten verouderd zijn, regenereert de volgende worker de oude rode caps (execution hazard voor Task 9/10/16).

**Uitkomst:** geëscaleerd naar JP. De BLOCKER-fix is een besluit (hardware/headroom/workload/geheugensemantiek), geen doc-edit; ronde 2 wacht op JP's richting. Deze delta is **niet** geaccepteerd; §7.8 blijft tot een besluit in de herziene-maar-nog-niet-goedgekeurde staat.

## 14. Acceptatie van dit ontwerp

Dit ontwerp kreeg dubbele GO voor de delta-review na rondecap 10 (R11). De route is daarmee goedgekeurd: eerst een stabiele Forgejo Runner 12.10.1-tweemachinepool op `scrum4me-server` en `max2`, daarna pas een afzonderlijke rolling Runner 13-fase.

De zes post-GO-wijzigingen uit "Revisie na R11" — repo-tracking en versiebeheer, headroomgate op beide hosts, Python-controller, convergente quarantaine, eerlijke variabelentelling met jobduurbaseline, en redactionele fixes — zijn beoordeeld in delta-review R12 en kregen GO in ronde 3. Commit `182de44` van de canonieke repo is daarmee de goedgekeurde revisie.

Productie-uitvoering zelf is nog niet gestart. De volgende stap is een uitvoerbaar implementatieplan met exacte read-only inventarisatiecommando's, bestandsinhoud, deploymentcommando's, gates, testworkflows en rollbackcommando's.
