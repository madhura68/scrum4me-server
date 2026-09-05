# forgejo-runner/tests/test_trust_scope.py
import base64
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import trust_scope
import trust_scope_cli

GEDEELDE_LABELS = ("ubuntu-latest",)


def b64(tekst):
    return {"content": base64.b64encode(tekst.encode()).decode(), "encoding": "base64",
            "path": "wf.yml", "type": "file", "name": "wf.yml"}


class FakeClient:
    """Levert vaste API-antwoorden; raakt geen netwerk."""

    def __init__(self, repos, contents=None, collaborators=None, permissions=None,
                 teams=None, team_members=None, protections=None, unreadable=()):
        self._repos = repos
        self._contents = contents or {}
        self._collaborators = collaborators or {}
        self._permissions = permissions or {}
        self._teams = teams or {}
        self._team_members = team_members or {}
        self._protections = protections or {}
        self._unreadable = set(unreadable)

    def repos(self):
        return self._repos

    def contents(self, full_name, path):
        if (full_name, path) in self._unreadable:
            raise trust_scope.Unreadable(f"{full_name}:{path}")
        return self._contents.get((full_name, path))

    def collaborators(self, full_name):
        return self._collaborators.get(full_name, [])

    def collaborator_permission(self, full_name, login):
        return self._permissions.get((full_name, login), {})

    def teams(self, full_name):
        return self._teams.get(full_name, [])

    def team_members(self, team_id):
        return self._team_members.get(team_id, [])

    def branch_protections(self, full_name):
        return self._protections.get(full_name, [])


REPO_ACTIONS = {
    "full_name": "janpeter/app", "has_actions": True, "private": True,
    "internal": False, "fork": False, "default_branch": "main",
    "owner": {"login": "janpeter"},
}
REPO_NO_ACTIONS = dict(REPO_ACTIONS, full_name="janpeter/stil", has_actions=False)

ALLOWLIST = {
    "repositories": [
        {"full_name": "janpeter/app", "actions_enabled": True,
         "workflow_source": ".forgejo/workflows", "writers": ["janpeter"]},
        {"full_name": "janpeter/stil", "actions_enabled": False,
         "workflow_source": None, "writers": ["janpeter"]},
    ],
    "identities": [{"name": "janpeter"}],
}

MAP = [{"name": "ci.yml", "type": "file", "path": ".forgejo/workflows/ci.yml"}]


class TestWorkflowSource(unittest.TestCase):
    def test_forgejo_map_wint_van_github_fallback(self):
        client = FakeClient([REPO_ACTIONS], contents={
            ("janpeter/app", ".forgejo/workflows"): MAP,
            ("janpeter/app", ".github/workflows"): [{"name": "oud.yml", "type": "file"}],
            ("janpeter/app", ".forgejo/workflows/ci.yml"): b64("on: push\n"),
        })
        inv = trust_scope.inventory(client, GEDEELDE_LABELS)
        self.assertEqual(inv["repositories"][0]["workflow_source"], ".forgejo/workflows")

    def test_valt_terug_op_github_als_forgejo_map_ontbreekt(self):
        client = FakeClient([REPO_ACTIONS], contents={
            ("janpeter/app", ".github/workflows"): [
                {"name": "ci.yml", "type": "file", "path": ".github/workflows/ci.yml"}],
            ("janpeter/app", ".github/workflows/ci.yml"): b64("on: push\n"),
        })
        inv = trust_scope.inventory(client, GEDEELDE_LABELS)
        self.assertEqual(inv["repositories"][0]["workflow_source"], ".github/workflows")

    def test_onleesbare_map_is_fail_closed(self):
        client = FakeClient([REPO_ACTIONS], unreadable=[("janpeter/app", ".forgejo/workflows")])
        verdict = trust_scope.classify(trust_scope.inventory(client, GEDEELDE_LABELS), ALLOWLIST)
        self.assertFalse(verdict.ok)
        self.assertTrue(verdict.unreadable)

    def test_onleesbaar_workflowbestand_is_fail_closed(self):
        client = FakeClient([REPO_ACTIONS], contents={
            ("janpeter/app", ".forgejo/workflows"): MAP,
            ("janpeter/app", ".forgejo/workflows/ci.yml"): {
                "content": "@@geen-base64@@", "encoding": "base64",
                "path": "ci.yml", "type": "file", "name": "ci.yml"},
        })
        verdict = trust_scope.classify(trust_scope.inventory(client, GEDEELDE_LABELS), ALLOWLIST)
        self.assertFalse(verdict.ok)
        self.assertTrue(verdict.unreadable)

    def test_repo_zonder_actions_krijgt_geen_workflowbron(self):
        inv = trust_scope.inventory(FakeClient([REPO_NO_ACTIONS]), GEDEELDE_LABELS)
        self.assertIsNone(inv["repositories"][0]["workflow_source"])


