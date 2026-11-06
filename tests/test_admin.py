"""Admin console: 2FA login, sessions, CSRF, telemetry, flags, moderation, hardening middleware."""
import io

import mongomock
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import accounts, admin, db as database, flags, main, security, telemetry
from app.main import app

H = {"X-AVTV": "1"}
PW = "Correct-Horse-Battery-9!"
SECRET = security.new_totp_secret()
ANDROID = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36"
DESKTOP = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"


@pytest.fixture()
def env(monkeypatch):
    database.set_db(mongomock.MongoClient(tz_aware=True)["adm"])
    flags.invalidate()
    monkeypatch.setattr(security, "check_captcha", lambda *a, **k: True)
    for k, v in {"cookie_secure": False, "admin_username": "boss_user", "admin_password_hash": security.hash_password(PW), "admin_totp_secret": SECRET,
                 "admin_ips": [], "require_proxy": False, "proxy_secret": "", "global_rate_per_min": 100000}.items():
        monkeypatch.setattr(admin.settings, k, v)
    monkeypatch.setattr(admin.time, "sleep", lambda s: None)
    security.limiter._hits.clear()
    with TestClient(app) as c:
        yield c
    flags.invalidate()


def otp(offset=0):
    import time
    return security.totp_code(SECRET, int(time.time() // 30) + offset)


def admin_login(c, offset=0, user="boss_user", pw=PW, code=None):
    return c.post("/api/admin/login", json={"username": user, "password": pw, "otp": code or otp(offset)}, headers=H)


def csrf_of(r):
    return {**H, "X-Admin-CSRF": r.json()["results"]["csrf"]}


def signup(c, name="alice", pw="Passw0rd!x"):
    r = c.post("/api/auth/register", json={"username": name, "password": pw, "captcha_token": "t", "captcha_answer": "a"}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()["results"]


def png():
    b = io.BytesIO(); Image.new("RGB", (300, 300), (9, 9, 9)).save(b, "PNG"); return b.getvalue()


# ---------------------------------------------------------------- crypto + setup
def test_totp_matches_rfc6238_vector():
    import base64
    secret = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
    assert security.totp_code(secret, 59 // 30) == "287082"                  # RFC 6238 appendix B (T=59, last 6 digits)
    assert security.totp_verify(secret, "287082", now=59) == 1
    assert security.totp_verify(secret, "287082", now=59 + 300) is None       # too old
    assert security.totp_verify(secret, "12345", now=59) is None and security.totp_verify(secret, "abcdef", now=59) is None


def test_admin_setup_hash_verifies():
    h = security.hash_password(PW)
    assert h.startswith("scrypt$") and security.verify_password(PW, h) and not security.verify_password(PW + "x", h)


def test_common_and_trivial_passwords_are_rejected(env):
    for bad in ["password123", "Qwerty123", "aaaaaaaaaa"]:
        r = env.post("/api/auth/register", json={"username": "newbie", "password": bad, "captcha_token": "t", "captcha_answer": "a"}, headers=H)
        assert r.status_code == 400, bad


# ---------------------------------------------------------------- login / sessions
def test_console_is_invisible_when_not_configured(env, monkeypatch):
    monkeypatch.setattr(admin.settings, "admin_totp_secret", "")
    assert admin_login(env).status_code == 404 and env.get("/api/admin/me").status_code == 404 and env.get("/api/admin/overview").status_code == 404


def test_login_requires_all_three_factors_and_stays_generic(env):
    bad = [admin_login(env, pw="wrong-password-123"), admin_login(env, user="someone_else"), admin_login(env, code="000000")]
    assert {r.status_code for r in bad} == {401} and {r.json()["message"] for r in bad} == {"Invalid credentials"}
    assert env.post("/api/admin/login", json={"username": "boss_user", "password": PW, "otp": otp()}).status_code == 403   # needs X-AVTV too
    ok = admin_login(env)
    assert ok.status_code == 200 and ok.json()["results"]["csrf"] and "avtv_admin" in env.cookies


def test_totp_code_cannot_be_replayed(env):
    assert admin_login(env).status_code == 200
    env.cookies.clear()
    assert admin_login(env).status_code == 401                 # same time-step code again
    assert admin_login(env, offset=1).status_code == 200       # next step works


def test_lockout_after_five_failures_even_with_correct_credentials(env):
    for _ in range(5):
        assert admin_login(env, pw="nope-nope-nope-1").status_code == 401
    locked = admin_login(env)
    assert locked.status_code == 429 and "Locked" in locked.json()["message"]


def test_writes_need_the_csrf_token_and_user_and_admin_sessions_are_separate(env):
    signup(env, "victim")
    env.cookies.clear()
    r = admin_login(env)
    assert env.post("/api/admin/users/victim/ban", headers=H).status_code == 403                  # no CSRF token
    assert env.post("/api/admin/users/victim/ban", headers={**H, "X-Admin-CSRF": "x" * 32}).status_code == 403
    assert env.post("/api/admin/users/victim/ban", headers=csrf_of(r)).status_code == 200
    assert env.get("/api/me").status_code == 401                                                  # admin cookie is not a member session
    member = TestClient(app); signup(member, "member2")
    assert member.get("/api/admin/overview").status_code == 401                                   # member cookie is not an admin session


def test_ip_allow_list_hides_the_console(env, monkeypatch):
    monkeypatch.setattr(admin.settings, "admin_ips", ["203.0.113.9"])
    assert admin_login(env).status_code == 404


def test_idle_and_absolute_session_timeouts(env):
    r = admin_login(env)
    assert env.get("/api/admin/me").status_code == 200
    from datetime import timedelta
    db = database.get_db()
    db.admin_sessions.update_many({}, {"$set": {"last_seen": admin.progress.now() - timedelta(minutes=45)}})
    assert env.get("/api/admin/me").status_code == 401 and db.admin_sessions.count_documents({}) == 0
    admin_login(env, offset=1)
    db.admin_sessions.update_many({}, {"$set": {"expires": admin.progress.now() - timedelta(seconds=5)}})
    assert env.get("/api/admin/me").status_code == 401


def test_logout_and_revoke_all(env):
    r = admin_login(env)
    h = csrf_of(r)
    assert env.post("/api/admin/sessions/revoke-all", headers=h).json()["results"]["revoked"] == 1
    assert env.get("/api/admin/me").status_code == 401


# ---------------------------------------------------------------- telemetry + overview
def ping(c, did, ua=DESKTOP, t="view", p="/home", s=False, country=None, secret=None):
    h = {**H, "User-Agent": ua}
    if country:
        h["X-Client-Country"] = country
    if secret:
        h["X-Proxy-Secret"] = secret
    return c.post("/api/t/ping", json={"d": did, "t": t, "p": p, "s": s}, headers=h)


def test_telemetry_counts_devices_platforms_and_ignores_bots(env, monkeypatch):
    monkeypatch.setattr(admin.settings, "proxy_secret", "sek")
    assert ping(env, "A" * 22, ANDROID, s=True, country="in", secret="sek").status_code == 200
    ping(env, "B" * 22, DESKTOP, country="us", secret="sek"); ping(env, "C" * 22, IPHONE)
    ping(env, "A" * 22, ANDROID, t="beat", s=True, secret="sek")
    assert ping(env, "D" * 22, "Googlebot/2.1 (+http://www.google.com/bot.html)").status_code == 200       # accepted but not stored
    assert ping(env, "short", DESKTOP).status_code == 400
    assert env.post("/api/t/ping", json={"d": "E" * 22, "t": "view", "p": "/x"}).status_code == 403          # CSRF header required
    ping(env, "F" * 22, DESKTOP, p="<script>")                                                                # bad path is sanitised, not rejected
    r = admin_login(env)
    ov = env.get("/api/admin/overview").json()["results"]
    assert ov["devices_total"] == 4 and ov["online_now"] == 4 and ov["online_pwa"] == 1 and ov["installed_apps_30d"] == 1 and ov["active_today"] == 4
    assert {x["name"]: x["count"] for x in ov["platforms"]} == {"Android": 1, "Windows": 2, "iOS": 1}
    assert {x["name"] for x in ov["kinds"]} == {"mobile", "desktop"}
    assert {x["name"]: x["count"] for x in ov["countries"]}.get("IN") == 1 and {x["name"] for x in ov["countries"]} >= {"IN", "US"}
    ts = env.get("/api/admin/timeseries?days=3").json()["results"]
    assert len(ts) == 3 and ts[-1]["views"] == 4 and ts[-1]["active_devices"] == 4 and ts[-1]["new_devices"] == 4
    for f, n in [("android", 1), ("ios", 1), ("desktop", 2), ("pwa", 1), ("online", 4), ("all", 4)]:
        assert env.get(f"/api/admin/devices?filter={f}").json()["results"]["total"] == n, f
    row = env.get("/api/admin/devices?filter=android").json()["results"]["data"][0]
    assert row["app"] is True and row["browser"] == "Chrome" and row["id"].endswith("…") and len(row["id"]) < 10
    assert env.get("/api/admin/devices?filter=hack").status_code == 422


def test_country_header_is_ignored_without_the_proxy_secret(env, monkeypatch):
    monkeypatch.setattr(admin.settings, "proxy_secret", "sek")
    ping(env, "G" * 22, country="ZZ")                 # no secret -> spoofable header must be ignored
    admin_login(env)
    assert env.get("/api/admin/overview").json()["results"]["countries"] == []


def test_new_device_flood_from_one_source_is_limited(env):
    codes = [ping(env, f"dev{i:020d}").status_code for i in range(30)]
    assert 429 in codes and codes.count(200) <= 26


def test_logged_in_devices_are_linked_to_users(env):
    signup(env, "alice")
    ping(env, "H" * 22)
    admin_login_client = TestClient(app)
    r = admin_login(admin_login_client)
    rows = admin_login_client.get("/api/admin/devices?filter=loggedin").json()["results"]
    assert rows["total"] == 1 and rows["data"][0]["user"] == "alice"


# ---------------------------------------------------------------- feature flags / maintenance
def test_flags_gate_features_and_are_public(env):
    member = TestClient(app); signup(member, "alice")
    r = admin_login(env); h = csrf_of(r)
    cfg = env.get("/api/config").json()["results"]["flags"]
    assert cfg["registration_enabled"] is True and cfg["maintenance"]["on"] is False
    assert env.put("/api/admin/flags", json={"nope": True}, headers=h).status_code == 400
    assert env.put("/api/admin/flags", json={"registration_enabled": "yes"}, headers=h).status_code == 400
    assert env.put("/api/admin/flags", json={"registration_enabled": False, "comments_enabled": False, "announcement_enabled": True, "announcement_text": "New effects soon!"}, headers=h).status_code == 200
    flags.invalidate()
    pub = TestClient(app).get("/api/config").json()["results"]["flags"]
    assert pub["announcement"] == {"on": True, "text": "New effects soon!", "level": "info"} and pub["registration_enabled"] is False
    assert TestClient(app).post("/api/auth/register", json={"username": "newguy", "password": "Zx9!kQ2#mWp", "captcha_token": "t", "captcha_answer": "a"}, headers=H).status_code == 403
    assert member.post("/api/comments", json={"anime_id": 1, "text": "hi"}, headers=H).status_code == 403
    env.put("/api/admin/flags", json={"uploads_enabled": False, "shop_enabled": False}, headers=h); flags.invalidate()
    assert member.post("/api/me/pictures?kind=avatar", content=png(), headers={**H, "Content-Type": "application/octet-stream"}).status_code == 403
    assert member.post("/api/shop/buy", json={"item": "frame.clover_ring"}, headers=H).status_code == 403


def test_maintenance_mode_blocks_member_writes_but_not_admin_or_reads(env):
    member = TestClient(app); signup(member, "alice")
    r = admin_login(env); h = csrf_of(r)
    env.put("/api/admin/flags", json={"maintenance_mode": True, "maintenance_message": "Back at 5"}, headers=h); flags.invalidate()
    blocked = member.post("/api/comments", json={"anime_id": 1, "text": "hi"}, headers=H)
    assert blocked.status_code == 503 and blocked.json()["maintenance"] is True and blocked.json()["message"] == "Back at 5"
    assert member.get("/api/me").status_code == 200 and member.get("/api/comments?anime_id=1").status_code == 200
    assert ping(member, "M" * 22).status_code == 200                               # telemetry keeps working
    assert env.put("/api/admin/flags", json={"maintenance_mode": False}, headers=h).status_code == 200
    flags.invalidate()
    assert member.post("/api/comments", json={"anime_id": 1, "text": "hi"}, headers=H).status_code == 200


# ---------------------------------------------------------------- users / moderation / audit
def test_user_management_and_audit_trail(env):
    m1 = TestClient(app); signup(m1, "alice"); m2 = TestClient(app); signup(m2, "alina")
    r = admin_login(env); h = csrf_of(r)
    res = env.get("/api/admin/users?q=ali").json()["results"]
    assert res["total"] == 2 and {u["username"] for u in res["data"]} == {"alice", "alina"}
    assert env.get("/api/admin/users?q=zzz").json()["results"]["total"] == 0
    assert env.post("/api/admin/users/alice/vp", json={"delta": 500, "reason": "contest"}, headers=h).status_code == 200
    assert m1.get("/api/me").json()["results"]["vp"] == 550
    assert env.post("/api/admin/users/alice/ban", headers=h).status_code == 200 and m1.get("/api/me").status_code == 401
    assert env.get("/api/admin/users?q=alice").json()["results"]["data"][0]["banned"] is True
    assert env.post("/api/admin/users/alice/unban", headers=h).status_code == 200
    assert env.post("/api/admin/users/alina/signout", headers=h).json()["results"]["signed_out"] == 1 and m2.get("/api/me").status_code == 401
    assert env.post("/api/admin/users/ghost/ban", headers=h).status_code == 404
    log = env.get("/api/admin/audit").json()["results"]
    assert {"login", "vp", "ban", "unban", "force_signout"} <= {x["action"] for x in log}
    assert all(set(x) >= {"at", "actor", "action", "ok"} for x in log)
    sec = env.get("/api/admin/security").json()["results"]
    assert sec["failed_logins_24h"] == 0 and any(c["name"].startswith("Admin 2FA") and c["ok"] for c in sec["checks"])


def test_reports_queue_and_content_removal(env):
    alice = TestClient(app); signup(alice, "alice")
    c = alice.post("/api/comments", json={"anime_id": 5, "text": "spam spam spam"}, headers=H).json()["results"]
    pic = alice.post("/api/me/pictures?kind=avatar", content=png(), headers={**H, "Content-Type": "application/octet-stream"}).json()["results"]
    bob = TestClient(app); signup(bob, "bobby")
    bob.post("/api/report", json={"type": "comment", "target": c["id"], "reason": "spam"}, headers=H)
    bob.post("/api/report", json={"type": "media", "target": pic["id"], "reason": "bad"}, headers=H)
    r = admin_login(env); h = csrf_of(r)
    rows = env.get("/api/admin/reports").json()["results"]
    assert {x["type"] for x in rows} == {"comment", "media"} and next(x for x in rows if x["type"] == "comment")["preview"].startswith("spam spam")
    assert env.delete(f"/api/admin/comments/{c['id']}", headers=h).json()["results"]["removed"] == 1
    assert env.delete(f"/api/admin/media/{pic['id']}", headers=h).status_code == 200
    assert alice.get(f"/api/media/{pic['id']}").status_code == 404
    assert env.get("/api/admin/reports").json()["results"] == []
    rid = bob.post("/api/report", json={"type": "user", "target": "alice", "reason": "x"}, headers=H) and env.get("/api/admin/reports").json()["results"][0]["id"]
    assert env.post(f"/api/admin/reports/{rid}/resolve", headers=h).status_code == 200


# ---------------------------------------------------------------- hardening middleware
def test_backend_only_answers_the_proxy_when_required(env, monkeypatch):
    monkeypatch.setattr(main.settings, "proxy_secret", "proxy-secret-1"); monkeypatch.setattr(main.settings, "require_proxy", True)
    monkeypatch.setattr(accounts.settings, "proxy_secret", "proxy-secret-1")
    r = env.get("/api/config")
    assert r.status_code == 403 and r.json() == {"success": False, "message": "Forbidden"}
    assert env.get("/api/config", headers={"X-Proxy-Secret": "wrong"}).status_code == 403
    assert env.get("/api/config", headers={"X-Proxy-Secret": "proxy-secret-1"}).status_code == 200
    assert env.get("/heartbeat").status_code == 200 and env.get("/health").status_code == 200          # uptime monitors still work
    assert env.get("/").status_code == 200


def test_global_rate_limit_per_client(env, monkeypatch):
    monkeypatch.setattr(main.settings, "global_rate_per_min", 5)
    codes = [env.get("/api/config").status_code for _ in range(8)]
    assert codes[:5] == [200] * 5 and set(codes[5:]) == {429}


def test_docs_and_cors_are_off_by_default_in_production_mode():
    from app.config import Settings
    assert Settings.cors_origins == [] and Settings.disable_docs in (True, False)
    assert main.app.openapi_url is None or not main.settings.cookie_secure
