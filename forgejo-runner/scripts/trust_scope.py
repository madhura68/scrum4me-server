# forgejo-runner/scripts/trust_scope.py
"""Trustscope-inventarisatie en -classificatie volgens 7.7 van het migratieontwerp.

Fail-closed: alles wat niet ondubbelzinnig uitleesbaar is, telt als onleesbaar
en maakt het oordeel rood. De module doet zelf geen netwerk-IO; de client wordt
ingespoten, zodat de tests geen echte instance nodig hebben.
"""

import re
from dataclasses import dataclass, field

RISKY_TRIGGERS = ("pull_request_target", "pull_request", "workflow_run")
FORGEJO_WORKFLOWS = ".forgejo/workflows"
GITHUB_WORKFLOWS = ".github/workflows"
WORKFLOW_SUFFIXEN = (".yml", ".yaml")


class Unreadable(Exception):
    """Een object bestaat mogelijk wel maar is niet ondubbelzinnig te lezen."""


@dataclass
class Verdict:
    hard: list = field(default_factory=list)
    soft: list = field(default_factory=list)
    unreadable: list = field(default_factory=list)
    # Risicovolle kruisingen die JP per repo expliciet heeft bevestigd
    # (risky_triggers_acknowledged). Aanvaard restrisico, geen harde afwijking;
    # blokkeert de gate niet, maar wordt apart geregistreerd voor de audit (§7.7).
    accepted: list = field(default_factory=list)

    @property
    def ok(self):
        return not self.hard and not self.unreadable


def _workflow_source(client, full_name):
    """Forgejo gebruikt .forgejo/workflows en valt anders terug op .github/workflows."""
    for path in (FORGEJO_WORKFLOWS, GITHUB_WORKFLOWS):
        listing = client.contents(full_name, path)
        if listing is None:
            continue    # map bestaat niet; probeer de fallback
        _eis_lijst_van_dicts(listing, f"{full_name}:{path}")
        if listing:
            return path, listing
    return None, []


BEKENDE_TEAMROLLEN = ("none", "read", "write", "admin", "owner")


def _eis_lijst_van_dicts(waarde, context):
    """Valideert de vorm van een externe responscollectie vóór iteratie.

    Zonder deze check levert een dict waar een lijst wordt verwacht een
    `AttributeError` op in plaats van een auditeerbare `Unreadable`, en een
    lege dict voor een workflowmap zou als "map afwezig" worden gelezen en de
    fallback aansturen in plaats van het ongeldige schema rood te maken.
    """
    if not isinstance(waarde, list):
        raise Unreadable(f"{context}: geen lijst maar {type(waarde).__name__}")
    for item in waarde:
        if not isinstance(item, dict):
            raise Unreadable(f"{context}: item is geen object maar {type(item).__name__}")
    return waarde


def _valideer_repo(repo):
    """Fail-closed validatie van de repository-objectvorm.

    Een ontbrekend veld is geen "nee" maar een onvolledige meting. Zonder deze
    check zou een ontbrekende `has_actions` de hele inspectie overslaan en een
    ontbrekende `owner.login` de meest bevoorrechte identiteit onzichtbaar maken.
    """
    naam = repo.get("full_name")
    if not naam:
        raise Unreadable("repository zonder full_name in de zoekrespons")
    if not isinstance(repo.get("has_actions"), bool):
        raise Unreadable(f"{naam}: has_actions ontbreekt of is geen boolean")
    if not (repo.get("owner") or {}).get("login"):
        raise Unreadable(f"{naam}: owner.login ontbreekt")
    if not repo.get("default_branch"):
        raise Unreadable(f"{naam}: default_branch ontbreekt")
    return naam


def _decodeer(entry):
    """Leest de inhoud van een ContentsResponse. Alles wat niet ondubbelzinnig
    te decoderen is, is onleesbaar en dus fail-closed."""
    import base64
    inhoud = entry.get("content")
    if inhoud is None:
        raise Unreadable(f"{entry.get('path')}: geen content in de respons")
    if "encoding" not in entry:
        # Een ontbrekend veld is iets anders dan "ondubbelzinnig platte tekst".
        # Base64 die als platte tekst wordt gescand bevat geen triggernamen en
        # zou de repository ten onrechte schoon verklaren — onder-detectie is
        # precies de gevaarlijke faalrichting.
        raise Unreadable(f"{entry.get('path')}: encoding-veld ontbreekt")
    codering = (entry.get("encoding") or "").lower()
    if codering == "base64":
        try:
            return base64.b64decode(inhoud).decode("utf-8", errors="strict")
        except Exception as exc:
            raise Unreadable(f"{entry.get('path')}: base64 niet te decoderen: {exc}") from exc
    if codering in ("", "utf-8", "plain"):
        return inhoud
    raise Unreadable(f"{entry.get('path')}: onbekende encoding {codering!r}")


