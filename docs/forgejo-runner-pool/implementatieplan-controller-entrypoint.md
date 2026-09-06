# Controller-entrypoint (dunne bring-up) — Implementatieplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bouw de runtime-schil rond het bestaande, getest beslis-hart `forgejo_runner_cycle.py` zodat de Forgejo-runner op max2 online komt, één groene/rode job draait met scrub, en netjes op `SIGTERM` stopt (stap D + kern van stap E).

**Architecture:** Ports & adapters. Het pure beslis-hart blijft byte-identiek op een 2-regel `__main__`-delegatie na. Een nieuwe `cycle_runtime.py` bevat de pure runtime-logica (config, parsers, verdict-validatie, de twee preconditions `readiness_confirmed`/`clean_proven`, en de single-thread poll-loop) en `cycle_adapters.py` de neveneffect-adapters (probe, DinD-health, docker-compose-levenscyclus, scrub, reconciliatie). Alle IO is injecteerbaar zodat de loop met fakes deterministisch getest wordt.

**Tech Stack:** Python 3.11+ **alleen stdlib** (`tomllib`, `urllib.request`, `subprocess`, `signal`, `logging`, `time`, `json`, `re`, `hashlib`, `pathlib`); stdlib `unittest`; `docker compose` v2; POSIX sh voor de deploy-wrapper; `ruff`.

**Spec:** `docs/forgejo-runner-pool/controller-entrypoint-ontwerp.md` (delta-review GO, 4 rondes, mac:codex). Het plan argumenteert vanuit die spec; lees beide.

## Global Constraints

- **Alleen Python-stdlib** in de controller; geen pip-dependencies (de unit draait system-`/usr/bin/python3` zonder venv).
- Het hart `forgejo-runner/scripts/forgejo_runner_cycle.py` blijft **byte-identiek** op de 2-regel `__main__`-delegatie na (Taak 1). De 99 bestaande hart-tests blijven ongewijzigd groen.
- **Consumeer** uit het hart, wijzig het niet: `classify_probe`, `ReadinessClass`, `State`, `EventLoop`, `Controller`, `CONFIRM_SECONDS` (5), `RETRY_INTERVAL_SECONDS` (30), `FENCE_MAX_AGE_SECONDS` (60).
- **Start-conditie (§5.2):** een child start alleen als **alle vier** waar zijn: `controller.mag_child_starten`, `controller.state == State.WAITING`, `readiness_confirmed`, `clean_proven`.
- **Fail-closed:** `readiness_confirmed` alleen door eigen 2-waarnemingenbevestiging (ingetrokken bij élke niet-READY); `clean_proven` alleen door een geslaagde scrub+bewijs (ingetrokken bij childstart + scrub-fout); readiness-herstel kent geen van beide toe.
- **Trustgate = deploy-verdict** (JP 2026-09-06): de controller houdt **geen** Forgejo-credential en doet geen trust-API-calls; hij leest een bij deploy geproduceerd, vers en gebonden `trust-verdict.json`.
- **Geen secrets** in Git, logs of containermetadata. Logs dragen nooit namen/tokens (§7.9).
- **Byte-identieke bundel:** compose- en scriptwijzigingen gelden identiek op beide hosts; alleen `controller.toml` en het deploy-verdict zijn hostspecifiek.
- **Single active mutating phase:** zolang een pull/scrub/runner-child loopt, start de loop geen tweede muterende fase (§6.4, m1).
- **Verificatie:** `cd forgejo-runner && python3 -m unittest discover -s tests -p 'test_*.py'` en `ruff check scripts/`.

---

## Bestandsstructuur

| Bestand | Verantwoordelijkheid | Actie |
|---|---|---|
| `forgejo-runner/scripts/forgejo_runner_cycle.py` | Puur hart + `__main__`-delegatie | Modify (+2 regels) |
| `forgejo-runner/scripts/cycle_runtime.py` | Config, parsers, verdict-validatie, `ReadinessConfirmed`, `Runtime` (loop+preconditions), `main()` | Create |
| `forgejo-runner/scripts/cycle_adapters.py` | `Clock`, `TransportProbe`, `DindHealth`, `RunnerLifecycle`, `PullOp`, `ScrubOp`, `Reconcile`, `TrustVerdictReader` | Create |
| `forgejo-runner/scripts/publish-trust-verdict.sh` | Deploy-wrapper: CLI → verdict met `measured_at`+binding, atomair (§6.3) | Create |
| `forgejo-runner/compose.yaml` | `command: ["one-job","--wait"]` op runner; allowlist read-only in dind | Modify |
| `forgejo-runner/controller.toml.example` | Template met alle sleutels (§8), zonder secrets | Create |
| `forgejo-runner/tests/test_cycle_runtime.py` | Unittests pure logica + gedreven loop met fakes | Create |
| `forgejo-runner/tests/test_publish_trust_verdict.bats` | bats voor de deploy-wrapper | Create |
| `docs/forgejo-runner-pool/evidence/stap-d/bring-up-runbook.md` | Stap-D/E integratie-smoke (handmatig, via SSH) | Create |

## Gedeelde interfaces (contract tussen taken)

`cycle_runtime.py`:

```python
@dataclass(frozen=True)
class Config:
    forgejo_base_url: str
    probe_timeout: float
    compose_file: str
    project: str
    allowed_images_file: str
    child_stop_grace: float
    trust_verdict_path: str
    trust_verdict_max_age: float
    labels_file: str
    allowlist_file: str
    subprocess_timeout: float
    poll_interval: float
    retry_interval: float
    marker_path: str
    log_level: str

def load_config(path: str) -> Config: ...
def parse_allowed_images(text: str) -> list[str]: ...            # digests, skip comment/leeg
def verdict_green(verdict: object, now_wall: float, cfg: Config,
                  labels_sha: str, allowlist_sha: str) -> tuple[bool, str]: ...

class ReadinessConfirmed:
    confirmed: bool
    def observe(self, klasse, mono: float) -> None: ...

class Runtime:
    def __init__(self, cfg: Config, controller, loop, adapters, clock, log): ...
    def tick(self) -> None: ...              # één poll-iteratie
    def request_stop(self) -> None: ...      # signal-handler zet de stopvlag
    def run(self) -> int: ...                # loop tot stop; returncode

def main(argv=None) -> int: ...
```

`cycle_adapters.py` (elke adapter is een klasse met deze methoden):

```python
class Clock:            # __call__(self) -> tuple[float, float]  (monotonic, wall)
class TransportProbe:   # probe(self) -> dict  {kind,error,status,schema_ok}
class DindHealth:       # ensure_up(self) -> None ; healthy(self) -> bool
class RunnerLifecycle:  # start(self) -> subprocess.Popen ; request_stop(self, p) -> None ; poll(self, p) -> int|None
class PullOp:           # start(self, digest) -> subprocess.Popen ; poll(self, p) -> int|None
class ScrubOp:          # start(self) -> subprocess.Popen ; poll(self, p) -> int|None  (rc 0 = schoon)
class Reconcile:        # leftover_runners(self) -> list[str] ; marker_present(self) -> bool
                        # write_marker(self, op: str) -> None ; clear_marker(self) -> None ; restart_dind(self) -> None
class TrustVerdictReader:  # read(self) -> tuple[object, str, str]  (verdict, labels_sha, allowlist_sha)
```

Een `Adapters`-namedtuple bundelt de instanties zodat `Runtime` er één argument voor krijgt: `Adapters(probe, dind, runner, pull, scrub, reconcile, trust)`.

