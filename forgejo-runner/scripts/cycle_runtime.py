# forgejo-runner/scripts/cycle_runtime.py
"""Runtime-schil rond forgejo_runner_cycle.py (dunne bring-up)."""
import re
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