def _zonder_commentaar(tekst):
    """Haalt YAML-commentaar weg, zodat een labelnaam in commentaar niet als
    gebruik telt. Commentaar begint met `#` aan het begin van een regel of na
    witruimte."""
    regels = []
    for regel in tekst.splitlines():
        regels.append(re.sub(r"(^|\s)#.*$", "", regel))
    return "\n".join(regels)


def _onleesbare_runs_on(tekst):
    """True als een `runs-on:` niet uit letterlijke labels bestaat.

    Letterlijk is: een gewone scalar of een lijst van gewone scalars. Alles met
    `${{`, een anker/alias/tag, een block-scalar of een lege waarde zonder
    lijstitems eronder is niet te herleiden en telt als onleesbaar."""
    regels = tekst.splitlines()
    for i, regel in enumerate(regels):
        m = re.search(r"runs-on[\"']?\s*:(.*)$", regel)
        if not m:
            continue
        waarde = m.group(1).strip()
        if not waarde:
            # Blokvorm: verzamel de volgende, dieper ingesprongen regels.
            basis = len(regel) - len(regel.lstrip())
            rest = []
            for volgende in regels[i + 1:]:
                if not volgende.strip():
                    continue
                if len(volgende) - len(volgende.lstrip()) <= basis:
                    break
                rest.append(volgende.strip())
            if not rest:
                return True
            waarde = " ".join(rest)
        if "${{" in waarde or waarde[0] in "*&!|>{":
            return True
    return False


def scan_workflow(tekst, shared_labels):
    """Conservatieve detectie van risicovolle triggers en gedeeld-labelgebruik.

    Bewust geen YAML-parser: er is er geen beschikbaar zonder externe dependency,
    en een half-werkende parser is gevaarlijker dan overgevoelige detectie.
    Over-detectie kost hooguit een handmatige goedkeuring in de allowlist;
    onder-detectie laat onbetrouwbare code toe. Daarom een tekstscan die eerder
    te veel dan te weinig markeert.
    """
    gevonden = []
    for trigger in RISKY_TRIGGERS:
        if trigger in tekst and trigger not in gevonden:
            # pull_request_target bevat pull_request; alleen de langste telt.
            if trigger == "pull_request" and "pull_request_target" in gevonden:
                continue
            gevonden.append(trigger)
    zonder_commentaar = _zonder_commentaar(tekst)
    gebruikt_label = any(label and label in zonder_commentaar for label in shared_labels)
    # Een runs-on die we niet letterlijk kunnen lezen (expressie, matrix,
    # anker, blokvorm met expressie) kan tijdens het draaien op een gedeeld label
    # uitkomen. Bij een risicovolle trigger telt dat conservatief als gebruik van
    # het gedeelde label: hard tenzij JP het bevestigt.
    if gevonden and _onleesbare_runs_on(zonder_commentaar):
        gebruikt_label = True
    return gevonden, gebruikt_label


ROLLEN_MET_SCHRIJFRECHT = ("owner", "admin", "write")


