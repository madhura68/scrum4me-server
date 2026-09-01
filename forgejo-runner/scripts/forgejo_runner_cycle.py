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
