# Controller-entrypoint (dunne bring-up) — Implementatieplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bouw de runtime-schil rond het bestaande, getest beslis-hart `forgejo_runner_cycle.py` zodat de Forgejo-runner op max2 online komt, één groene/rode job draait met scrub, en netjes op `SIGTERM` stopt (stap D + kern van stap E).

**Architecture:** Ports & adapters. Het pure beslis-hart blijft byte-identiek op een 2-regel `__main__`-delegatie na. `cycle_runtime.py` bevat de pure runtime-logica (config, parsers, verdict-validatie, de twee preconditions, de single-thread poll-loop met een expliciete faseketen scrub→pre-pull→start) en `cycle_adapters.py` de neveneffect-adapters. Alle IO is injecteerbaar; een gedeeld testharnas (fake klok + fake Popen + fixtures) test de loop deterministisch.

**Tech Stack:** Python 3.11+ **alleen stdlib** (`tomllib`, `urllib.request`, `subprocess`, `signal`, `logging`, `time`, `json`, `re`, `math`, `hashlib`, `pathlib`); stdlib `unittest`; `docker compose` v2; POSIX sh voor de deploy-wrapper; `ruff`.

**Spec:** `docs/forgejo-runner-pool/controller-entrypoint-ontwerp.md` (delta-review GO, 4 rondes). Lees beide.

## Global Constraints

- **Alleen Python-stdlib** in de controller; geen pip-dependencies (system-`/usr/bin/python3`, geen venv).
- Het hart `forgejo-runner/scripts/forgejo_runner_cycle.py` blijft **byte-identiek** op de 2-regel `__main__`-delegatie na. De 99 hart-tests blijven ongewijzigd groen.
- **Consumeer** uit het hart: `classify_probe`, `ReadinessClass`, `State`, `EventLoop`, `Controller`, `CONFIRM_SECONDS`(5), `RETRY_INTERVAL_SECONDS`(30), `FENCE_MAX_AGE_SECONDS`(60).
- **Start-conditie (§5.2):** een runner start alleen als **alle** waar zijn: `mag_child_starten`, `state==WAITING`, `readiness_confirmed`, `clean_proven`, **pre-pull klaar**, `not _blocked`, `not _stop`.
- **Fail-closed overal:** elke subprocess-returncode wordt gecontroleerd; fout/onbekend = blokkerende uitkomst, nooit een lege/groene default. `readiness_confirmed` alleen door eigen 2-waarnemingenbevestiging; `clean_proven` alleen door geslaagde scrub+bewijs; readiness-herstel kent geen van beide toe.
- **Single active mutating phase (§6.4, m1):** hooguit één van {pull, scrub, runner-child} tegelijk actief; `_blocked` én `_stop` blokkeren élke nieuwe muterende actie (niet alleen de launch).
- **Pre-pull vóór start (§6.1 stap 3):** iedere toegestane digest wordt per digest gepulld via het DinD-endpoint vóórdat een runner start; pull-fout ⇒ geen start.
- **Trustgate = deploy-verdict** (JP 2026-09-06): de controller houdt **geen** Forgejo-credential; hij leest een bij deploy geproduceerd, vers, gebonden `trust-verdict.json`. Het verdict bindt aan de **werkelijk gemeten** bron (§6.3).
- **Geen secrets** in Git, logs of containermetadata; logs dragen nooit namen/tokens.
- **Byte-identieke bundel:** compose/scriptwijzigingen gelden identiek op beide hosts.
- **DinD-endpoint expliciet:** élke docker-call naar de inner DinD gebruikt `-H tcp://127.0.0.1:2375` (health, pull, scrub); DinD draait TCP-only zonder unix-socket (`compose.yaml:11`).
- **Verificatie:** `cd forgejo-runner && python3 -m unittest discover -s tests -p 'test_*.py'`, `ruff check scripts/`, en `bats tests/test_compose_contract.bats tests/test_publish_trust_verdict.bats`.

---

## Bestandsstructuur

| Bestand | Verantwoordelijkheid | Actie |
|---|---|---|
| `forgejo-runner/scripts/forgejo_runner_cycle.py` | Puur hart + `__main__`-delegatie | Modify (+2 regels) |
| `forgejo-runner/scripts/cycle_runtime.py` | Config, parsers, verdict-validatie, `ReadinessConfirmed`, `Runtime` (loop+preconditions+faseketen), `main()` | Create |
| `forgejo-runner/scripts/cycle_adapters.py` | `Clock`, `TransportProbe`, `DindHealth`, `RunnerLifecycle`, `PullOp`, `ScrubOp`, `Reconcile`, `TrustVerdictReader` | Create |
| `forgejo-runner/scripts/publish-trust-verdict.sh` | Deploy-wrapper: CLI → verdict met `measured_at`+binding, atomair (§6.3) | Create |
| `forgejo-runner/compose.yaml` | `command: ["one-job","--wait"]` op runner; allowlist read-only in dind | Modify |
| `forgejo-runner/controller.toml.example` | Template (§8), zonder secrets | Create |
| `forgejo-runner/tests/_harness.py` | Gedeeld testharnas (fake klok, fake Popen, fixtures, `build_runtime`) | Create |
| `forgejo-runner/tests/test_cycle_runtime.py` | Unittests pure logica + gedreven loop | Create |
| `forgejo-runner/tests/test_publish_trust_verdict.bats` | bats voor de deploy-wrapper | Create |
| `forgejo-runner/tests/test_compose_contract.bats` | uitbreiden: command + mount | Modify |
| `docs/forgejo-runner-pool/evidence/stap-d/bring-up-runbook.md` | Stap-D/E integratie-smoke | Create |

## Gedeelde interfaces

`cycle_runtime.py`:

```python
@dataclass(frozen=True)
class Config: ...   # velden = de §8-sleutels (zie Taak 1)
def load_config(path) -> Config: ...
def parse_allowed_images(text) -> list[str]: ...
def verdict_green(verdict, now_wall, cfg, labels_sha, allowlist_sha) -> tuple[bool, str]: ...
class ReadinessConfirmed:      # .confirmed ; .observe(klasse, mono)
class Runtime:                 # .__init__(cfg, controller, loop, adapters, clock, log)
                               # .tick() ; .request_stop() ; .run() -> int
def main(argv=None) -> int: ...
```

`cycle_adapters.py` — `Adapters = namedtuple("Adapters", "probe dind runner pull scrub reconcile trust")`; adaptermethoden:

```python
Clock().__call__() -> (mono, wall)
TransportProbe(base_url, timeout, opener=urlopen).probe() -> dict{kind,error,status,schema_ok}
DindHealth(...).ensure_up() ; .healthy() -> bool
RunnerLifecycle(...).start() -> Popen ; .request_stop(p) ; .poll(p) -> int|None
PullOp(...).start(digest) -> Popen ; .poll(p) -> int|None
ScrubOp(..., script, allow_in_dind).start() -> Popen ; .poll(p) -> int|None
Reconcile(..., marker_path).leftover_runners() -> list[str]   # raise ReconcileError bij rc!=0
    .marker_present() ; .write_marker(op) ; .clear_marker() ; .restart_dind()  # raise bij rc!=0
TrustVerdictReader(verdict_path, labels_file, allowlist_file).read() -> (verdict, labels_sha, allowlist_sha)
```

---

### Taak 1: sys.path-harnas + config-loader + `__main__`-delegatie

**Files:** Create `forgejo-runner/scripts/cycle_runtime.py`, `forgejo-runner/tests/_harness.py`, `forgejo-runner/tests/test_cycle_runtime.py`; Modify `forgejo-runner/scripts/forgejo_runner_cycle.py`

**Interfaces:** Produces `Config`, `load_config`.

- [ ] **Stap 1: Maak `tests/_harness.py`** (élk testbestand importeert dit eerst; het zet sys.path zoals de bestaande tests, `test_cycle_readiness.py:6`)

