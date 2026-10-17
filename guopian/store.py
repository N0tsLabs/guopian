"""SQLite catalog. One database per photo library, in <library>/.guopian/."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any, Iterable

from . import config, paths

# Columns added after the first release. Kept as an explicit list so an older
# catalog can be upgraded in place rather than thrown away and re-analysed.
_ADDED_PHOTO_COLUMNS = (
    ("cast_r", "REAL"), ("cast_b", "REAL"),
)
_ADDED_FACE_COLUMNS = (
    ("face_median", "REAL"), ("catch_l", "REAL"), ("catch_r", "REAL"),
)

# The face row is wide and has grown twice. Building the statement from the
# column list means the placeholder count cannot drift out of step with the
# column count -- a mismatch there fails the whole photo's analysis *after* the
# old rows have already been deleted.
_FACE_COLS = (
    "photo_id", "idx", "x", "y", "w", "h", "yaw", "pitch", "roll",
    "blink_l", "blink_r", "gaze_x", "gaze_y", "gaze_away",
    "smile", "jaw_open", "brow_down", "squint",
    "face_sharp", "face_sharp_ratio", "face_pct_high", "face_pct_low",
    "face_px", "eye_px", "face_median", "catch_l", "catch_r", "landmarks",
)
_FACE_INSERT = "INSERT INTO faces({}) VALUES({})".format(
    ",".join(_FACE_COLS), ",".join("?" * len(_FACE_COLS)))


def _face_values(photo_id: int, idx: int, f: dict):
    """Values in exactly the order of _FACE_COLS."""
    return (
        photo_id, idx,
        f.get("x"), f.get("y"), f.get("w"), f.get("h"),
        f.get("yaw"), f.get("pitch"), f.get("roll"),
        f.get("blink_l"), f.get("blink_r"),
        f.get("gaze_x"), f.get("gaze_y"), f.get("gaze_away"),
        f.get("smile"), f.get("jaw_open"), f.get("brow_down"), f.get("squint"),
        f.get("face_sharp"), f.get("face_sharp_ratio"),
        f.get("face_pct_high"), f.get("face_pct_low"),
        (f.get("gates") or {}).get("face_px"), (f.get("gates") or {}).get("eye_px"),
        f.get("face_median"), f.get("catch_l"), f.get("catch_r"),
        json.dumps(f.get("landmarks")) if f.get("landmarks") else None,
    )

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS photos (
    id            INTEGER PRIMARY KEY,
    path          TEXT UNIQUE NOT NULL,
    rel_path      TEXT,
    name          TEXT,
    size          INTEGER,
    mtime         REAL,
    ext           TEXT,

    width         INTEGER,
    height        INTEGER,
    taken_at      TEXT,
    taken_ts      REAL,
    camera        TEXT,
    lens          TEXT,
    iso           INTEGER,
    shutter       TEXT,
    aperture      REAL,
    focal         REAL,
    orientation   INTEGER,

    phash         BLOB,
    group_id      INTEGER,

    -- global metrics
    mean_luma     REAL,
    pct_high      REAL,
    pct_low       REAL,
    dynamic_range REAL,
    rms_contrast  REAL,
    lap_var       REAL,
    lap_var_mp    REAL,
    tenengrad     REAL,
    hf_ratio      REAL,
    noise         REAL,
    tilt_deg      REAL,
    tilt_support  REAL,
    blockiness    REAL,


    -- grey-world colour cast, ratios against green; judged in pass 2
    cast_r        REAL,
    cast_b        REAL,

    face_count    INTEGER DEFAULT 0,

    -- pass 2 (relative, whole-library)
    group_size    INTEGER DEFAULT 0,
    group_rank    INTEGER DEFAULT 0,
    group_score   REAL,
    suggest       TEXT,
    suggest_reason TEXT,
    suggest_conf  REAL,

    -- decision
    decision      TEXT,
    decided_at    REAL,
    note          TEXT,

    analysis_version INTEGER DEFAULT 0,
    analyzed_at   REAL,
    error         TEXT
);

CREATE INDEX IF NOT EXISTS idx_photos_group   ON photos(group_id);
CREATE INDEX IF NOT EXISTS idx_photos_decision ON photos(decision);
CREATE INDEX IF NOT EXISTS idx_photos_taken   ON photos(taken_ts);

CREATE TABLE IF NOT EXISTS faces (
    photo_id      INTEGER NOT NULL,
    idx           INTEGER NOT NULL,
    x REAL, y REAL, w REAL, h REAL,
    yaw REAL, pitch REAL, roll REAL,
    blink_l REAL, blink_r REAL,
    gaze_x REAL, gaze_y REAL, gaze_away REAL,
    smile REAL, jaw_open REAL, brow_down REAL, squint REAL,
    face_sharp REAL, face_sharp_ratio REAL, face_pct_high REAL, face_pct_low REAL,
    face_px REAL, eye_px REAL,
    face_median REAL,
    catch_l REAL, catch_r REAL,
    landmarks     TEXT,   -- JSON: the few landmark points we draw (eyes, nose, oval)
    PRIMARY KEY (photo_id, idx)
);

CREATE TABLE IF NOT EXISTS issues (
    photo_id      INTEGER NOT NULL,
    kind          TEXT NOT NULL,
    severity      TEXT NOT NULL,      -- fatal | high | medium | low | info
    confidence    REAL,
    face_idx      INTEGER,
    label_zh      TEXT,
    label_en      TEXT,
    detail        TEXT,
    evidence      TEXT                -- JSON bbox / numbers for the UI
);

CREATE INDEX IF NOT EXISTS idx_issues_photo ON issues(photo_id);
CREATE INDEX IF NOT EXISTS idx_issues_kind  ON issues(kind);

CREATE TABLE IF NOT EXISTS groups (
    id            INTEGER PRIMARY KEY,
    label         TEXT,
    size          INTEGER,
    best_photo_id INTEGER,
    score_json    TEXT
);

CREATE TABLE IF NOT EXISTS decisions_log (
    id            INTEGER PRIMARY KEY,
    photo_id      INTEGER NOT NULL,
    action        TEXT NOT NULL,
    prev_action   TEXT,
    at            REAL NOT NULL,
    batch         TEXT,
    undone        INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_log_photo ON decisions_log(photo_id);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS applies (
    batch   TEXT PRIMARY KEY,
    at      REAL NOT NULL,
    mode    TEXT NOT NULL,          -- quarantine | xmp | trash
    dest    TEXT,
    n       INTEGER,
    undone  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS apply_items (
    batch    TEXT NOT NULL,
    photo_id INTEGER NOT NULL,
    src      TEXT NOT NULL,
    dst      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_apply_items ON apply_items(batch);
"""