def _schrijvers(client, full_name, owner_login=None):
    """Iedere identiteit met schrijfrecht op de workflowbestanden van deze
    repository: de eigenaar, collaborators en teamleden.

    De eigenaar staat er expliciet bij omdat Forgejo hem niet in de
    collaboratorlijst opneemt. Zonder die regel zou juist de meest bevoorrechte
    identiteit onzichtbaar blijven voor de allowlist.

    `/repos/{owner}/{repo}/collaborators/{c}/permission` levert
    `RepoCollaboratorPermission`: `permission` (string), `role_name` (string) en
    `user`. Het is dus geen booleanmap; de rol wordt als string vergeleken.
    """
    schrijvers = set()

    if not owner_login:
        # De aanroepplek geeft entry["owner"] altijd mee en _valideer_repo heeft
        # die al gecontroleerd; een lege waarde betekent dus een onvolledige meting.
        raise Unreadable(f"{full_name}: eigenaar niet vastgesteld")
    schrijvers.add(owner_login)

    collabs = client.collaborators(full_name)
    if collabs is None:
        raise Unreadable(f"{full_name}: collaboratorlijst niet uitleesbaar")
    _eis_lijst_van_dicts(collabs, f"{full_name}: collaborators")
    for collab in collabs:
        login = collab.get("login")
        if not login:
            raise Unreadable(f"{full_name}: collaborator zonder login in de respons")
        perm = client.collaborator_permission(full_name, login)
        # De permissierespons is de beslissende meting voor deze identiteit.
        # Ontbreekt hij of mist hij beide rolvelden, dan is dat onleesbaar en
        # nooit "geen schrijfrecht": dat zou de collaborator stil uit writers
        # laten verdwijnen.
        if perm is None or not (perm.get("permission") or perm.get("role_name")):
            raise Unreadable(
                f"{full_name}: permissie van collaborator {login} niet uitleesbaar")
        rol = str(perm.get("permission") or perm.get("role_name")).lower()
        if rol in ROLLEN_MET_SCHRIJFRECHT:
            schrijvers.add(login)

    teams = client.teams(full_name)
    if teams is None:
        raise Unreadable(f"{full_name}: teamlijst niet uitleesbaar")
    _eis_lijst_van_dicts(teams, f"{full_name}: teams")
    for team in teams:
        team_id = team.get("id")
        rol = str(team.get("permission") or "").lower()
        if team_id is None:
            raise Unreadable(f"{full_name}: team zonder id in de respons")
        if rol not in BEKENDE_TEAMROLLEN:
            # Ontbrekend of onbekend: geen meting, dus geen "geen schrijver".
            raise Unreadable(
                f"{full_name}: team {team_id} heeft geen uitleesbare permission")
        if rol not in ROLLEN_MET_SCHRIJFRECHT:
            continue
        leden = client.team_members(team_id)
        if leden is None:
            raise Unreadable(f"{full_name}: leden van team {team_id} niet uitleesbaar")
        _eis_lijst_van_dicts(leden, f"{full_name}: leden van team {team_id}")
        for lid in leden:
            login = lid.get("login")
            if not login:
                raise Unreadable(f"{full_name}: teamlid zonder login in team {team_id}")
            schrijvers.add(login)

    return sorted(schrijvers)


def _deploy_keys(client, full_name):
    """Deploy keys van een repository, genormaliseerd op id/title/fingerprint/
    read_only. Een sleutel met schrijfrecht kan buiten de allowlist-identiteiten
    om code naar de repository pushen, dus een ontbrekend of verkeerd getypt
    veld is onleesbaar en nooit "alleen-lezen"."""
    sleutels = client.deploy_keys(full_name)
    if sleutels is None:
        raise Unreadable(f"{full_name}: deploy keys niet uitleesbaar")
    _eis_lijst_van_dicts(sleutels, f"{full_name}: deploy keys")
    uit = []
    for sleutel in sleutels:
        if not isinstance(sleutel.get("read_only"), bool):
            raise Unreadable(f"{full_name}: deploy key {sleutel.get('id')} zonder boolean read_only")
        if not isinstance(sleutel.get("fingerprint"), str) or not sleutel["fingerprint"]:
            raise Unreadable(f"{full_name}: deploy key {sleutel.get('id')} zonder fingerprint")
        uit.append({"id": sleutel.get("id"), "title": sleutel.get("title"),
                    "fingerprint": sleutel["fingerprint"], "read_only": sleutel["read_only"]})
    return uit