```python
# forgejo-runner/tests/_harness.py
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import cycle_runtime as cr          # noqa: E402
import cycle_adapters as ca         # noqa: E402
from forgejo_runner_cycle import (  # noqa: E402
    EventLoop, Controller, State, ReadinessClass as RC, classify_probe)

VALID_TOML = b"""
[forgejo]
base_url = "https://git.jp-visser.nl"
probe_timeout_seconds = 5
[dind]
compose_file = "/opt/forgejo-runner/compose.yaml"
project = "forgejo-runner"
marker_path = "/tmp/ctl/cycle-op.marker"
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

def write_toml(tmp, data=VALID_TOML):
    import os
    p = os.path.join(tmp, "controller.toml"); open(p, "wb").write(data); return p

class FakeClock:
    """Eén klok voor hart én runtime; wall == mono zodat event.mono en de
    runtime-cadans hetzelfde tijdsverloop zien."""
    def __init__(self): self.t = 0.0
    def advance(self, dt): self.t += dt
    def __call__(self): return self.t, self.t

class FakePopen:
    def __init__(self, argv=None, rc=None): self.argv = argv or []; self.rc = rc; self.signals = []
    def poll(self): return self.rc
    def send_signal(self, s): self.signals.append(s)
```

- [ ] **Stap 2: Falende config-test**

```python
# forgejo-runner/tests/test_cycle_runtime.py
import os, tempfile, unittest
from _harness import cr, write_toml, VALID_TOML

class TestConfig(unittest.TestCase):
    def test_load_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = cr.load_config(write_toml(tmp))
        self.assertEqual(cfg.forgejo_base_url, "https://git.jp-visser.nl")
        self.assertEqual(cfg.child_stop_grace, 200.0)
        self.assertEqual(cfg.marker_path, "/tmp/ctl/cycle-op.marker")
    def test_missing_key_clean_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = VALID_TOML.replace(b'project = "forgejo-runner"', b"")
            with self.assertRaises(ValueError) as ctx:
                cr.load_config(write_toml(tmp, bad))
        self.assertIn("dind.project", str(ctx.exception))

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Stap 3: Run — FAIL** (`ModuleNotFoundError: cycle_runtime`).

Run: `cd forgejo-runner && python3 -m unittest tests.test_cycle_runtime -v`

- [ ] **Stap 4: Implementeer Config + load_config**

```python
# forgejo-runner/scripts/cycle_runtime.py
"""Runtime-schil rond forgejo_runner_cycle.py (dunne bring-up)."""
import tomllib
from dataclasses import dataclass

@dataclass(frozen=True)
class Config:
    forgejo_base_url: str; probe_timeout: float
    compose_file: str; project: str; marker_path: str
    allowed_images_file: str; child_stop_grace: float
    trust_verdict_path: str; trust_verdict_max_age: float
    labels_file: str; allowlist_file: str
    subprocess_timeout: float; poll_interval: float; retry_interval: float
    log_level: str

def _req(d, section, key):
    try: return d[section][key]
    except (KeyError, TypeError): raise ValueError(f"controller.toml mist {section}.{key}") from None

def load_config(path):
    with open(path, "rb") as fh:
        d = tomllib.load(fh)
    return Config(
        forgejo_base_url=str(_req(d, "forgejo", "base_url")),
        probe_timeout=float(_req(d, "forgejo", "probe_timeout_seconds")),
        compose_file=str(_req(d, "dind", "compose_file")),
        project=str(_req(d, "dind", "project")),
        marker_path=str(_req(d, "dind", "marker_path")),
        allowed_images_file=str(_req(d, "runner", "allowed_images_file")),
        child_stop_grace=float(_req(d, "runner", "child_stop_grace_seconds")),
        trust_verdict_path=str(_req(d, "trust", "verdict_path")),
        trust_verdict_max_age=float(_req(d, "trust", "verdict_max_age_seconds")),
        labels_file=str(_req(d, "trust", "labels_file")),
        allowlist_file=str(_req(d, "trust", "allowlist_file")),
        subprocess_timeout=float(_req(d, "docker", "subprocess_timeout_seconds")),
        poll_interval=float(_req(d, "cadence", "poll_interval_seconds")),
        retry_interval=float(_req(d, "cadence", "retry_interval_seconds")),
        log_level=str(d.get("log", {}).get("level", "INFO")),
    )
```

- [ ] **Stap 5: Voeg de `__main__`-delegatie aan het hart toe** (einde `forgejo_runner_cycle.py`)

```python


if __name__ == "__main__":
    from cycle_runtime import main
    raise SystemExit(main())
```

- [ ] **Stap 6: Run — PASS + hart-tests groen**

Run: `cd forgejo-runner && python3 -m unittest tests.test_cycle_runtime -v && python3 -m unittest discover -s tests -p 'test_cycle_*.py'`

- [ ] **Stap 7: Commit** `git add forgejo-runner/scripts/cycle_runtime.py forgejo-runner/scripts/forgejo_runner_cycle.py forgejo-runner/tests/_harness.py forgejo-runner/tests/test_cycle_runtime.py && git commit -m "feat(controller): config-loader + testharnas + __main__-delegatie"`

---

### Taak 2: allowed-images parser (puur)

**Files:** Modify `cycle_runtime.py`, `tests/test_cycle_runtime.py`

- [ ] **Stap 1: Falende test (echt formaat)**

```python
from _harness import cr
class TestImages(unittest.TestCase):
    REAL = ("# commentaar\ncatthehacker/ubuntu@sha256:" + "c"*64 + "\t1729048576\n")
    def test_digest_tab_bytes(self):
        self.assertEqual(cr.parse_allowed_images(self.REAL), ["catthehacker/ubuntu@sha256:" + "c"*64])
    def test_blank_comment_ignored(self):
        self.assertEqual(cr.parse_allowed_images("\n#x\n  \n"), [])
    def test_invalid_raises(self):
        with self.assertRaises(ValueError): cr.parse_allowed_images("ubuntu:latest\t10\n")
```

- [ ] **Stap 2: Run — FAIL.**
- [ ] **Stap 3: Implementeer**

```python
import re
_DIGEST_RE = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")
def parse_allowed_images(text):
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"): continue
        digest = line.split("\t", 1)[0].strip()
        if not _DIGEST_RE.match(digest): raise ValueError(f"ongeldige digest-regel: {raw!r}")
        out.append(digest)
    return out
```

- [ ] **Stap 4: Run — PASS. Commit** `git commit -am "feat(controller): allowed-images parser"`

---

### Taak 3: verdict-validator (puur, fail-closed incl. NaN)

**Files:** Modify `cycle_runtime.py`, `tests/test_cycle_runtime.py`

- [ ] **Stap 1: Falende tests (incl. NaN/inf/bool — M9)**

```python
from _harness import cr, write_toml
class TestVerdict(unittest.TestCase):
    def _cfg(self):
        with tempfile.TemporaryDirectory() as tmp: return cr.load_config(write_toml(tmp))
    def _v(self, **o):
        b = {"ok": True, "measured_at": 1000.0, "forgejo_target": "https://git.jp-visser.nl",
             "labels_sha256": "LS", "allowlist_sha256": "AS"}; b.update(o); return b
    def test_green(self): self.assertTrue(cr.verdict_green(self._v(), 1500.0, self._cfg(), "LS", "AS")[0])
    def test_not_ok(self): self.assertFalse(cr.verdict_green(self._v(ok=False), 1500.0, self._cfg(), "LS", "AS")[0])
    def test_future(self): self.assertFalse(cr.verdict_green(self._v(measured_at=2000.0), 1500.0, self._cfg(), "LS", "AS")[0])
    def test_too_old(self): self.assertFalse(cr.verdict_green(self._v(), 1000.0+86401, self._cfg(), "LS", "AS")[0])
    def test_nan(self): self.assertFalse(cr.verdict_green(self._v(measured_at=float("nan")), 1500.0, self._cfg(), "LS", "AS")[0])
    def test_inf(self): self.assertFalse(cr.verdict_green(self._v(measured_at=float("inf")), 1500.0, self._cfg(), "LS", "AS")[0])
    def test_bool_ts(self): self.assertFalse(cr.verdict_green(self._v(measured_at=True), 1500.0, self._cfg(), "LS", "AS")[0])
    def test_binding(self): self.assertFalse(cr.verdict_green(self._v(), 1500.0, self._cfg(), "OTHER", "AS")[0])
    def test_non_dict(self): self.assertFalse(cr.verdict_green(None, 1500.0, self._cfg(), "LS", "AS")[0])