class TestTriggerscan(unittest.TestCase):
    def test_detecteert_pull_request_target(self):
        triggers, _ = trust_scope.scan_workflow("on:\n  pull_request_target:\n", GEDEELDE_LABELS)
        self.assertIn("pull_request_target", triggers)

    def test_pull_request_target_slokt_pull_request_niet_dubbel_op(self):
        triggers, _ = trust_scope.scan_workflow("on:\n  pull_request_target:\n", GEDEELDE_LABELS)
        self.assertEqual(triggers, ["pull_request_target"])

    def test_detecteert_workflow_run(self):
        triggers, _ = trust_scope.scan_workflow("on: workflow_run\n", GEDEELDE_LABELS)
        self.assertIn("workflow_run", triggers)

    def test_push_only_is_niet_riskant(self):
        triggers, _ = trust_scope.scan_workflow("on:\n  push:\n", GEDEELDE_LABELS)
        self.assertEqual(triggers, [])

    def test_detecteert_gedeeld_label(self):
        _, gebruikt = trust_scope.scan_workflow("runs-on: ubuntu-latest\n", GEDEELDE_LABELS)
        self.assertTrue(gebruikt)

    def test_ander_label_telt_niet_als_gedeeld(self):
        _, gebruikt = trust_scope.scan_workflow("runs-on: eigen-runner\n", GEDEELDE_LABELS)
        self.assertFalse(gebruikt)

    def test_inventory_vult_risky_triggers_werkelijk(self):
        client = FakeClient([REPO_ACTIONS], contents={
            ("janpeter/app", ".forgejo/workflows"): MAP,
            ("janpeter/app", ".forgejo/workflows/ci.yml"):
                b64("on:\n  pull_request:\njobs:\n  a:\n    runs-on: ubuntu-latest\n"),
        })
        repo = trust_scope.inventory(client, GEDEELDE_LABELS)["repositories"][0]
        self.assertEqual(repo["risky_triggers"], ["pull_request"])
        self.assertTrue(repo["gebruikt_gedeeld_label"])


