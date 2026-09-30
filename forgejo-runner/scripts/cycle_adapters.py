"""Neveneffect-adapters voor de cyclecontroller-runtime (dunne bring-up)."""

import hashlib
import http.client
import json
import os
import signal
import subprocess
import time
import urllib.request
import urllib.error


class Clock:
    def __call__(self):
        return time.monotonic(), time.time()


class TransportProbe:
    def __init__(self, base_url, timeout, opener=urllib.request.urlopen):
        self._url = base_url.rstrip("/") + "/api/v1/version"
        self._t = timeout
        self._open = opener

    def probe(self):
        req = urllib.request.Request(self._url, headers={"Accept": "application/json"})
        try:
            resp = self._open(req, timeout=self._t)
            try:
                body = resp.read()
            finally:
                getattr(resp, "close", lambda: None)()
            try:
                obj = json.loads(body)
                schema_ok = isinstance(obj, dict) and "version" in obj
            except ValueError:
                schema_ok = False
            return {
                "kind": "general",
                "error": None,
                "status": getattr(resp, "status", 200) or 200,
                "schema_ok": schema_ok,
            }
        except urllib.error.HTTPError as e:
            try:
                return {
                    "kind": "general",
                    "error": None,
                    "status": e.code,
                    "schema_ok": False,
                }
            finally:
                getattr(e, "close", lambda: None)()
        # HTTPException (IncompleteRead, BadStatusLine, …) is geen OSError maar komt wél
        # uit resp.read(): een afgebroken body is een transportfout, geen crash.
        except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
            return {
                "kind": "general",
                "error": f"{type(e).__name__}: {e}",
                "status": None,
                "schema_ok": False,
            }


def _run(argv, timeout):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


class _Compose:
    def __init__(
        self, compose_file, project, popen=subprocess.Popen, run=_run, timeout=30.0
    ):
        self._b = ["docker", "compose", "-f", compose_file, "-p", project]
        self._popen = popen
        self._run = run
        self._t = timeout


class DindHealth(_Compose):
    last_rc = None  # returncode van de laatste healthy()-check, voor de gatelog

    def ensure_up(self):
        return self._run(self._b + ["up", "-d", "dind"], self._t).returncode

    def healthy(self):
        self.last_rc = None
        cp = self._run(
            self._b
            + ["exec", "-T", "dind", "docker", "-H", "tcp://127.0.0.1:2375", "info"],
            self._t,
        )
        self.last_rc = cp.returncode
        return cp.returncode == 0


class RunnerLifecycle(_Compose):
    def start(self):
        return self._popen(self._b + ["--profile", "cycle", "run", "--rm", "runner"])

    def request_stop(self, p):
        p.send_signal(signal.SIGTERM)

    def poll(self, p):
        return p.poll()


class PullOp(_Compose):
    def start(self, digest):
        return self._popen(
            self._b
            + [
                "exec",
                "-T",
                "dind",
                "docker",
                "-H",
                "tcp://127.0.0.1:2375",
                "pull",
                digest,
            ]
        )

    def poll(self, p):
        return p.poll()


class ScrubOp(_Compose):
    def __init__(self, cf, proj, script, allow_in_dind, **kw):
        super().__init__(cf, proj, **kw)
        self._script = script
        self._allow = allow_in_dind

    def start(self):
        argv = self._b + [
            "exec",
            "-T",
            "dind",
            "sh",
            "-s",
            "--",
            "--endpoint",
            "tcp://127.0.0.1:2375",
            "--allow",
            self._allow,
        ]
        fh = open(self._script, "rb")
        try:
            return self._popen(argv, stdin=fh)
        finally:
            fh.close()

    def poll(self, p):
        return p.poll()


class ReconcileError(Exception):
    pass


class Reconcile(_Compose):
    def __init__(self, cf, proj, marker_path, **kw):
        super().__init__(cf, proj, **kw)
        self._project = proj
        self._marker = marker_path

    def _checked(self, args):
        cp = self._run(self._b + args, self._t)
        if cp.returncode != 0:
            raise ReconcileError(
                f"{' '.join(args)}: rc={cp.returncode} {cp.stderr.strip()}"
            )
        return cp

    def leftover_runners(self):
        # RAW `docker ps` (niet `docker compose ps`): een one-off container
        # (`compose --profile cycle run --rm runner`) draagt het label
        # com.docker.compose.oneoff=True en wordt door `compose ps` genegeerd,
        # maar blijft zichtbaar via de label-filter hieronder — dat is precies
        # de achtergebleven runner die B1/_stop_complete moeten kunnen zien.
        argv = [
            "docker",
            "ps",
            "-a",
            "--filter",
            f"label=com.docker.compose.project={self._project}",
            "--filter",
            "label=com.docker.compose.service=runner",
            "-q",
        ]
        cp = self._run(argv, self._t)
        if cp.returncode != 0:
            raise ReconcileError(
                f"docker ps (leftover): rc={cp.returncode} {cp.stderr.strip()}"
            )
        return [ln.strip() for ln in (cp.stdout or "").splitlines() if ln.strip()]

    def marker_present(self):
        return os.path.exists(self._marker)

    def write_marker(self, op):
        os.makedirs(os.path.dirname(self._marker), exist_ok=True)
        tmp = self._marker + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"op": op}, fh)
        os.replace(tmp, self._marker)

    def clear_marker(self):
        try:
            os.remove(self._marker)
        except FileNotFoundError:
            pass

    def restart_dind(self):
        self._checked(["kill", "dind"])
        self._checked(["up", "-d", "dind"])


class TrustVerdictReader:
    def __init__(self, vp, lf, af):
        self._vp = vp
        self._lf = lf
        self._af = af
        self.last_error = None  # reden van de laatste niet-leesbare invoer (voor de gatelog)

    def read(self):
        self.last_error = None
        try:
            with open(self._vp, "rb") as fh:
                verdict = json.load(fh)
        except FileNotFoundError:
            verdict = None
        except (OSError, ValueError) as exc:
            # Fail-closed: onleesbaar (bv. PermissionError) telt als "geen verdict".
            self.last_error = f"verdict onleesbaar: {type(exc).__name__}"
            verdict = None
        return verdict, self._sha(self._lf), self._sha(self._af)

    def _sha(self, path):
        try:
            with open(path, "rb") as fh:
                return hashlib.sha256(fh.read()).hexdigest()
        except FileNotFoundError:
            return ""
        except OSError as exc:
            self.last_error = f"{os.path.basename(path)} onleesbaar: {type(exc).__name__}"
            return ""