```

- [ ] **Stap 2: Run — FAIL.**
- [ ] **Stap 3: Implementeer**

```python
import math
def verdict_green(verdict, now_wall, cfg, labels_sha, allowlist_sha):
    if not isinstance(verdict, dict): return False, "verdict is geen object"
    if verdict.get("ok") is not True: return False, "ok is niet true"
    m = verdict.get("measured_at")
    if isinstance(m, bool) or not isinstance(m, (int, float)) or not math.isfinite(m):
        return False, "measured_at ontbreekt/ongeldig/niet-eindig"
    age = now_wall - float(m)
    if age < 0: return False, "measured_at ligt in de toekomst"
    if age > cfg.trust_verdict_max_age: return False, "verdict is te oud"
    if verdict.get("forgejo_target") != cfg.forgejo_base_url: return False, "target-binding mismatch"
    if verdict.get("labels_sha256") != labels_sha: return False, "labels-binding mismatch"
    if verdict.get("allowlist_sha256") != allowlist_sha: return False, "allowlist-binding mismatch"
    return True, "groen"
```

- [ ] **Stap 4: Run — PASS. Commit** `git commit -am "feat(controller): verdict-validator (fail-closed, NaN/inf/bool geweigerd)"`

---

### Taak 4: `ReadinessConfirmed` (puur)

**Files:** Modify `cycle_runtime.py`, `tests/test_cycle_runtime.py`

- [ ] **Stap 1: Falende test (B1-spoor)**

```python
from _harness import cr, RC
class TestReadinessConfirmed(unittest.TestCase):
    def test_trace(self):
        r = cr.ReadinessConfirmed()
        r.observe(RC.READY, 0.0);  self.assertFalse(r.confirmed)
        r.observe(RC.READY, 30.0); self.assertTrue(r.confirmed)
        r.observe(RC.SOURCE_WAIT, 60.0); self.assertFalse(r.confirmed)
        r.observe(RC.READY, 120.0); self.assertFalse(r.confirmed)
        r.observe(RC.READY, 150.0); self.assertTrue(r.confirmed)
    def test_too_close(self):
        r = cr.ReadinessConfirmed(); r.observe(RC.READY, 0.0); r.observe(RC.READY, 1.0)
        self.assertFalse(r.confirmed)
```

- [ ] **Stap 2: Run — FAIL.**
- [ ] **Stap 3: Implementeer**

```python
from forgejo_runner_cycle import ReadinessClass, CONFIRM_SECONDS
class ReadinessConfirmed:
    def __init__(self, confirm_seconds=CONFIRM_SECONDS):
        self._confirm = confirm_seconds; self._first = None; self.confirmed = False
    def observe(self, klasse, mono):
        if klasse is not ReadinessClass.READY:
            self._first = None; self.confirmed = False; return
        if self._first is None: self._first = mono
        elif (mono - self._first) >= self._confirm: self.confirmed = True
```

- [ ] **Stap 4: Run — PASS. Commit** `git commit -am "feat(controller): readiness_confirmed precondition"`

---

### Taak 5: Adapters — `Clock` + `TransportProbe` (schema + timeouts — M8)

**Files:** Create `cycle_adapters.py`; Modify `tests/test_cycle_runtime.py`

- [ ] **Stap 1: Falende tests**

```python
import io, socket, urllib.error
from _harness import ca, classify_probe, RC
class TestProbe(unittest.TestCase):
    def _p(self, opener): return ca.TransportProbe("https://x", 5.0, opener=opener).probe()
    def test_ready(self):
        self.assertEqual(classify_probe(self._p(lambda r, timeout: io.BytesIO(b'{"version":"1"}'))), RC.READY)
    def test_wrong_schema_not_ready(self):
        p = self._p(lambda r, timeout: io.BytesIO(b'{"note":"no version here"}'))
        self.assertEqual(classify_probe(p), RC.PROTOCOL)     # geen version-veld
    def test_5xx(self):
        def o(r, timeout): raise urllib.error.HTTPError("u", 503, "x", {}, None)
        self.assertEqual(classify_probe(self._p(o)), RC.SOURCE_WAIT)
    def test_401_protocol(self):
        def o(r, timeout): raise urllib.error.HTTPError("u", 401, "x", {}, None)
        self.assertEqual(classify_probe(self._p(o)), RC.PROTOCOL)
    def test_urlerror(self):
        def o(r, timeout): raise urllib.error.URLError("refused")
        self.assertEqual(classify_probe(self._p(o)), RC.SOURCE_WAIT)
    def test_readtimeout(self):
        def o(r, timeout): raise TimeoutError("read timed out")
        self.assertEqual(classify_probe(self._p(o)), RC.SOURCE_WAIT)
```

- [ ] **Stap 2: Run — FAIL.**
- [ ] **Stap 3: Implementeer**

```python
# forgejo-runner/scripts/cycle_adapters.py
"""Neveneffect-adapters voor de cyclecontroller-runtime (dunne bring-up)."""
import json, signal, subprocess, time, urllib.request, urllib.error

class Clock:
    def __call__(self): return time.monotonic(), time.time()

class TransportProbe:
    def __init__(self, base_url, timeout, opener=urllib.request.urlopen):
        self._url = base_url.rstrip("/") + "/api/v1/version"; self._t = timeout; self._open = opener
    def probe(self):
        req = urllib.request.Request(self._url, headers={"Accept": "application/json"})
        try:
            resp = self._open(req, timeout=self._t)
            try:
                body = resp.read()
            finally:
                getattr(resp, "close", lambda: None)()
            try:
                obj = json.loads(body); schema_ok = isinstance(obj, dict) and "version" in obj
            except ValueError:
                schema_ok = False
            return {"kind": "general", "error": None,
                    "status": getattr(resp, "status", 200) or 200, "schema_ok": schema_ok}
        except urllib.error.HTTPError as e:
            return {"kind": "general", "error": None, "status": e.code, "schema_ok": False}
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return {"kind": "general", "error": str(e), "status": None, "schema_ok": False}
```

- [ ] **Stap 4: Run — PASS. Commit** `git commit -am "feat(controller): Clock + TransportProbe (schema-veld + timeouts)"`

---

### Taak 6: Adapters — DinD-health, runner, pull (met `-H`), scrub (M5-argv)

**Files:** Modify `cycle_adapters.py`, `tests/test_cycle_runtime.py`

- [ ] **Stap 1: Falende tests (argv, incl. pull `-H` en scrub-script-fixture)**

```python
import tempfile, os
from _harness import ca, FakePopen
class TestDockerAdapters(unittest.TestCase):
    def setUp(self):
        self.spawned = []; self.popen = lambda argv, **kw: self.spawned.append((argv, kw)) or FakePopen(argv)
    def test_runner_argv(self):
        ca.RunnerLifecycle("/c", "p", popen=self.popen).start()
        self.assertEqual(self.spawned[-1][0],
            ["docker","compose","-f","/c","-p","p","--profile","cycle","run","--rm","runner"])
    def test_pull_argv_has_endpoint(self):
        ca.PullOp("/c","p", popen=self.popen).start("img@sha256:"+"a"*64)
        argv = self.spawned[-1][0]
        self.assertEqual(argv[:8], ["docker","compose","-f","/c","-p","p","exec","-T"])
        self.assertIn("-H", argv); self.assertIn("tcp://127.0.0.1:2375", argv)
        self.assertIn("pull", argv); self.assertIn("img@sha256:"+"a"*64, argv)
    def test_scrub_argv_and_opens_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            sc = os.path.join(tmp, "scrub.sh"); open(sc, "wb").write(b"#!/bin/sh\n")
            ca.ScrubOp("/c","p", sc, "/etc/forgejo-runner/allowed-job-images.txt", popen=self.popen).start()
        argv, kw = self.spawned[-1]
        self.assertIn("--endpoint", argv); self.assertIn("tcp://127.0.0.1:2375", argv)
        self.assertIn("--allow", argv); self.assertIn("/etc/forgejo-runner/allowed-job-images.txt", argv)
        self.assertIn("stdin", kw)          # script via stdin