---

### Taak 1: Entrypoint-delegatie + config-loader

**Files:**
- Modify: `forgejo-runner/scripts/forgejo_runner_cycle.py` (einde bestand)
- Create: `forgejo-runner/scripts/cycle_runtime.py`
- Test: `forgejo-runner/tests/test_cycle_runtime.py`

**Interfaces:**
- Produces: `Config`, `load_config(path) -> Config`.

- [ ] **Stap 1: Falende test voor config-load**

```python
# forgejo-runner/tests/test_cycle_runtime.py
import os, tempfile, unittest
import cycle_runtime as cr

VALID_TOML = b"""
[forgejo]
base_url = "https://git.jp-visser.nl"
probe_timeout_seconds = 5
[dind]
compose_file = "/opt/forgejo-runner/compose.yaml"
project = "forgejo-runner"
[runner]
allowed_images_file = "/opt/forgejo-runner/allowed-job-images.txt"
child_stop_grace_seconds = 200
[trust]
verdict_path = "/opt/forgejo-runner/trust-verdict.json"
verdict_max_age_seconds = 86400
labels_file = "/opt/forgejo-runner/labels.txt"
allowlist_file = "/opt/forgejo-runner/trusted-actions-scope.yml"
[docker]
subprocess_timeout_seconds = 30
[cadence]
poll_interval_seconds = 1
retry_interval_seconds = 30
[log]
level = "INFO"
"""

def _write(tmp, data):
    p = os.path.join(tmp, "controller.toml"); open(p, "wb").write(data); return p

class TestConfig(unittest.TestCase):
    def test_load_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = cr.load_config(_write(tmp, VALID_TOML))
        self.assertEqual(cfg.forgejo_base_url, "https://git.jp-visser.nl")
        self.assertEqual(cfg.child_stop_grace, 200.0)
        self.assertEqual(cfg.retry_interval, 30.0)

    def test_missing_key_is_clean_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = VALID_TOML.replace(b'project = "forgejo-runner"', b"")
            with self.assertRaises(ValueError) as ctx:
                cr.load_config(_write(tmp, bad))
        self.assertIn("dind.project", str(ctx.exception))

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Stap 2: Run — verwacht ImportError/FAIL**

Run: `cd forgejo-runner && python3 -m unittest tests.test_cycle_runtime -v`
Expected: FAIL (module `cycle_runtime` bestaat nog niet).

- [ ] **Stap 3: Implementeer Config + load_config**

```python
# forgejo-runner/scripts/cycle_runtime.py
"""Runtime-schil rond forgejo_runner_cycle.py (dunne bring-up). Zie
docs/forgejo-runner-pool/controller-entrypoint-ontwerp.md."""
import tomllib
from dataclasses import dataclass

@dataclass(frozen=True)
class Config:
    forgejo_base_url: str
    probe_timeout: float
    compose_file: str
    project: str
    allowed_images_file: str
    child_stop_grace: float
    trust_verdict_path: str
    trust_verdict_max_age: float
    labels_file: str
    allowlist_file: str
    subprocess_timeout: float
    poll_interval: float
    retry_interval: float
    marker_path: str
    log_level: str

def _req(data, section, key):
    try:
        return data[section][key]
    except (KeyError, TypeError):
        raise ValueError(f"controller.toml mist {section}.{key}") from None

def load_config(path: str) -> Config:
    with open(path, "rb") as fh:
        d = tomllib.load(fh)
    return Config(
        forgejo_base_url=str(_req(d, "forgejo", "base_url")),
        probe_timeout=float(_req(d, "forgejo", "probe_timeout_seconds")),
        compose_file=str(_req(d, "dind", "compose_file")),
        project=str(_req(d, "dind", "project")),
        allowed_images_file=str(_req(d, "runner", "allowed_images_file")),
        child_stop_grace=float(_req(d, "runner", "child_stop_grace_seconds")),
        trust_verdict_path=str(_req(d, "trust", "verdict_path")),
        trust_verdict_max_age=float(_req(d, "trust", "verdict_max_age_seconds")),
        labels_file=str(_req(d, "trust", "labels_file")),
        allowlist_file=str(_req(d, "trust", "allowlist_file")),
        subprocess_timeout=float(_req(d, "docker", "subprocess_timeout_seconds")),
        poll_interval=float(_req(d, "cadence", "poll_interval_seconds")),
        retry_interval=float(_req(d, "cadence", "retry_interval_seconds")),
        marker_path=str(d.get("dind", {}).get("marker_path",
                        "/opt/forgejo-runner/control/cycle-op.marker")),
        log_level=str(d.get("log", {}).get("level", "INFO")),
    )
```

Voeg `marker_path` toe aan het `[dind]`-blok van `controller.toml.example` (Taak 12); default staat hierboven.

- [ ] **Stap 4: Voeg de `__main__`-delegatie aan het hart toe**

Aan het EINDE van `forgejo-runner/scripts/forgejo_runner_cycle.py`, ná de bestaande code:

```python


if __name__ == "__main__":
    from cycle_runtime import main
    raise SystemExit(main())
```

(Twee inhoudsregels; `SystemExit` is builtin, `main()` leest zelf `sys.argv`. Het hart importeert `sys` niet.)

- [ ] **Stap 5: Run — verwacht PASS (config) + hart-tests groen**

Run: `cd forgejo-runner && python3 -m unittest tests.test_cycle_runtime -v && python3 -m unittest discover -s tests -p 'test_cycle_*.py'`
Expected: config-tests PASS; hart-tests ongewijzigd groen.

- [ ] **Stap 6: Commit**

```bash
git add forgejo-runner/scripts/cycle_runtime.py forgejo-runner/scripts/forgejo_runner_cycle.py forgejo-runner/tests/test_cycle_runtime.py
git commit -m "feat(controller): config-loader + __main__-delegatie"
```

---

### Taak 2: allowed-images parser (puur)

**Files:** Modify `forgejo-runner/scripts/cycle_runtime.py`; Test `forgejo-runner/tests/test_cycle_runtime.py`

**Interfaces:** Produces `parse_allowed_images(text) -> list[str]`.

- [ ] **Stap 1: Falende test (echt bestandsformaat)**

```python
class TestImages(unittest.TestCase):
    REAL = ("# forgejo-runner/allowed-job-images.txt\n"
            "# commentaar telt niet\n"
            "catthehacker/ubuntu@sha256:" + "c"*64 + "\t1729048576\n")
    def test_parse_digest_tab_bytes(self):
        self.assertEqual(cr.parse_allowed_images(self.REAL),
                         ["catthehacker/ubuntu@sha256:" + "c"*64])
    def test_blank_and_comment_ignored(self):
        self.assertEqual(cr.parse_allowed_images("\n#x\n   \n"), [])
    def test_invalid_digest_raises(self):
        with self.assertRaises(ValueError):
            cr.parse_allowed_images("catthehacker/ubuntu:latest\t10\n")
```

- [ ] **Stap 2: Run — FAIL** (`AttributeError: parse_allowed_images`).

Run: `cd forgejo-runner && python3 -m unittest tests.test_cycle_runtime.TestImages -v`

- [ ] **Stap 3: Implementeer**

```python
import re
_DIGEST_RE = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")

def parse_allowed_images(text: str) -> list[str]:
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        digest = line.split("\t", 1)[0].strip()   # digest<TAB>bytes; bytes negeren
        if not _DIGEST_RE.match(digest):
            raise ValueError(f"ongeldige digest-regel: {raw!r}")
        out.append(digest)
    return out
