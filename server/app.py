"""FastAPI server for Trigonometry Sprint.

Run with:
    uvicorn server.app:app --reload

Endpoints (match the client `stores.RemoteLevelStore` contract):

    POST   /auth/signup         {username, password} → {token, user}
    POST   /auth/login          {username, password} → {token, user}
    GET    /auth/me                                   → {user}

    GET    /levels?state=…&q=…                        → [{id, meta}]
    GET    /levels/mine                               → [{id, meta}]
    GET    /levels/{id}                               → {meta, objects}
    POST   /levels              {meta, objects}       → {id}
    PUT    /levels/{id}         {meta, objects}       → 204
    POST   /levels/{id}/state   {state}               → 204
    DELETE /levels/{id}                               → 204

    GET    /health                                    → {ok: True}

Auth: bearer token in `Authorization` header. Token is a short random
hex string indexed to a user id in the `sessions` table — no external
JWT dep. Password hashing via stdlib `pbkdf2_hmac`. SQLite lives at
``server/data/trigsprint.db`` by default; override with the
``TRIGSPRINT_DB_PATH`` env var.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import time
from typing import Any, Dict, List, Optional

try:
    from fastapi import FastAPI, HTTPException, Depends, Header
    from pydantic import BaseModel
except ImportError as e:
    raise SystemExit(
        "server/app.py needs FastAPI installed. "
        "Run `pip install -r requirements-server.txt` first."
    ) from e


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------

DB_PATH = os.environ.get(
    "TRIGSPRINT_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                 "trigsprint.db"),
)


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init_db() -> None:
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            username     TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            is_admin     INTEGER NOT NULL DEFAULT 0,
            created_at   INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token        TEXT PRIMARY KEY,
            user_id      INTEGER NOT NULL REFERENCES users(id),
            created_at   INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS levels (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            author_id    INTEGER NOT NULL REFERENCES users(id),
            meta_json    TEXT NOT NULL,
            objects_json TEXT NOT NULL,
            state        TEXT NOT NULL DEFAULT 'drafted',
            created_at   INTEGER NOT NULL,
            updated_at   INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_levels_state
            ON levels(state);
        CREATE INDEX IF NOT EXISTS idx_levels_author
            ON levels(author_id);
        CREATE TABLE IF NOT EXISTS progress (
            user_id      INTEGER NOT NULL,
            level_id     INTEGER NOT NULL,
            best_normal  INTEGER NOT NULL DEFAULT 0,
            best_practice INTEGER NOT NULL DEFAULT 0,
            coins_collected INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, level_id)
        );
        """)


# --------------------------------------------------------------------------
# Auth helpers
# --------------------------------------------------------------------------

def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt,
                                120_000).hex()


def _make_token() -> str:
    return secrets.token_hex(24)


def _user_from_token(token: Optional[str]) -> Optional[sqlite3.Row]:
    if not token:
        return None
    with _conn() as c:
        row = c.execute(
            "SELECT u.* FROM users u JOIN sessions s "
            "ON s.user_id = u.id WHERE s.token = ?",
            (token,)).fetchone()
    return row


def _parse_bearer(auth: Optional[str]) -> Optional[str]:
    if not auth or not auth.lower().startswith("bearer "):
        return None
    return auth.split(" ", 1)[1].strip()


def require_user(authorization: Optional[str] = Header(default=None)):
    user = _user_from_token(_parse_bearer(authorization))
    if user is None:
        raise HTTPException(status_code=401, detail="login_required")
    return user


def optional_user(authorization: Optional[str] = Header(default=None)):
    return _user_from_token(_parse_bearer(authorization))


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------

class AuthIn(BaseModel):
    username: str
    password: str


class LevelIn(BaseModel):
    meta: Dict[str, Any]
    objects: List[Dict[str, Any]]


class StateIn(BaseModel):
    state: str


# --------------------------------------------------------------------------
# App
# --------------------------------------------------------------------------

app = FastAPI(title="Trigonometry Sprint")
_init_db()


@app.get("/health")
def health():
    return {"ok": True}


# ---- auth -----------------------------------------------------------------

@app.post("/auth/signup")
def signup(body: AuthIn):
    if len(body.password) < 8:
        raise HTTPException(400, "password_too_short")
    if not body.username or len(body.username) > 32:
        raise HTTPException(400, "bad_username")
    with _conn() as c:
        row = c.execute("SELECT 1 FROM users WHERE username = ?",
                        (body.username,)).fetchone()
        if row:
            raise HTTPException(409, "username_taken")
        salt = secrets.token_bytes(16)
        pw_hash = _hash_password(body.password, salt)
        c.execute(
            "INSERT INTO users(username, password_hash, password_salt, "
            "created_at) VALUES (?, ?, ?, ?)",
            (body.username, pw_hash, salt.hex(), int(time.time())))
        user_id = c.execute(
            "SELECT id FROM users WHERE username = ?",
            (body.username,)).fetchone()["id"]
        token = _make_token()
        c.execute("INSERT INTO sessions(token, user_id, created_at) "
                  "VALUES (?, ?, ?)",
                  (token, user_id, int(time.time())))
    return {"token": token, "user": {"id": user_id,
                                      "username": body.username}}


