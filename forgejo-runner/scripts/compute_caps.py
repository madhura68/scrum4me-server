# forgejo-runner/scripts/compute_caps.py
"""Berekent de resourcecaps volgens 7.8 van het migratieontwerp.

Limiet per service = max(ondergrens, 150% van de gemeten piek), waarbij de piek
naar boven wordt afgerond op 0,5 vCPU, 256 MiB en 128 PID. De headroomgate
geldt na delta-review R12 op beide hosts.
"""

import math
from dataclasses import dataclass

GIB = 1024 ** 3
MIB = 1024 ** 2

ONDERGRENS = {
    "runner": {"cpu": 1.0, "mem": 1 * GIB, "pids": 256},
    "dind": {"cpu": 2.0, "mem": 4 * GIB, "pids": 2048},
}
MARGE = 1.5
STAP_CPU = 0.5
STAP_MEM = 256 * MIB
STAP_PIDS = 128


@dataclass
class Caps:
    runner_cpu: float
    runner_mem_bytes: int
    runner_pids: int
    dind_cpu: float
    dind_mem_bytes: int
    dind_pids: int


def _omhoog(waarde, stap):
    return math.ceil(waarde / stap) * stap


def _voor_service(samples, prefix, ondergrens):
    piek_cpu = max((float(s[f"{prefix}_cpu_pct"]) for s in samples), default=0.0) / 100.0
    piek_mem = max((int(s[f"{prefix}_mem_bytes"]) for s in samples), default=0)
    piek_pids = max((int(s[f"{prefix}_pids"]) for s in samples), default=0)
    return (
        max(ondergrens["cpu"], _omhoog(piek_cpu * MARGE, STAP_CPU)),
        int(max(ondergrens["mem"], _omhoog(piek_mem * MARGE, STAP_MEM))),
        int(max(ondergrens["pids"], _omhoog(piek_pids * MARGE, STAP_PIDS))),
    )


def compute(samples):
    r_cpu, r_mem, r_pids = _voor_service(samples, "runner", ONDERGRENS["runner"])
    d_cpu, d_mem, d_pids = _voor_service(samples, "dind", ONDERGRENS["dind"])
    return Caps(runner_cpu=r_cpu, runner_mem_bytes=r_mem, runner_pids=r_pids,
                dind_cpu=d_cpu, dind_mem_bytes=d_mem, dind_pids=d_pids)


def headroom_ok(caps, vcpu, lowest_mem_available):
    redenen = []
    cpu_som = caps.runner_cpu + caps.dind_cpu
    mem_som = caps.runner_mem_bytes + caps.dind_mem_bytes
    if cpu_som > vcpu * 0.5:
        redenen.append(
            f"vCPU: som van de limieten {cpu_som} overschrijdt 50% van {vcpu} vCPU")
    if mem_som > lowest_mem_available * 0.5:
        redenen.append(
            f"geheugen: som van de limieten {mem_som} bytes overschrijdt 50% van de "
            f"laagste MemAvailable {lowest_mem_available} bytes")
    return (not redenen), redenen
