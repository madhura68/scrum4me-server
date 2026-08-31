# forgejo-runner/scripts/trust_scope.py
"""Trustscope-inventarisatie en -classificatie volgens 7.7 van het migratieontwerp.

Fail-closed: alles wat niet ondubbelzinnig uitleesbaar is, telt als onleesbaar
en maakt het oordeel rood. De module doet zelf geen netwerk-IO; de client wordt
ingespoten, zodat de tests geen echte instance nodig hebben.
"""

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
    gebruikt_label = any(label and label in tekst for label in shared_labels)
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

        if repo["has_actions"] and not entry.get("actions_enabled"):
            verdict.hard.append(
                f"{name}: Actions staat aan terwijl de allowlist uitgaat van uit")

        for writer in repo.get("writers", []):
            if writer not in approved_identities:
                verdict.hard.append(
                    f"{name}: niet-goedgekeurde workflow-schrijver {writer}")

        for trigger in repo.get("risky_triggers", []):
            if repo.get("gebruikt_gedeeld_label"):
                verdict.hard.append(
                    f"{name}: trigger {trigger} in een workflow die een gedeeld runnerlabel "
                    f"gebruikt; onbetrouwbare code kan zo op de pool starten")
            else:
                verdict.soft.append(
                    f"{name}: trigger {trigger} aanwezig maar zonder gedeeld runnerlabel; "
                    f"binnen 24 uur beoordelen")

        if repo["has_actions"] and repo["workflow_source"] is None:
            verdict.soft.append(
                f"{name}: Actions staat aan maar er is geen workflowmap gevonden")

        if repo.get("gebruikt_gedeeld_label") and not repo.get("branch_protection"):
            verdict.soft.append(
                f"{name}: gebruikt de gedeelde labels maar heeft geen branch-protection "
                f"op {repo.get('default_branch')}; binnen 24 uur beoordelen")

    return verdict
