# forgejo-runner/scripts/cycle_runtime.py
"""Runtime-schil rond forgejo_runner_cycle.py (dunne bring-up)."""

import argparse
import os
import sys
import logging
import math
import re
import signal
import tomllib
from collections import namedtuple
from dataclasses import dataclass

from forgejo_runner_cycle import (
    Controller,
    EventLoop,
    ReadinessClass,
    State,
    classify_probe,
    CONFIRM_SECONDS,
)


@dataclass(frozen=True)
class Config:
    forgejo_base_url: str
    probe_timeout: float
    compose_file: str
    project: str
    marker_path: str
    allowed_images_file: str
    child_stop_grace: float
    trust_verdict_path: str
    trust_verdict_max_age: float
    labels_file: str
    allowlist_file: str
    subprocess_timeout: float
    poll_interval: float
    retry_interval: float
    log_level: str


def _req(d, section, key):
    try:
        return d[section][key]
    except (KeyError, TypeError):
        raise ValueError(f"controller.toml mist {section}.{key}") from None


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


# TimeoutStopSec van forgejo-runner-cycle.service: systemd SIGKILLt de controller na
# deze tijd, dus de stopgrace van de runner-child moet er strikt onder blijven.
UNIT_TIMEOUT_STOP_SEC = 300
_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def validate_config(cfg):
    """Semantische controle voor --check; geeft ALLE problemen terug (lege lijst = ok).
    Bewust niet in load_config: die draait ook bij echte start, waar de
    trust-verdict-map en bestanden door timers/installatie ontstaan."""
    problems = []
    for naam in ("compose_file", "allowed_images_file", "labels_file", "allowlist_file"):
        pad = getattr(cfg, naam)
        if not os.path.isfile(pad):
            problems.append(f"{naam} is geen bestaand bestand: {pad}")
    for naam in ("marker_path", "trust_verdict_path"):
        map_ = os.path.dirname(getattr(cfg, naam))
        if not os.path.isdir(map_):
            problems.append(f"map van {naam} bestaat niet: {map_}")
    for naam in (
        "poll_interval",
        "retry_interval",
        "probe_timeout",
        "subprocess_timeout",
        "child_stop_grace",
    ):
        waarde = getattr(cfg, naam)
        if not (math.isfinite(waarde) and waarde > 0):
            problems.append(f"{naam} moet een eindig getal > 0 zijn: {waarde}")
    if math.isfinite(cfg.child_stop_grace) and cfg.child_stop_grace >= UNIT_TIMEOUT_STOP_SEC:
        problems.append(
            f"child_stop_grace ({cfg.child_stop_grace}) moet < {UNIT_TIMEOUT_STOP_SEC} "
            "(TimeoutStopSec van de unit)"
        )
    if cfg.log_level not in _LOG_LEVELS:
        problems.append(f"log.level {cfg.log_level!r} niet in {', '.join(_LOG_LEVELS)}")
    return problems


_DIGEST_RE = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")


def parse_allowed_images(text):
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        digest = line.split("\t", 1)[0].strip()
        if not _DIGEST_RE.match(digest):
            raise ValueError(f"ongeldige digest-regel: {raw!r}")
        out.append(digest)
    return out


def verdict_green(verdict, now_wall, cfg, labels_sha, allowlist_sha):
    if not isinstance(verdict, dict):
        return False, "verdict is geen object"
    if verdict.get("ok") is not True:
        return False, "ok is niet true"
    m = verdict.get("measured_at")
    if isinstance(m, bool) or not isinstance(m, (int, float)) or not math.isfinite(m):
        return False, "measured_at ontbreekt/ongeldig/niet-eindig"
    age = now_wall - float(m)
    if age < 0:
        return False, "measured_at ligt in de toekomst"
    if age > cfg.trust_verdict_max_age:
        return False, "verdict is te oud"
    if verdict.get("forgejo_target") != cfg.forgejo_base_url:
        return False, "target-binding mismatch"
    if verdict.get("labels_sha256") != labels_sha:
        return False, "labels-binding mismatch"
    if verdict.get("allowlist_sha256") != allowlist_sha:
        return False, "allowlist-binding mismatch"
    return True, "groen"