def inventory(client, shared_labels=()):
    repositories = []
    unreadable = []

    for repo in client.repos():
        try:
            full_name = _valideer_repo(repo)
        except Unreadable as exc:
            # Fail-closed: het oordeel wordt hierdoor rood, en de overige
            # repositories worden nog wel gemeten zodat het beeld compleet is.
            unreadable.append(str(exc))
            continue
        entry = {
            "full_name": full_name,
            "has_actions": bool(repo.get("has_actions")),
            "private": bool(repo.get("private")),
            "internal": bool(repo.get("internal")),
            "fork": bool(repo.get("fork")),
            "default_branch": repo.get("default_branch"),
            "owner": (repo.get("owner") or {}).get("login"),
            "workflow_source": None,
            "workflows": [],
            "risky_triggers": [],
            "gebruikt_gedeeld_label": False,
            "writers": [],
            "deploy_keys": [],
            "branch_protection": None,
            "unreadable": [],
        }

        if entry["has_actions"]:
            listing = []
            try:
                entry["workflow_source"], listing = _workflow_source(client, full_name)
            except Unreadable as exc:
                entry["unreadable"].append(str(exc))

            for item in listing:
                naam = item.get("name", "")
                if item.get("type") != "file" or not naam.endswith(WORKFLOW_SUFFIXEN):
                    continue
                pad = item.get("path") or f"{entry['workflow_source']}/{naam}"
                entry["workflows"].append(pad)
                try:
                    bestand = client.contents(full_name, pad)
                    if isinstance(bestand, list) or bestand is None:
                        raise Unreadable(f"{full_name}:{pad}: geen bestandsrespons")
                    triggers, gebruikt = scan_workflow(_decodeer(bestand), shared_labels)
                except Unreadable as exc:
                    entry["unreadable"].append(str(exc))
                    continue
                for trigger in triggers:
                    if trigger not in entry["risky_triggers"]:
                        entry["risky_triggers"].append(trigger)
                entry["gebruikt_gedeeld_label"] = entry["gebruikt_gedeeld_label"] or gebruikt

            try:
                entry["writers"] = _schrijvers(client, full_name, entry["owner"])
            except Unreadable as exc:
                entry["unreadable"].append(str(exc))

            try:
                entry["deploy_keys"] = _deploy_keys(client, full_name)
            except Unreadable as exc:
                entry["unreadable"].append(str(exc))

            try:
                regels = client.branch_protections(full_name)
                if regels is None:
                    raise Unreadable(f"{full_name}: branch-protection niet uitleesbaar")
                _eis_lijst_van_dicts(regels, f"{full_name}: branch_protections")
                entry["branch_protection"] = [
                    r for r in regels
                    if r.get("branch_name") == entry["default_branch"]
                    or r.get("rule_name") == entry["default_branch"]
                ]
            except Unreadable as exc:
                entry["unreadable"].append(str(exc))

        unreadable.extend(entry["unreadable"])
        repositories.append(entry)

    return {"repositories": repositories, "unreadable": unreadable}