class Store:
    def __init__(self, work_dir: str):
        os.makedirs(work_dir, exist_ok=True)
        self.work_dir = work_dir
        self.db_path = os.path.join(work_dir, "catalog.db")
        self._local = threading.local()
        con = self.conn
        con.executescript(SCHEMA)
        self._migrate(con)
        con.commit()

    def _migrate(self, con: sqlite3.Connection) -> None:
        """Bring an older catalog up to the current schema.

        Two kinds of change happen here:

        `maybe` and `skip` were user-facing states before the model collapsed to
        three judgements. Both meant "I have not really decided", which is now
        simply the absence of a decision -- so they go back to NULL and the
        photo returns to the unreviewed pool. The decision *log* is left alone:
        it is history, and rewriting it would falsify what actually happened.

        New metric columns are added in place. `CREATE TABLE IF NOT EXISTS`
        never alters an existing table, so a catalog made by an older build
        would silently fail every INSERT that mentions a new column.
        """
        for table, cols in (("photos", _ADDED_PHOTO_COLUMNS),
                            ("faces", _ADDED_FACE_COLUMNS)):
            have = {r[1] for r in con.execute("PRAGMA table_info({})".format(table))}
            for name, decl in cols:
                if name not in have:
                    con.execute("ALTER TABLE {} ADD COLUMN {} {}".format(
                        table, name, decl))

        if not config.RETIRED_DECISIONS:
            return
        marks = ",".join("?" * len(config.RETIRED_DECISIONS))
        cur = con.execute(
            "UPDATE photos SET decision=NULL WHERE decision IN ({})".format(marks),
            config.RETIRED_DECISIONS)
        if cur.rowcount:
            paths.log("migrated {} decision(s) from the old model back to "
                      "unreviewed".format(cur.rowcount))

    # -- connection per thread (sqlite objects are not shareable) ----------
    @property
    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.db_path, timeout=30.0)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = c
        return c

    def close(self):
        c = getattr(self._local, "conn", None)
        if c is not None:
            c.close()
            self._local.conn = None

    # -- meta -------------------------------------------------------------
    def get_meta(self, key: str, default=None):
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except Exception:
            return default

    def set_meta(self, key: str, value):
        # NOTE: must commit. A connection left with an open write transaction
        # holds a RESERVED lock, and SQLite returns SQLITE_BUSY *immediately*
        # (it detects the same-process holder) -- every other thread then sees
        # "database is locked" with no retry.
        self.conn.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )
        self.conn.commit()

    def release(self):
        """Commit or roll back anything pending, then drop this thread's handle.

        Called from the server teardown so a failed request can never leave a
        transaction open for the next one.
        """
        c = getattr(self._local, "conn", None)
        if c is None:
            return
        try:
            c.commit()
        except Exception:
            try:
                c.rollback()
            except Exception:
                pass
        try:
            c.close()
        except Exception:
            pass
        self._local.conn = None

    # -- photos -----------------------------------------------------------
    def upsert_scanned(self, rows: Iterable[dict]) -> int:
        """Insert/refresh filesystem facts. Keeps existing analysis intact."""
        n = 0
        cur = self.conn.cursor()
        for r in rows:
            cur.execute(
                """INSERT INTO photos(path, rel_path, name, size, mtime, ext)
                   VALUES(:path,:rel_path,:name,:size,:mtime,:ext)
                   ON CONFLICT(path) DO UPDATE SET
                       size=excluded.size, mtime=excluded.mtime,
                       rel_path=excluded.rel_path, name=excluded.name,
                       ext=excluded.ext""",
                r,
            )
            n += 1
        self.conn.commit()
        return n

    def needs_analysis(self, version: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM photos WHERE analysis_version < ? OR analysis_version IS NULL "
            "ORDER BY taken_ts IS NULL, taken_ts, path",
            (version,),
        ).fetchall()

    def stale_paths(self) -> list[int]:
        """Photos whose file vanished or changed size/mtime."""
        out = []
        for row in self.conn.execute("SELECT id, path, size, mtime FROM photos").fetchall():
            try:
                st = os.stat(row["path"])
            except OSError:
                out.append(row["id"])
                continue
            if abs(st.st_size - (row["size"] or -1)) > 0 or abs(st.st_mtime - (row["mtime"] or -1)) > 1e-6:
                out.append(row["id"])
        return out

    def save_analysis(self, photo_id: int, meta: dict, metrics: dict,
                      faces: list[dict], issues: list[dict], phash_blob: bytes | None):
        con = self.conn
        con.execute("DELETE FROM faces WHERE photo_id=?", (photo_id,))
        con.execute("DELETE FROM issues WHERE photo_id=?", (photo_id,))
        con.execute(
            """UPDATE photos SET
                 width=:width, height=:height, taken_at=:taken_at, taken_ts=:taken_ts,
                 camera=:camera, lens=:lens, iso=:iso, shutter=:shutter,
                 aperture=:aperture, focal=:focal, orientation=:orientation,
                 phash=:phash,
                 mean_luma=:mean_luma, pct_high=:pct_high, pct_low=:pct_low,
                 dynamic_range=:dynamic_range, rms_contrast=:rms_contrast,
                 lap_var=:lap_var, lap_var_mp=:lap_var_mp, tenengrad=:tenengrad,
                 hf_ratio=:hf_ratio, noise=:noise, tilt_deg=:tilt_deg,
                 tilt_support=:tilt_support,
                 blockiness=:blockiness, face_count=:face_count,
                 cast_r=:cast_r, cast_b=:cast_b,
                 analysis_version=:analysis_version, analyzed_at=:analyzed_at,
                 error=NULL
               WHERE id=:id""",
            {**meta, **metrics, "phash": phash_blob, "id": photo_id,
             "analysis_version": config.ANALYSIS_VERSION, "analyzed_at": time.time()},
        )
        for i, f in enumerate(faces):
            con.execute(_FACE_INSERT, _face_values(photo_id, i, f))
        for it in issues:
            con.execute(
                """INSERT INTO issues(photo_id, kind, severity, confidence, face_idx,
                                      label_zh, label_en, detail, evidence)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (photo_id, it["kind"], it["severity"], it.get("confidence"),
                 it.get("face_idx"), it.get("label_zh"), it.get("label_en"),
                 it.get("detail"), json.dumps(it.get("evidence")) if it.get("evidence") else None),
            )
        con.commit()

    def mark_error(self, photo_id: int, msg: str):
        self.conn.execute(
            "UPDATE photos SET error=?, analysis_version=?, analyzed_at=? WHERE id=?",
            (msg[:500], config.ANALYSIS_VERSION, time.time(), photo_id),
        )
        self.conn.commit()

    # -- pass 2 -----------------------------------------------------------
    def save_pass2(self, groups: list[dict], verdicts: dict[int, dict],
                   issues: dict[int, list[dict]]):
        con = self.conn
        con.execute("DELETE FROM issues")
        con.execute("DELETE FROM groups")
        con.execute("UPDATE photos SET group_id=NULL, group_size=0, group_rank=0, group_score=NULL, "
                    "suggest=NULL, suggest_reason=NULL, suggest_conf=NULL")
        for g in groups:
            con.execute("INSERT INTO groups(id, label, size, best_photo_id, score_json) "
                        "VALUES(?,?,?,?,?)",
                        (g["gid"], "组 {}".format(g["gid"]), len(g["members"]),
                         g.get("best"), json.dumps(g.get("scores") or {})))
            for m in g["members"]:
                con.execute(
                    "UPDATE photos SET group_id=?, group_size=?, group_rank=?, group_score=? WHERE id=?",
                    (g["gid"], len(g["members"]), g["rank"].get(m, 1),
                     g["scores"].get(m), m),
                )
        for pid, v in verdicts.items():
            con.execute("UPDATE photos SET suggest=?, suggest_reason=?, suggest_conf=? WHERE id=?",
                        (v.get("suggest"), v.get("reason"), v.get("confidence"), pid))
        for pid, items in issues.items():
            for it in items:
                con.execute(
                    """INSERT INTO issues(photo_id, kind, severity, confidence, face_idx,
                                          label_zh, label_en, detail, evidence)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (pid, it["kind"], it["severity"], it.get("confidence"),
                     it.get("face_idx"), it.get("label_zh"), it.get("label_en"),
                     it.get("detail"),
                     json.dumps(it.get("evidence")) if it.get("evidence") else None),
                )
        con.commit()

    def load_rows(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM photos ORDER BY taken_ts IS NULL, taken_ts, path").fetchall()]

    def load_face_index(self) -> dict[int, list[dict]]:
        out: dict[int, list[dict]] = {}
        for r in self.conn.execute("SELECT * FROM faces").fetchall():
            d = dict(r)
            if d.get("landmarks"):
                try:
                    d["landmarks"] = json.loads(d["landmarks"])
                except Exception:
                    d["landmarks"] = None
            yaw = abs(d.get("yaw") or 0.0)
            face_px = d.get("face_px")
            eye_px = d.get("eye_px")
            too_small = face_px is not None and face_px < config.FACE_MIN_PIXELS
            eye_too_small = eye_px is not None and eye_px < config.EYE_MIN_PIXELS * 2
            d["gates"] = {
                "face_px": face_px, "eye_px": eye_px, "yaw": yaw,
                "too_small": bool(too_small), "eye_too_small": bool(eye_too_small),
                "turned": yaw > config.FACE_EDGE_MAX_YAW,
                "judge_eyes": not (too_small or eye_too_small or yaw > config.FACE_EDGE_MAX_YAW),
            }
            out.setdefault(d["photo_id"], []).append(d)
        return out

    # -- decisions --------------------------------------------------------
    def set_decision(self, photo_id: int, action: str, batch: str | None = None):
        con = self.conn
        # `clear` is not a fourth judgement, it is the absence of one.
        value = None if action == config.CLEAR else action
        row = con.execute("SELECT decision FROM photos WHERE id=?", (photo_id,)).fetchone()
        prev = row["decision"] if row else None
        if prev == value:
            return prev
        # decided_at only means something while a decision exists.
        con.execute("UPDATE photos SET decision=?, decided_at=? WHERE id=?",
                    (value, time.time() if value else None, photo_id))
        con.execute(
            "INSERT INTO decisions_log(photo_id, action, prev_action, at, batch, undone) "
            "VALUES(?,?,?,?,?,0)",
            (photo_id, action, prev, time.time(), batch),
        )
        con.commit()
        return prev

    def undo_batch(self, batch: str) -> dict:
        """Revert every decision a single batch made.

        The grid decides a whole group at once -- the survivors kept, the rest
        marked rejected -- so undo has to take the whole batch back, not just
        the last row. Undoing one of ten decisions would leave the library in a
        state the user never chose.
        """
        con = self.conn
        rows = con.execute(
            """SELECT * FROM decisions_log WHERE batch=? AND undone=0
               ORDER BY id DESC""", (batch,)).fetchall()
        if not rows:
            return {"restored": 0, "photos": []}
        ids = []
        for row in rows:
            con.execute("UPDATE photos SET decision=?, decided_at=? WHERE id=?",
                        (row["prev_action"], time.time(), row["photo_id"]))
            con.execute("UPDATE decisions_log SET undone=1 WHERE id=?", (row["id"],))
            ids.append(row["photo_id"])
        con.commit()
        return {"restored": len(rows), "photos": ids}

    def undo_last(self) -> dict | None:
        con = self.conn
        row = con.execute(
            "SELECT * FROM decisions_log WHERE undone=0 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        con.execute("UPDATE photos SET decision=?, decided_at=? WHERE id=?",
                    (row["prev_action"], time.time(), row["photo_id"]))
        con.execute("UPDATE decisions_log SET undone=1 WHERE id=?", (row["id"],))
        con.commit()
        return {"photo_id": row["photo_id"], "restored_to": row["prev_action"],
                "undone_action": row["action"]}

    def decision_counts(self) -> dict:
        rows = self.conn.execute(
            "SELECT COALESCE(decision,'undecided') d, COUNT(*) n FROM photos GROUP BY d"
        ).fetchall()
        return {r["d"]: r["n"] for r in rows}
