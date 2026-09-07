# forgejo-runner/tests/_harness.py
import collections, dataclasses, os, pathlib, signal, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import cycle_runtime as cr          # noqa: E402
from forgejo_runner_cycle import (  # noqa: E402
    EventLoop, Controller, State, ReadinessClass as RC, classify_probe)
# cycle_adapters bestaat pas vanaf Taak 5; tests die het nodig hebben doen zelf
# `import cycle_adapters as ca` ná deze import (die zet sys.path). Alle per-taak
# runs gebruiken de discovery-vorm zodat tests/ op sys.path staat:
#   python3 -m unittest discover -s tests -p 'test_cycle_runtime.py' -v

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
    p = os.path.join(tmp, "controller.toml")
    with open(p, "wb") as fh:
        fh.write(data)
    return p

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

FakeAdapters = collections.namedtuple("FakeAdapters", "probe dind runner pull scrub reconcile trust")

class Recorder:
    """Elke start levert een VERSE FakePopen — geen exitcode-erfenis (M3). scrub/pull
    voltooien standaard rc=0 op de volgende _advance_op; de runner blijft lopen
    (rc=None) tot een test hem afrondt. Stuur via `auto[kind]` (rc bij start) of
    `pops[kind].rc` (na de start)."""
    def __init__(self):
        self.starts = []; self.pops = {}; self.auto = {"scrub": 0, "pull": 0, "runner": None}
    def _mk(self, kind):
        self.starts.append(kind); p = FakePopen([kind], rc=self.auto[kind])
        self.pops[kind] = p; return p

def build_runtime(tmp, klasse="READY", healthy=True, verdict_ok=True,
                  leftover=None, marker=False, digests=("img@sha256:"+"a"*64,)):
    clock = FakeClock(); rec = Recorder()
    pd = ({"kind":"general","error":None,"status":200,"schema_ok":True} if klasse=="READY"
          else {"kind":"general","error":"x","status":None,"schema_ok":False})
    probe = type("P", (), {"probe": staticmethod(lambda: pd)})()
    dind = type("D", (), {"ensure_up": staticmethod(lambda: None), "healthy": staticmethod(lambda: healthy)})()
    runner = type("R", (), {"start": lambda s: rec._mk("runner"),
                            "request_stop": lambda s, p: p.send_signal(signal.SIGTERM),
                            "poll": lambda s, p: p.poll()})()
    pull = type("Pu", (), {"start": lambda s, d: rec._mk("pull"), "poll": lambda s, p: p.poll()})()
    scrub = type("Sc", (), {"start": lambda s: rec._mk("scrub"), "poll": lambda s, p: p.poll()})()
    mkst = {"m": marker}                          # stateful marker zodat tests hem observeren (M1)
    reconcile = type("Re", (), {"leftover_runners": staticmethod(lambda: list(leftover or [])),
                                "marker_present": staticmethod(lambda: mkst["m"]),
                                "write_marker": staticmethod(lambda op: mkst.__setitem__("m", True)),
                                "clear_marker": staticmethod(lambda: mkst.__setitem__("m", False)),
                                "restart_dind": staticmethod(lambda: None)})()
    trust = type("T", (), {"read": staticmethod(lambda: ({"ok": verdict_ok}, "LS", "AS"))})()
    ad = FakeAdapters(probe, dind, runner, pull, scrub, reconcile, trust)
    # ECHT tijdelijk allowed-images-bestand zodat _load_digests de test-digests leest (M3)
    img = os.path.join(tmp, "allowed.txt")
    with open(img, "w") as f:
        f.write("# test\n" + "".join(f"{d}\t1\n" for d in digests))
    cfg = dataclasses.replace(cr.load_config(write_toml(tmp)), allowed_images_file=img)
    loop = EventLoop(clock); controller = Controller(loop)
    import logging as _lg
    rt = cr.Runtime(cfg, controller, loop, ad, clock, _lg.getLogger("t"))
    rt._trust_green = lambda: (verdict_ok, "test")     # verdict-binding buiten scope in loop-tests
    return rt, controller, rec, clock