class TestSchrijvers(unittest.TestCase):
    def _client(self, **kw):
        basis = dict(contents={("janpeter/app", ".forgejo/workflows"): []})
        basis.update(kw)
        return FakeClient([REPO_ACTIONS], **basis)

    def test_collaborator_met_push_is_schrijver(self):
        client = self._client(
            collaborators={"janpeter/app": [{"login": "eva"}]},
            permissions={("janpeter/app", "eva"): {"permission": "write"}})
        # De eigenaar janpeter hoort er per definitie bij.
        self.assertEqual(trust_scope.inventory(client, GEDEELDE_LABELS)["repositories"][0]["writers"],
                         ["eva", "janpeter"])

    def test_collaborator_met_alleen_pull_is_geen_schrijver(self):
        client = self._client(
            collaborators={"janpeter/app": [{"login": "lezer"}]},
            permissions={("janpeter/app", "lezer"): {"permission": "read"}})
        self.assertEqual(trust_scope.inventory(client, GEDEELDE_LABELS)["repositories"][0]["writers"],
                         ["janpeter"])

    def test_teamlid_met_write_telt_ook_als_schrijver(self):
        client = self._client(
            teams={"janpeter/app": [{"id": 7, "name": "devs", "permission": "write"}]},
            team_members={7: [{"login": "sam"}]})
        self.assertEqual(trust_scope.inventory(client, GEDEELDE_LABELS)["repositories"][0]["writers"],
                         ["janpeter", "sam"])

    def test_teamlid_met_alleen_read_telt_niet(self):
        client = self._client(
            teams={"janpeter/app": [{"id": 8, "name": "kijkers", "permission": "read"}]},
            team_members={8: [{"login": "kim"}]})
        self.assertEqual(trust_scope.inventory(client, GEDEELDE_LABELS)["repositories"][0]["writers"],
                         ["janpeter"])

    def test_eigenaar_is_altijd_schrijver_ook_zonder_collaborators(self):
        # Forgejo neemt de eigenaar niet op in /collaborators; zonder deze regel
        # zou de meest bevoorrechte identiteit onzichtbaar blijven.
        client = self._client()
        self.assertEqual(trust_scope.inventory(client, GEDEELDE_LABELS)["repositories"][0]["writers"],
                         ["janpeter"])

    def test_permissierespons_is_de_echte_RepoCollaboratorPermission_vorm(self):
        # /collaborators/{c}/permission levert permission, role_name en user —
        # geen booleanmap. Deze test pint die vorm vast.
        client = self._client(
            collaborators={"janpeter/app": [{"login": "eva"}]},
            permissions={("janpeter/app", "eva"): {
                "permission": "write", "role_name": "write", "user": {"login": "eva"}}})
        self.assertIn("eva", trust_scope.inventory(client, GEDEELDE_LABELS)["repositories"][0]["writers"])

    def test_rol_owner_telt_als_schrijver(self):
        client = self._client(
            collaborators={"janpeter/app": [{"login": "baas"}]},
            permissions={("janpeter/app", "baas"): {"permission": "owner"}})
        self.assertIn("baas", trust_scope.inventory(client, GEDEELDE_LABELS)["repositories"][0]["writers"])

    def test_onbekend_teamlid_is_een_harde_afwijking(self):
        client = self._client(
            teams={"janpeter/app": [{"id": 7, "name": "devs", "permission": "admin"}]},
            team_members={7: [{"login": "vreemdeling"}]})
        verdict = trust_scope.classify(trust_scope.inventory(client, GEDEELDE_LABELS), ALLOWLIST)
        self.assertFalse(verdict.ok)
        self.assertTrue(any("vreemdeling" in h for h in verdict.hard))


