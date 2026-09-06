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
            try:
                return {"kind": "general", "error": None, "status": e.code, "schema_ok": False}
            finally:
                getattr(e, "close", lambda: None)()
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return {"kind": "general", "error": str(e), "status": None, "schema_ok": False}

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
        fh = open(self._script, "rb")
        try:
            return self._popen(argv, stdin=fh)
        finally:
            fh.close()
    def poll(self, p): return p.poll()
