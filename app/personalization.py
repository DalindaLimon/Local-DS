"""Per-user source weights from likes/dislikes, weighted shuffle and exploration."""

from __future__ import annotations

import math
import random
import sqlite3
from collections.abc import Callable, Hashable, Sequence
from typing import TypeVar

from app.config import Settings
from app.db import now, tx

T = TypeVar("T")

ITEM_TABLES = {"item": "items", "short": "shorts"}


# --------------------------------------------------------------------------- math


def decay_factor(age_seconds: float, halflife_days: float) -> float:
    if halflife_days <= 0:
        return 1.0
    return 0.5 ** (max(age_seconds, 0.0) / (halflife_days * 86400.0))


def compute_score(
    reactions: Sequence[tuple[int, float]],
    at: float,
    halflife_days: float,
    dislike_factor: float,
    reset_at: float | None = None,
) -> float:
    """score = sum(value * strength * 0.5 ** (age / halflife)) over reactions after reset."""
    total = 0.0
    for value, created_at in reactions:
        if reset_at is not None and created_at < reset_at:
            continue
        strength = 1.0 if value > 0 else dislike_factor
        total += (1 if value > 0 else -1) * strength * decay_factor(at - created_at, halflife_days)
    return total


def weight_from_score(score: float, s: Settings, manual: str | None = None) -> float:
    try:
        w = s.like_base**score
    except OverflowError:
        w = s.max_weight if score > 0 else s.min_weight
    if manual == "boost":
        w *= s.boost_multiplier
    elif manual == "mute":
        w = s.min_weight
    return max(s.min_weight, min(s.max_weight, w))


# --------------------------------------------------------------------------- storage


def recompute_weight(conn: sqlite3.Connection, user_id: int, source_id: int, s: Settings) -> tuple[float, float]:
    pref = conn.execute(
        "SELECT manual, reset_at FROM user_source_prefs WHERE user_id=? AND source_id=?", (user_id, source_id)
    ).fetchone()
    manual = pref["manual"] if pref else None
    reset_at = pref["reset_at"] if pref else None
    rows = conn.execute(
        "SELECT value, created_at FROM reactions WHERE user_id=? AND source_id=?", (user_id, source_id)
    ).fetchall()
    t = now()
    score = compute_score(
        [(r["value"], r["created_at"]) for r in rows], t, s.reaction_halflife_days, s.dislike_factor, reset_at
    )
    weight = weight_from_score(score, s, manual)
    conn.execute(
        """INSERT INTO user_source_prefs(user_id, source_id, weight, score, manual, reset_at, updated_at)
           VALUES(?,?,?,?,?,?,?)
           ON CONFLICT(user_id, source_id) DO UPDATE SET weight=excluded.weight, score=excluded.score,
             updated_at=excluded.updated_at""",
        (user_id, source_id, weight, score, manual, reset_at, t),
    )
    return weight, score


def recompute_all(conn: sqlite3.Connection, s: Settings) -> int:
    """Nightly job: re-apply decay to every (user, source) pair that has history or prefs."""
    pairs = conn.execute(
        """SELECT DISTINCT user_id, source_id FROM reactions WHERE source_id IS NOT NULL
           UNION SELECT user_id, source_id FROM user_source_prefs"""
    ).fetchall()
    for p in pairs:
        if conn.execute("SELECT 1 FROM sources WHERE id=?", (p["source_id"],)).fetchone():
            recompute_weight(conn, p["user_id"], p["source_id"], s)
    return len(pairs)


def get_prefs(conn: sqlite3.Connection, user_id: int) -> dict[int, sqlite3.Row]:
    rows = conn.execute("SELECT * FROM user_source_prefs WHERE user_id=?", (user_id,)).fetchall()
    return {r["source_id"]: r for r in rows}


def get_weights(conn: sqlite3.Connection, user_id: int) -> dict[int, float]:
    return {sid: r["weight"] for sid, r in get_prefs(conn, user_id).items()}


def muted_sources(conn: sqlite3.Connection, user_id: int) -> set[int]:
    rows = conn.execute(
        "SELECT source_id FROM user_source_prefs WHERE user_id=? AND manual='mute'", (user_id,)
    ).fetchall()
    return {r["source_id"] for r in rows}


def set_manual(conn: sqlite3.Connection, user_id: int, source_id: int, mode: str | None, s: Settings) -> float:
    if mode not in (None, "boost", "mute"):
        raise ValueError("mode must be boost, mute or none")
    with tx(conn):
        conn.execute(
            """INSERT INTO user_source_prefs(user_id, source_id, weight, score, manual, updated_at)
               VALUES(?,?,1.0,0,?,?) ON CONFLICT(user_id, source_id) DO UPDATE SET manual=excluded.manual""",
            (user_id, source_id, mode, now()),
        )
        weight, _ = recompute_weight(conn, user_id, source_id, s)
    return weight


def reset_source(conn: sqlite3.Connection, user_id: int, source_id: int, s: Settings) -> float:
    """Reset taste for a source: earlier reactions stop counting (they are kept, not deleted)."""
    with tx(conn):
        conn.execute(
            """INSERT INTO user_source_prefs(user_id, source_id, weight, score, manual, reset_at, updated_at)
               VALUES(?,?,1.0,0,NULL,?,?) ON CONFLICT(user_id, source_id)
               DO UPDATE SET manual=NULL, reset_at=excluded.reset_at""",
            (user_id, source_id, now(), now()),
        )
        weight, _ = recompute_weight(conn, user_id, source_id, s)
    return weight


