# forgejo-runner/tests/_harness.py
import pathlib, sys
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
    import os
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