class ReadinessConfirmed:
    def __init__(self, confirm_seconds=CONFIRM_SECONDS):
        self._confirm = confirm_seconds
        self._first = None
        self.confirmed = False

    def observe(self, klasse, mono):
        if klasse is not ReadinessClass.READY:
            self._first = None
            self.confirmed = False
            return
        if self._first is None:
            self._first = mono
        elif (mono - self._first) >= self._confirm:
            self.confirmed = True


Adapters = namedtuple("Adapters", "probe dind runner pull scrub reconcile trust")


class Runtime:
    def __init__(self, cfg, controller, loop, adapters, clock, log):
        self.cfg = cfg
        self.controller = controller
        self.loop = loop
        self.a = adapters
        self.clock = clock
        self.log = log
        self.readiness = ReadinessConfirmed()
        self.clean_proven = False
        self.child = None
        self.op = None  # op = (kind, Popen)
        self._digests = []
        self._pull_queue = []
        self._loaded = False
        self._blocked = False
        self._blocked_reason = None
        self._blocked_logged = None  # mono-tijd van de laatste blokkade-logregel
        self._dind_last = None  # laatst gelogde (gezond, detail) van de DinD-gate
        self._stop = False
        self._reconciled = False
        self._last_probe = None
        self._stop_deadline = None
        self._ev_cursor = 0
        self._trust_last = None  # laatst gelogde (groen, reden) van de trustgate

    def _load_digests(self):
        if not self._loaded:
            with open(self.cfg.allowed_images_file, encoding="utf-8") as fh:
                self._digests = parse_allowed_images(fh.read())
            self._pull_queue = list(
                self._digests
            )  # óók de EERSTE cyclus pre-pullt (M2)
            self._loaded = True

    def _trust_green(self):
        try:
            verdict, ls, as_ = self.a.trust.read()
        except Exception as exc:  # fail-closed: een onverwachte leesfout mag de tick niet slopen
            return False, f"trust-read faalde: {type(exc).__name__}: {exc}"
        green, reden = verdict_green(verdict, self.clock()[1], self.cfg, ls, as_)
        detail = getattr(self.a.trust, "last_error", None)
        if not green and detail:
            reden = f"{reden} ({detail})"
        return green, reden

    def _safe_probe(self):
        try:
            return self.a.probe.probe()
        except Exception as exc:
            self.log.warning("probe faalde onverwacht: %s: %s → transportfout", type(exc).__name__, exc)
            return {"kind": "general", "error": f"{type(exc).__name__}: {exc}", "status": None, "schema_ok": False}

    def _dind_healthy(self):
        try:
            healthy = bool(self.a.dind.healthy())
            detail = "" if healthy else f"rc={getattr(self.a.dind, 'last_rc', None)}"
        except Exception as exc:
            healthy = False
            detail = f"{type(exc).__name__}: {exc}"
        state = (healthy, detail)
        if state != self._dind_last:
            eerste = self._dind_last is None
            self._dind_last = state
            if healthy:
                if not eerste:  # een gezonde start is geen nieuws, herstel wel
                    self.log.info("dind gezond")
            else:
                self.log.warning("dind health-check ROOD: %s → geen nieuwe runners", detail)
        return healthy

    def _block(self, reden, now=None):
        # Eén plek waar de blokkade aan gaat, zodat de reden nooit stil verdwijnt.
        if not self._blocked:
            self.log.warning("controller GEBLOKKEERD: %s", reden)
            self._blocked_logged = self.clock()[0] if now is None else now
        self._blocked = True
        self._blocked_reason = reden

    def _remind_blocked(self, now):
        if self._blocked and (now - self._blocked_logged) >= self.cfg.retry_interval:
            self._blocked_logged = now
            self.log.warning("controller nog steeds geblokkeerd: %s", self._blocked_reason)

    def _log_trust_transition(self, green, reden):
        # Een rode trustgate was stil: de reden werd weggegooid terwijl unit en DinD
        # groen bleven, dus de runner viel uit zonder spoor in de journal (max2 ISS-8,
        # en opnieuw 2026-09-25). Alleen loggen bij een wissel — dit draait elke tick.
        state = (bool(green), reden)
        if state == self._trust_last:
            return
        self._trust_last = state
        if green:
            self.log.info("trustgate groen")
        else:
            self.log.warning("trustgate ROOD: %s → geen nieuwe runners", reden)

    def _readiness_and_gates(self, now):
        klasse = classify_probe(self._safe_probe())
        self.readiness.observe(klasse, now)
        self.controller.on_event(self.loop.submit("readiness", {"klasse": klasse}))
        green, reden = self._trust_green()
        self._log_trust_transition(green, reden)
        healthy = self._dind_healthy()
        self.controller.gates_groen = bool(green) and healthy

    def _busy(self):
        return self.op is not None or self.child is not None

    def _may_start(self):
        return (
            not self._blocked
            and not self._stop
            and not self._busy()
            and self.controller.mag_child_starten
            and self.controller.state == State.WAITING
            and self.readiness.confirmed
            and self.clean_proven
            and not self._pull_queue
        )

    def _begin_op(self, kind, digest=None):
        self.a.reconcile.write_marker(kind)
        p = self.a.pull.start(digest) if kind == "pull" else self.a.scrub.start()
        self.op = (kind, p)

    def _advance_op(self):
        if self.op is None:
            return
        kind, p = self.op
        rc = self.a.pull.poll(p) if kind == "pull" else self.a.scrub.poll(p)
        if rc is None:
            return
        self.op = None
        if (
            rc is not None and rc >= 0
        ):  # normaal geëindigd → DinD-side klaar → marker weg;
            self.a.reconcile.clear_marker()  # rc<0 (door signaal gedood) → onzeker einde → marker bewaren (M1/M4)
        if kind == "scrub":
            self.controller.on_event(self.loop.submit("scrub_done", {"ok": rc == 0}))
            self.clean_proven = rc == 0
            self.log.info("cyclus: scrub ok=%s", rc == 0)
            if rc != 0:
                self.log.warning("scrub faalde rc=%s", rc)
        else:  # pull
            if rc == 0:
                if self._pull_queue:
                    self._pull_queue.pop(0)
            else:
                self._block(f"pre-pull faalde rc={rc}")

    def _advance_child(self):
        if self.child is None:
            return
        rc = self.a.runner.poll(self.child)
        if rc is None:
            return
        self.child = None
        self.log.info("cyclus: runner exit rc=%s", rc)
        self.controller.on_event(self.loop.submit("child_exit", {"code": rc}))
        self._pull_queue = list(self._digests)  # volgende cyclus opnieuw pre-pullen
        if not self._stop:
            self._begin_op("scrub")  # §7.9: scrub na élke exit

    def _drive_cycle(self):
        if self._blocked or self._stop or self._busy() or self.child is not None:
            return
        if not self.clean_proven:
            self._begin_op("scrub")
            return
        if self._pull_queue:
            self._begin_op("pull", self._pull_queue[0])
            return

    def _start_runner(self):
        self.clean_proven = False
        try:
            self.child = self.a.runner.start()
        except Exception as exc:  # fail-closed: geen child, volgende tick probeert opnieuw
            self.child = None
            self.log.warning("runner-start faalde: %s: %s → geen runner", type(exc).__name__, exc)
            return
        self.log.info("cyclus: runner gestart")

    def tick(self):
        self._load_digests()
        now, wall = self.clock()
        if (
            self._last_probe is None
            or (now - self._last_probe) >= self.cfg.retry_interval
        ):
            self._last_probe = now
            try:
                rc = self.a.dind.ensure_up()
                if isinstance(rc, int) and rc != 0:
                    self.log.warning("dind ensure_up (compose up -d dind) gaf rc=%s", rc)
            except Exception as exc:
                self.log.warning("dind ensure_up faalde: %r", exc)
            self._readiness_and_gates(now)
        self._remind_blocked(now)
        self.controller.tick(now, wall)
        self._reconcile_once()  # Taak 10
        self._advance_op()
        self._advance_child()
        self._drive_cycle()
        if self._may_start():
            self._start_runner()
        self._drain_events()

    def _drain_events(self):
        while getattr(self, "_ev_cursor", 0) < len(self.loop.events):
            ev = self.loop.events[self._ev_cursor]
            self._ev_cursor = getattr(self, "_ev_cursor", 0) + 1
            if ev.kind in ("alarm", "fence_set", "cancel_en_redispatch"):
                self.log.warning(
                    "hart-event %s seq=%s payload=%s", ev.kind, ev.event_seq, ev.payload
                )

    def _reconcile_once(self):
        if self._reconciled or self._stop:
            return  # geen reconcile/mutatie tijdens stop (M4)
        self._reconciled = True
        try:
            if self.a.reconcile.leftover_runners():
                self._block("startup: achtergebleven runner — fail-closed")
                return
            if self.a.reconcile.marker_present():
                self.log.warning(
                    "startup: onderbroken operatie — DinD-herstart + volledige scrub"
                )
                self.a.reconcile.restart_dind()
                self.clean_proven = False
                self._begin_op("scrub")
        except Exception as exc:  # ReconcileError e.d. → fail-closed
            self._block(f"startup-reconciliatie faalde: {exc!r}")

    def request_stop(self):
        self._stop = True
        self.controller.drain(self.clock()[0])
        if self.child is not None:
            self.a.runner.request_stop(self.child)
        if self.op is not None:  # ook een lopende pull/scrub signaleren (M4/§9)
            self.op[1].send_signal(signal.SIGTERM)

    def _stop_complete(self):
        if self.child is not None or self.op is not None:
            return False
        try:
            return not self.a.reconcile.leftover_runners()  # container aantoonbaar weg
        except Exception:
            return False  # onbekend → niet klaar

    def _stop_result(self, overshoot):
        if overshoot or not self._stop_complete():
            return 1
        return (
            1 if self.a.reconcile.marker_present() else 0
        )  # bewaarde marker = onzeker einde → non-zero (M1)

    def run(self):
        import signal as _sig
        import time as _t

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


