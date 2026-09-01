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


@dataclass
class Fence:
    """Schedulingfence (§7.7). Gezet op de eerste afwijkende probe; blokkeert
    iedere childstart tot hij bevestigd of veilig gewist is."""

    fence_seq: int
    gezet_op_mono: float
    eerste_klasse: object
    zwaarste_klasse: object = None

    def __post_init__(self):
        self.zwaarste_klasse = self.eerste_klasse

    def observe(self, klasse):
        if klasse is ReadinessClass.READY:
            return
        if SEVERITY[klasse] > SEVERITY[self.zwaarste_klasse]:
            self.zwaarste_klasse = klasse

    def verlopen(self, now):
        return (now - self.gezet_op_mono) >= FENCE_MAX_AGE_SECONDS


MAINTENANCE_MAX_DUUR_SECONDS = 1800.0


@dataclass(frozen=True)
class MaintenanceRecord:
    """Vooraf gearmd control-plane-onderhoudsvenster (§7.7).

    Geldigheid is bewust een wandklokinterval: het is een menselijk geplande
    afspraak die op beide hosts identiek wordt gearmd. Fencedeadlines blijven
    monotoon; die twee klokken worden nooit door elkaar gebruikt.
    """

    maintenance_id: str
    start_utc: float
    eind_utc: float

    @classmethod
    def parse(cls, data):
        for veld in ("maintenance_id", "start_utc", "eind_utc"):
            if veld not in data:
                raise ValueError(f"maintenance-record mist {veld}")
        if not str(data["maintenance_id"]).strip():
            raise ValueError("maintenance_id mag niet leeg zijn")
        duur = float(data["eind_utc"]) - float(data["start_utc"])
        if duur <= 0:
            raise ValueError("maintenance-record heeft geen positieve duur")
        if duur > MAINTENANCE_MAX_DUUR_SECONDS:
            raise ValueError(
                f"maintenance-record duurt {duur}s, maximaal {MAINTENANCE_MAX_DUUR_SECONDS}s")
        return cls(maintenance_id=str(data["maintenance_id"]),
                   start_utc=float(data["start_utc"]),
                   eind_utc=float(data["eind_utc"]))

    def geldig_op(self, wall):
        return self.start_utc <= wall < self.eind_utc


_KLASSE_NAAR_STATE = {
    ReadinessClass.SOURCE_WAIT: State.SOURCE_WAIT,
    ReadinessClass.CREDENTIAL_ERROR: State.CREDENTIAL_ERROR,
    ReadinessClass.PROTOCOL: State.QUARANTINED,
}

# Toestanden waarin een job nog onderweg is. §7.9 wil dat een vóór-latch job
# gecontroleerd eindigt; een fouttoestand die tijdens zo'n job wordt bevestigd
# wordt daarom vastgelegd als volgende_state en pas na de scrub van kracht.
_JOB_IN_UITVOERING = (State.RUNNING, State.SCRUBBING)