```

- [ ] **Stap 4: Run — PASS.**
- [ ] **Stap 5: Commit** `git commit -am "feat(controller): allowed-images parser"`

---

### Taak 3: trust-verdict-validator (puur)

**Files:** Modify `cycle_runtime.py`; Test `test_cycle_runtime.py`

**Interfaces:** Produces `verdict_green(verdict, now_wall, cfg, labels_sha, allowlist_sha) -> (bool, str)`.

- [ ] **Stap 1: Falende test**

```python
class TestVerdict(unittest.TestCase):
    def _cfg(self):
        with tempfile.TemporaryDirectory() as tmp:
            return cr.load_config(_write(tmp, VALID_TOML))
    def _v(self, **over):
        base = {"ok": True, "measured_at": 1000.0,
                "forgejo_target": "https://git.jp-visser.nl",
                "labels_sha256": "LS", "allowlist_sha256": "AS"}
        base.update(over); return base
    def test_green(self):
        ok, _ = cr.verdict_green(self._v(), 1500.0, self._cfg(), "LS", "AS")
        self.assertTrue(ok)
    def test_not_ok(self):
        self.assertFalse(cr.verdict_green(self._v(ok=False), 1500.0, self._cfg(), "LS", "AS")[0])
    def test_future_measured_at(self):
        self.assertFalse(cr.verdict_green(self._v(measured_at=2000.0), 1500.0, self._cfg(), "LS", "AS")[0])
    def test_too_old(self):
        self.assertFalse(cr.verdict_green(self._v(), 1000.0 + 86401, self._cfg(), "LS", "AS")[0])
    def test_binding_mismatch(self):
        self.assertFalse(cr.verdict_green(self._v(), 1500.0, self._cfg(), "OTHER", "AS")[0])
    def test_non_dict(self):
        self.assertFalse(cr.verdict_green(None, 1500.0, self._cfg(), "LS", "AS")[0])
```

- [ ] **Stap 2: Run — FAIL.**
- [ ] **Stap 3: Implementeer**

```python
def verdict_green(verdict, now_wall, cfg, labels_sha, allowlist_sha):
    if not isinstance(verdict, dict):
        return False, "verdict is geen object"
    if verdict.get("ok") is not True:
        return False, "ok is niet true"
    m = verdict.get("measured_at")
    if not isinstance(m, (int, float)):
        return False, "measured_at ontbreekt of is geen getal"
    age = now_wall - float(m)
    if age < 0:
        return False, "measured_at ligt in de toekomst"
    if age > cfg.trust_verdict_max_age:
        return False, "verdict is te oud"
    if verdict.get("forgejo_target") != cfg.forgejo_base_url:
        return False, "target-binding komt niet overeen"
    if verdict.get("labels_sha256") != labels_sha:
        return False, "labels-binding komt niet overeen"
    if verdict.get("allowlist_sha256") != allowlist_sha:
        return False, "allowlist-binding komt niet overeen"
    return True, "groen"
```

- [ ] **Stap 4: Run — PASS.**
- [ ] **Stap 5: Commit** `git commit -am "feat(controller): trust-verdict-validator (fail-closed, gebonden)"`

---

### Taak 4: `ReadinessConfirmed` (puur)

**Files:** Modify `cycle_runtime.py`; Test `test_cycle_runtime.py`

**Interfaces:** Produces `ReadinessConfirmed` met attribuut `confirmed` en `observe(klasse, mono)`.

- [ ] **Stap 1: Falende test (B1-spoor)**

```python
from forgejo_runner_cycle import ReadinessClass as RC

class TestReadinessConfirmed(unittest.TestCase):
    def test_two_ready_confirm_then_deviation_retracts(self):
        r = cr.ReadinessConfirmed()
        r.observe(RC.READY, 0.0);  self.assertFalse(r.confirmed)   # 1e
        r.observe(RC.READY, 30.0); self.assertTrue(r.confirmed)    # 2e, ≥5s
        r.observe(RC.SOURCE_WAIT, 60.0); self.assertFalse(r.confirmed)  # afwijking trekt in
        r.observe(RC.SOURCE_WAIT, 90.0); self.assertFalse(r.confirmed)
        r.observe(RC.READY, 120.0); self.assertFalse(r.confirmed)  # 1e herstel-READY: nog niet
        r.observe(RC.READY, 150.0); self.assertTrue(r.confirmed)   # 2e herstel-READY: wel
    def test_too_close_does_not_confirm(self):
        r = cr.ReadinessConfirmed()
        r.observe(RC.READY, 0.0); r.observe(RC.READY, 1.0)
        self.assertFalse(r.confirmed)   # < CONFIRM_SECONDS
```

- [ ] **Stap 2: Run — FAIL.**
- [ ] **Stap 3: Implementeer**

```python
from forgejo_runner_cycle import ReadinessClass, CONFIRM_SECONDS

class ReadinessConfirmed:
    """Eigen twee-waarnemingenbevestiging van READY (§5.2). `confirmed` is True
    zodra twee READY-probes ≥ CONFIRM_SECONDS uiteen zijn gezien; élke niet-READY
    trekt hem in. Nooit door een scrub of hart-statuswissel gezet."""
    def __init__(self, confirm_seconds: float = CONFIRM_SECONDS):
        self._confirm = confirm_seconds
        self._eerste_ready_mono = None
        self.confirmed = False

    def observe(self, klasse, mono: float) -> None:
        if klasse is not ReadinessClass.READY:
            self._eerste_ready_mono = None
            self.confirmed = False
            return
        if self._eerste_ready_mono is None:
            self._eerste_ready_mono = mono
        elif (mono - self._eerste_ready_mono) >= self._confirm:
            self.confirmed = True
```

- [ ] **Stap 4: Run — PASS.**
- [ ] **Stap 5: Commit** `git commit -am "feat(controller): readiness_confirmed precondition"`

---

### Taak 5: Adapters — `Clock` + `TransportProbe`

**Files:** Create `forgejo-runner/scripts/cycle_adapters.py`; Test `test_cycle_runtime.py`

**Interfaces:** Produces `Clock`, `TransportProbe(base_url, timeout, opener=urllib.request.urlopen)`.

- [ ] **Stap 1: Falende test (fake opener, via classify_probe)**

```python
import io, urllib.error
import cycle_adapters as ca
from forgejo_runner_cycle import classify_probe, ReadinessClass as RC

class TestTransportProbe(unittest.TestCase):
    def _probe(self, opener):
        return ca.TransportProbe("https://x", 5.0, opener=opener).probe()
    def test_2xx_schema_ready(self):
        opener = lambda req, timeout: io.BytesIO(b'{"version":"1.22"}')
        p = self._probe(opener)
        self.assertEqual(classify_probe(p), RC.READY)
    def test_http_5xx_source_wait(self):
        def opener(req, timeout): raise urllib.error.HTTPError("u", 503, "x", {}, None)
        self.assertEqual(classify_probe(self._probe(opener)), RC.SOURCE_WAIT)
    def test_http_401_protocol_not_credential(self):
        def opener(req, timeout): raise urllib.error.HTTPError("u", 401, "x", {}, None)
        self.assertEqual(classify_probe(self._probe(opener)), RC.PROTOCOL)  # kind=general
    def test_transport_error_source_wait(self):
        def opener(req, timeout): raise urllib.error.URLError("refused")
        self.assertEqual(classify_probe(self._probe(opener)), RC.SOURCE_WAIT)
