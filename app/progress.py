"""Void Points (VP), ranks, avatar frames and computed badges: the 'come back daily' layer."""
from datetime import datetime, timedelta, timezone

RANKS = [  # (min VP, title)
    (0, "Newcomer"), (500, "Void Initiate"), (2000, "Shadow Watcher"),
    (5000, "Rift Walker"), (10000, "Void Sage"), (25000, "Ascended"),
]
AVATAR_BG_COUNT = 12   # gradient swatches for the default avatar and accent colour

# reason -> (points each, max points per day)
VP_RULES = {"comment": (3, 15), "episode": (5, 100), "list_add": (2, 10), "welcome": (50, 50)}
CHECKIN_BASE, CHECKIN_STREAK_BONUS, CHECKIN_STREAK_CAP = 10, 2, 7
MINUTES_PER_EPISODE = 24


def now() -> datetime:
    return datetime.now(timezone.utc)


def today() -> str:
    return now().strftime("%Y-%m-%d")


def rank_index(vp: int) -> int:
    idx = 0
    for i, (lo, _) in enumerate(RANKS):
        if vp >= lo:
            idx = i
    return idx


def rank_info(vp: int) -> dict:
    i = rank_index(vp)
    cur = RANKS[i]
    nxt = RANKS[i + 1] if i + 1 < len(RANKS) else None
    pct = 100 if not nxt else round((vp - cur[0]) / (nxt[0] - cur[0]) * 100, 1)
    return {"index": i, "title": cur[1], "next_title": nxt[1] if nxt else None,
            "next_at": nxt[0] if nxt else None, "progress": pct,
            "ladder": [{"title": t, "at": lo} for lo, t in RANKS]}


def award(db, user: dict, reason: str, amount: int | None = None) -> int:
    """Give VP respecting the per-day cap of `reason`. Returns the points actually granted."""
    per, cap = VP_RULES.get(reason, (amount or 0, amount or 0))
    amount = per if amount is None else amount
    day = today()
    earned = (user.get("vp_day") or {})
    got = earned.get("r", {}) if earned.get("d") == day else {}
    room = max(0, cap - got.get(reason, 0))
    give = min(amount, room)
    if give <= 0:
        return 0
    got[reason] = got.get(reason, 0) + give
    db.users.update_one({"_id": user["_id"]}, {"$inc": {"vp": give}, "$set": {"vp_day": {"d": day, "r": got}}})
    db.vp_log.insert_one({"user_id": user["_id"], "delta": give, "reason": reason, "at": now()})
    user["vp"] = user.get("vp", 0) + give
    user["vp_day"] = {"d": day, "r": got}
    return give


def checkin(db, user: dict) -> dict:
    day = today()
    if user.get("last_checkin") == day:
        return {"already": True, "granted": 0, "streak": user.get("streak", 0), "vp": user.get("vp", 0)}
    yesterday = (now() - timedelta(days=1)).strftime("%Y-%m-%d")
    streak = user.get("streak", 0) + 1 if user.get("last_checkin") == yesterday else 1
    grant = CHECKIN_BASE + CHECKIN_STREAK_BONUS * min(streak, CHECKIN_STREAK_CAP)
    db.users.update_one({"_id": user["_id"]}, {"$inc": {"vp": grant, "days_checked": 1},
                                               "$set": {"last_checkin": day, "streak": streak},
                                               "$max": {"best_streak": streak}})
    db.vp_log.insert_one({"user_id": user["_id"], "delta": grant, "reason": "checkin", "at": now()})
    return {"already": False, "granted": grant, "streak": streak, "vp": user.get("vp", 0) + grant}


# (id, icon key (drawn by the frontend), name, description, predicate(stats))
BADGES = [
    ("first_steps", "footprints", "First Steps", "Create your account", lambda s: True),
    ("first_episode", "play", "First Episode", "Finish your first episode", lambda s: s["episodes"] >= 1),
    ("binge_10", "popcorn", "Warming Up", "Finish 10 episodes", lambda s: s["episodes"] >= 10),
    ("binge_100", "tv", "Marathoner", "Finish 100 episodes", lambda s: s["episodes"] >= 100),
    ("binge_500", "trophy", "Living Room Legend", "Finish 500 episodes", lambda s: s["episodes"] >= 500),
    ("commenter", "chat", "Voice Heard", "Post 5 comments", lambda s: s["comments"] >= 5),
    ("curator", "books", "Curator", "Add 10 anime to your list", lambda s: s["list_total"] >= 10),
    ("finisher", "check", "Finisher", "Mark 5 anime as completed", lambda s: s["completed"] >= 5),
    ("streak_7", "flame", "On Fire", "7-day check-in streak", lambda s: s["best_streak"] >= 7),
    ("streak_30", "volcano", "Unstoppable", "30-day check-in streak", lambda s: s["best_streak"] >= 30),
    ("rank_sage", "crystal", "Void Sage", "Reach the Void Sage rank", lambda s: s["rank"] >= 4),
    ("picture", "camera", "Say Cheese", "Upload a profile picture", lambda s: s["pics"] >= 1),
    ("gallery", "image", "Gallery", "Upload 5 pictures", lambda s: s["pics"] >= 5),
    ("collector", "gem", "Collector", "Own 5 shop items", lambda s: s["owned"] >= 5),
    ("big_spender", "crown", "High Roller", "Own 15 shop items", lambda s: s["owned"] >= 15),
]


def badges_for(stats: dict) -> list[dict]:
    return [{"id": i, "icon": ic, "name": n, "desc": d, "earned": bool(fn(stats))} for i, ic, n, d, fn in BADGES]
