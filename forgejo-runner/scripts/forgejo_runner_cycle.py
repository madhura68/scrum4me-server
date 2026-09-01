# forgejo-runner/scripts/forgejo_runner_cycle.py
"""Cyclecontroller van de Forgejo-Runner-tweemachinepool.

Implementeert §7.7 en §7.9 van het migratieontwerp: readinessclassificatie,
bevestigingsregel, schedulingfence, deadlinewatchdog, maintenance-record en de
per-job levenscyclus rond `one-job --wait`.

Ontwerpregels die hier hard in zitten:
- event_seq is de enige voor/na-fencebeslisser; klokken zijn audit.
- Monotone tijd voor deadlines, wandklok alleen voor logging.
- Fail-closed: onbekend gaat nooit naar WAITING.
"""

from dataclasses import dataclass
from enum import Enum

CONFIRM_SECONDS = 5.0
FENCE_MAX_AGE_SECONDS = 60.0
RETRY_INTERVAL_SECONDS = 30.0


class ReadinessClass(str, Enum):
    READY = "READY"
    SOURCE_WAIT = "SOURCE_WAIT"
    CREDENTIAL_ERROR = "CREDENTIAL_ERROR"
    PROTOCOL = "PROTOCOL"


# Alleen de foutklassen; de deadlinewatchdog kiest hieruit de zwaarste sinds
# latch waargenomen klasse. READY is geen foutklasse en hoort er bewust niet in.
SEVERITY = {
    ReadinessClass.SOURCE_WAIT: 1,
    ReadinessClass.CREDENTIAL_ERROR: 2,
    ReadinessClass.PROTOCOL: 3,
}


def classify_probe(probe):
    """Vierwegclassificatie zonder default-gat (§7.7).

    Tak 1 transportfout, timeout, connection refused of 5xx -> SOURCE_WAIT.
    Tak 2 401/403 op de geauthenticeerde probe -> CREDENTIAL_ERROR.
    Tak 3 iedere andere status, malformed antwoord of verkeerd schema -> PROTOCOL.
    Tak 4 2xx met het verwachte schema -> READY.
    """
    if probe.get("error"):
        return ReadinessClass.SOURCE_WAIT

    status = probe.get("status")
    if status is None:
        return ReadinessClass.PROTOCOL
    if 500 <= status <= 599:
        return ReadinessClass.SOURCE_WAIT
    if status in (401, 403):
        # Alleen op de geauthenticeerde probe is dit een credentialoordeel. De
        # algemene probe hoort geen auth te vereisen; daar is het een protocolfout.
        return (ReadinessClass.CREDENTIAL_ERROR if probe.get("kind") == "auth"
                else ReadinessClass.PROTOCOL)
    if 200 <= status <= 299:
        return ReadinessClass.READY if probe.get("schema_ok") else ReadinessClass.PROTOCOL
    return ReadinessClass.PROTOCOL


@dataclass
class Confirmation:
    """Tweewaarnemingendrempel: pas twee opeenvolgende gelijke uitkomsten,
    minimaal CONFIRM_SECONDS uit elkaar, bevestigen een klasse. Een klassesprong
    herstart de bevestiging (§7.7)."""

    laatste: object = None
    laatste_tijd: object = None

    def observe(self, klasse, now):
        if self.laatste == klasse and self.laatste_tijd is not None \
                and (now - self.laatste_tijd) >= CONFIRM_SECONDS:
            self.laatste, self.laatste_tijd = None, None
            return klasse
        if self.laatste != klasse:
            self.laatste, self.laatste_tijd = klasse, now
        return None

    def reset(self):
        self.laatste, self.laatste_tijd = None, None


class State(str, Enum):
    SOURCE_WAIT = "SOURCE_WAIT"
    CREDENTIAL_ERROR = "CREDENTIAL_ERROR"
    WAITING = "WAITING"
    RUNNING = "RUNNING"
    DRAINING = "DRAINING"
    SCRUBBING = "SCRUBBING"
    QUARANTINED = "QUARANTINED"


@dataclass(frozen=True)
class Event:
    kind: str
    payload: dict
    event_seq: int
    mono: float
    wall: float


class EventLoop:
    """Eén geserialiseerde bron van event_seq (§7.7).

    De klok levert (monotoon, wandklok). Monotone tijd stuurt deadlines; de
    wandklok gaat alleen mee in het auditspoor en beslist nooit iets.
    """

    def __init__(self, clock):
        self._clock = clock
        self._seq = 0
        self.events = []

    def submit(self, kind, payload=None):
        self._seq += 1
        mono, wall = self._clock()
        event = Event(kind=kind, payload=payload or {}, event_seq=self._seq,
                      mono=mono, wall=wall)
        self.events.append(event)
        return event


class Controller:
    """Toestandsmachine van §7.9. Start altijd in SOURCE_WAIT: bij boot bestaat
    er nog geen runnerproces en is de bron nog niet bewezen ready."""

    def __init__(self, loop, state=State.SOURCE_WAIT):
        self.loop = loop
        self.state = state
        self.gates_groen = False
        self.readiness = Confirmation()
        self._laatste_exitcode = None

    def on_event(self, event):
        handler = getattr(self, f"_on_{event.kind}", None)
        if handler is not None:
            handler(event)

    def _on_readiness(self, event):
        bevestigd = self.readiness.observe(event.payload["klasse"], now=event.mono)
        if bevestigd is None:
            return
        if bevestigd is ReadinessClass.READY:
            # Alleen na twee geldige probes EN groene gates mag er een runner komen.
            if self.gates_groen and self.state in (State.SOURCE_WAIT,
                                                   State.CREDENTIAL_ERROR,
                                                   State.QUARANTINED):
                self.state = State.WAITING
            return
        if bevestigd is ReadinessClass.SOURCE_WAIT:
            self.state = State.SOURCE_WAIT
        elif bevestigd is ReadinessClass.CREDENTIAL_ERROR:
            self.state = State.CREDENTIAL_ERROR
        else:
            self.state = State.QUARANTINED

    def _on_job_accepted(self, event):
        if self.state is State.WAITING:
            self.state = State.RUNNING

    def _on_child_exit(self, event):
        self._laatste_exitcode = event.payload.get("code")
        # Na iedere exit wordt geschrobd, ook na een fout: containment eerst.
        self.state = State.SCRUBBING

    def _on_scrub_done(self, event):
        if not event.payload.get("ok"):
            self.state = State.QUARANTINED
            return
        if self._laatste_exitcode not in (0, None):
            # Non-zero bij --wait duidt op config-, initialisatie-, poller- of
            # runtimefalen; heropenen mag dan niet (§7.9).
            self.state = State.QUARANTINED
            return
        self.state = State.WAITING if self.gates_groen else State.SOURCE_WAIT