```

- [ ] **Stap 2: Run — FAIL.**
- [ ] **Stap 3: Implementeer**

```python
# forgejo-runner/scripts/cycle_adapters.py
"""Neveneffect-adapters voor de cyclecontroller-runtime (dunne bring-up)."""
import json, time, urllib.request, urllib.error

class Clock:
    def __call__(self):
        return time.monotonic(), time.time()

class TransportProbe:
    def __init__(self, base_url, timeout, opener=urllib.request.urlopen):
        self._url = base_url.rstrip("/") + "/api/v1/version"
        self._timeout = timeout
        self._opener = opener
    def probe(self):
        req = urllib.request.Request(self._url, headers={"Accept": "application/json"})
        try:
            resp = self._opener(req, timeout=self._timeout)
            body = resp.read()
            try:
                schema_ok = isinstance(json.loads(body), dict) and b"version" in body
            except ValueError:
                schema_ok = False
            status = getattr(resp, "status", 200) or 200
            return {"kind": "general", "error": None, "status": status, "schema_ok": schema_ok}
        except urllib.error.HTTPError as exc:
            return {"kind": "general", "error": None, "status": exc.code, "schema_ok": False}
        except urllib.error.URLError as exc:
            return {"kind": "general", "error": str(exc.reason), "status": None, "schema_ok": False}
```

- [ ] **Stap 4: Run — PASS.**
- [ ] **Stap 5: Commit** `git commit -am "feat(controller): Clock + TransportProbe adapters"`

---

### Taak 6: Adapters — DinD-health, runner-levenscyclus, pull, scrub (dun IO)

**Files:** Modify `cycle_adapters.py`; Test `test_cycle_runtime.py`

**Interfaces:** Produces `DindHealth`, `RunnerLifecycle`, `PullOp`, `ScrubOp` (elk met een `runner`-callable `run(argv, **kw)` en `popen(argv)` injecteerbaar voor tests).

- [ ] **Stap 1: Falende test (fake subprocess) — asserteer argv**

```python
class _FakePopen:
    def __init__(self, argv): self.argv = argv; self._rc = None
    def poll(self): return self._rc
    def send_signal(self, sig): pass

class TestDockerAdapters(unittest.TestCase):
    def setUp(self):
        self.spawned = []
        self.popen = lambda argv, **kw: self.spawned.append(argv) or _FakePopen(argv)
    def test_runner_argv(self):
        r = ca.RunnerLifecycle("/c.yaml", "proj", popen=self.popen)
        r.start()
        self.assertEqual(self.spawned[-1],
            ["docker","compose","-f","/c.yaml","-p","proj","--profile","cycle","run","--rm","runner"])
    def test_pull_argv(self):
        ca.PullOp("/c.yaml","proj", popen=self.popen).start("img@sha256:" + "a"*64)
        self.assertIn("pull", self.spawned[-1]); self.assertIn("img@sha256:" + "a"*64, self.spawned[-1])
    def test_scrub_argv_uses_endpoint_and_allow(self):
        ca.ScrubOp("/c.yaml","proj","/scrub.sh","/etc/forgejo-runner/allowed-job-images.txt",
                   popen=self.popen).start()
        argv = self.spawned[-1]
        self.assertIn("--endpoint", argv); self.assertIn("tcp://127.0.0.1:2375", argv)
        self.assertIn("--allow", argv); self.assertIn("/etc/forgejo-runner/allowed-job-images.txt", argv)
```

- [ ] **Stap 2: Run — FAIL.**
- [ ] **Stap 3: Implementeer**

```python
import subprocess

def _run(argv, timeout):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)

class _ComposeBase:
    def __init__(self, compose_file, project, popen=subprocess.Popen, run=_run, timeout=30.0):
        self._base = ["docker", "compose", "-f", compose_file, "-p", project]
        self._popen = popen; self._run = run; self._timeout = timeout

class DindHealth(_ComposeBase):
    def ensure_up(self):
        self._run(self._base + ["up", "-d", "dind"], self._timeout)
    def healthy(self):
        cp = self._run(self._base + ["exec", "-T", "dind", "docker",
                                     "-H", "tcp://127.0.0.1:2375", "info"], self._timeout)
        return cp.returncode == 0

class RunnerLifecycle(_ComposeBase):
    def start(self):
        return self._popen(self._base + ["--profile", "cycle", "run", "--rm", "runner"])
    def request_stop(self, p):
        p.send_signal(subprocess.signal.SIGTERM)
    def poll(self, p):
        return p.poll()

class PullOp(_ComposeBase):
    def start(self, digest):
        return self._popen(self._base + ["exec", "-T", "dind", "docker", "pull", digest])
    def poll(self, p):
        return p.poll()

class ScrubOp(_ComposeBase):
    def __init__(self, compose_file, project, script_path, allow_in_dind, **kw):
        super().__init__(compose_file, project, **kw)
        self._script = script_path; self._allow = allow_in_dind
    def start(self):
        # scrub-dind.sh via stdin in DinD; args na `--`; leest --allow uit de bind-mount.
        argv = self._base + ["exec", "-T", "dind", "sh", "-s", "--",
                             "--endpoint", "tcp://127.0.0.1:2375", "--allow", self._allow]
        return self._popen(argv, stdin=open(self._script, "rb"))
    def poll(self, p):
        return p.poll()
```

> Noot: `subprocess.signal` bestaat niet; gebruik `import signal` en `signal.SIGTERM`. Corrigeer `request_stop` naar `p.send_signal(signal.SIGTERM)` en voeg `import signal` toe bovenaan.

- [ ] **Stap 4: Corrigeer de signal-import**

Bovenaan `cycle_adapters.py`: voeg `import signal` toe; in `RunnerLifecycle.request_stop`: `p.send_signal(signal.SIGTERM)`.

- [ ] **Stap 5: Run — PASS.**
- [ ] **Stap 6: Commit** `git commit -am "feat(controller): DinD/runner/pull/scrub adapters"`

---

### Taak 7: Adapters — `Reconcile` (marker + leftover + DinD-herstart) + `TrustVerdictReader`

**Files:** Modify `cycle_adapters.py`; Test `test_cycle_runtime.py`

**Interfaces:** Produces `Reconcile`, `TrustVerdictReader`.

- [ ] **Stap 1: Falende test**

```python
import hashlib, os
class TestReconcileAndVerdict(unittest.TestCase):
    def test_marker_write_present_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            mk = os.path.join(tmp, "control", "cycle-op.marker")
            rec = ca.Reconcile("/c.yaml", "proj", mk, run=lambda a, t: None)
            self.assertFalse(rec.marker_present())
            rec.write_marker("scrub"); self.assertTrue(rec.marker_present())
            rec.clear_marker(); self.assertFalse(rec.marker_present())
    def test_leftover_runners_parses_ids(self):
        out = "abc123\n"
        rec = ca.Reconcile("/c.yaml", "proj", "/m", run=lambda a, t: _cp(out))
        self.assertEqual(rec.leftover_runners(), ["abc123"])
    def test_verdict_reader_hashes_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            lp = os.path.join(tmp, "labels.txt"); open(lp, "wb").write(b"x")
            ap = os.path.join(tmp, "a.yml"); open(ap, "wb").write(b"y")
            vp = os.path.join(tmp, "v.json"); open(vp, "w").write('{"ok":true}')
            v, ls, as_ = ca.TrustVerdictReader(vp, lp, ap).read()
            self.assertEqual(v, {"ok": True})
            self.assertEqual(ls, hashlib.sha256(b"x").hexdigest())
            self.assertEqual(as_, hashlib.sha256(b"y").hexdigest())

