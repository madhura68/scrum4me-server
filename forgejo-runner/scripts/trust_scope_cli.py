# forgejo-runner/scripts/trust_scope_cli.py
"""Netwerkclient en CLI voor de trustscope-gate.

Exitcodes: 0 groen, 10 zachte afwijking, 20 harde afwijking, 30 onleesbaar.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

import trust_scope
from trust_scope import Unreadable


class ForgejoClient:
    def __init__(self, base_url, token):
        self.base = base_url.rstrip("/")
        self.token = token

    def _get(self, path, params=None, *, missing_ok=False, not_applicable=()):
        """Haalt een API-pad op. Een foutstatus is standaard NIET normaal.

        Twee uitzonderingen, allebei gedocumenteerd in de OpenAPI-spec van deze
        instance en allebei expliciet per aanroep:

        - `missing_ok=True` bij het aftasten van de twee workflowmappen: een 404
          betekent daar "map bestaat niet" en stuurt de fallback aan.
        - `not_applicable=(405,)` bij `/repos/{owner}/{repo}/teams`: Forgejo
          antwoordt daar met "repo is not owned by an organization" voor iedere
          repository van een gebruiker. Dat is geen onleesbare meting maar een
          endpoint dat niet van toepassing is.

        Overal elders zou een foutstatus stil "geen collaborators", "geen teams"
        of "geen branch-protection" betekenen, en dat is fail-open in een gate
        die volgens 7.7 fail-closed moet zijn.
        """
        url = f"{self.base}/api/v1{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"Authorization": f"token {self.token}"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and missing_ok:
                return None
            if exc.code in not_applicable:
                return None
            raise Unreadable(f"{path}: HTTP {exc.code}") from exc
        except (urllib.error.URLError, ValueError) as exc:
            raise Unreadable(f"{path}: {exc}") from exc

    def _gepagineerd(self, path):
        """Haalt een gepagineerd lijstendpoint volledig op.

        `/repos/{owner}/{repo}/collaborators` en `/teams/{id}/members` kennen
        blijkens de spec `page` en `limit`. Zonder paginering levert de instance
        haar eigen default, en een afgekapte schrijversverzameling maakt de gate
        stil groen: een schrijver die nooit in de lijst verschijnt kan per
        definitie geen harde afwijking opleveren.
        """
        out, page = [], 1
        while True:
            items = self._get(path, {"limit": 50, "page": page})
            if not isinstance(items, list):
                raise Unreadable(f"{path} pagina {page}: geen lijst")
            out.extend(items)
            if len(items) < 50:
                return out
            page += 1

    def repos(self):
        """Alle zichtbare repositories, gepagineerd.

        Een onverwachte vorm is hier extra gevaarlijk: een stilzwijgend lege
        lijst betekent "niets te toetsen" en zou de trustgate groen maken
        zonder een enkele repository te hebben gemeten.
        """
        out, page = [], 1
        while True:
            data = self._get("/repos/search", {"limit": 50, "page": page})
            if not isinstance(data, dict) or not isinstance(data.get("data"), list):
                raise Unreadable(f"/repos/search pagina {page}: onverwachte respons")
            items = data["data"]
            out.extend(items)
            if len(items) < 50:
                return out
            page += 1

    def contents(self, full_name, path):
        # De enige plek waar een 404 een geldige uitkomst is: de workflowmap
        # bestaat niet en de fallback moet worden geprobeerd.
        return self._get(f"/repos/{full_name}/contents/{path}", missing_ok=True)

    # Hieronder is een 404 nooit normaal: die maakt de meting onvolledig en
    # moet de gate rood maken in plaats van een lege verzameling te leveren.
    def collaborators(self, full_name):
        return self._gepagineerd(f"/repos/{full_name}/collaborators")

    def collaborator_permission(self, full_name, login):
        return self._get(f"/repos/{full_name}/collaborators/{login}/permission")

    def teams(self, full_name):
        # Een repository van een gebruiker heeft geen teams; Forgejo meldt dat
        # met een gedocumenteerde 405. Dat is "niet van toepassing", geen
        # onleesbare meting - anders kan de gate voor zulke repo's nooit groen
        # worden. /teams kent geen page/limit en wordt dus niet gepagineerd.
        resultaat = self._get(f"/repos/{full_name}/teams", not_applicable=(405,))
        return [] if resultaat is None else resultaat

    def team_members(self, team_id):
        return self._gepagineerd(f"/teams/{team_id}/members")

    def branch_protections(self, full_name):
        return self._get(f"/repos/{full_name}/branch_protections")


def load_allowlist(path):
    """Leest de strikte YAML-deelverzameling van trusted-actions-scope.yml."""
    doc = {"identities": [], "repositories": [], "approved_by": "", "approved_at": ""}
    section, current = None, None
    for raw in open(path, encoding="utf-8"):
        line = raw.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        text = line.strip()
        if indent == 0 and text.endswith(":"):
            section = text[:-1]
            continue
        if indent == 0 and ":" in text:
            key, _, value = text.partition(":")
            doc[key.strip()] = value.strip().strip('"')
            section = None
            continue
        if text.startswith("- "):
            current = {}
            doc.setdefault(section, []).append(current)
            text = text[2:].strip()
            if not text:
                continue
        if current is not None and ":" in text:
            key, _, value = text.partition(":")
            value = value.strip().strip('"')
            if value in ("true", "false"):
                value = value == "true"
            elif value.startswith("[") and value.endswith("]"):
                value = [v.strip().strip('"') for v in value[1:-1].split(",") if v.strip()]
            elif value in ("null", "~", ""):
                value = None
            current[key.strip()] = value
    return doc


def load_shared_labels(path):
    """Leest de labelnamen uit labels.txt. Een regel heeft de vorm
    `naam:docker://image@sha256:...`; alleen het deel voor de eerste dubbele punt
    is de labelnaam waarop een workflow `runs-on` kan matchen."""
    namen = []
    for regel in open(path, encoding="utf-8"):
        regel = regel.strip()
        if not regel or regel.startswith("#"):
            continue
        namen.append(regel.split(":", 1)[0])
    return tuple(namen)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--allowlist", required=True)
    ap.add_argument("--labels", required=True,
                    help="pad naar labels.txt; de labelnamen bepalen of een workflow "
                         "de gedeelde pool kan bereiken")
    ap.add_argument("--out", required=True)
    ap.add_argument("--emit-allowlist", action="store_true",
                    help="print een allowlist-voorstel uit de meting en wijzig niets")
    args = ap.parse_args()

    token = os.environ.get("FORGEJO_TOKEN", "")
    if not token:
        print("FORGEJO_TOKEN ontbreekt", file=sys.stderr)
        return 30

    client = ForgejoClient(os.environ.get("FORGEJO_URL", "https://git.jp-visser.nl"), token)
    shared_labels = load_shared_labels(args.labels)
    if not shared_labels:
        print("fail-closed: geen gedeelde labels gelezen uit labels.txt", file=sys.stderr)
        return 30
    try:
        inv = trust_scope.inventory(client, shared_labels)
    except Unreadable as exc:
        print(f"fail-closed: {exc}", file=sys.stderr)
        return 30
    except Exception as exc:                      # noqa: BLE001 - bewust breed
        # Een onverwachte fout is geen groen oordeel. Zonder deze vangst zou de
        # gate met een traceback eindigen en een niet-nul exitcode geven die
        # niet als fail-closed te onderscheiden is van een crash.
        print(f"fail-closed: onverwachte fout: {exc!r}", file=sys.stderr)
        return 30

    if args.emit_allowlist:
        print("version: 1")
        print('approved_by: ""')
        print('approved_at: ""')
        print("\nidentities:")
        names = sorted({w for r in inv["repositories"] for w in r["writers"]})
        for name in names:
            print(f"  - name: {name}")
        print("\nrepositories:")
        for repo in sorted(inv["repositories"], key=lambda r: r["full_name"]):
            print(f"  - full_name: {repo['full_name']}")
            print(f"    actions_enabled: {str(repo['has_actions']).lower()}")
            source = repo["workflow_source"]
            print(f"    workflow_source: {source if source else 'null'}")
            print(f"    writers: [{', '.join(repo['writers'])}]")
        return 0

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "trust-inventory.json"), "w", encoding="utf-8") as fh:
        json.dump(inv, fh, indent=2, sort_keys=True, ensure_ascii=False)

    allowlist = load_allowlist(args.allowlist)
    if not allowlist.get("approved_by"):
        print("fail-closed: de allowlist is nog niet door JP goedgekeurd", file=sys.stderr)
        return 30

    verdict = trust_scope.classify(inv, allowlist)
    with open(os.path.join(args.out, "trust-verdict.json"), "w", encoding="utf-8") as fh:
        json.dump({"hard": verdict.hard, "soft": verdict.soft,
                   "unreadable": verdict.unreadable, "accepted": verdict.accepted,
                   "ok": verdict.ok},
                  fh, indent=2, ensure_ascii=False)

    for item in verdict.unreadable:
        print(f"ONLEESBAAR: {item}", file=sys.stderr)
    for item in verdict.hard:
        print(f"HARD: {item}", file=sys.stderr)
    for item in verdict.soft:
        print(f"ZACHT: {item}", file=sys.stderr)
    # Aanvaarde kruisingen wijzigen de exitcode niet, maar worden altijd getoond.
    for item in verdict.accepted:
        print(f"AANVAARD: {item}", file=sys.stderr)

    if verdict.unreadable:
        return 30
    if verdict.hard:
        return 20
    if verdict.soft:
        return 10
    return 0


if __name__ == "__main__":
    sys.exit(main())