@app.post("/auth/login")
def login(body: AuthIn):
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE username = ?",
                        (body.username,)).fetchone()
        if not row:
            raise HTTPException(401, "invalid_credentials")
        salt = bytes.fromhex(row["password_salt"])
        if _hash_password(body.password, salt) != row["password_hash"]:
            raise HTTPException(401, "invalid_credentials")
        token = _make_token()
        c.execute("INSERT INTO sessions(token, user_id, created_at) "
                  "VALUES (?, ?, ?)",
                  (token, row["id"], int(time.time())))
    return {"token": token, "user": {"id": row["id"],
                                      "username": row["username"]}}


@app.get("/auth/me")
def me(user=Depends(require_user)):
    return {"user": {"id": user["id"], "username": user["username"]}}


# ---- levels ---------------------------------------------------------------

def _row_to_summary(r) -> Dict[str, Any]:
    return {"id": r["id"], "meta": json.loads(r["meta_json"])}


@app.get("/levels")
def list_levels(state: Optional[str] = None, q: Optional[str] = None,
                user=Depends(optional_user)):
    with _conn() as c:
        sql = "SELECT * FROM levels"
        params: List[Any] = []
        clauses = []
        if state == "published_or_verified":
            clauses.append("state IN ('published', 'verified')")
        elif state in ("drafted", "published", "verified"):
            clauses.append("state = ?")
            params.append(state)
        else:
            clauses.append("state IN ('published', 'verified')")
        if q:
            clauses.append("meta_json LIKE ?")
            params.append(f"%{q}%")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY updated_at DESC LIMIT 200"
        rows = c.execute(sql, params).fetchall()
    return [_row_to_summary(r) for r in rows]


@app.get("/levels/mine")
def list_mine(user=Depends(require_user)):
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM levels WHERE author_id = ? "
            "ORDER BY updated_at DESC",
            (user["id"],)).fetchall()
    return [_row_to_summary(r) for r in rows]


@app.get("/levels/{lid}")
def get_level(lid: int, user=Depends(optional_user)):
    with _conn() as c:
        r = c.execute("SELECT * FROM levels WHERE id = ?",
                      (lid,)).fetchone()
    if not r:
        raise HTTPException(404, "not_found")
    if r["state"] == "drafted" and (not user or user["id"] != r["author_id"]):
        raise HTTPException(403, "private_draft")
    return {"id": r["id"],
            "meta": json.loads(r["meta_json"]),
            "objects": json.loads(r["objects_json"])}


@app.post("/levels")
def create_level(body: LevelIn, user=Depends(require_user)):
    now = int(time.time())
    meta = dict(body.meta)
    meta["author"] = user["username"]
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO levels(author_id, meta_json, objects_json, "
            "state, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user["id"], json.dumps(meta), json.dumps(body.objects),
             "drafted", now, now))
        return {"id": cur.lastrowid}


@app.put("/levels/{lid}", status_code=204)
def update_level(lid: int, body: LevelIn, user=Depends(require_user)):
    with _conn() as c:
        row = c.execute("SELECT * FROM levels WHERE id = ?",
                        (lid,)).fetchone()
        if not row:
            raise HTTPException(404, "not_found")
        if row["author_id"] != user["id"]:
            raise HTTPException(403, "not_author")
        meta = dict(body.meta)
        meta["author"] = user["username"]
        c.execute(
            "UPDATE levels SET meta_json = ?, objects_json = ?, "
            "updated_at = ? WHERE id = ?",
            (json.dumps(meta), json.dumps(body.objects),
             int(time.time()), lid))
    return


@app.post("/levels/{lid}/state", status_code=204)
def set_state(lid: int, body: StateIn, user=Depends(require_user)):
    if body.state not in ("drafted", "published", "verified"):
        raise HTTPException(400, "bad_state")
    with _conn() as c:
        row = c.execute("SELECT * FROM levels WHERE id = ?",
                        (lid,)).fetchone()
        if not row:
            raise HTTPException(404, "not_found")
        if body.state == "verified":
            if not user["is_admin"]:
                raise HTTPException(403, "admin_only")
        else:
            if row["author_id"] != user["id"]:
                raise HTTPException(403, "not_author")
        c.execute("UPDATE levels SET state = ?, updated_at = ? WHERE id = ?",
                  (body.state, int(time.time()), lid))
    return


@app.delete("/levels/{lid}", status_code=204)
def delete_level(lid: int, user=Depends(require_user)):
    with _conn() as c:
        row = c.execute("SELECT * FROM levels WHERE id = ?",
                        (lid,)).fetchone()
        if not row:
            raise HTTPException(404, "not_found")
        if row["author_id"] != user["id"] and not user["is_admin"]:
            raise HTTPException(403, "not_author")
        c.execute("DELETE FROM levels WHERE id = ?", (lid,))
    return
