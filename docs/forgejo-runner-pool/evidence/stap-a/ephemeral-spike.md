# Ephemeral-spike

Instance: https://git.jp-visser.nl

Canary-label: `ephemeral-spike-20260831`

## 1. Registratie accepteert `ephemeral: true`

- record-id: `4`
- uuid: `f9971e6e-2e02-4de5-8385-175a6b322777`
- respons bevatte een token: ja (waarde bewust niet vastgelegd)

## 2. Het record toont ephemeral en draagt geen labels

```json
{
  "description": "stap-A ephemeral spike",
  "ephemeral": true,
  "id": 4,
  "labels": null,
  "name": "ephemeral-spike-20260831",
  "owner_id": 0,
  "repo_id": 0,
  "status": "offline",
  "uuid": "f9971e6e-2e02-4de5-8385-175a6b322777",
  "version": ""
}
```

## 3. Opruimen

Record `4` is verwijderd; een GET erop geeft geen record meer terug.

## 4. Subcommando's van de runner:12-image (max2)

Getoetst read-only in een wegwerpcontainer op `max2`, zonder registratie:

```
ssh janpeter@max2 'docker run --rm --entrypoint forgejo-runner \
  code.forgejo.org/forgejo/runner:12 --help'
```

Beschikbare subcommando's: `cache-server`, `create-runner-file` (deprecated),
`daemon`, `exec`, `generate-config`, `help`, `one-job`, `register` (deprecated),
`validate`. **`one-job` bestaat** — geen BLOCKER voor het ontwerp; dit is tevens de
eerste bevestiging van de `one-job --wait`-opdracht die Task 17 hard hervalideert.

### Bijvangst: mutable-tag drift tussen de twee hosts (bevinding)

De pull van `code.forgejo.org/forgejo/runner:12` op `max2` leverde manifestdigest
`sha256:eb6e7bc21973382d261e6eb883dbd27b8cb56939d33a3bfd79a1352b7f9a33a0`.
De reeds draaiende image op `scrum4me-server` (Task 2, images.json) heeft RepoDigest
`code.forgejo.org/forgejo/runner@sha256:3d49075f9115054ae2485d8cea2819296a904dfd4f00017285168028615d8533`.

Dezelfde tag `:12`, twee verschillende digests: de hosts zouden onder één tag
verschillende runner-binaries draaien. Dit is een live bevestiging van waarom §7 en
stap B (Task 16) op **digestniveau** pinnen in plaats van op de tag. Task 16 moet de
canonieke digest vanaf de registry resolven en beide hosts vanaf diezelfde digest
uitrollen; deze meting laat zien dat "gewoon `:12`" niet reproduceerbaar is.

## 5. De afweging (geen aanbeveling — besluit is voor de delta-review)

### Wat gemeten is
- Registratie met `ephemeral: true` wordt geaccepteerd (record id 4, respons bevatte
  een token). Het teruggelezen record toont `ephemeral: true` en is **labelloos**
  (`labels: null`), global scope, status `offline` (er verbond geen daemon). Het record
  is daarna verwijderd; de vóór/na-telling van de recordlijst is identiek.
- Niet hier gemeten (vereist een echte job): dat Forgejo een ephemeral runner hooguit
  één job toewijst en het record daarna zelf verwijdert. Dat wordt een extra assertie in
  stap E op `max2`.
- De runner:12-image biedt `one-job`; `daemon` bestaat eveneens. De tag `:12` drift
  aantoonbaar tussen de hosts (zie §4).

### Wat ephemeral zou toevoegen
Server-side afdwinging dat een **gelekt runnertoken geen volgende job kan opvragen**:
Forgejo verwijdert het record na één job. Dat is direct relevant omdat §7.6 een
privileged DinD met global scope naast productie accepteert en het ontwerp zwaar op
tokenhygiëne (§7.3) leunt; ephemeral verplaatst een deel van die garantie van
client-side discipline naar de server.

### Wat het kost
Een ephemeral record wordt na één job door het systeem verwijderd, dus de
cyclecontroller moet **elke cyclus opnieuw registreren** met een registratietoken. Dat
raakt:
- **§7.3** — tokenhygiëne verandert van één stabiel runnertoken naar een
  registratietoken dat elke cyclus wordt gebruikt (nieuw sleutelbeheer, nieuwe
  faalmodi).
- **§7.4** — de gate "alleen de twee bedoelde records bieden de gedeelde labels aan"
  wordt **dynamisch** in plaats van statisch: records komen en gaan per cyclus, dus het
  nulbewijs en de recordinventarisatie moeten met een bewegend doel omgaan.

Wat het **niet** oplost: het FetchTask-ambiguïteitsvenster bij een drain blijft bestaan.
Het assignment-nulbewijs uit §7.9 en de schedulingfence uit §7.7 blijven dus onverkort
nodig, ephemeral of niet.

## Besluit (JP, 2026-08-31)

Ephemeral wordt **niet** opgenomen: het GO'de ontwerp met persistente records en de
client-side fence blijft leidend. Deze spike blijft als bewijs bewaard en kan later
heropend worden als de server-side token-leak-garantie dat waard blijkt. Er komt niets
ephemeral-gerelateerds in de bundel. (Besluit vastgelegd na de meting; de afweging
hierboven bleef bewust zonder aanbeveling.)