class Controller:
    """Toestandsmachine van §7.9. Start altijd in SOURCE_WAIT: bij boot bestaat
    er nog geen runnerproces en is de bron nog niet bewezen ready."""

    def __init__(self, loop, state=State.SOURCE_WAIT):
        self.loop = loop
        self.state = state
        self.gates_groen = False
        self.nulbewijs_ok = False
        self.readiness = Confirmation()
        self.fence = None
        self.volgende_state = None
        self.maintenance = None
        self.algemene_readiness_bevestigd = False
        self._laatste_exitcode = None

    @property
    def mag_child_starten(self):
        """Een fence blokkeert onvoorwaardelijk; een unit-restart omzeilt hem nooit."""
        return self.fence is None and self.gates_groen and self.state in (
            State.WAITING, State.SOURCE_WAIT)

    def latch_verdict(self, event):
        """Alleen een lokaal event met event_seq strikt kleiner dan fence_seq is
        vóór-latch. Alles daarbuiten is fail-closed op/na-latch (§7.7)."""
        if self.fence is None:
            return "op-of-na"
        return "voor" if event.event_seq < self.fence.fence_seq else "op-of-na"

    def on_event(self, event):
        handler = getattr(self, f"_on_{event.kind}", None)
        if handler is not None:
            handler(event)

    def _commit_of_onthoud(self, state):
        """Een lopende job niet abrupt afbreken (§7.9): tijdens RUNNING of
        SCRUBBING wordt de geselecteerde volgende toestand alleen vastgelegd."""
        if self.state in _JOB_IN_UITVOERING:
            self.volgende_state = state
        else:
            self.state = state

    def _on_readiness(self, event):
        klasse = event.payload["klasse"]

        if klasse is not ReadinessClass.READY:
            if self.fence is None:
                self.fence = Fence(fence_seq=event.event_seq,
                                   gezet_op_mono=event.mono,
                                   eerste_klasse=klasse)
                # Informatief, geen alarm: reviewronde 8 wilde de fence direct
                # maar de ruis niet.
                self.loop.submit("fence_set", {"fence_seq": self.fence.fence_seq,
                                               "klasse": klasse})
                if self.state is State.WAITING:
                    self.state = State.DRAINING
            else:
                self.fence.observe(klasse)
        elif self.fence is not None:
            self.fence.observe(klasse)

        bevestigd = self.readiness.observe(klasse, now=event.mono)
        if bevestigd is None:
            return

        if bevestigd is ReadinessClass.READY:
            if self.fence is not None:
                # Herstel na een afwijking. §7.7 eist hier naast twee geldige
                # probes ook het assignment-nulbewijs en groene gates.
                if self.nulbewijs_ok and self.gates_groen:
                    self.fence = None
                    self.volgende_state = None
                    self.state = State.WAITING
                return
            # Koude start: er is geen gestopte runner waarvoor een nulbewijs
            # bestaat. §7.7 spreekt daarom van het "eventueel uitgestelde"
            # nulbewijs; zonder deze tak komt een verse host nooit uit
            # SOURCE_WAIT.
            if self.gates_groen and self.state in (State.SOURCE_WAIT,
                                                   State.CREDENTIAL_ERROR,
                                                   State.QUARANTINED):
                self.state = State.WAITING
            return

        self.fence = None
        self.loop.submit("alarm", {"klasse": bevestigd, "reden": "bevestigde fouttoestand"})
        self._commit_of_onthoud(_KLASSE_NAAR_STATE[bevestigd])

    def _startupuitzondering_actief(self, wall):
        """Binnen een geldig gearmd venster en zolang de algemene readiness nog
        niet tweemaal geldig is, committeert de watchdog uitsluitend SOURCE_WAIT.

        Dit verzacht uitsluitend de DEADLINECOMMIT. De gewone vierwegclassificatie
        en de bevestigingsregel blijven binnen het venster onveranderd, zodat een
        bevestigde 401/403 ook daar correct wordt gemeld (§7.7).
        """
        return (self.maintenance is not None
                and self.maintenance.geldig_op(wall)
                and not self.algemene_readiness_bevestigd)

    def tick(self, now, wall=None):
        """Deadlinewatchdog: een onopgeloste fence ouder dan zestig seconden
        commit deterministisch naar de zwaarste sinds latch waargenomen klasse.

        `now` is monotoon en stuurt de deadline; `wall` toetst alleen de
        geldigheid van het maintenance-venster en valt terug op de wandklok van
        het laatste event.
        """
        if self.fence is None or not self.fence.verlopen(now):
            return
        if wall is None:
            wall = self.loop.events[-1].wall if self.loop.events else 0.0

        if self._startupuitzondering_actief(wall):
            klasse = ReadinessClass.SOURCE_WAIT
            verwacht = True
        else:
            klasse = self.fence.zwaarste_klasse
            verwacht = False

        self.loop.submit("alarm", {"klasse": klasse,
                                   "reden": "fence-deadline bereikt",
                                   "verwacht": verwacht,
                                   "maintenance_id": (self.maintenance.maintenance_id
                                                      if self.maintenance else None)})
        self.fence = None
        self.readiness.reset()
        self._commit_of_onthoud(_KLASSE_NAAR_STATE[klasse])

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
        if self.volgende_state is not None:
            # Tijdens de job is een fouttoestand bevestigd of door de
            # deadlinewatchdog gecommit; die geldt nu de job voorbij is.
            self.state, self.volgende_state = self.volgende_state, None
            return
        if self.fence is not None:
            # Onopgeloste fence: heropenen zou hem langs de scrubroute
            # omzeilen, terwijl hij onvoorwaardelijk hoort te blokkeren.
            self.state = State.DRAINING
            return
        self.state = State.WAITING if self.gates_groen else State.SOURCE_WAIT
