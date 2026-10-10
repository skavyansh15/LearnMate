"""Tiny JSON-file storage. Every user gets their own folder: data/users/<user_id>/ (files are never shared)."""
import json
import os
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import date

import config
from errors import UserError

_lock = threading.RLock()
UID_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
ID_RE = re.compile(r"^[a-f0-9]{8,32}$")
DEMO_ID = "demo-python-lists"
_hits = defaultdict(deque)


def new_uid():
    return secrets.token_urlsafe(18)


def new_id():
    return secrets.token_hex(6)


def _udir(uid, *sub):
    if not UID_RE.match(uid or ""):  # also blocks path tricks like '../'
        raise UserError("bad_user", "Invalid session.", "Reload the page.")
    p = config.USERS_DIR.joinpath(uid, *sub)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _check_id(value):
    if not ID_RE.match(value or ""):
        raise UserError("not_found", "Item not found.", status=404)
    return value


def _read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return default


def _write(path, obj):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)  # never leaves a half-written file


# ---------- courses ----------------------------------------------------------
def demo_course():
    return _read(config.DEMO_DIR / "course.json", None)


def list_courses(uid):
    demo = demo_course()
    mine = [_read(p, None) for p in sorted(_udir(uid, "courses").glob("*.json"))]
    return ([demo] if demo else []) + sorted([c for c in mine if c], key=lambda c: c["created"])


def get_course(uid, cid):
    if cid == DEMO_ID:
        c = demo_course()
        if c:
            return c
    else:
        c = _read(_udir(uid, "courses") / f"{_check_id(cid)}.json", None)
        if c:
            return c
    raise UserError("not_found", "Course not found.", "It may have been deleted.", 404)


def is_demo(cid):
    return cid == DEMO_ID


def course_dir(uid, cid):
    return _udir(uid, "media", _check_id(cid))


def save_course(uid, course):
    with _lock:
        _write(_udir(uid, "courses") / f"{_check_id(course['id'])}.json", course)


def delete_course(uid, cid):
    with _lock:
        (_udir(uid, "courses") / f"{_check_id(cid)}.json").unlink(missing_ok=True)
        # Clean up any local video media files
        mdir = _udir(uid, "media", _check_id(cid))
        if mdir.exists():
            for p in mdir.glob("*"):
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass
            try:
                mdir.rmdir()
            except Exception:
                pass


def count_courses(uid):
    return len(list(_udir(uid, "courses").glob("*.json")))


# ---------- saved quizzes / interviews --------------------------------------
def save_obj(uid, kind, obj):
    with _lock:
        _write(_udir(uid, kind) / f"{_check_id(obj['id'])}.json", obj)


def load_obj(uid, kind, oid):
    obj = _read(_udir(uid, kind) / f"{_check_id(oid)}.json", None)
    if not obj:
        raise UserError("not_found", f"{kind[:-1].title()} not found.", "Start a new one.", 404)
    return obj


# ---------- progress ---------------------------------------------------------
def get_progress(uid):
    return _read(_udir(uid) / "progress.json", {})


def update_progress(uid, cid, fn):
    with _lock:
        data = get_progress(uid)
        rec = data.setdefault(cid, {"max_position": 0, "questions": 0, "quizzes": [], "interviews": []})
        fn(rec)
        _write(_udir(uid) / "progress.json", data)
        return rec


# ---------- cost control -----------------------------------------------------
def allow_ai_call(uid):
    """Per-user daily budget of AI calls. After it is used up, demo-mode answers are shown instead."""
    with _lock:
        path = _udir(uid) / "usage.json"
        usage = _read(path, {})
        if usage.get("date") != str(date.today()):
            usage = {"date": str(date.today()), "calls": 0}
        if usage["calls"] >= config.DAILY_AI_CALLS:
            return False
        usage["calls"] += 1
        _write(path, usage)
        return True


def usage_today(uid):
    u = _read(_udir(uid) / "usage.json", {})
    return u.get("calls", 0) if u.get("date") == str(date.today()) else 0


def rate_ok(uid):
    now = time.time()
    q = _hits[uid]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= config.RATE_PER_MIN:
        return False
    q.append(now)
    return True