def _build_adapters(cfg):
    from cycle_adapters import (
        Clock,
        TransportProbe,
        DindHealth,
        RunnerLifecycle,
        PullOp,
        ScrubOp,
        Reconcile,
        TrustVerdictReader,
    )

    scrub = os.path.join(os.path.dirname(__file__), "scrub-dind.sh")
    allow = "/etc/forgejo-runner/allowed-job-images.txt"
    return Clock(), Adapters(
        probe=TransportProbe(cfg.forgejo_base_url, cfg.probe_timeout),
        dind=DindHealth(cfg.compose_file, cfg.project, timeout=cfg.subprocess_timeout),
        runner=RunnerLifecycle(
            cfg.compose_file, cfg.project, timeout=cfg.subprocess_timeout
        ),
        pull=PullOp(cfg.compose_file, cfg.project, timeout=cfg.subprocess_timeout),
        scrub=ScrubOp(
            cfg.compose_file, cfg.project, scrub, allow, timeout=cfg.subprocess_timeout
        ),
        reconcile=Reconcile(
            cfg.compose_file,
            cfg.project,
            cfg.marker_path,
            timeout=cfg.subprocess_timeout,
        ),
        trust=TrustVerdictReader(
            cfg.trust_verdict_path, cfg.labels_file, cfg.allowlist_file
        ),
    )


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        cfg = load_config(args.config)
    except (OSError, ValueError) as exc:
        print(f"config-fout: {exc}", file=sys.stderr)
        return 2
    if args.check:
        # Vóór _build_adapters: --check raakt geen docker, netwerk of loop.
        problems = validate_config(cfg)
        if problems:
            print("config-fout: " + "; ".join(problems), file=sys.stderr)
            return 2
        return 0
    logging.basicConfig(
        level=getattr(logging, cfg.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    clock, adapters = _build_adapters(cfg)
    controller = Controller(EventLoop(clock))
    rt = Runtime(
        cfg, controller, controller.loop, adapters, clock, logging.getLogger("cycle")
    )
    return rt.run()


if __name__ == "__main__":
    # Het gedocumenteerde `python3 scripts/cycle_runtime.py --config … --check`.
    # Geen circulaire import: forgejo_runner_cycle importeert cycle_runtime alleen
    # binnen zijn eigen __main__-blok.
    raise SystemExit(main())