```

- [ ] **Stap 2: Run — FAIL.**
- [ ] **Stap 3: Implementeer**

```python
def _run(argv, timeout):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)

class _Compose:
    def __init__(self, compose_file, project, popen=subprocess.Popen, run=_run, timeout=30.0):
        self._b = ["docker", "compose", "-f", compose_file, "-p", project]
        self._popen = popen; self._run = run; self._t = timeout

class DindHealth(_Compose):
    def ensure_up(self): self._run(self._b + ["up", "-d", "dind"], self._t)
    def healthy(self):
        cp = self._run(self._b + ["exec","-T","dind","docker","-H","tcp://127.0.0.1:2375","info"], self._t)
        return cp.returncode == 0

class RunnerLifecycle(_Compose):
    def start(self): return self._popen(self._b + ["--profile","cycle","run","--rm","runner"])
    def request_stop(self, p): p.send_signal(signal.SIGTERM)
    def poll(self, p): return p.poll()

class PullOp(_Compose):
    def start(self, digest):
        return self._popen(self._b + ["exec","-T","dind","docker","-H","tcp://127.0.0.1:2375","pull",digest])
    def poll(self, p): return p.poll()

class ScrubOp(_Compose):
    def __init__(self, cf, proj, script, allow_in_dind, **kw):
        super().__init__(cf, proj, **kw); self._script = script; self._allow = allow_in_dind
    def start(self):
        argv = self._b + ["exec","-T","dind","sh","-s","--",
                          "--endpoint","tcp://127.0.0.1:2375","--allow",self._allow]
        return self._popen(argv, stdin=open(self._script, "rb"))
    def poll(self, p): return p.poll()
```

- [ ] **Stap 4: Run — PASS. Commit** `git commit -am "feat(controller): DinD/runner/pull(-H)/scrub adapters"`

---

### Taak 7: Adapters — `Reconcile` (rc-gecontroleerd — B2) + `TrustVerdictReader`

**Files:** Modify `cycle_adapters.py`, `tests/test_cycle_runtime.py`

- [ ] **Stap 1: Falende tests (rc!=0 blokkeert)**

```python
import hashlib
from _harness import ca
def _cp(out="", rc=0, err=""):
    class C: pass
    c = C(); c.returncode = rc; c.stdout = out; c.stderr = err; return c
class TestReconcile(unittest.TestCase):
    def test_leftover_ok(self):
        rec = ca.Reconcile("/c","p","/m", run=lambda a,t: _cp("abc\n"))
        self.assertEqual(rec.leftover_runners(), ["abc"])
    def test_leftover_rc_error_raises(self):
        rec = ca.Reconcile("/c","p","/m", run=lambda a,t: _cp("", rc=1, err="boom"))
        with self.assertRaises(ca.ReconcileError): rec.leftover_runners()
    def test_restart_kill_fail_raises(self):
        calls = {"n": 0}
        def run(a, t):
            calls["n"] += 1; return _cp(rc=0) if "up" in a else _cp(rc=1)   # kill faalt
        rec = ca.Reconcile("/c","p","/m", run=run)
        with self.assertRaises(ca.ReconcileError): rec.restart_dind()
    def test_marker_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            mk = os.path.join(tmp, "c", "m"); rec = ca.Reconcile("/c","p",mk, run=lambda a,t:_cp())
            self.assertFalse(rec.marker_present()); rec.write_marker("scrub")
            self.assertTrue(rec.marker_present()); rec.clear_marker(); self.assertFalse(rec.marker_present())
    def test_verdict_reader_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            lp=os.path.join(tmp,"l"); open(lp,"wb").write(b"x"); ap=os.path.join(tmp,"a"); open(ap,"wb").write(b"y")
            vp=os.path.join(tmp,"v"); open(vp,"w").write('{"ok":true}')
            v, ls, as_ = ca.TrustVerdictReader(vp, lp, ap).read()
            self.assertEqual(v, {"ok": True}); self.assertEqual(ls, hashlib.sha256(b"x").hexdigest())
```

- [ ] **Stap 2: Run — FAIL.**
- [ ] **Stap 3: Implementeer**

```python
import hashlib, os

class ReconcileError(Exception): pass

class Reconcile(_Compose):
    def __init__(self, cf, proj, marker_path, **kw):
        super().__init__(cf, proj, **kw); self._marker = marker_path
    def _checked(self, args):
        cp = self._run(self._b + args, self._t)
        if cp.returncode != 0:
            raise ReconcileError(f"{' '.join(args)}: rc={cp.returncode} {cp.stderr.strip()}")
        return cp
    def leftover_runners(self):
        cp = self._checked(["ps", "-q", "runner"])
        return [ln.strip() for ln in (cp.stdout or "").splitlines() if ln.strip()]
    def marker_present(self): return os.path.exists(self._marker)
    def write_marker(self, op):
        os.makedirs(os.path.dirname(self._marker), exist_ok=True)
        tmp = self._marker + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"op": op}, fh)
        os.replace(tmp, self._marker)
    def clear_marker(self):
        try: os.remove(self._marker)
        except FileNotFoundError: pass
    def restart_dind(self):
        self._checked(["kill", "dind"]); self._checked(["up", "-d", "dind"])

class TrustVerdictReader:
    def __init__(self, vp, lf, af): self._vp=vp; self._lf=lf; self._af=af
    def read(self):
        try:
            with open(self._vp, "rb") as fh: verdict = json.load(fh)
        except (FileNotFoundError, ValueError): verdict = None
        return verdict, _sha256(self._lf), _sha256(self._af)

def _sha256(path):
    try:
        with open(path, "rb") as fh: return hashlib.sha256(fh.read()).hexdigest()
    except FileNotFoundError: return ""
```

- [ ] **Stap 4: Run — PASS. Commit** `git commit -am "feat(controller): Reconcile (rc-gecontroleerd) + TrustVerdictReader"`

---

### Taak 8: `Runtime` — skelet + readiness/gates + faseketen + start-conditie

**Files:** Modify `cycle_runtime.py`, `tests/test_cycle_runtime.py`

**Interfaces:** Consumes alle adapters + hart. Produces `Runtime`.

De `build_runtime`-helper (in `_harness.py`) construeert een Runtime met FakeClock (gedeeld met de EventLoop) en injecteerbare fake-adapters. Voeg toe aan `_harness.py`:

```python
import collections
FakeAdapters = collections.namedtuple("FakeAdapters", "probe dind runner pull scrub reconcile trust")

class Recorder:
    """Verzamelt fase-starts en levert per fase een FakePopen met stuurbare rc."""
    def __init__(self):
        self.starts = []; self.pops = {"runner": FakePopen(), "pull": FakePopen(), "scrub": FakePopen()}
    def _mk(self, kind):
        self.starts.append(kind); return self.pops[kind]