class TestVierenveertigVierNulVier(unittest.TestCase):
    """Een 404 op een trustscope-endpoint mag nooit stil "leeg" betekenen.

    Alleen het aftasten van de workflowmappen kent afwezigheid als geldige
    uitkomst; alles daarbuiten moet de gate rood maken (7.7 fail-closed).
    """

    class StubClient(FakeClient):
        def __init__(self, leeg_endpoint):
            super().__init__([REPO_ACTIONS],
                             contents={("janpeter/app", ".forgejo/workflows"): []})
            self.leeg = leeg_endpoint

        def collaborators(self, full_name):
            return None if self.leeg == "collaborators" else []

        def teams(self, full_name):
            return None if self.leeg == "teams" else []

        def branch_protections(self, full_name):
            return None if self.leeg == "branch_protections" else []

    def _verdict(self, endpoint):
        client = self.StubClient(endpoint)
        return trust_scope.classify(trust_scope.inventory(client, GEDEELDE_LABELS), ALLOWLIST)

    def test_404_op_collaborators_is_fail_closed(self):
        verdict = self._verdict("collaborators")
        self.assertFalse(verdict.ok)
        self.assertTrue(any("collaboratorlijst" in u for u in verdict.unreadable))

    def test_404_op_teams_is_fail_closed(self):
        verdict = self._verdict("teams")
        self.assertFalse(verdict.ok)
        self.assertTrue(any("teamlijst" in u for u in verdict.unreadable))

    def test_404_op_branch_protections_is_fail_closed(self):
        verdict = self._verdict("branch_protections")
        self.assertFalse(verdict.ok)
        self.assertTrue(any("branch-protection" in u for u in verdict.unreadable))

    def test_ontbrekende_permissierespons_is_fail_closed(self):
        client = FakeClient(
            [REPO_ACTIONS],
            contents={("janpeter/app", ".forgejo/workflows"): []},
            collaborators={"janpeter/app": [{"login": "eva"}]},
            permissions={})   # geen permissierespons voor eva
        verdict = trust_scope.classify(trust_scope.inventory(client, GEDEELDE_LABELS), ALLOWLIST)
        self.assertFalse(verdict.ok)
        self.assertTrue(any("eva" in u for u in verdict.unreadable))

    def test_permissierespons_zonder_rolvelden_is_fail_closed(self):
        client = FakeClient(
            [REPO_ACTIONS],
            contents={("janpeter/app", ".forgejo/workflows"): []},
            collaborators={"janpeter/app": [{"login": "eva"}]},
            permissions={("janpeter/app", "eva"): {"user": {"login": "eva"}}})
        verdict = trust_scope.classify(trust_scope.inventory(client, GEDEELDE_LABELS), ALLOWLIST)
        self.assertFalse(verdict.ok)
        self.assertTrue(any("eva" in u for u in verdict.unreadable))

    def test_client_geeft_alleen_bij_missing_ok_none_terug(self):
        import urllib.error
        import trust_scope_cli

        class Nep404:
            def __call__(self, req, timeout=None):
                raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

        client = trust_scope_cli.ForgejoClient("https://voorbeeld.invalid", "x")
        origineel = trust_scope_cli.urllib.request.urlopen
        trust_scope_cli.urllib.request.urlopen = Nep404()
        try:
            # De workflowmap mag ontbreken.
            self.assertIsNone(client._get("/repos/a/b/contents/.forgejo/workflows",
                                          missing_ok=True))
            # Alles daarbuiten is onleesbaar.
            with self.assertRaises(trust_scope.Unreadable):
                client._get("/repos/a/b/collaborators")
        finally:
            trust_scope_cli.urllib.request.urlopen = origineel


class TestClientResponsvormen(unittest.TestCase):
    """Gedrag van de netwerkclient bij statuscodes en paginering.

    Gebruikt een nep-`urlopen`; er gaat geen verkeer naar een echte instance.
    """

    class NepRespons:
        def __init__(self, payload):
            import json as _json
            self._payload = _json.dumps(payload).encode()

        def read(self):
            return self._payload

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _met_urlopen(self, vervanger, functie):
        import trust_scope_cli
        origineel = trust_scope_cli.urllib.request.urlopen
        trust_scope_cli.urllib.request.urlopen = vervanger
        try:
            return functie(trust_scope_cli)
        finally:
            trust_scope_cli.urllib.request.urlopen = origineel

    def _status(self, code):
        import urllib.error

        def vervanger(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, code, "x", {}, None)
        return vervanger

    def test_405_op_teams_is_niet_van_toepassing(self):
        # Forgejo antwoordt zo voor iedere repository van een gebruiker.
        # Gemeten op deze instance voor janpeter/scrum4me-server en janpeter/max2.
        def doe(mod):
            client = mod.ForgejoClient("https://voorbeeld.invalid", "x")
            return client.teams("janpeter/app")
        self.assertEqual(self._met_urlopen(self._status(405), doe), [])

    def test_403_op_teams_blijft_onleesbaar(self):
        def doe(mod):
            client = mod.ForgejoClient("https://voorbeeld.invalid", "x")
            with self.assertRaises(trust_scope.Unreadable):
                client.teams("janpeter/app")
        self._met_urlopen(self._status(403), doe)

    def test_500_op_teams_blijft_onleesbaar(self):
        def doe(mod):
            client = mod.ForgejoClient("https://voorbeeld.invalid", "x")
            with self.assertRaises(trust_scope.Unreadable):
                client.teams("janpeter/app")
        self._met_urlopen(self._status(500), doe)

    def test_collaborators_worden_volledig_gepagineerd(self):
        paginas = {1: [{"login": f"u{i}"} for i in range(50)],
                   2: [{"login": "laatste"}]}

        def vervanger(req, timeout=None):
            nummer = 2 if "page=2" in req.full_url else 1
            return self.NepRespons(paginas[nummer])

        def doe(mod):
            client = mod.ForgejoClient("https://voorbeeld.invalid", "x")
            return client.collaborators("janpeter/app")

        resultaat = self._met_urlopen(vervanger, doe)
        self.assertEqual(len(resultaat), 51)
        self.assertEqual(resultaat[-1]["login"], "laatste")

    def test_gepagineerd_endpoint_dat_geen_lijst_geeft_is_onleesbaar(self):
        def vervanger(req, timeout=None):
            return self.NepRespons({"onverwacht": True})

        def doe(mod):
            client = mod.ForgejoClient("https://voorbeeld.invalid", "x")
            with self.assertRaises(trust_scope.Unreadable):
                client.collaborators("janpeter/app")
        self._met_urlopen(vervanger, doe)