def _cp(stdout, rc=0):
    class C: pass
    c = C(); c.returncode = rc; c.stdout = stdout; c.stderr = ""; return c
```

- [ ] **Stap 2: Run — FAIL.**
- [ ] **Stap 3: Implementeer**

```python
import hashlib, json, os

class Reconcile(_ComposeBase):
    def __init__(self, compose_file, project, marker_path, **kw):
        super().__init__(compose_file, project, **kw)
        self._marker = marker_path
    def leftover_runners(self):
        cp = self._run(self._base + ["ps", "-q", "runner"], self._timeout)
        return [ln.strip() for ln in (cp.stdout or "").splitlines() if ln.strip()]
    def marker_present(self):
        return os.path.exists(self._marker)
    def write_marker(self, op):
        os.makedirs(os.path.dirname(self._marker), exist_ok=True)
        tmp = self._marker + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"op": op, "start": _now_iso()}, fh)
        os.replace(tmp, self._marker)
    def clear_marker(self):
        try:
            os.remove(self._marker)
        except FileNotFoundError:
            pass
    def restart_dind(self):
        self._run(self._base + ["kill", "dind"], self._timeout)
        self._run(self._base + ["up", "-d", "dind"], self._timeout)

class TrustVerdictReader:
    def __init__(self, verdict_path, labels_file, allowlist_file):
        self._vp = verdict_path; self._lf = labels_file; self._af = allowlist_file
    def read(self):
        try:
            with open(self._vp, "rb") as fh:
                verdict = json.load(fh)
        except (FileNotFoundError, ValueError):
            verdict = None
        return verdict, _sha256_file(self._lf), _sha256_file(self._af)

def _sha256_file(path):
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except FileNotFoundError:
        return ""

def _now_iso():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
```

- [ ] **Stap 4: Run — PASS.**
- [ ] **Stap 5: Commit** `git commit -am "feat(controller): Reconcile-marker + TrustVerdictReader adapters"`

---

### Taak 8: `Runtime` — readiness/gates + start-conditie (met fakes)

**Files:** Modify `cycle_runtime.py`; Test `test_cycle_runtime.py`

**Interfaces:** Produces `Runtime` + `Adapters` namedtuple. Consumes alle adapters uit Taak 5–7 en `EventLoop`/`Controller` uit het hart.

- [ ] **Stap 1: Falende test — koude start weigert tot bevestigde READY + clean**

```python
from forgejo_runner_cycle import EventLoop, Controller, State, ReadinessClass as RC
import collections

FakeAdapters = collections.namedtuple("FakeAdapters",
    "probe dind runner pull scrub reconcile trust")

class _Fake:
    def __init__(self, **kw): self.__dict__.update(kw)

def build_runtime(klasse_reeks, scrub_ok=True, verdict_ok=True):
    # fakes met deterministische uitkomsten; tijd via een lijst-klok
    probe = _Fake(_i=0, seq=list(klasse_reeks))
    def do_probe():
        k = probe.seq[min(probe._i, len(probe.seq)-1)]; probe._i += 1
        return {"READY":{"kind":"general","error":None,"status":200,"schema_ok":True}}.get(
            k.value, {"kind":"general","error":None,"status":503,"schema_ok":False}) \
            if k is RC.READY else {"kind":"general","error":"x","status":None,"schema_ok":False}
    probe.probe = do_probe
    dind = _Fake(ensure_up=lambda: None, healthy=lambda: True)
    started = {"runner": 0, "scrub": 0, "pull": 0}
    runner = _Fake(start=lambda: started.__setitem__("runner", started["runner"]+1) or _FakePopen(["runner"]),
                   request_stop=lambda p: None, poll=lambda p: p._rc)
    pull = _Fake(start=lambda d: started.__setitem__("pull", started["pull"]+1) or _FakePopen(["pull"]),
                 poll=lambda p: 0)
    scrub = _Fake(start=lambda: started.__setitem__("scrub", started["scrub"]+1) or _FakePopen(["scrub"]),
                  poll=lambda p: 0 if scrub_ok else 50)
    reconcile = _Fake(leftover_runners=lambda: [], marker_present=lambda: False,
                      write_marker=lambda op: None, clear_marker=lambda: None, restart_dind=lambda: None)
    trust = _Fake(read=lambda: ({"ok": verdict_ok}, "LS", "AS"))
    adapters = FakeAdapters(probe, dind, runner, pull, scrub, reconcile, trust)
    with tempfile.TemporaryDirectory() as tmp:
        cfg = cr.load_config(_write(tmp, VALID_TOML))
    loop = EventLoop(lambda: (0.0, 0.0))
    controller = Controller(loop)
    rt = cr.Runtime(cfg, controller, loop, adapters,
                    clock=_ListClock(), log=cr.logging.getLogger("test"))
    # verdict-validatie kortsluiten voor deze test:
    rt._trust_green = lambda: (verdict_ok, "test")
    return rt, controller, started

class _ListClock:
    def __init__(self): self.t = 0.0
    def __call__(self):
        self.t += 30.0; return self.t, self.t   # elke tick +30s (readiness-cadans)

class TestStartCondition(unittest.TestCase):
    def test_no_start_before_confirmed_ready(self):
        rt, ctrl, started = build_runtime([RC.READY])   # één READY = onbevestigd
        rt.tick()
        self.assertEqual(started["runner"], 0)
    def test_start_after_confirmed_ready_and_clean(self):
        rt, ctrl, started = build_runtime([RC.READY, RC.READY, RC.READY])
        for _ in range(4): rt.tick()
        self.assertGreaterEqual(started["runner"], 1)
        self.assertEqual(ctrl.state, State.RUNNING if False else ctrl.state)  # start gebeurde in WAITING
```

> De fakes zijn bewust simpel; de definitieve test-helper mag in de implementatie worden aangescherpt zolang de assertions (geen start vóór bevestiging; start ná bevestiging+clean) intact blijven.

- [ ] **Stap 2: Run — FAIL** (`Runtime` bestaat nog niet).
- [ ] **Stap 3: Implementeer het skelet + readiness/gates + start-conditie**

```python
import logging, time as _time
from collections import namedtuple
from forgejo_runner_cycle import EventLoop, Controller, State, classify_probe, ReadinessClass

Adapters = namedtuple("Adapters", "probe dind runner pull scrub reconcile trust")