def build_runtime(tmp, klasse="READY", healthy=True, verdict_ok=True,
                  leftover=None, marker=False, digests=("img@sha256:"+"a"*64,)):
    clock = FakeClock(); rec = Recorder()
    probe_dict = {"kind":"general","error":None,"status":200,"schema_ok":True} if klasse=="READY" \
                 else {"kind":"general","error":"x","status":None,"schema_ok":False}
    probe = type("P", (), {"probe": staticmethod(lambda: probe_dict)})()
    dind = type("D", (), {"ensure_up": staticmethod(lambda: None), "healthy": staticmethod(lambda: healthy)})()
    runner = type("R", (), {"start": lambda self: rec._mk("runner"),
                            "request_stop": lambda self, p: p.send_signal(15),
                            "poll": lambda self, p: p.poll()})()
    pull = type("Pu", (), {"start": lambda self, d: rec._mk("pull"), "poll": lambda self, p: p.poll()})()
    scrub = type("Sc", (), {"start": lambda self: rec._mk("scrub"), "poll": lambda self, p: p.poll()})()
    reconcile = type("Re", (), {"leftover_runners": staticmethod(lambda: list(leftover or [])),
                                "marker_present": staticmethod(lambda: marker),
                                "write_marker": staticmethod(lambda op: None),
                                "clear_marker": staticmethod(lambda: None),
                                "restart_dind": staticmethod(lambda: None)})()
    trust = type("T", (), {"read": staticmethod(lambda: ({"ok": verdict_ok}, "LS", "AS"))})()
    ad = FakeAdapters(probe, dind, runner, pull, scrub, reconcile, trust)
    cfg = cr.load_config(write_toml(tmp))
    # kortsluiten: verdict-binding niet toetsen in loop-tests
    object.__setattr__(cfg, "_digests_override", list(digests)) if False else None
    loop = EventLoop(clock); controller = Controller(loop)
    import logging
    rt = cr.Runtime(cfg, controller, loop, ad, clock, logging.getLogger("t"))
    rt._digests = list(digests)                       # pre-pull-bron injecteren
    rt._trust_green = lambda: (verdict_ok, "test")     # binding buiten scope in loop-tests
    return rt, controller, rec, clock