class TestGenesteVormen(unittest.TestCase):
    """Een 200 met de verkeerde container- of itemvorm is onleesbaar, geen leegte."""

    def _verdict(self, client):
        return trust_scope.classify(trust_scope.inventory(client, GEDEELDE_LABELS), ALLOWLIST)

    def _rood(self, verdict, fragment):
        self.assertFalse(verdict.ok)
        self.assertTrue(any(fragment in u for u in verdict.unreadable),
                        f"{fragment!r} niet gevonden in {verdict.unreadable}")

    def test_workflowmap_als_dict_is_fail_closed(self):
        client = FakeClient([REPO_ACTIONS], contents={
            ("janpeter/app", ".forgejo/workflows"): {"onverwacht": True}})
        self._rood(self._verdict(client), "geen lijst")

    def test_workflowitem_dat_geen_object_is_is_fail_closed(self):
        client = FakeClient([REPO_ACTIONS], contents={
            ("janpeter/app", ".forgejo/workflows"): ["ci.yml"]})
        self._rood(self._verdict(client), "geen object")

    def test_collaborators_als_dict_is_fail_closed(self):
        client = FakeClient([REPO_ACTIONS],
                            contents={("janpeter/app", ".forgejo/workflows"): []},
                            collaborators={"janpeter/app": {"login": "eva"}})
        self._rood(self._verdict(client), "collaborators: geen lijst")

    def test_branch_protections_als_dict_is_fail_closed(self):
        client = FakeClient([REPO_ACTIONS],
                            contents={("janpeter/app", ".forgejo/workflows"): []},
                            protections={"janpeter/app": {"branch_name": "main"}})
        self._rood(self._verdict(client), "branch_protections: geen lijst")