def classify(inv, allowlist):
    """Splitst afwijkingen in hard en zacht volgens 7.7."""
    verdict = Verdict()
    verdict.unreadable.extend(inv.get("unreadable", []))

    approved_repos = {r["full_name"]: r for r in allowlist.get("repositories", [])}
    approved_identities = {i["name"] for i in allowlist.get("identities", [])}

    for repo in inv["repositories"]:
        name = repo["full_name"]
        entry = approved_repos.get(name)

        if entry is None:
            if repo["has_actions"]:
                verdict.hard.append(
                    f"{name}: Actions staat aan maar de repository staat niet in de allowlist")
            else:
                verdict.soft.append(
                    f"{name}: nieuwe repository zonder Actions; binnen 24 uur beoordelen")
            continue

        # actions_enabled moet een echte boolean True zijn; een verkeerd getypte
        # waarde (bv. de string "false", die de loader als truthy string bewaart)
        # mag geen toestemming geven. `is not True` is bewust strenger dan een
        # truthy-check: bool False EN elk niet-boolean type leiden tot hard.
        if repo["has_actions"] and entry.get("actions_enabled") is not True:
            verdict.hard.append(
                f"{name}: Actions staat aan maar de allowlist bevestigt actions_enabled "
                f"niet als True (drift of ongeldig type)")

        # Een schrijver moet een goedgekeurde identiteit zijn én voor déze repo in
        # `writers:` staan (ISS-42). Alleen de globale lijst handhaven keurde een
        # per-repo bedoelde identiteit stil voor elke repo goed. Fail-closed: een
        # ontbrekende of niet-lijstvormige `writers` (ook een gequote "[...]") geeft
        # geen enkele schrijver toestemming.
        repo_writers_raw = entry.get("writers")
        if isinstance(repo_writers_raw, list) and all(
                isinstance(w, str) for w in repo_writers_raw):
            repo_writers = set(repo_writers_raw)
        else:
            repo_writers = set()
            verdict.hard.append(
                f"{name}: writers ontbreekt of is ongeldig in de allowlist "
                f"(verwacht een lijst van namen)")

        for writer in repo.get("writers", []):
            if writer not in approved_identities:
                verdict.hard.append(
                    f"{name}: niet-goedgekeurde workflow-schrijver {writer}")
            elif writer not in repo_writers:
                verdict.hard.append(
                    f"{name}: schrijver {writer} is niet goedgekeurd voor deze repository "
                    f"(ontbreekt in writers)")

        # §7.7 (ISS-9-delta): een risky-trigger op een gedeeld label is HARD, tenzij
        # JP hem voor deze repo expliciet heeft bevestigd. Fail-closed: alleen een
        # lijst waarvan elk lid een bekende risky-trigger is telt als bevestiging.
        # Iedere andere vorm — een string (ook een gequote "[...]" die de loader
        # als lijst zou kunnen lezen), een dict, of een lijst met een onbekend of
        # niet-string lid — accepteert nooit en laat de kruising hard, met een
        # zachte melding zodat de misconfiguratie niet stil blijft.
        ack_raw = entry.get("risky_triggers_acknowledged")
        if ack_raw in (None, [], ()):
            acknowledged = set()
        elif isinstance(ack_raw, list) and all(t in RISKY_TRIGGERS for t in ack_raw):
            acknowledged = set(ack_raw)
        else:
            acknowledged = set()
            verdict.soft.append(
                f"{name}: risky_triggers_acknowledged is ongeldig (verwacht een lijst van "
                f"bekende triggers {list(RISKY_TRIGGERS)}); fail-closed genegeerd, de kruising "
                f"blijft hard")
        for trigger in repo.get("risky_triggers", []):
            if repo.get("gebruikt_gedeeld_label"):
                if trigger in acknowledged:
                    verdict.accepted.append(
                        f"{name}: trigger {trigger} op een gedeeld runnerlabel is expliciet "
                        f"bevestigd (risky_triggers_acknowledged); restrisico aanvaard per §7.6/§7.7")
                else:
                    verdict.hard.append(
                        f"{name}: trigger {trigger} in een workflow die een gedeeld runnerlabel "
                        f"gebruikt; onbetrouwbare code kan zo op de pool starten")
            else:
                verdict.soft.append(
                    f"{name}: trigger {trigger} aanwezig maar zonder gedeeld runnerlabel; "
                    f"binnen 24 uur beoordelen")

        # Deploy keys met schrijfrecht: HARD tenzij de fingerprint per repo is
        # bevestigd in deploy_keys_acknowledged. Zelfde fail-closed patroon als
        # risky_triggers_acknowledged: alleen een lijst van niet-lege strings telt.
        dk_raw = entry.get("deploy_keys_acknowledged")
        if dk_raw in (None, [], ()):
            dk_ack = set()
        elif isinstance(dk_raw, list) and all(isinstance(f, str) and f for f in dk_raw):
            dk_ack = set(dk_raw)
        else:
            dk_ack = set()
            verdict.soft.append(
                f"{name}: deploy_keys_acknowledged is ongeldig (verwacht een lijst van "
                f"fingerprints); fail-closed genegeerd, schrijf-deploy-keys blijven hard")
        for sleutel in repo.get("deploy_keys", []):
            if sleutel["read_only"]:
                continue
            label = f"{sleutel.get('title')!r} (id {sleutel.get('id')}, {sleutel['fingerprint']})"
            if sleutel["fingerprint"] in dk_ack:
                verdict.accepted.append(
                    f"{name}: deploy key {label} met schrijfrecht is expliciet bevestigd "
                    f"(deploy_keys_acknowledged); restrisico aanvaard")
            else:
                verdict.hard.append(
                    f"{name}: deploy key {label} heeft schrijfrecht en is niet bevestigd "
                    f"in deploy_keys_acknowledged")

        if repo["has_actions"] and repo["workflow_source"] is None:
            verdict.soft.append(
                f"{name}: Actions staat aan maar er is geen workflowmap gevonden")

        if repo.get("gebruikt_gedeeld_label") and not repo.get("branch_protection"):
            verdict.soft.append(
                f"{name}: gebruikt de gedeelde labels maar heeft geen branch-protection "
                f"op {repo.get('default_branch')}; binnen 24 uur beoordelen")

    return verdict