```

- [ ] **Stap 1: Falende tests (koude start weigert; na bevestiging+clean+pull start)**

```python
from _harness import build_runtime, State
class TestStartCondition(unittest.TestCase):
    def test_no_start_before_confirmed_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt, ctrl, rec, clock = build_runtime(tmp)
            rt.tick()                                   # één probe → onbevestigd
            self.assertNotIn("runner", rec.starts)
    def test_start_after_confirmed_clean_pulled(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt, ctrl, rec, clock = build_runtime(tmp)
            for _ in range(8):                          # meerdere ticks; klok +30s per probe
                clock.advance(30.0)
                # laat een gestarte scrub/pull meteen 'klaar (rc0)' zijn:
                for kind in ("scrub", "pull"):
                    rec.pops[kind].rc = 0
                rt.tick()
            self.assertIn("scrub", rec.starts)          # eerst schoon
            self.assertIn("pull", rec.starts)           # dan pre-pull
            self.assertIn("runner", rec.starts)         # dan start
            self.assertTrue(rec.starts.index("runner") > rec.starts.index("pull") > rec.starts.index("scrub"))
```

- [ ] **Stap 2: Run — FAIL.**
- [ ] **Stap 3: Implementeer het skelet + faseketen**

```python
import logging
from collections import namedtuple
from forgejo_runner_cycle import EventLoop, Controller, State, classify_probe, ReadinessClass

Adapters = namedtuple("Adapters", "probe dind runner pull scrub reconcile trust")

class Runtime:
    def __init__(self, cfg, controller, loop, adapters, clock, log):
        self.cfg=cfg; self.controller=controller; self.loop=loop; self.a=adapters
        self.clock=clock; self.log=log
        self.readiness=ReadinessConfirmed(); self.clean_proven=False
        self.child=None; self.op=None            # op = (kind, Popen)
        self._digests=[]; self._pull_queue=[]; self._loaded=False
        self._blocked=False; self._stop=False; self._reconciled=False
        self._last_probe=None; self._stop_deadline=None

    def _load_digests(self):
        if not self._loaded:
            with open(self.cfg.allowed_images_file, encoding="utf-8") as fh:
                self._digests = parse_allowed_images(fh.read())
            self._loaded = True

    def _trust_green(self):
        verdict, ls, as_ = self.a.trust.read()
        return verdict_green(verdict, self.clock()[1], self.cfg, ls, as_)

    def _readiness_and_gates(self, now):
        klasse = classify_probe(self.a.probe.probe())
        self.readiness.observe(klasse, now)
        self.controller.on_event(self.loop.submit("readiness", {"klasse": klasse}))
        green, _ = self._trust_green()
        self.controller.gates_groen = bool(green) and self.a.dind.healthy()

    def _busy(self): return self.op is not None or self.child is not None

    def _may_start(self):
        return (not self._blocked and not self._stop and not self._busy()
                and self.controller.mag_child_starten
                and self.controller.state == State.WAITING
                and self.readiness.confirmed and self.clean_proven and not self._pull_queue)

    def _begin_op(self, kind, digest=None):
        self.a.reconcile.write_marker(kind)
        p = self.a.pull.start(digest) if kind == "pull" else self.a.scrub.start()
        self.op = (kind, p)

    def _advance_op(self):
        if self.op is None: return
        kind, p = self.op
        rc = (self.a.pull.poll(p) if kind == "pull" else self.a.scrub.poll(p))
        if rc is None: return
        self.op = None; self.a.reconcile.clear_marker()
        if kind == "scrub":
            self.controller.on_event(self.loop.submit("scrub_done", {"ok": rc == 0}))
            self.clean_proven = (rc == 0)
            if rc != 0: self.log.warning("scrub faalde rc=%s", rc)
        else:  # pull
            if rc == 0:
                if self._pull_queue: self._pull_queue.pop(0)
            else:
                self._blocked = True; self.log.warning("pre-pull faalde rc=%s → geblokkeerd", rc)

    def _advance_child(self):
        if self.child is None: return
        rc = self.a.runner.poll(self.child)
        if rc is None: return
        self.child = None
        self.controller.on_event(self.loop.submit("child_exit", {"code": rc}))
        self._pull_queue = list(self._digests)          # volgende cyclus opnieuw pre-pullen
        if not self._stop:
            self._begin_op("scrub")                     # §7.9: scrub na élke exit

    def _drive_cycle(self):
        if self._blocked or self._stop or self._busy() or self.child is not None: return
        if not self.clean_proven: self._begin_op("scrub"); return
        if self._pull_queue: self._begin_op("pull", self._pull_queue[0]); return

    def _start_runner(self):
        self.clean_proven = False
        self.child = self.a.runner.start()

    def tick(self):
        self._load_digests()
        now, wall = self.clock()
        if self._last_probe is None or (now - self._last_probe) >= self.cfg.retry_interval:
            self._last_probe = now; self.a.dind.ensure_up(); self._readiness_and_gates(now)
        self.controller.tick(now, wall)
        self._reconcile_once()          # Taak 10
        self._advance_op()
        self._advance_child()
        self._drive_cycle()
        if self._may_start(): self._start_runner()

    def _reconcile_once(self): pass     # Taak 10
```

- [ ] **Stap 4: Run — PASS.**
- [ ] **Stap 5: Commit** `git commit -am "feat(controller): Runtime faseketen scrub→pre-pull→start"`

---

### Taak 9: `Runtime` — cyclus-uitkomsten (exit0/scrubfout) + B2-regressie

**Files:** Modify `tests/test_cycle_runtime.py`

- [ ] **Stap 1: Falende tests**

```python
class TestCycle(unittest.TestCase):
    def _ready(self, rt, rec, clock, n=8):
        for _ in range(n):
            clock.advance(30.0)
            for k in ("scrub","pull"): rec.pops[k].rc = 0
            rt.tick()
    def test_exit0_scrub_ok_waiting(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt, ctrl, rec, clock = build_runtime(tmp); self._ready(rt, rec, clock)
            self.assertIn("runner", rec.starts)
            rec.pops["runner"].rc = 0                    # runner klaar exit 0
            rec.pops["scrub"] = type(rec.pops["scrub"])(rc=0)  # verse scrub-Popen, rc0
            rt.tick(); rt.tick()
            self.assertTrue(rt.clean_proven)
    def test_scrub_fail_blocks_next_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt, ctrl, rec, clock = build_runtime(tmp); self._ready(rt, rec, clock)
            rec.pops["runner"].rc = 0
            rec.pops["scrub"] = type(rec.pops["scrub"])(rc=50)  # scrub faalt
            for _ in range(3): rt.tick()
            self.assertFalse(rt.clean_proven)
            self.assertFalse(rt._may_start())            # geen start op vuile DinD (B2)
```

- [ ] **Stap 2: Run — verwacht dat de eerste test al slaagt** (de faseketen uit Taak 8 dekt dit). Voeg alleen de assertions toe; als iets rood is, corrigeer de fase-afhandeling in `_advance_op`/`_advance_child`.
- [ ] **Stap 3: Commit** `git commit -am "test(controller): cyclus-uitkomsten + B2-regressie"`

---

### Taak 10: `Runtime` — startup-reconciliatie + operatiemarker (§6.4) + B1-guard

**Files:** Modify `cycle_runtime.py`, `tests/test_cycle_runtime.py`

- [ ] **Stap 1: Falende tests (B1: geblokkeerd start geen scrub/pull/launch; marker → herstart+scrub)**

```python
class TestReconcile(unittest.TestCase):
    def test_leftover_blocks_all_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt, ctrl, rec, clock = build_runtime(tmp, leftover=["live"])
            for _ in range(6):
                clock.advance(30.0)
                for k in ("scrub","pull"): rec.pops[k].rc = 0
                rt.tick()
            self.assertTrue(rt._blocked)
            self.assertEqual(rec.starts, [])             # géén scrub/pull/runner (B1)
    def test_marker_triggers_restart_and_scrub(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = {"restart": 0}
            rt, ctrl, rec, clock = build_runtime(tmp, marker=True)
            rt.a.reconcile.restart_dind = lambda: calls.__setitem__("restart", 1)
            rt.tick()
            self.assertEqual(calls["restart"], 1)
            self.assertIn("scrub", rec.starts)
            self.assertFalse(rt.clean_proven)
```

- [ ] **Stap 2: Run — FAIL.**
- [ ] **Stap 3: Implementeer `_reconcile_once` (fout uit Reconcile ⇒ blokkeer)**

```python
    def _reconcile_once(self):
        if self._reconciled: return
        self._reconciled = True
        try:
            if self.a.reconcile.leftover_runners():
                self._blocked = True; self.log.warning("startup: achtergebleven runner — fail-closed"); return
            if self.a.reconcile.marker_present():
                self.log.warning("startup: onderbroken operatie — DinD-herstart + volledige scrub")
                self.a.reconcile.restart_dind()
                self.clean_proven = False; self._begin_op("scrub")
        except Exception as exc:                         # ReconcileError e.d. → fail-closed
            self._blocked = True; self.log.warning("startup-reconciliatie faalde: %r → geblokkeerd", exc)
```

Bevestig dat `_drive_cycle` én `_may_start` beide `self._blocked` respecteren (staat al in Taak 8).

- [ ] **Stap 4: Run — PASS. Commit** `git commit -am "feat(controller): startup-reconciliatie + B1-guard (blokkeert alle mutatie)"`

---

### Taak 11: `Runtime` — stopcontract over álle operaties (§9, M6)

**Files:** Modify `cycle_runtime.py`, `tests/test_cycle_runtime.py`

- [ ] **Stap 1: Falende tests**

```python
class TestStop(unittest.TestCase):
    def test_stop_with_child_no_new_scrub_exit_after_gone(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt, ctrl, rec, clock = build_runtime(tmp)
            rt._stop=False; rt.child=rec.pops["runner"]; rt.request_stop()
            self.assertIn(15, rec.pops["runner"].signals)   # SIGTERM naar child
            rec.pops["runner"].rc=None; self.assertFalse(rt._stop_complete())
            rec.pops["runner"].rc=0; rt._advance_child()
            self.assertIsNone(rt.op)                          # géén nieuwe scrub tijdens stop
            self.assertTrue(rt._stop_complete())
    def test_stop_during_scrub_waits(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt, ctrl, rec, clock = build_runtime(tmp)
            rt.op=("scrub", rec.pops["scrub"]); rec.pops["scrub"].rc=None
            rt.request_stop(); self.assertFalse(rt._stop_complete())
            rec.pops["scrub"].rc=0; rt._advance_op(); self.assertTrue(rt._stop_complete())
    def test_deadline_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt, ctrl, rec, clock = build_runtime(tmp)
            rt.child=rec.pops["runner"]; rec.pops["runner"].rc=None
            self.assertEqual(rt._stop_result(overshoot=True), 1)   # geen succes bij deadline
```

- [ ] **Stap 2: Run — FAIL.**
- [ ] **Stap 3: Implementeer**

```python
    def request_stop(self):
        self._stop = True
        self.controller.drain(self.clock()[0])
        if self.child is not None: self.a.runner.request_stop(self.child)

    def _stop_complete(self):
        if self.child is not None or self.op is not None: return False
        try:
            return not self.a.reconcile.leftover_runners()   # container aantoonbaar weg
        except Exception:
            return False                                     # onbekend → niet klaar

    def _stop_result(self, overshoot):
        return 0 if (self._stop_complete() and not overshoot) else 1

    def run(self):
        import signal as _sig, time as _t
        _sig.signal(_sig.SIGTERM, lambda *_: self.request_stop())
        _sig.signal(_sig.SIGINT, lambda *_: self.request_stop())
        while True:
            self.tick()
            if self._stop:
                if self._stop_deadline is None:
                    self._stop_deadline = self.clock()[0] + self.cfg.child_stop_grace
                overshoot = self.clock()[0] >= self._stop_deadline
                if self._stop_complete() or overshoot:
                    if overshoot and not self._stop_complete():
                        self.log.warning("stop: grens overschreden — onschone stop")
                    return self._stop_result(overshoot)
            _t.sleep(self.cfg.poll_interval)
```

`_advance_child` start al géén scrub als `self._stop` (Taak 8). Bevestig dat en dat `_drive_cycle`/`_may_start` `_stop` respecteren.

- [ ] **Stap 4: Run — PASS. Commit** `git commit -am "feat(controller): stopcontract over child+pull+scrub, geen succes bij deadline"`

---

### Taak 12: `main()` + §10-logging + compose-command/mount + toml-template

**Files:** Modify `cycle_runtime.py`, `forgejo-runner/compose.yaml`; Create `forgejo-runner/controller.toml.example`; Modify `tests/test_cycle_runtime.py`, `tests/test_compose_contract.bats`

- [ ] **Stap 1: Falende tests (main --check; loggen van hart-alarmen)**

```python
class TestMain(unittest.TestCase):
    def test_check_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            # vervang de padverwijzingen door bestaande dummies zodat --check niet op IO struikelt
            cfg_path = write_toml(tmp)
            self.assertEqual(cr.main(["--config", cfg_path, "--check"]), 0)
    def test_missing_config(self):
        self.assertNotEqual(cr.main(["--config", "/nope.toml"]), 0)

class TestLogging(unittest.TestCase):
    def test_alarm_events_are_logged(self):
        import logging
        with tempfile.TemporaryDirectory() as tmp:
            rt, ctrl, rec, clock = build_runtime(tmp)
            with self.assertLogs(rt.log, level="WARNING") as cm:
                rt.loop.submit("alarm", {"klasse": "X", "reden": "test"})
                rt._drain_events()
            self.assertTrue(any("alarm" in m for m in cm.output))
```

- [ ] **Stap 2: Run — FAIL.**
- [ ] **Stap 3: Implementeer `_drain_events` + `main`** (drain de hart-events naar de log — §10)

```python
    def _drain_events(self):
        while getattr(self, "_ev_cursor", 0) < len(self.loop.events):
            ev = self.loop.events[self._ev_cursor]; self._ev_cursor = getattr(self, "_ev_cursor", 0) + 1
            if ev.kind in ("alarm", "fence_set", "cancel_en_redispatch"):
                self.log.warning("hart-event %s seq=%s payload=%s", ev.kind, ev.event_seq, ev.payload)
```

Roep `self._drain_events()` aan het einde van `tick()` aan. Init `self._ev_cursor = 0` in `__init__`.

```python
import argparse, os, sys

def _build_adapters(cfg):
    from cycle_adapters import (Clock, TransportProbe, DindHealth, RunnerLifecycle,
                                PullOp, ScrubOp, Reconcile, TrustVerdictReader)
    scrub = os.path.join(os.path.dirname(__file__), "scrub-dind.sh")
    allow = "/etc/forgejo-runner/allowed-job-images.txt"
    return Clock(), Adapters(
        probe=TransportProbe(cfg.forgejo_base_url, cfg.probe_timeout),
        dind=DindHealth(cfg.compose_file, cfg.project, timeout=cfg.subprocess_timeout),
        runner=RunnerLifecycle(cfg.compose_file, cfg.project, timeout=cfg.subprocess_timeout),
        pull=PullOp(cfg.compose_file, cfg.project, timeout=cfg.subprocess_timeout),
        scrub=ScrubOp(cfg.compose_file, cfg.project, scrub, allow, timeout=cfg.subprocess_timeout),
        reconcile=Reconcile(cfg.compose_file, cfg.project, cfg.marker_path, timeout=cfg.subprocess_timeout),
        trust=TrustVerdictReader(cfg.trust_verdict_path, cfg.labels_file, cfg.allowlist_file))

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True); ap.add_argument("--check", action="store_true")
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
    if args.check: return 0
    return rt.run()
```

- [ ] **Stap 4: compose.yaml** — service `runner`: voeg `command: ["one-job", "--wait"]` toe. Service `dind`, onder `volumes:`: `- ./allowed-job-images.txt:/etc/forgejo-runner/allowed-job-images.txt:ro`.
- [ ] **Stap 5: Maak `controller.toml.example`** (het §8-blok, met `marker_path` in `[dind]`; geen secrets).
- [ ] **Stap 6: Breid `test_compose_contract.bats` uit** — laad env voor de variabelen zodat `config` normaliseert:

```bash
@test "runner draagt one-job --wait; dind mount de allowlist read-only" {
  run env RUNNER_IMAGE=x DIND_IMAGE=y RUNNER_CPUS=1 RUNNER_MEM=1g RUNNER_PIDS=100 \
      DIND_CPUS=1 DIND_MEM=1g DIND_PIDS=100 docker compose -f compose.yaml config
  [ "$status" -eq 0 ]
  echo "$output" | grep -q "one-job"
  echo "$output" | grep -q "/etc/forgejo-runner/allowed-job-images.txt"
}
```

- [ ] **Stap 7: Run — PASS** (`unittest tests.test_cycle_runtime` + `bats tests/test_compose_contract.bats`).
- [ ] **Stap 8: Commit** `git commit -am "feat(controller): main() + §10-logging + compose command/mount + toml-template"`

---

### Taak 13: Deploy-wrapper `publish-trust-verdict.sh` (B3/M4/m10)

**Files:** Create `forgejo-runner/scripts/publish-trust-verdict.sh`; Create `forgejo-runner/tests/test_publish_trust_verdict.bats`

- [ ] **Stap 1: Falende bats-tests**

```bash
# forgejo-runner/tests/test_publish_trust_verdict.bats
setup() { TMP="$(mktemp -d)"; printf 'l' > "$TMP/labels.txt"; printf 'a' > "$TMP/allow.yml"; }
teardown() { rm -rf "$TMP"; }

@test "geeft de target door aan de CLI via FORGEJO_URL en bindt daaraan (B3)" {
  cat > "$TMP/cli.py" <<'PY'
import os, sys
out = sys.argv[sys.argv.index("--out")+1]
open(out + "/trust-verdict.json","w").write('{"ok":true}')
open(os.environ["PROBE_FILE"],"w").write(os.environ.get("FORGEJO_URL","UNSET"))
PY
  PROBE_FILE="$TMP/seen" run scripts/publish-trust-verdict.sh --cli-py "$TMP/cli.py" \
    --labels "$TMP/labels.txt" --allowlist "$TMP/allow.yml" --target https://git.jp-visser.nl --out "$TMP/v.json"
  [ "$status" -eq 0 ]
  [ "$(cat "$TMP/seen")" = "https://git.jp-visser.nl" ]      # CLI zag de target-bron
  grep -q '"forgejo_target":"https://git.jp-visser.nl"' "$TMP/v.json"
  grep -q '"measured_at":' "$TMP/v.json"
}

@test "mislukte meting publiceert geen nieuw groen en meldt falen (M4)" {
  printf '{"ok":true,"measured_at":9999999999,"forgejo_target":"x"}' > "$TMP/v.json"; cp "$TMP/v.json" "$TMP/before"
  cat > "$TMP/fail.py" <<'PY'
import sys; sys.exit(30)
PY
  run scripts/publish-trust-verdict.sh --cli-py "$TMP/fail.py" --labels "$TMP/labels.txt" \
    --allowlist "$TMP/allow.yml" --target https://x --out "$TMP/v.json"
  [ "$status" -ne 0 ]                                        # falen zichtbaar
  diff "$TMP/before" "$TMP/v.json"                           # geen NIEUW groen gepubliceerd
}
```

- [ ] **Stap 2: Run — FAIL.**
- [ ] **Stap 3: Implementeer** (invoke via `python3`; `FORGEJO_URL=target`; hashtool vooraf gekozen)

```bash
#!/bin/sh
# forgejo-runner/scripts/publish-trust-verdict.sh
# Deploy-wrapper (§6.3). Draait de trustgate-CLI met FORGEJO_URL=<target> in een
# verse out-dir; publiceert een controller-verdict met measured_at + binding aan
# de WERKELIJK gemeten target ALLEEN bij CLI-exit 0. Bij falen wordt niets
# gepubliceerd en het oude bestand niet aangeraakt (het vervalt op measured_at).
# Exit: 0 gepubliceerd, 3 meting mislukt, 2 gebruik.
set -eu

hashtool() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'
  else echo "geen sha256-tool" >&2; exit 2; fi
}

CLI_PY=""; LABELS=""; ALLOWLIST=""; TARGET=""; OUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --cli-py) CLI_PY="$2"; shift 2;; --labels) LABELS="$2"; shift 2;;
    --allowlist) ALLOWLIST="$2"; shift 2;; --target) TARGET="$2"; shift 2;;
    --out) OUT="$2"; shift 2;; *) echo "onbekend: $1" >&2; exit 2;;
  esac