class TestVerplichteVelden(unittest.TestCase):
    """Een ontbrekend veld binnen een gemeten object is een onvolledige meting,
    nooit een stilzwijgende "nee" (7.7 fail-closed)."""

    def _verdict(self, client):
        return trust_scope.classify(trust_scope.inventory(client, GEDEELDE_LABELS), ALLOWLIST)

    def _rood(self, verdict, fragment):
        self.assertFalse(verdict.ok)
        self.assertTrue(any(fragment in u for u in verdict.unreadable),
                        f"{fragment!r} niet gevonden in {verdict.unreadable}")

    def test_repo_zonder_has_actions_is_fail_closed(self):
        repo = {k: v for k, v in REPO_ACTIONS.items() if k != "has_actions"}
        self._rood(self._verdict(FakeClient([repo])), "has_actions")

    def test_has_actions_als_null_is_fail_closed(self):
        repo = dict(REPO_ACTIONS, has_actions=None)
        self._rood(self._verdict(FakeClient([repo])), "has_actions")

    def test_repo_zonder_owner_login_is_fail_closed(self):
        repo = dict(REPO_ACTIONS, owner={})
        self._rood(self._verdict(FakeClient([repo])), "owner.login")

    def test_repo_zonder_default_branch_is_fail_closed(self):
        repo = {k: v for k, v in REPO_ACTIONS.items() if k != "default_branch"}
        self._rood(self._verdict(FakeClient([repo])), "default_branch")

    def test_collaborator_zonder_login_is_fail_closed(self):
        client = FakeClient(
            [REPO_ACTIONS],
            contents={("janpeter/app", ".forgejo/workflows"): []},
            collaborators={"janpeter/app": [{"avatar_url": "x"}]})
        self._rood(self._verdict(client), "collaborator zonder login")

    def test_team_zonder_permission_is_fail_closed(self):
        client = FakeClient(
            [REPO_ACTIONS],
            contents={("janpeter/app", ".forgejo/workflows"): []},
            teams={"janpeter/app": [{"id": 7, "name": "devs"}]})
        self._rood(self._verdict(client), "geen uitleesbare permission")

    def test_teamlid_zonder_login_is_fail_closed(self):
        client = FakeClient(
            [REPO_ACTIONS],
            contents={("janpeter/app", ".forgejo/workflows"): []},
            teams={"janpeter/app": [{"id": 7, "name": "devs", "permission": "write"}]},
            team_members={7: [{"full_name": "Zonder Login"}]})
        self._rood(self._verdict(client), "teamlid zonder login")

    def test_workflowbestand_zonder_encoding_is_fail_closed(self):
        bestand = {"content": "b24gcHVzaAo=", "path": "ci.yml", "type": "file", "name": "ci.yml"}
        client = FakeClient([REPO_ACTIONS], contents={
            ("janpeter/app", ".forgejo/workflows"): MAP,
            ("janpeter/app", ".forgejo/workflows/ci.yml"): bestand,
        })
        self._rood(self._verdict(client), "encoding-veld ontbreekt")

    def test_volledig_object_blijft_gewoon_groen(self):
        # De strengheid mag een correcte meting niet rood maken.
        client = FakeClient(
            [REPO_ACTIONS],
            contents={("janpeter/app", ".forgejo/workflows"): []},
            collaborators={"janpeter/app": [{"login": "eva"}]},
            permissions={("janpeter/app", "eva"): {"permission": "read"}},
            teams={"janpeter/app": [{"id": 7, "name": "kijkers", "permission": "read"}]},
            protections={"janpeter/app": [{"branch_name": "main"}]})
        verdict = self._verdict(client)
        self.assertTrue(verdict.ok, f"onverwacht rood: {verdict.hard} {verdict.unreadable}")