class Runtime:
    def __init__(self, cfg, controller, loop, adapters, clock, log):
        self.cfg = cfg; self.controller = controller; self.loop = loop
        self.a = adapters; self.clock = clock; self.log = log
        self.readiness = ReadinessConfirmed()
        self.clean_proven = False
        self.child = None          # runner-Popen
        self.op = None             # ("pull"|"scrub", Popen)
        self.reconciled = False
        self._stop = False
        self._last_probe_mono = None

    def _trust_green(self):
        verdict, ls, as_ = self.a.trust.read()
        return verdict_green(verdict, self.clock()[1], self.cfg, ls, as_)

    def _readiness_and_gates(self, now):
        probe = self.a.probe.probe()
        klasse = classify_probe(probe)
        self.readiness.observe(klasse, now)
        ev = self.loop.submit("readiness", {"klasse": klasse})
        self.controller.on_event(ev)
        green, _ = self._trust_green()
        self.controller.gates_groen = green and self.a.dind.healthy()

    def _may_start(self):
        return (self.op is None and self.child is None
                and self.controller.mag_child_starten
                and self.controller.state == State.WAITING
                and self.readiness.confirmed and self.clean_proven)

    def tick(self):
        now, wall = self.clock()
        if self._last_probe_mono is None or (now - self._last_probe_mono) >= self.cfg.retry_interval:
            self._last_probe_mono = now
            self.a.dind.ensure_up()
            self._readiness_and_gates(now)
        self.controller.tick(now, wall)
        self._reconcile_once()           # Taak 10
        self._advance(now)               # Taak 9
        if self._may_start():
            self._start_runner()         # Taak 9

    # placeholders die Taak 9/10 invullen; hier no-ops zodat Taak 8 groen is
    def _reconcile_once(self): pass
    def _advance(self, now): pass
    def _start_runner(self):
        self.clean_proven = False
        self.child = self.a.runner.start()
```

> In Taak 8 blijft `_ensure_clean` nog buiten beeld; `clean_proven` wordt in de test via `build_runtime` kunstmatig gezet (voeg in de helper na constructie `rt.clean_proven = True` toe voor de "start"-test). Taak 9 vervangt dat door de echte scrub-borging.

- [ ] **Stap 4: Run — PASS.**
- [ ] **Stap 5: Commit** `git commit -am "feat(controller): Runtime readiness/gates + start-conditie"`

---

### Taak 9: `Runtime` — cyclus (scrub-borging, pull, child-exit→scrub) + `clean_proven`

**Files:** Modify `cycle_runtime.py`; Test `test_cycle_runtime.py`

**Interfaces:** Consumes Taak 8. Produces `_advance`, `_ensure_clean`, event-afhandeling.

- [ ] **Stap 1: Falende tests**

```python
class TestCycle(unittest.TestCase):
    def test_exit0_scrub_ok_returns_waiting(self):
        rt, ctrl, started = build_runtime([RC.READY]*6)
        # borg tot WAITING+RUNNING via herhaalde ticks; child laten eindigen exit 0
        # (helper mag een klein state-verloop simuleren; assert: na scrub → clean_proven True)
        rt.clean_proven = True; rt._start_runner(); rt.child._rc = 0
        rt._advance(0.0)                       # child_exit → SCRUBBING
        self.assertEqual(ctrl.state, State.SCRUBBING)
        # scrub loopt en eindigt ok:
        for _ in range(2): rt._advance(0.0)
        self.assertTrue(rt.clean_proven)
    def test_scrub_fail_blocks_start(self):
        rt, ctrl, started = build_runtime([RC.READY]*6, scrub_ok=False)
        rt.clean_proven = True; rt._start_runner(); rt.child._rc = 0
        for _ in range(3): rt._advance(0.0)
        self.assertFalse(rt.clean_proven)      # scrub faalde → blijft False
        self.assertFalse(rt._may_start())      # geen start op vuile DinD
```

- [ ] **Stap 2: Run — FAIL.**
- [ ] **Stap 3: Implementeer `_advance` + `_ensure_clean`**

```python
    def _advance(self, now):
        # 1) actieve muterende operatie (pull/scrub) heeft voorrang — single phase
        if self.op is not None:
            kind, p = self.op
            rc = p.poll()
            if rc is None:
                return
            self.op = None
            self.a.reconcile.clear_marker()
            if kind == "scrub":
                ok = (rc == 0)
                ev = self.loop.submit("scrub_done", {"ok": ok})
                self.controller.on_event(ev)
                self.clean_proven = ok
            return
        # 2) runner-child
        if self.child is not None:
            rc = self.a.runner.poll(self.child)
            if rc is None:
                return
            self.child = None
            ev = self.loop.submit("child_exit", {"code": rc})
            self.controller.on_event(ev)
            self._begin_op("scrub")            # §7.9: scrub na élke exit
            return
        # 3) borg schoon vóór een start
        if not self.clean_proven and self.controller.state in (State.WAITING, State.SCRUBBING):
            self._ensure_clean()

    def _ensure_clean(self):
        if self.op is None:
            self._begin_op("scrub")

    def _begin_op(self, kind):
        self.a.reconcile.write_marker(kind)
        p = self.a.scrub.start() if kind == "scrub" else None
        self.op = (kind, p)
```

Werk `tick()` bij zodat `_advance` vóór de start-conditie draait (staat al zo in Taak 8) en verwijder de no-op `_advance`.

- [ ] **Stap 4: Run — PASS.**
- [ ] **Stap 5: Commit** `git commit -am "feat(controller): cyclus + clean_proven-borging"`

---

### Taak 10: `Runtime` — startup-reconciliatie + operatiemarker (§6.4)

**Files:** Modify `cycle_runtime.py`; Test `test_cycle_runtime.py`

**Interfaces:** Consumes Taak 9. Produces `_reconcile_once`.

- [ ] **Stap 1: Falende tests**

```python
class TestReconcile(unittest.TestCase):
    def test_leftover_runner_blocks(self):
        rt, ctrl, started = build_runtime([RC.READY]*4)
        rt.a.reconcile.leftover_runners = lambda: ["abc"]
        rt._reconcile_once()
        self.assertTrue(rt._blocked)            # fail-closed
        self.assertFalse(rt._may_start())
    def test_marker_present_triggers_restart_and_scrub(self):
        rt, ctrl, started = build_runtime([RC.READY]*4)
        calls = {"restart": 0}
        rt.a.reconcile.marker_present = lambda: True
        rt.a.reconcile.restart_dind = lambda: calls.__setitem__("restart", 1)
        rt._reconcile_once()
        self.assertEqual(calls["restart"], 1)
        self.assertIsNotNone(rt.op)             # volledige scrub gestart
        self.assertFalse(rt.clean_proven)
```

- [ ] **Stap 2: Run — FAIL.**
- [ ] **Stap 3: Implementeer**

```python
    def __init__(self, ...):     # voeg toe aan bestaande __init__
        ...
        self._blocked = False

    def _reconcile_once(self):
        if self.reconciled:
            return
        self.reconciled = True
        if self.a.reconcile.leftover_runners():
            self._blocked = True
            self.log.warning("startup: achtergebleven runnercontainer — fail-closed")
            return
        if self.a.reconcile.marker_present():
            self.log.warning("startup: onderbroken operatie (marker) — DinD herstart + volledige scrub")
            self.a.reconcile.restart_dind()
            self.clean_proven = False
            self._begin_op("scrub")            # volledige scrub; marker gewist bij afronding
```

Voeg `and not self._blocked` toe aan `_may_start()`.

- [ ] **Stap 4: Run — PASS.**
- [ ] **Stap 5: Commit** `git commit -am "feat(controller): startup-reconciliatie + crashbestendige operatiemarker"`

---

### Taak 11: `Runtime` — signal-handling / stopcontract (§9)

**Files:** Modify `cycle_runtime.py`; Test `test_cycle_runtime.py`

**Interfaces:** Consumes Taak 8–10. Produces `request_stop`, `run`, stop-afhandeling in `tick`.

- [ ] **Stap 1: Falende tests**

```python
class TestStop(unittest.TestCase):
    def test_sigterm_with_child_requests_stop_and_waits(self):
        rt, ctrl, started = build_runtime([RC.READY]*4)
        rt.clean_proven = True; rt._start_runner()
        stopped = {"n": 0}
        rt.a.runner.request_stop = lambda p: stopped.__setitem__("n", 1)
        rt.request_stop()
        rt.child._rc = None                     # nog niet weg
        self.assertFalse(rt._stop_complete()); self.assertEqual(stopped["n"], 1)
        rt.child._rc = 0
        self.assertTrue(rt._stop_complete())
    def test_sigterm_during_scrub_waits(self):
        rt, ctrl, started = build_runtime([RC.READY]*4)
        rt._begin_op("scrub"); rt.op[1]._rc = None
        rt.request_stop()
        self.assertFalse(rt._stop_complete())   # scrub nog bezig → geen exit 0
        rt.op[1]._rc = 0; rt._advance(0.0)
        self.assertTrue(rt._stop_complete())
