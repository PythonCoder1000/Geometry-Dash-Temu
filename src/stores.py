"""Storage interfaces: `AuthStore` + `LevelStore`.

Two abstract interfaces with two implementations each:

- `LocalAuthStore` / `LocalLevelStore` — everything lives on the user's
  disk (`prefs.json`, `LEVELS_DIR`). Used when offline, in tests, or
  when no `TRIGSPRINT_SERVER_URL` is configured.
- `RemoteAuthStore` / `RemoteLevelStore` — HTTP against the FastAPI
  server in `server/app.py`. Uses `requests` if available, falls back
  to `urllib.request` otherwise so the game doesn't add a hard dep.

The factory `get_stores()` picks the pair based on the environment.
All menu code should go through these interfaces so offline / test
environments work identically to the real thing.
"""

import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import prefs
from constants import LEVELS_DIR


# --------------------------------------------------------------------------
# Data classes (dicts for simplicity — easy to serialise / round-trip).
# --------------------------------------------------------------------------

LEVEL_STATES = ("drafted", "published", "verified")


def _state_of(meta: Dict[str, Any]) -> str:
    """Derive a level's canonical state from its meta dict. Verified
    wins over published; drafts are the default."""
    if meta.get("verified"):
        return "verified"
    if meta.get("published"):
        return "published"
    return "drafted"


# --------------------------------------------------------------------------
# AuthStore — login, signup, current user
# --------------------------------------------------------------------------

class AuthStore:
    """Abstract. Subclasses throw their own errors on auth failure."""

    def current_username(self) -> Optional[str]: ...
    def login(self, username: str, password: str) -> bool: ...
    def signup(self, username: str, password: str) -> bool: ...
    def logout(self) -> None: ...