class TestClassificatie(unittest.TestCase):
    def _inv(self, **overrides):
        repo = {
            "full_name": "janpeter/app", "has_actions": True,
            "workflow_source": ".forgejo/workflows", "writers": ["janpeter"],
            "risky_triggers": [], "gebruikt_gedeeld_label": False,
            "branch_protection": [{"branch_name": "main"}],
            "default_branch": "main", "unreadable": [],
        }
        repo.update(overrides)
        return {"repositories": [repo], "unreadable": []}

    def test_alles_bekend_is_groen(self):
        verdict = trust_scope.classify(self._inv(), ALLOWLIST)
        self.assertTrue(verdict.ok)
        self.assertEqual(verdict.hard, [])
        self.assertEqual(verdict.soft, [])

    def test_onbekende_schrijver_is_hard(self):
        verdict = trust_scope.classify(self._inv(writers=["janpeter", "vreemdeling"]), ALLOWLIST)
        self.assertFalse(verdict.ok)
        self.assertTrue(any("vreemdeling" in h for h in verdict.hard))

    def test_risicotrigger_met_gedeeld_label_is_hard(self):
        verdict = trust_scope.classify(
            self._inv(risky_triggers=["pull_request_target"], gebruikt_gedeeld_label=True),
            ALLOWLIST)
        self.assertFalse(verdict.ok)
        self.assertTrue(any("pull_request_target" in h for h in verdict.hard))

    def _allowlist_met_ack(self, ack):
        return {
            "repositories": [{"full_name": "janpeter/app", "actions_enabled": True,
                              "workflow_source": ".forgejo/workflows", "writers": ["janpeter"],
                              "risky_triggers_acknowledged": ack}],
            "identities": [{"name": "janpeter"}],
        }

    def test_bevestigde_risicotrigger_op_gedeeld_label_is_accepted_niet_hard(self):
        # ISS-9: JP bevestigt de kruising per repo (risky_triggers_acknowledged);
        # dan is het een expliciet aanvaard restrisico, geen harde afwijking.
        verdict = trust_scope.classify(
            self._inv(risky_triggers=["pull_request"], gebruikt_gedeeld_label=True),
            self._allowlist_met_ack(["pull_request"]))
        self.assertTrue(verdict.ok, f"onverwacht rood: {verdict.hard}")
        self.assertEqual(verdict.hard, [])
        self.assertTrue(any("pull_request" in a for a in verdict.accepted))

    def test_ack_dekt_alleen_de_genoemde_trigger(self):
        verdict = trust_scope.classify(
            self._inv(risky_triggers=["pull_request", "workflow_run"], gebruikt_gedeeld_label=True),
            self._allowlist_met_ack(["pull_request"]))
        self.assertFalse(verdict.ok)
        self.assertTrue(any("workflow_run" in h for h in verdict.hard))
        self.assertFalse(any("pull_request" in h for h in verdict.hard))
        self.assertTrue(any("pull_request" in a for a in verdict.accepted))

    def test_ack_verzacht_geen_andere_harde_afwijking(self):
        # De ack geldt uitsluitend de risky-trigger-kruising, niet een onbekende schrijver.
        verdict = trust_scope.classify(
            self._inv(risky_triggers=["pull_request"], gebruikt_gedeeld_label=True,
                      writers=["janpeter", "vreemdeling"]),
            self._allowlist_met_ack(["pull_request"]))
        self.assertFalse(verdict.ok)
        self.assertTrue(any("vreemdeling" in h for h in verdict.hard))
        self.assertTrue(any("pull_request" in a for a in verdict.accepted))

    def test_ack_zonder_gedeeld_label_verandert_niets(self):
        verdict = trust_scope.classify(
            self._inv(risky_triggers=["pull_request"], gebruikt_gedeeld_label=False),
            self._allowlist_met_ack(["pull_request"]))
        self.assertTrue(verdict.ok)
        self.assertTrue(any("pull_request" in z for z in verdict.soft))
        self.assertEqual(verdict.accepted, [])

    def test_ack_als_string_ipv_lijst_is_fail_closed(self):
        # Een verkeerd geconfigureerde ack (string i.p.v. lijst) mag NOOIT stil
        # accepteren; hij valt terug op hard.
        verdict = trust_scope.classify(
            self._inv(risky_triggers=["pull_request"], gebruikt_gedeeld_label=True),
            self._allowlist_met_ack("pull_request"))
        self.assertFalse(verdict.ok)
        self.assertTrue(any("pull_request" in h for h in verdict.hard))
        self.assertEqual(verdict.accepted, [])
        self.assertTrue(any("ongeldig" in z for z in verdict.soft))

    def test_ack_met_niet_string_lid_is_fail_closed(self):
        # Reviewronde 1 (mac:codex): alleen het buitenste type checken was te zwak.
        verdict = trust_scope.classify(
            self._inv(risky_triggers=["pull_request"], gebruikt_gedeeld_label=True),
            self._allowlist_met_ack(["pull_request", 1]))
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.accepted, [])
        self.assertTrue(any("pull_request" in h for h in verdict.hard))
        self.assertTrue(any("ongeldig" in z for z in verdict.soft))

    def test_ack_met_onhashbaar_lid_crasht_niet_en_is_fail_closed(self):
        # [{}] mag geen TypeError geven maar een rood oordeel.
        verdict = trust_scope.classify(
            self._inv(risky_triggers=["pull_request"], gebruikt_gedeeld_label=True),
            self._allowlist_met_ack([{}]))
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.accepted, [])

    def test_ack_met_onbekende_trigger_is_fail_closed(self):
        # Je kunt alleen bekende risky-triggers bevestigen; 'push' is ongeldig.
        verdict = trust_scope.classify(
            self._inv(risky_triggers=["pull_request"], gebruikt_gedeeld_label=True),
            self._allowlist_met_ack(["push"]))
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.accepted, [])
        self.assertTrue(any("ongeldig" in z for z in verdict.soft))

    def test_geen_ack_veld_is_ongewijzigd_hard(self):
        # Regressie: zonder het veld blijft de kruising hard (bestaand gedrag).
        verdict = trust_scope.classify(
            self._inv(risky_triggers=["pull_request"], gebruikt_gedeeld_label=True),
            ALLOWLIST)
        self.assertFalse(verdict.ok)
        self.assertTrue(any("pull_request" in h for h in verdict.hard))

    def test_risicotrigger_zonder_gedeeld_label_is_zacht(self):
        verdict = trust_scope.classify(
            self._inv(risky_triggers=["pull_request"], gebruikt_gedeeld_label=False), ALLOWLIST)
        self.assertTrue(verdict.ok)
        self.assertTrue(any("pull_request" in z for z in verdict.soft))

    def test_ontbrekende_branch_protection_bij_gedeeld_label_is_zacht(self):
        verdict = trust_scope.classify(
            self._inv(gebruikt_gedeeld_label=True, branch_protection=[]), ALLOWLIST)
        self.assertTrue(verdict.ok)
        self.assertTrue(any("branch-protection" in z for z in verdict.soft))

    def test_nieuwe_repo_zonder_actions_is_zacht(self):
        inv = self._inv()
        inv["repositories"].append({
            "full_name": "janpeter/nieuw", "has_actions": False, "workflow_source": None,
            "writers": [], "risky_triggers": [], "gebruikt_gedeeld_label": False,
            "branch_protection": [], "default_branch": "main", "unreadable": [],
        })
        verdict = trust_scope.classify(inv, ALLOWLIST)
        self.assertTrue(verdict.ok)
        self.assertTrue(any("janpeter/nieuw" in z for z in verdict.soft))

    def test_nieuwe_repo_met_actions_is_hard(self):
        inv = self._inv()
        inv["repositories"].append({
            "full_name": "janpeter/nieuw", "has_actions": True,
            "workflow_source": ".forgejo/workflows", "writers": [],
            "risky_triggers": [], "gebruikt_gedeeld_label": False,
            "branch_protection": [], "default_branch": "main", "unreadable": [],
        })
        verdict = trust_scope.classify(inv, ALLOWLIST)
        self.assertFalse(verdict.ok)
        self.assertTrue(any("janpeter/nieuw" in h for h in verdict.hard))


