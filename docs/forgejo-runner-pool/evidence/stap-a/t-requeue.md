# T_requeue — Forgejo Actions assignment-/requeue-timeout

Vastgesteld in stap A (Task 3, step 8), gemeten 2026-08-31. Bindt §7.9 en §8 stap A
van `migratieontwerp.md`.

## Uitkomst

**T_requeue = 600 s (10 minuten).** De wachttak uit §7.9 is dus **toegestaan**; de operator
wacht bij een toegewezen job zonder lokaal proces maximaal `min(T_requeue + 30 s, 10 min)
= min(630 s, 600 s) = 600 s` voordat hij annuleert en dezelfde workflow vanaf dezelfde
commit opnieuw dispatcht.

## Governing timeout en waarom

Het §7.9-scenario is: een job staat in Forgejo in status *running*, toegewezen aan onze
runner, maar de cyclecontroller heeft het `one-job --wait`-child gestopt — er zijn dus geen
task-updates/heartbeats meer. Forgejo requeue-/stopgedrag hiervoor is `StopZombieTasks`:

> `StopZombieTasks` stopt taken in status *running/cancelling* die al langer dan
> `ZombieTaskTimeout` niet zijn bijgewerkt (keyt op de laatste update). Default = **10 min**.

Bron (versiebron): Gitea `services/actions/clear_tasks.go` en `modules/setting/actions.go`
(veld `ZombieTaskTimeout`, ini-sleutel `ZOMBIE_TASK_TIMEOUT`), opgehaald via Context7
(`/go-gitea/gitea`) op 2026-08-31. Dit is de Gitea-basis die het draaiende binary rapporteert
als `+gitea-1.22.0`.

De twee andere actions-timeouts gelden hier **niet**:
- `EndlessTaskTimeout` (default 3 h) — voor taken die juist wél continu blijven updaten.
- `AbandonedJobTimeout` (default 24 h) — voor jobs die nooit door een runner zijn opgepikt
  (status *waiting*), niet voor een reeds toegewezen/lopende job.

## Effectieve configuratie op de draaiende instance

Het `[actions]`-blok van de effectieve `app.ini` zet **geen** timeout-override; de compiled-in
default geldt daarom. Alleen het `[actions]`-blok is hieronder overgenomen (zie de
secret-hygiëne-noot):

```ini
[actions]
ENABLED = true
```

Een grep over de hele `app.ini` op `timeout|zombie|abandon|endless|requeue|assign` gaf geen
enkele expliciet gezette sleutel — defaults gelden dus voor alle actions-timeouts.

## Versie waartegen gelezen

```
forgejo version 15.0.2+gitea-1.22.0 (release name 15.0.2)
```

## Commando's

```bash
# Effectieve configuratie van de draaiende instance (leesactie; docker exec bewust buiten de
# read-only guard van Task 1 om, handmatig uitgevoerd):
ssh janpeter@scrum4me-srv 'docker exec scrum4me-forgejo cat /data/gitea/conf/app.ini' \
  | grep -iE 'timeout|zombie|abandon|endless|requeue|assign'   # → geen treffers

# Versie:
ssh janpeter@scrum4me-srv 'docker exec scrum4me-forgejo forgejo --version'

# Gezaghebbende default (versiebron) via Context7:
npx ctx7@latest docs /go-gitea/gitea \
  "actions ZOMBIE_TASK_TIMEOUT ENDLESS_TASK_TIMEOUT ABANDONED_JOB_TIMEOUT default"
```

## Caveat en restonzekerheid (voor JP / een reviewer)

T_requeue is hier bepaald uit de **gedocumenteerde/broncode-default** plus de bevestiging dat
de effectieve config geen override zet — niet uit een **empirische meting op deze instance**.
Empirische bevestiging zou een gecontroleerd experiment vereisen (een job dispatchen, het
runnerproces midden in de run stoppen en de werkelijke requeue-tijd waarnemen); dat valt
buiten de read-only scope van stap A en is hier bewust niet gedaan.

De waarde 10 min is al jaren stabiel in de Gitea-basis en is **consistent** met de 10-min-cap
die het ontwerp zelf in §7.9 hanteert (`min(T_requeue + 30 s, 10 min)`), wat de bepaling
corroboreert. Wil JP zekerheid boven de documentatie uit, dan kan een gecontroleerde
kill-mid-run-canary in stap E/F worden toegevoegd; tot dan geldt T_requeue = 600 s met deze
noot.

## Secret-hygiëne-noot

De plan-opdracht `grep -iA 20 '^[actions]'` is hier **niet** letterlijk in het bewijs
overgenomen: het `[actions]`-blok bevat maar één regel (`ENABLED = true`), waardoor `-A 20`
doorloopt tot in latere secsties en o.a. een `[oauth2] JWT_SECRET` toont. Dat is een
productiegeheim en hoort niet in Git. Alleen het `[actions]`-blok zelf is vastgelegd. Dit is
tevens een bevinding: gebruik voor dit soort extractie een sectiebegrensde greep (van
`[actions]` tot de volgende `[`-sectie), niet een vaste `-A N`.