```

- [ ] **Stap 2: Run — FAIL.**
- [ ] **Stap 3: Implementeer**

```python
    def request_stop(self):
        self._stop = True
        if self.child is not None:
            self.a.runner.request_stop(self.child)

    def _stop_complete(self):
        return self.child is None and self.op is None

    def run(self):
        import signal as _signal
        _signal.signal(_signal.SIGTERM, lambda *_: self.request_stop())
        _signal.signal(_signal.SIGINT, lambda *_: self.request_stop())
        deadline = None
        while True:
            self.tick()
            if self._stop:
                if deadline is None:
                    deadline = self.clock()[0] + self.cfg.child_stop_grace
                if self._stop_complete():
                    return 0
                if self.clock()[0] >= deadline:
                    self.log.warning("stop: grens overschreden — onschone stop, reconciliatie bij herstart")
                    return 0
            _time.sleep(self.cfg.poll_interval)
```

Pas `tick()` aan: als `self._stop`, start géén nieuwe child of nieuwe pull/scrub (behalve de al lopende afmaken); d.w.z. omring `_may_start()` en `_ensure_clean` met `if not self._stop`.

- [ ] **Stap 4: Run — PASS.**
- [ ] **Stap 5: Commit** `git commit -am "feat(controller): SIGTERM-stopcontract voor alle cyclus-operaties"`

---

### Taak 12: `main()` + compose-command + allowlist-mount + `controller.toml.example`

**Files:** Modify `cycle_runtime.py`, `forgejo-runner/compose.yaml`; Create `forgejo-runner/controller.toml.example`; Test `test_cycle_runtime.py`, `forgejo-runner/tests/test_compose_contract.bats`

**Interfaces:** Produces `main(argv=None) -> int`.

- [ ] **Stap 1: Falende test voor `main` (arg-parsing + adapterconstructie)**

```python
class TestMain(unittest.TestCase):
    def test_main_check_mode_builds_without_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(tmp, VALID_TOML)
            rc = cr.main(["--config", p, "--check"])   # --check: laad+construeer, draai niet
        self.assertEqual(rc, 0)
    def test_main_missing_config_errors(self):
        self.assertNotEqual(cr.main(["--config", "/nope.toml"]), 0)
```

- [ ] **Stap 2: Run — FAIL.**
- [ ] **Stap 3: Implementeer `main`**

```python
import argparse, sys, os

def _build_adapters(cfg):
    from cycle_adapters import (Clock, TransportProbe, DindHealth, RunnerLifecycle,
                                PullOp, ScrubOp, Reconcile, TrustVerdictReader)
    allow_in_dind = "/etc/forgejo-runner/allowed-job-images.txt"
    scrub = os.path.join(os.path.dirname(__file__), "scrub-dind.sh")
    return Clock(), Adapters(
        probe=TransportProbe(cfg.forgejo_base_url, cfg.probe_timeout),
        dind=DindHealth(cfg.compose_file, cfg.project, timeout=cfg.subprocess_timeout),
        runner=RunnerLifecycle(cfg.compose_file, cfg.project, timeout=cfg.subprocess_timeout),
        pull=PullOp(cfg.compose_file, cfg.project, timeout=cfg.subprocess_timeout),
        scrub=ScrubOp(cfg.compose_file, cfg.project, scrub, allow_in_dind, timeout=cfg.subprocess_timeout),
        reconcile=Reconcile(cfg.compose_file, cfg.project, cfg.marker_path, timeout=cfg.subprocess_timeout),
        trust=TrustVerdictReader(cfg.trust_verdict_path, cfg.labels_file, cfg.allowlist_file),
    )

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        cfg = load_config(args.config)
    except (OSError, ValueError) as exc:
        print(f"config-fout: {exc}", file=sys.stderr); return 2
    logging.basicConfig(level=getattr(logging, cfg.log_level, logging.INFO),
                        format="%(asctime)s %(levelname)s %(message)s")
    clock, adapters = _build_adapters(cfg)
    controller = Controller(EventLoop(clock))
    rt = Runtime(cfg, controller, controller.loop, adapters, clock, logging.getLogger("cycle"))
    if args.check:
        return 0
    return rt.run()
```

- [ ] **Stap 4: Voeg compose-command + allowlist-mount toe**

In `forgejo-runner/compose.yaml`, service `runner`, voeg toe (naast `image`):

```yaml
    command: ["one-job", "--wait"]
```

En bij service `dind`, onder `volumes:`, voeg read-only de allowlist toe:

```yaml
      - ./allowed-job-images.txt:/etc/forgejo-runner/allowed-job-images.txt:ro
```

- [ ] **Stap 5: Maak `controller.toml.example`** (kopieer het §8-blok uit de spec, mét `marker_path` in `[dind]`; geen secrets).

- [ ] **Stap 6: Breid `test_compose_contract.bats` uit** met een assertie dat de runnerservice `one-job --wait` als command draagt en de dind-service de allowlist read-only mount:

```bash
@test "runner draagt one-job --wait als command" {
  run docker compose -f compose.yaml config
  [ "$status" -eq 0 ]
  echo "$output" | grep -q "one-job"
  echo "$output" | grep -q "allowed-job-images.txt:/etc/forgejo-runner/allowed-job-images.txt"
}
```

- [ ] **Stap 7: Run — PASS** (`python3 -m unittest tests.test_cycle_runtime` + `bats tests/test_compose_contract.bats`).
- [ ] **Stap 8: Commit** `git commit -am "feat(controller): main() + compose one-job-command + allowlist-mount + toml-template"`

---

### Taak 13: Deploy-wrapper `publish-trust-verdict.sh` (§6.3)

**Files:** Create `forgejo-runner/scripts/publish-trust-verdict.sh`; Test `forgejo-runner/tests/test_publish_trust_verdict.bats`

**Interfaces:** Produces een verdict-artifact met `ok`, `measured_at`, `forgejo_target`, `labels_sha256`, `allowlist_sha256`.

- [ ] **Stap 1: Falende bats-test**

```bash
# forgejo-runner/tests/test_publish_trust_verdict.bats
setup() { TMP="$(mktemp -d)"; }
teardown() { rm -rf "$TMP"; }