class TestAckViaLoader(unittest.TestCase):
    """De fail-closed-belofte moet ook op de echte CLI-route gelden: de eigen
    mini-YAML-loader mag een gequote scalar "[pull_request]" niet als lijst lezen."""

    def _classify_ack_regel(self, regel):
        yml = (
            'version: 1\n'
            'approved_by: "janpeter"\n'
            'identities:\n'
            '  - name: janpeter\n'
            'repositories:\n'
            '  - full_name: janpeter/app\n'
            '    actions_enabled: true\n'
            '    workflow_source: .forgejo/workflows\n'
            '    writers: [janpeter]\n'
            f'    {regel}\n'
        )
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as fh:
            fh.write(yml)
            path = fh.name
        try:
            allowlist = trust_scope_cli.load_allowlist(path)
        finally:
            pathlib.Path(path).unlink()
        inv = {"repositories": [{
            "full_name": "janpeter/app", "has_actions": True,
            "workflow_source": ".forgejo/workflows", "writers": ["janpeter"],
            "risky_triggers": ["pull_request"], "gebruikt_gedeeld_label": True,
            "branch_protection": [{"branch_name": "main"}],
            "default_branch": "main", "unreadable": [],
        }], "unreadable": []}
        return trust_scope.classify(inv, allowlist)

    def test_echte_lijst_via_loader_wordt_accepted(self):
        verdict = self._classify_ack_regel("risky_triggers_acknowledged: [pull_request]")
        self.assertTrue(verdict.ok, f"onverwacht rood: {verdict.hard}")
        self.assertTrue(any("pull_request" in a for a in verdict.accepted))

    def test_gequote_scalar_via_loader_is_fail_closed(self):
        # Regressie voor de MAJOR uit reviewronde 1 (mac:codex): de gequote
        # YAML-string "[pull_request]" mag de gate niet groen maken.
        verdict = self._classify_ack_regel('risky_triggers_acknowledged: "[pull_request]"')
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.accepted, [])
        self.assertTrue(any("pull_request" in h for h in verdict.hard))


if __name__ == "__main__":
    unittest.main()
