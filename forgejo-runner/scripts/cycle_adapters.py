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
            return {"kind": "general", "error": None, "status": e.code, "schema_ok": False}
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return {"kind": "general", "error": str(e), "status": None, "schema_ok": False}