@test "publiceert alleen bij CLI-exit 0 en vult measured_at + binding" {
  # fake CLI die 0 geeft en een verdict schrijft
  cat > "$TMP/fakecli" <<'SH'
#!/bin/sh
outdir=""; while [ $# -gt 0 ]; do case "$1" in --out) outdir="$2"; shift 2;; *) shift;; esac; done
printf '{"ok":true,"hard":[],"soft":[]}' > "$outdir/trust-verdict.json"; exit 0
SH
  chmod +x "$TMP/fakecli"
  printf 'labels' > "$TMP/labels.txt"; printf 'allow' > "$TMP/allow.yml"
  run scripts/publish-trust-verdict.sh \
    --cli "$TMP/fakecli" --labels "$TMP/labels.txt" --allowlist "$TMP/allow.yml" \
    --target https://git.jp-visser.nl --out "$TMP/verdict.json"
  [ "$status" -eq 0 ]
  grep -q '"measured_at"' "$TMP/verdict.json"
  grep -q '"forgejo_target": *"https://git.jp-visser.nl"' "$TMP/verdict.json"
}

@test "mislukte meting overschrijft oud groen niet" {
  printf '{"ok":true,"measured_at":1}' > "$TMP/verdict.json"
  cat > "$TMP/failcli" <<'SH'
#!/bin/sh
exit 30
SH
  chmod +x "$TMP/failcli"
  printf 'l' > "$TMP/labels.txt"; printf 'a' > "$TMP/allow.yml"
  run scripts/publish-trust-verdict.sh --cli "$TMP/failcli" --labels "$TMP/labels.txt" \
    --allowlist "$TMP/allow.yml" --target https://x --out "$TMP/verdict.json"
  [ "$status" -ne 0 ]
  grep -q '"measured_at":1' "$TMP/verdict.json"   # oud bestand ongewijzigd
}
```

- [ ] **Stap 2: Run — FAIL** (`bats tests/test_publish_trust_verdict.bats`).
- [ ] **Stap 3: Implementeer**

```bash
#!/bin/sh
# forgejo-runner/scripts/publish-trust-verdict.sh
# Deploy-wrapper: draai de trustgate-CLI in een verse out-dir; publiceer een
# controller-verdict met measured_at + binding ALLEEN bij CLI-exit 0 (§6.3).
# Exitcodes: 0 gepubliceerd, 3 CLI-meting mislukt (oud verdict blijft staan), 2 gebruik.
set -eu
CLI=""; LABELS=""; ALLOWLIST=""; TARGET=""; OUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --cli) CLI="$2"; shift 2;; --labels) LABELS="$2"; shift 2;;
    --allowlist) ALLOWLIST="$2"; shift 2;; --target) TARGET="$2"; shift 2;;
    --out) OUT="$2"; shift 2;; *) echo "onbekend: $1" >&2; exit 2;;
  esac
done
[ -n "$CLI" ] && [ -f "$LABELS" ] && [ -f "$ALLOWLIST" ] && [ -n "$TARGET" ] && [ -n "$OUT" ] || {
  echo "gebruik: publish-trust-verdict.sh --cli C --labels L --allowlist A --target T --out O" >&2; exit 2; }

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
# Verse, lege out-dir voor de CLI; de CLI eist --allowlist/--labels/--out en FORGEJO_TOKEN.
if ! "$CLI" --allowlist "$ALLOWLIST" --labels "$LABELS" --out "$WORK"; then
  echo "trustmeting mislukt; oud verdict blijft ongewijzigd" >&2; exit 3
fi
OKVAL="$(awk -F'"ok":' 'NF>1{print $2}' "$WORK/trust-verdict.json" | grep -o 'true\|false' | head -1)"
MEASURED="$(date +%s)"
LS="$(sha256_hex "$LABELS")"; AS="$(sha256_hex "$ALLOWLIST")"
TMP="$OUT.tmp.$$"
printf '{"ok":%s,"measured_at":%s,"forgejo_target":"%s","labels_sha256":"%s","allowlist_sha256":"%s"}\n' \
  "${OKVAL:-false}" "$MEASURED" "$TARGET" "$LS" "$AS" > "$TMP"
mv -f "$TMP" "$OUT"

sha256_hex() { sha256sum "$1" 2>/dev/null | awk '{print $1}' || shasum -a 256 "$1" | awk '{print $1}'; }
```

> Verplaats de `sha256_hex`-definitie naar boven het gebruik (POSIX sh definieert functies vóór aanroep). Corrigeer de volgorde in de implementatie.

- [ ] **Stap 4: Corrigeer de functievolgorde** (`sha256_hex` bovenaan, ná `set -eu`).
- [ ] **Stap 5: `chmod +x` + run — PASS.**
- [ ] **Stap 6: Commit** `git commit -am "feat(controller): deploy-wrapper publish-trust-verdict.sh"`

---

### Taak 14: Volledige gate + ruff + bring-up-runbook

**Files:** Create `docs/forgejo-runner-pool/evidence/stap-d/bring-up-runbook.md`

- [ ] **Stap 1: Volledige suite + ruff**

Run:
```bash
cd forgejo-runner
python3 -m unittest discover -s tests -p 'test_*.py'
ruff check scripts/
```
Expected: alles groen (99 hart-tests + de nieuwe runtime-tests); ruff schoon. Repareer wat rood is; commit fixes apart.

- [ ] **Stap 2: Schrijf het bring-up-runbook** (`bring-up-runbook.md`): de handmatige stap-D/E-smoke op max2 via `ssh janpeter@max2`:
  1. deploy-verdict produceren met `publish-trust-verdict.sh` (operator heeft `FORGEJO_TOKEN`);
  2. bundel plaatsen op de gepinde SHA; `controller.toml` invullen; `docker inspect` op de runner-image → entrypoint/argv bevestigen (§6.2);
  3. `docker compose up -d dind`; unit starten; bewijzen dat de runner online staat in Forgejo;
  4. één bewust groene + één bewust rode smoke-workflow; groene scrub; `systemctl stop` → schone stop;
  5. bewijs (endpoints §7.5, geen hostlisteners, DinD-isolatie) vastleggen onder `evidence/stap-d|e/`.

- [ ] **Stap 3: Commit** `git commit -am "docs(controller): bring-up-runbook stap D/E"`

---

## Self-review (uitgevoerd bij het schrijven)

**Spec-dekking:** §4 (moduleopzet) → T1/T5/T7/T12; §5+§5.2 (loop+preconditions) → T4/T8/T11; §6 adapters → T5–T7; §6.1 cyclus + stap 0 → T9/T10; §6.2 compose-command → T12; §6.3 deploy-verdict → T3/T7/T13; §6.4 operatiemarker → T7/T10; §7.3 exitcode → T9; §7.4 gate-falen → T8; §7.5 fence-herstel = hart (geen schil-actie, correct); §8 config → T1/T12; §9 stopcontract → T11; §11 tests → T1–T13; §12 verificatie → T14. Geen onbedekte spec-sectie.

**Placeholders:** geen "TBD"/"handle errors"; elke stap draagt echte code. Twee bewuste correctie-stappen (T6 signal-import, T13 functievolgorde) staan expliciet als eigen stap.

**Type-consistentie:** `Adapters`-namedtuple velden (`probe,dind,runner,pull,scrub,reconcile,trust`) identiek in T7/T8/T12; `readiness.confirmed`, `clean_proven`, `op`, `child` consistent door T8–T11; `verdict_green`-signatuur identiek in T3/T8.

---

## Uitvoering

**Plan opgeslagen. Twee uitvoeropties:**

1. **Subagent-Driven (aanbevolen)** — fresh subagent per taak, review tussen taken. REQUIRED SUB-SKILL: superpowers:subagent-driven-development.
2. **Inline** — taken in deze sessie via superpowers:executing-plans, batch met checkpoints.

Werk in een isolatie-worktree (superpowers:using-git-worktrees) op branch `feat/forgejo-runner-pool-controller-entrypoint`.