class LocalAuthStore(AuthStore):
    """Filesystem-backed auth. Passwords are hashed with a simple PBKDF2
    (stdlib, no extra deps). Not intended for cross-machine use — this
    is the offline fallback and the implementation used by tests.

    SECURITY NOTE: this is a *convenience* login, NOT a security boundary.
    The salt + PBKDF2 hash sit in plaintext JSON next to the user's level
    data; anyone with filesystem access already owns the game state
    (levels, prefs, Best%). The hash only makes casual shoulder-surfing
    of the password harder; it doesn't protect level ownership from a
    motivated attacker on the same machine. Use RemoteAuthStore +
    server/app.py if real account separation matters."""

    def __init__(self):
        self._users_path = os.path.join(
            os.path.dirname(os.path.abspath(LEVELS_DIR)), "auth_local.json")

    # ---- users.json helpers ------------------------------------------------
    def _load(self) -> Dict[str, Any]:
        try:
            with open(self._users_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save(self, data: Dict[str, Any]) -> None:
        try:
            os.makedirs(os.path.dirname(self._users_path), exist_ok=True)
        except OSError:
            pass
        try:
            with open(self._users_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError:
            pass

    @staticmethod
    def _hash(password: str, salt: bytes) -> str:
        import hashlib
        h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
        return h.hex()

    # ---- public API --------------------------------------------------------
    def current_username(self) -> Optional[str]:
        return prefs.get("signed_in_username", None)

    def login(self, username: str, password: str) -> bool:
        data = self._load()
        row = data.get(username)
        if not row:
            return False
        salt = bytes.fromhex(row["salt"])
        if self._hash(password, salt) != row["hash"]:
            return False
        prefs.set("signed_in_username", username)
        return True

    def signup(self, username: str, password: str) -> bool:
        username = username.strip()
        if not username or len(password) < 8:
            return False
        data = self._load()
        if username in data:
            return False
        salt = os.urandom(16)
        data[username] = {
            "salt": salt.hex(),
            "hash": self._hash(password, salt),
            "created": int(time.time()),
        }
        self._save(data)
        prefs.set("signed_in_username", username)
        return True

    def logout(self) -> None:
        prefs.set("signed_in_username", None)


# --------------------------------------------------------------------------
# LevelStore — list / load / save / set state
# --------------------------------------------------------------------------

class LevelStore:
    """Abstract."""

    def list_mine(self, username: Optional[str]) -> List[Tuple[str, Dict]]: ...
    def list_public(self) -> List[Tuple[str, Dict]]: ...
    def load(self, level_id: str) -> Optional[Tuple[Dict, List[Dict]]]: ...
    def save(self, level_id: Optional[str], meta: Dict,
             objects: List[Dict], *, author: Optional[str] = None,
             ) -> str: ...
    def set_state(self, level_id: str, state: str,
                  *, username: Optional[str] = None) -> bool: ...
    def delete(self, level_id: str,
               *, username: Optional[str] = None) -> bool: ...


class LocalLevelStore(LevelStore):
    """Wraps the existing `levels.py` module. `level_id` is the file's
    basename without .json extension. Author-ownership is enforced by
    comparing the meta's `author` field to the provided username."""

    def _path_for(self, level_id: str) -> str:
        fn = level_id if level_id.endswith(".json") else level_id + ".json"
        return os.path.join(LEVELS_DIR, fn)

    def _filename(self, level_id: str) -> str:
        return level_id if level_id.endswith(".json") else level_id + ".json"

    def list_mine(self, username: Optional[str]) -> List[Tuple[str, Dict]]:
        from levels import list_level_summaries
        out = []
        for fn, meta in list_level_summaries():
            if username is None or (meta.get("author") or "") == username:
                out.append((fn, meta))
        return out

    def list_public(self) -> List[Tuple[str, Dict]]:
        from levels import list_level_summaries
        return [(fn, m) for fn, m in list_level_summaries()
                if m.get("published") or m.get("verified")]

    def load(self, level_id: str) -> Optional[Tuple[Dict, List[Dict]]]:
        from levels import load_level_full
        path = self._path_for(level_id)
        if not os.path.isfile(path):
            return None
        try:
            return load_level_full(path)
        except (OSError, ValueError):
            return None

    def save(self, level_id, meta, objects, *, author=None):
        from levels import save_level, _safe_filename  # noqa
        if author is not None:
            meta = dict(meta)
            meta["author"] = author
        name = meta.get("name", "Untitled")
        fn = level_id if level_id else None
        save_level(objects, name, fn, meta=meta)
        return fn or _safe_filename(name)

    def set_state(self, level_id, state, *, username=None):
        from levels import load_level_full, save_level
        if state not in LEVEL_STATES:
            return False
        path = self._path_for(level_id)
        if not os.path.isfile(path):
            return False
        try:
            meta, objects = load_level_full(path)
        except (OSError, ValueError):
            return False
        # Author-only for drafted↔published; verified is moderator-only
        # and rejected here (admin CLI handles that in the real server).
        if username is not None and (meta.get("author") or "") != username:
            if state != "verified":
                return False
        meta["published"] = state in ("published", "verified")
        meta["verified"] = (state == "verified")
        save_level(objects, meta.get("name", "Untitled"),
                   self._filename(level_id), meta=meta)
        return True

    def delete(self, level_id, *, username=None):
        path = self._path_for(level_id)
        if not os.path.isfile(path):
            return False
        try:
            from levels import load_level_full
            meta, _ = load_level_full(path)
            if username is not None and (meta.get("author") or "") != username:
                return False
        except Exception:
            pass
        try:
            os.remove(path)
            return True
        except OSError:
            return False


# --------------------------------------------------------------------------
# Remote stores — lightweight HTTP client against `server/app.py`.
# --------------------------------------------------------------------------

class _HTTP:
    """Minimal HTTP helper. Uses ``requests`` if installed (better
    error messages) and falls back to ``urllib`` so we don't have to
    add a hard dep."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._token: Optional[str] = prefs.get("auth_token", None)

    def set_token(self, tok: Optional[str]):
        self._token = tok
        prefs.set("auth_token", tok)

    def _request(self, method: str, path: str,
                 body: Optional[Dict] = None) -> Tuple[int, Dict]:
        url = self.base_url + path
        data_bytes = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            import requests  # type: ignore
            resp = requests.request(method, url, data=data_bytes,
                                    headers=headers, timeout=6.0)
            try:
                return resp.status_code, resp.json()
            except ValueError:
                return resp.status_code, {}
        except ImportError:
            import urllib.request
            import urllib.error
            req = urllib.request.Request(url, data=data_bytes,
                                         method=method, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=6.0) as r:
                    raw = r.read()
                    try:
                        return r.status, json.loads(raw) if raw else {}
                    except ValueError:
                        return r.status, {}
            except urllib.error.HTTPError as e:
                try:
                    return e.code, json.loads(e.read() or b"{}")
                except (ValueError, OSError):
                    return e.code, {}
            except urllib.error.URLError:
                return 0, {"error": "unreachable"}


class RemoteAuthStore(AuthStore):
    def __init__(self, http: _HTTP):
        self._http = http

    def current_username(self) -> Optional[str]:
        return prefs.get("signed_in_username", None)

    def login(self, username, password):
        sc, body = self._http._request(
            "POST", "/auth/login", {"username": username, "password": password})
        if sc == 200 and body.get("token"):
            self._http.set_token(body["token"])
            prefs.set("signed_in_username", username)
            return True
        return False

    def signup(self, username, password):
        sc, body = self._http._request(
            "POST", "/auth/signup", {"username": username, "password": password})
        if sc == 200 and body.get("token"):
            self._http.set_token(body["token"])
            prefs.set("signed_in_username", username)
            return True
        return False

    def logout(self):
        self._http.set_token(None)
        prefs.set("signed_in_username", None)


class RemoteLevelStore(LevelStore):
    """HTTP-backed level store. All payloads are JSON bodies identical
    to what the local store round-trips, so offline→online migration is
    trivial."""

    def __init__(self, http: _HTTP):
        self._http = http

    def list_mine(self, username):
        sc, body = self._http._request("GET", "/levels/mine")
        if sc != 200 or not isinstance(body, list):
            return []
        return [(str(e.get("id")), e.get("meta", {})) for e in body]

    def list_public(self):
        sc, body = self._http._request("GET",
                                       "/levels?state=published_or_verified")
        if sc != 200 or not isinstance(body, list):
            return []
        return [(str(e.get("id")), e.get("meta", {})) for e in body]

    def load(self, level_id):
        sc, body = self._http._request("GET", f"/levels/{level_id}")
        if sc != 200:
            return None
        return body.get("meta", {}), body.get("objects", [])

    def save(self, level_id, meta, objects, *, author=None):
        body = {"meta": meta, "objects": objects}
        if level_id:
            sc, resp = self._http._request("PUT", f"/levels/{level_id}", body)
            return level_id if sc == 204 else ""
        sc, resp = self._http._request("POST", "/levels", body)
        return str(resp.get("id")) if sc == 200 else ""

    def set_state(self, level_id, state, *, username=None):
        sc, _ = self._http._request("POST",
                                    f"/levels/{level_id}/state",
                                    {"state": state})
        return sc in (200, 204)

    def delete(self, level_id, *, username=None):
        sc, _ = self._http._request("DELETE", f"/levels/{level_id}")
        return sc in (200, 204)


# --------------------------------------------------------------------------
# Factory
# --------------------------------------------------------------------------

def get_stores() -> Tuple[AuthStore, LevelStore]:
    """Return (auth, levels). Picks remote if a server URL is configured
    AND the server is reachable — otherwise local mocks.

    URL resolution order:
      1. ``TRIGSPRINT_SERVER_URL`` environment variable (dev override).
      2. ``server_config.DEFAULT_SERVER_URL`` (baked into the build).
      3. Empty → LocalAuthStore / LocalLevelStore (offline mode).

    A single unreachability at boot falls back to local so the game
    never hangs waiting on a dead server.
    """
    url = os.environ.get("TRIGSPRINT_SERVER_URL", "").strip()
    if not url:
        try:
            from server_config import DEFAULT_SERVER_URL
            url = (DEFAULT_SERVER_URL or "").strip()
        except ImportError:
            url = ""
    if not url:
        return LocalAuthStore(), LocalLevelStore()
    http = _HTTP(url)
    # Cheap reachability probe — /health is a trivial endpoint.
    sc, _ = http._request("GET", "/health")
    if sc != 200:
        return LocalAuthStore(), LocalLevelStore()
    return RemoteAuthStore(http), RemoteLevelStore(http)