done
[ -n "$CLI_PY" ] && [ -f "$LABELS" ] && [ -f "$ALLOWLIST" ] && [ -n "$TARGET" ] && [ -n "$OUT" ] || {
  echo "gebruik: --cli-py P --labels L --allowlist A --target T --out O" >&2; exit 2; }

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
# De CLI meet de bron uit FORGEJO_URL (trust_scope_cli.py); bind het verdict daaraan.
if ! FORGEJO_URL="$TARGET" python3 "$CLI_PY" --allowlist "$ALLOWLIST" --labels "$LABELS" --out "$WORK"; then
  echo "trustmeting mislukt; geen nieuw verdict gepubliceerd" >&2; exit 3
fi
OKVAL="$(grep -o '"ok"[[:space:]]*:[[:space:]]*\(true\|false\)' "$WORK/trust-verdict.json" | grep -o 'true\|false' | head -1)"
LS="$(hashtool "$LABELS")"; AS="$(hashtool "$ALLOWLIST")"
TMP="$OUT.tmp.$$"
printf '{"ok":%s,"measured_at":%s,"forgejo_target":"%s","labels_sha256":"%s","allowlist_sha256":"%s"}\n' \
  "${OKVAL:-false}" "$(date +%s)" "$TARGET" "$LS" "$AS" > "$TMP"