def react(conn: sqlite3.Connection, user_id: int, item_type: str, item_id: int, value: int, s: Settings) -> dict:
    """Set the user's reaction on an item to +1, -1 or 0 (remove).

    Returns the new reaction value, item counts and the updated source weight.
    """
    if item_type not in ITEM_TABLES:
        raise ValueError("bad item type")
    if value not in (-1, 0, 1):
        raise ValueError("bad value")
    table = ITEM_TABLES[item_type]
    with tx(conn):
        item = conn.execute(f"SELECT id, source_id FROM {table} WHERE id=?", (item_id,)).fetchone()
        if not item:
            raise LookupError("item not found")
        source_id = item["source_id"]
        prev = conn.execute(
            "SELECT value FROM reactions WHERE user_id=? AND item_type=? AND item_id=?", (user_id, item_type, item_id)
        ).fetchone()
        prev_value = prev["value"] if prev else 0
        if value == 0:
            conn.execute(
                "DELETE FROM reactions WHERE user_id=? AND item_type=? AND item_id=?", (user_id, item_type, item_id)
            )
        elif value != prev_value:
            conn.execute(
                """INSERT INTO reactions(user_id, item_type, item_id, source_id, value, created_at)
                   VALUES(?,?,?,?,?,?) ON CONFLICT(user_id, item_type, item_id)
                   DO UPDATE SET value=excluded.value, created_at=excluded.created_at, source_id=excluded.source_id""",
                (user_id, item_type, item_id, source_id, value, now()),
            )
        if item_type == "short":
            conn.execute(
                """UPDATE shorts SET
                     like_count=(SELECT COUNT(*) FROM reactions WHERE item_type='short' AND item_id=? AND value=1),
                     dislike_count=(SELECT COUNT(*) FROM reactions WHERE item_type='short' AND item_id=? AND value=-1)
                   WHERE id=?""",
                (item_id, item_id, item_id),
            )
        weight = None
        if source_id is not None:
            weight, _ = recompute_weight(conn, user_id, source_id, s)
    counts = conn.execute(
        """SELECT SUM(value=1) AS likes, SUM(value=-1) AS dislikes FROM reactions
           WHERE item_type=? AND item_id=?""",
        (item_type, item_id),
    ).fetchone()
    return {
        "value": value,
        "previous": prev_value,
        "likes": counts["likes"] or 0,
        "dislikes": counts["dislikes"] or 0,
        "source_id": source_id,
        "weight": weight,
    }


# --------------------------------------------------------------------------- ordering


def weighted_shuffle(items: Sequence[T], weight_of: Callable[[T], float], rng: random.Random | None = None) -> list[T]:
    """Efraimidis-Spirakis weighted random order: key = u ** (1 / w), sorted descending."""
    rng = rng or random.Random()
    keyed = []
    for it in items:
        w = max(weight_of(it), 1e-9)
        u = rng.random() or 1e-12
        keyed.append((u ** (1.0 / w), it))
    keyed.sort(key=lambda kv: kv[0], reverse=True)
    return [it for _, it in keyed]


def mix_exploration(
    ordered: Sequence[T],
    explore_percent: float,
    rng: random.Random | None = None,
    key: Callable[[T], Hashable] = lambda x: x,
) -> list[tuple[T, bool]]:
    """Reserve ~explore_percent of slots for uniformly random picks.

    Returns (item, explored) pairs. Every item appears exactly once.
    """
    rng = rng or random.Random()
    frac = max(0.0, min(1.0, explore_percent / 100.0))
    uniform = list(ordered)
    rng.shuffle(uniform)
    used: set = set()
    out: list[tuple[T, bool]] = []
    i = j = 0
    n = len(ordered)
    while len(out) < n:
        explore = rng.random() < frac
        if explore:
            while j < n and key(uniform[j]) in used:
                j += 1
            if j < n:
                it = uniform[j]
                while i < n and key(ordered[i]) in used:
                    i += 1
                used.add(key(it))
                # Only flag as explored when it jumped ahead of its weighted position.
                out.append((it, i < n and key(ordered[i]) != key(it)))
                continue
        while i < n and key(ordered[i]) in used:
            i += 1
        if i < n:
            it = ordered[i]
            used.add(key(it))
            out.append((it, False))
    return out


def recency_decay(age_seconds: float, halflife_hours: float) -> float:
    return 0.5 ** (max(age_seconds, 0.0) / (max(halflife_hours, 0.01) * 3600.0))


def foryou_score(weight: float, age_seconds: float, halflife_hours: float) -> float:
    return weight * recency_decay(age_seconds, halflife_hours)


def share_of_feed(weights: dict[int, float]) -> dict[int, float]:
    total = sum(weights.values())
    if total <= 0:
        return {k: 0.0 for k in weights}
    return {k: round(100.0 * v / total, 1) for k, v in weights.items()}


def why_line(weight: float, likes: int, dislikes: int, manual: str | None, explored: bool = False) -> str:
    if explored:
        return "Exploring: a random pick so your feed doesn't become a bubble"
    if manual == "boost":
        return f"Source weight {weight:.1f}x (you boosted this source)"
    parts = []
    if likes:
        parts.append(f"liked {likes} of its posts")
    if dislikes:
        parts.append(f"disliked {dislikes}")
    if not parts:
        return "New source for you (weight 1.0x)" if math.isclose(weight, 1.0) else f"Source weight {weight:.1f}x"
    return f"Source weight {weight:.1f}x because you " + " and ".join(parts)
