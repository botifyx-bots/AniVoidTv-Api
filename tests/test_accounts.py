"""Accounts / community tests against an in-memory Mongo (mongomock). No network."""
import mongomock
import pytest
from fastapi.testclient import TestClient

from app import accounts, db as database, progress, security
from app.main import app

H = {"X-AVTV": "1"}


@pytest.fixture()
def api(monkeypatch):
    database.set_db(mongomock.MongoClient(tz_aware=True)["test"])
    monkeypatch.setattr(security, "check_captcha", lambda *a, **k: True)  # captcha has its own test
    monkeypatch.setattr(accounts.settings, "cookie_secure", False)
    security.limiter._hits.clear()
    with TestClient(app) as c:
        yield c


def signup(c, name="alice", pw="Passw0rd!x"):
    r = c.post("/api/auth/register", json={"username": name, "password": pw, "confirm": pw,
                                           "captcha_token": "t", "captcha_answer": "a"}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()["results"]


def test_csrf_header_required(api):
    assert api.post("/api/auth/logout").status_code == 403
    assert api.post("/api/auth/logout", headers=H).status_code == 200


def test_captcha_roundtrip_and_single_use():
    db = mongomock.MongoClient(tz_aware=True)["c"]
    cap = security.new_captcha()
    assert cap["image"].startswith("data:image/svg+xml;base64,")
    token = security.sign({"t": "c", "n": "n1", "h": security._ans_hash("n1", "ABCDE")}, 300)
    assert security.check_captcha(db, token, "abcde") is True      # case-insensitive
    assert security.check_captcha(db, token, "abcde") is False     # replay blocked
    t2 = security.sign({"t": "c", "n": "n2", "h": security._ans_hash("n2", "ABCDE")}, 300)
    assert security.check_captcha(db, t2, "WRONG") is False
    assert security.check_captcha(db, "garbage", "x") is False


def test_register_login_logout_me(api):
    me = signup(api)
    assert me["username"] == "alice" and me["vp"] == 50 and me["rank"]["title"] == "Newcomer"
    assert api.get("/api/me").json()["results"]["username"] == "alice"       # cookie session works
    assert api.post("/api/auth/logout", headers=H).status_code == 200
    assert api.get("/api/me").status_code == 401
    r = api.post("/api/auth/login", json={"username": "ALICE", "password": "Passw0rd!x"}, headers=H)
    assert r.status_code == 200 and api.get("/api/me").status_code == 200
    bad = api.post("/api/auth/login", json={"username": "alice", "password": "nope"}, headers=H)
    assert bad.status_code == 401


@pytest.mark.parametrize("name,pw,msg", [
    ("ab", "Passw0rd!x", "3-20"), ("bad name", "Passw0rd!x", "letters"), ("admin", "Passw0rd!x", "reserved"),
    ("okname", "short", "8-64"), ("okname", "has space 123", "8-64"), ("longername", "longername", "same as your username"),
])
def test_register_validation(api, name, pw, msg):
    r = api.post("/api/auth/register", json={"username": name, "password": pw, "captcha_token": "t", "captcha_answer": "a"}, headers=H)
    assert r.status_code == 400 and msg in r.json()["message"]


def test_duplicate_username_case_insensitive(api):
    signup(api, "Bob")
    r = api.post("/api/auth/register", json={"username": "bob", "password": "Passw0rd!x", "captcha_token": "t", "captcha_answer": "a"}, headers=H)
    assert r.status_code == 409


def test_wrong_captcha_rejected(api, monkeypatch):
    monkeypatch.setattr(security, "check_captcha", lambda *a, **k: False)
    r = api.post("/api/auth/register", json={"username": "carol", "password": "Passw0rd!x", "captcha_token": "t", "captcha_answer": "a"}, headers=H)
    assert r.status_code == 400 and r.json()["captcha_failed"] is True


def test_password_change_signs_out_other_sessions(api):
    signup(api)
    other = TestClient(app)
    other.cookies.update(api.cookies)
    assert other.get("/api/me").status_code == 200
    r = api.post("/api/me/password", json={"current": "Passw0rd!x", "new": "N3wPassw0rd#"}, headers=H)
    assert r.status_code == 200
    assert other.get("/api/me").status_code == 401           # old session revoked
    assert api.get("/api/me").status_code == 200             # this one re-issued
    assert api.post("/api/me/password", json={"current": "wrong", "new": "N3wPassw0rd#2"}, headers=H).status_code == 400


def test_profile_update_rules(api):
    signup(api)
    ok = api.patch("/api/me", json={"bio": "anime fan", "favorites": [{"id": 1, "title": "A", "poster": "p"}] * 3 + [{"id": "x"}]}, headers=H)
    assert ok.status_code == 200 and len(ok.json()["results"]["favorites"]) == 1       # de-duped, junk dropped
    assert api.patch("/api/me", json={"bio": "visit www.spam.com"}, headers=H).status_code == 400
    assert api.patch("/api/me", json={"avatar": {"icon": "fox", "bg": 3}}, headers=H).status_code == 200
    assert api.patch("/api/me", json={"avatar": {"icon": "\U0001F4A9"}}, headers=H).status_code == 400      # emoji icons are gone
    assert api.patch("/api/me", json={"banner": {"preset": "p4"}}, headers=H).json()["results"]["banner"] == {"pic": None, "preset": "p4"}
    assert api.patch("/api/me", json={"banner": {"preset": "nope"}}, headers=H).status_code == 400
    r = api.post("/api/me/username", json={"username": "alice2", "password": "Passw0rd!x"}, headers=H)
    assert r.status_code == 200 and r.json()["results"]["username"] == "alice2"
    assert api.post("/api/me/username", json={"username": "alice3", "password": "Passw0rd!x"}, headers=H).status_code == 429


def test_display_name_rules(api):
    signup(api, "alice")
    other = TestClient(app)
    signup(other, "bobby")
    ok = api.patch("/api/me", json={"display_name": "Alice  in  Wonderland"}, headers=H).json()["results"]
    assert ok["name"] == "Alice in Wonderland" and ok["username"] == "alice"                 # spaces collapsed, handle unchanged
    for bad in ["a", "x" * 25, "bad<name>", "see www.spam.com", "bobby", "Admin", "\u200b\u200b"]:
        assert api.patch("/api/me", json={"display_name": bad}, headers=H).status_code in (400, 409), bad
    assert api.patch("/api/me", json={"display_name": "Zoë ✨".replace("✨", "")}, headers=H).status_code == 200     # unicode letters are fine
    assert api.patch("/api/me", json={"display_name": ""}, headers=H).json()["results"]["name"] == "alice"           # clear -> back to username


def test_checkin_and_streak(api):
    signup(api)
    first = api.post("/api/me/checkin", headers=H).json()["results"]
    assert first["granted"] == 12 and first["streak"] == 1 and first["vp"] == 62
    again = api.post("/api/me/checkin", headers=H).json()["results"]
    assert again["already"] is True and again["granted"] == 0


def test_comments_reactions_and_stickers(api):
    signup(api, "alice")
    assert api.get("/api/comments?anime_id=7").json()["results"]["data"] == []
    c = api.post("/api/comments", json={"anime_id": 7, "text": "great show"}, headers=H).json()["results"]
    assert c["mine"] and c["vp_gained"] == 3 and c["user"]["name"] == "alice"
    r = api.post("/api/comments", json={"anime_id": 7, "text": "agreed", "parent_id": c["id"]}, headers=H).json()["results"]
    assert r["parent_id"] == c["id"]
    assert api.post("/api/comments", json={"anime_id": 7, "text": "see http://x.com"}, headers=H).status_code == 400
    assert api.post("/api/comments", json={"anime_id": 7, "text": ""}, headers=H).status_code == 400
    listing = api.get("/api/comments?anime_id=7").json()["results"]
    assert listing["data"][0]["reply_count"] == 1
    assert api.get(f"/api/comments/{c['id']}/replies").json()["results"]["data"][0]["text"] == "agreed"
    v = api.post(f"/api/comments/{c['id']}/react", json={"key": "love"}, headers=H).json()["results"]
    assert v == {"reactions": {"love": 1}, "my_reaction": "love"}
    v = api.post(f"/api/comments/{c['id']}/react", json={"key": "fire"}, headers=H).json()["results"]
    assert v["reactions"] == {"fire": 1}                                                  # switching replaces, not adds
    assert api.post(f"/api/comments/{c['id']}/react", json={"key": "\U0001F4A9"}, headers=H).status_code == 400
    assert api.get("/api/comments?anime_id=7").json()["results"]["data"][0]["my_reaction"] == "fire"
    assert api.post(f"/api/comments/{c['id']}/react", json={"key": None}, headers=H).json()["results"]["reactions"] == {}
    # stickers: free packs work, paid packs need buying, unknown ones are rejected
    security.limiter._hits.clear()                      # comment rate limit (6/min) is tested elsewhere
    s1 = api.post("/api/comments", json={"anime_id": 7, "text": "", "sticker": "blobs:happy"}, headers=H)
    assert s1.status_code == 200 and s1.json()["results"]["sticker"] == "blobs:happy"
    assert api.post("/api/comments", json={"anime_id": 7, "text": "", "sticker": "spirits:boo"}, headers=H).status_code == 403
    assert api.post("/api/comments", json={"anime_id": 7, "text": "", "sticker": "blobs:nope"}, headers=H).status_code == 400
    other = TestClient(app)
    assert other.post("/api/comments", json={"anime_id": 7, "text": "hi"}, headers=H).status_code == 401
    signup(other, "mallory")
    assert other.delete(f"/api/comments/{c['id']}", headers=H).status_code == 403
    assert api.delete(f"/api/comments/{c['id']}", headers=H).json()["results"]["removed"] == 2


def test_list_and_public_profile(api):
    signup(api, "alice")
    assert api.put("/api/list/5", json={"status": "watching", "title": "Show", "poster": "p"}, headers=H).json()["results"]["vp_gained"] == 2
    assert api.put("/api/list/5", json={"status": "completed"}, headers=H).json()["results"]["vp_gained"] == 0
    assert api.put("/api/list/6", json={"status": "bad"}, headers=H).status_code == 400
    assert api.get("/api/list/5").json()["results"]["status"] == "completed"
    lst = api.get("/api/list?status=completed").json()["results"]
    assert lst["data"][0]["title"] == "Show" and lst["counts"]["completed"] == 1
    pub = TestClient(app).get("/api/users/ALICE").json()["results"]            # no auth needed
    assert pub["stats"]["list_counts"]["completed"] == 1 and "email" not in pub and "id" not in pub
    assert TestClient(app).get("/api/users/nobody").status_code == 404
    api.patch("/api/me", json={"privacy": {"show_list": False}}, headers=H)
    assert TestClient(app).get("/api/users/alice/list").status_code == 403
    assert TestClient(app).get("/api/users/alice").json()["results"]["stats"]["list_counts"] is None
    assert api.delete("/api/list/5", headers=H).status_code == 200
    assert api.get("/api/list/5").json()["results"]["status"] is None


def test_continue_watching_and_merge(api):
    signup(api)
    api.put("/api/continue/10", json={"title": "A", "poster": "p", "episode": 3}, headers=H)
    api.put("/api/continue/11", json={"title": "B", "poster": "p", "episode": 1, "audio": "dub"}, headers=H)
    items = api.get("/api/continue").json()["results"]
    assert [i["anime_id"] for i in items] == [11, 10] and items[0]["audio"] == "dub"
    merged = api.post("/api/continue/merge", json={"items": [
        {"anime_id": 10, "title": "A", "episode": 1, "updated_at": 1000},          # older than server -> ignored
        {"anime_id": 12, "title": "C", "episode": 4, "updated_at": 4102444800000},  # new
        {"anime_id": "junk"}]}, headers=H).json()["results"]
    assert {i["anime_id"] for i in merged} == {10, 11, 12}
    assert next(i for i in merged if i["anime_id"] == 10)["episode"] == 3
    api.delete("/api/continue/10", headers=H)
    assert 10 not in [i["anime_id"] for i in api.get("/api/continue").json()["results"]]
    assert api.delete("/api/continue", headers=H).json()["results"]["removed"] == 2


def test_watch_complete_counts_once_and_unlocks_badges(api):
    signup(api)
    first = api.post("/api/watch/complete", json={"anime_id": 3, "episode": 1}, headers=H).json()["results"]
    assert first == {"counted": True, "vp_gained": 5}
    assert api.post("/api/watch/complete", json={"anime_id": 3, "episode": 1}, headers=H).json()["results"]["counted"] is False
    me = api.get("/api/me").json()["results"]
    assert me["stats"]["episodes"] == 1 and me["stats"]["hours"] == 0.4
    assert {b["id"] for b in me["badges"] if b["earned"]} == {"first_steps", "first_episode"}
    assert all(not any(ord(ch) > 0x2000 for ch in b["icon"]) for b in me["badges"])      # badge icons are keys, not emoji


def test_daily_vp_cap():
    db = mongomock.MongoClient(tz_aware=True)["cap"]
    u = {"_id": 1, "vp": 0}
    db.users.insert_one(u)
    total = sum(progress.award(db, u, "comment") for _ in range(10))
    assert total == 15                                    # cap of 15 VP/day for comments


def test_google_flow(api, monkeypatch):
    monkeypatch.setattr(accounts.settings, "google_client_id", "cid")
    monkeypatch.setattr(accounts, "_verify_google", lambda cred: {"sub": "g-1", "email": "x@gmail.com"})
    r = api.post("/api/auth/google", json={"credential": "tok"}, headers=H).json()["results"]
    assert r["status"] == "need_username"
    done = api.post("/api/auth/google/complete", json={"ticket": r["ticket"], "username": "gina"}, headers=H)
    assert done.status_code == 200 and done.json()["results"]["google_linked"] is True
    api.post("/api/auth/logout", headers=H)
    again = api.post("/api/auth/google", json={"credential": "tok"}, headers=H).json()["results"]
    assert again["status"] == "ok" and again["user"]["username"] == "gina"
    assert api.post("/api/auth/google/complete", json={"ticket": "bad", "username": "zed"}, headers=H).status_code == 400


def test_accounts_disabled_without_database(monkeypatch):
    monkeypatch.setattr(database, "_db", None)
    monkeypatch.setattr(database.settings, "mongodb_uri", "")
    with TestClient(app) as c:
        assert c.get("/api/config").json()["results"]["accounts"] is False
        assert c.get("/api/comments?anime_id=1").status_code == 503
        assert c.get("/api/me").status_code == 401