mv -f "$TMP" "$OUT"
```

- [ ] **Stap 4: `chmod +x scripts/publish-trust-verdict.sh` + run — PASS.**
- [ ] **Stap 5: Commit** `git commit -am "feat(controller): publish-trust-verdict.sh (target-binding, python3-invoke, hashtool)"`

---

### Taak 14: Volledige gate (unittest + ruff + bats) + bring-up-runbook

**Files:** Create `docs/forgejo-runner-pool/evidence/stap-d/bring-up-runbook.md`

- [ ] **Stap 1: Volledige suite**

Run:
```bash
cd forgejo-runner
python3 -m unittest discover -s tests -p 'test_*.py'
ruff check scripts/
bats tests/test_compose_contract.bats tests/test_publish_trust_verdict.bats
```
Expected: alles groen (99 hart-tests + runtime-tests; bats groen; ruff schoon). Repareer wat rood is; commit fixes apart.

- [ ] **Stap 2: Schrijf `bring-up-runbook.md`** — handmatige stap-D/E-smoke op max2 (`ssh janpeter@max2`): (1) `publish-trust-verdict.sh` met de operator-`FORGEJO_TOKEN`; (2) bundel op gepinde SHA, `controller.toml` invullen, `docker inspect` runner-image → entrypoint/argv (§6.2); (3) `docker compose up -d dind`, unit starten, runner online in Forgejo; (4) één groene + één rode smoke-workflow, groene scrub, `systemctl stop` → schone stop; (5) bewijs (endpoints §7.5, geen hostlisteners, DinD-isolatie) onder `evidence/stap-d|e/`.

- [ ] **Stap 3: Commit** `git commit -am "docs(controller): bring-up-runbook stap D/E"`

---

## Self-review (uitgevoerd)

**Spec-dekking:** §4 → T1/T5/T7/T12; §5+§5.2 (4-weg + preconditions) → T4/T8/T10/T11; §6 adapters → T5–T7; §6.1 cyclus incl. **pre-pull** → T8; stap 0 → T10; §6.2 → T12; §6.3 (verdict + wrapper met target-binding) → T3/T7/T13; §6.4 marker → T7/T10; §7.3 exit → T8/T9; §7.4 → T8/T10; §8 → T1/T12; §9 stopcontract → T11; §10 logging → T12; §11 tests → alle; §12 → T14. Geen gat.

**Placeholders:** geen; elke stap draagt echte code. `main --check` is expliciet gedefinieerd.

**Type-consistentie:** `Adapters`-velden identiek in T7/T8/T12; fase-namen `"scrub"/"pull"/"runner"` consistent in `_begin_op`/`_advance_*`/`Recorder`; `_stop`/`_blocked`/`clean_proven`/`_pull_queue` door T8–T12; `verdict_green`-signatuur identiek T3/T8; `ReconcileError` T7/T10.

**Adres ronde-1-review:** B1 (`_blocked` guard't `_drive_cycle` én `_may_start` → T10-test `rec.starts==[]`); B2 (`Reconcile._checked` raise, `_reconcile_once` fail-closed → T7/T10); B3 (`FORGEJO_URL=$TARGET` → T13); M4 (falen publiceert geen nieuw groen, `diff` → T13); M5 (pre-pull-fase + `-H` → T6/T8); M6 (`_stop_result` non-zero, geen scrub tijdens stop → T11); M7 (gedeelde `FakeClock`+`FakePopen`+`_harness` sys.path, echte fixtures, consistent poll → alle tests); M8 (`"version" in obj` + TimeoutError/OSError → T5); M9 (`math.isfinite` + bool-afwijzing → T3); m10 (`python3`-invoke + `hashtool` → T13); m11 (`_drain_events`-logging + bats in gate → T12/T14).

---

## Uitvoering

**Plan opgeslagen. Twee opties:** (1) **Subagent-Driven** (aanbevolen) — fresh subagent per taak, review tussen taken (superpowers:subagent-driven-development); (2) **Inline** — superpowers:executing-plans, batch met checkpoints. Werk in een isolatie-worktree op branch `feat/forgejo-runner-pool-controller-entrypoint`.

## Review record

Delta-variant, één cross-model reviewer `mac:codex` (het plan is claude-authored).

### Ronde 1 — commit `b7a3c32` — mac:codex — NO-GO (3 BLOCKER, 6 MAJOR, 2 MINOR)

Alle bevindingen geverifieerd tegen de boom (codex reproduceerde plan-code in isolatie) en aanvaard:

- **B1** — `_blocked` guardde alleen de launch; `_advance` kon een scrub starten die de levende leftover-job sloopt. Fix: `_blocked`/`_stop` blokkeren élke muterende actie (`_drive_cycle` + `_may_start`); test asserteert `rec.starts==[]` (T10).
- **B2** — `Reconcile` negeerde returncodes (fail-open). Fix: `_checked` raise `ReconcileError`; `_reconcile_once` fail-closed (T7/T10).
- **B3** — wrapper bond aan `--target` maar gaf die niet aan de CLI (die leest `FORGEJO_URL`). Fix: `FORGEJO_URL=$TARGET` bij de CLI (T13).
- **M4** — mislukte meting mocht oud groen niet als nieuwe validatie laten gelden. Fix: falen publiceert niets + exit≠0; freshness blijft aan `measured_at` verankerd; test met `diff` (T13). (Deployment-generatie-binding is follow-up.)
- **M5** — pre-pull ontbrak volledig; `PullOp` miste `-H`. Fix: expliciete pre-pull-fase per digest (scrub→pull→start), `-H tcp://127.0.0.1:2375` (T6/T8).
- **M6** — stop retourneerde 0 bij deadline en dekte pull/scrub niet; child-exit startte scrub tijdens stop. Fix: `_stop_complete` over alle operaties + leftover-check, `_stop_result` non-zero bij overshoot, geen scrub bij `_stop`, `controller.drain` (T11).
- **M7** — de testreeks werd niet groen. Fix: gedeeld `_harness` (sys.path zoals `test_cycle_readiness.py:6`, één `FakeClock` voor hart+runtime, `FakePopen` met stuurbare rc, echte scriptfixtures, consistent poll-contract, assertions op fases/aantallen).
- **M8** — probe accepteerde verkeerd schema + miste timeouts. Fix: `"version" in obj`, vang `TimeoutError/OSError`, sluit de response (T5).
- **M9** — NaN passeerde de leeftijdscontrole. Fix: `math.isfinite` + bool-afwijzing (T3).
- **m10** — CLI is mode 100644 + broze hashfallback. Fix: `python3 "$CLI_PY"`, `hashtool` kiest vooraf (T13).
- **m11** — logging/gate incompleet. Fix: `_drain_events` logt hart-alarmen (§10), gate draait ook bats, compose-test met fixture-env (T12/T14).

Verdict ronde 1: **NO-GO**. Fixes toegepast; ronde 2 opnieuw naar `mac:codex`.
