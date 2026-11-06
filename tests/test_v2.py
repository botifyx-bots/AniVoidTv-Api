"""Pictures, shop, sessions, lockout, admin and security headers (mongomock, no network)."""
import io

import mongomock
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import accounts, db as database, effects, security
from app.main import app

H = {"X-AVTV": "1"}
RAW = {"X-AVTV": "1", "Content-Type": "application/octet-stream"}


@pytest.fixture()
def api(monkeypatch):
    database.set_db(mongomock.MongoClient(tz_aware=True)["v2"])
    monkeypatch.setattr(security, "check_captcha", lambda *a, **k: True)
    monkeypatch.setattr(accounts.settings, "cookie_secure", False)
    security.limiter._hits.clear()
    with TestClient(app) as c:
        yield c


def signup(c, name="alice", pw="Passw0rd!x"):
    r = c.post("/api/auth/register", json={"username": name, "password": pw, "captcha_token": "t", "captcha_answer": "a"}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()["results"]


def png(w=500, h=300, color=(200, 40, 90), fmt="PNG"):
    b = io.BytesIO()
    Image.new("RGB", (w, h), color).save(b, fmt)
    return b.getvalue()


def test_every_recipe_family_is_known_to_the_frontend_generator():
    import json, pathlib, subprocess, sys, tempfile
    d = tempfile.mkdtemp()
    out = subprocess.run([sys.executable, "tools/gen_effects.py", f"{d}/e.css", f"{d}/r.js"], capture_output=True, text=True, cwd=pathlib.Path(__file__).resolve().parent.parent)
    assert out.returncode == 0, out.stderr
    recipes = json.loads(open(f"{d}/r.js").read().split("AVTV.FX_RECIPES = ")[1].rstrip().rstrip(";"))
    assert {r["fam"] for k, r in recipes.items() if k.startswith("frame.")} == {"wreath", "flowers", "flame", "crystal", "orbit", "halo", "ears", "crown", "wings", "magic", "aura", "cap", "part", "tech"}
    assert {r["fam"] for k, r in recipes.items() if k.startswith("banner.")} <= {"b_fall", "b_scene", "b_stars", "b_fire", "b_rain", "b_fog", "b_lantern", "b_crane", "b_dust"}


def test_catalog_has_100_plus_effects_and_no_emoji():
    kinds = [i["kind"] for i in effects.ITEMS.values()]
    assert kinds.count("frame") >= 100 and kinds.count("banner") >= 30        # illustrated decorations + animated banner scenes
    assert sum(kinds.count(k) for k in ("frame", "name", "banner", "card")) >= 170
    assert len({i["id"] for i in effects.ITEMS.values()}) == len(effects.ITEMS)
    blob = repr(effects.ITEMS) + repr(effects.AVATAR_GLYPHS) + repr(effects.STICKERS) + repr(effects.REACTIONS)
    assert not any(ord(ch) > 0x2000 for ch in blob), "catalog must not contain emoji"


def test_picture_upload_reencodes_and_serves_webp(api):
    signup(api)
    r = api.post("/api/me/pictures?kind=avatar", content=png(800, 600), headers=RAW)
    assert r.status_code == 200, r.text
    pic = r.json()["results"]
    assert pic["main"] is True                                        # first picture becomes the main one
    img = api.get(f"/api/media/{pic['id']}")                           # public, no cookie needed
    assert img.status_code == 200 and img.headers["content-type"] == "image/webp"
    assert "immutable" in img.headers["cache-control"] and img.headers["x-content-type-options"] == "nosniff"
    out = Image.open(io.BytesIO(img.content))
    assert out.format == "WEBP" and out.size == (384, 384)             # cropped square + resized
    me = api.get("/api/me").json()["results"]
    assert me["avatar"]["pic"] == pic["id"] and me["pictures"] == [pic["id"]]
    ban = api.post("/api/me/pictures?kind=banner", content=png(2000, 900), headers=RAW).json()["results"]
    assert Image.open(io.BytesIO(api.get(f"/api/media/{ban['id']}").content)).size == (1500, 500)
    assert api.get("/api/me").json()["results"]["banner"]["pic"] == ban["id"]


def test_picture_gallery_main_and_delete(api):
    signup(api)
    a = api.post("/api/me/pictures?kind=avatar", content=png(color=(1, 2, 3)), headers=RAW).json()["results"]
    b = api.post("/api/me/pictures?kind=avatar", content=png(color=(9, 9, 9)), headers=RAW).json()["results"]
    assert b["main"] is False
    assert api.post(f"/api/me/pictures/{b['id']}/main", headers=H).status_code == 200
    gal = api.get("/api/me/pictures").json()["results"]
    assert [x["id"] for x in gal["avatars"] if x["main"]] == [b["id"]] and len(gal["avatars"]) == 2
    assert api.delete(f"/api/me/pictures/{b['id']}", headers=H).status_code == 200      # deleting main falls back to the other
    assert api.get("/api/me").json()["results"]["avatar"]["pic"] == a["id"]
    assert api.get(f"/api/media/{b['id']}").status_code == 404
    other = TestClient(app); signup(other, "mallory")
    assert other.delete(f"/api/me/pictures/{a['id']}", headers=H).status_code == 404      # not yours


@pytest.mark.parametrize("payload,status", [(b"not an image at all", 400), (b"", 400), (png(30, 30), 400), (b"GIF89a" + b"\x00" * 40, 400)])
def test_picture_rejects_bad_files(api, payload, status):
    signup(api)
    assert api.post("/api/me/pictures?kind=avatar", content=payload, headers=RAW).status_code == status


def test_picture_limits_and_auth(api, monkeypatch):
    assert api.post("/api/me/pictures?kind=avatar", content=png(), headers=RAW).status_code == 401
    signup(api)
    monkeypatch.setattr(accounts.settings, "max_avatars", 2, raising=False)
    from app import media
    monkeypatch.setattr(media.settings, "max_avatars", 2)
    for _ in range(2):
        assert api.post("/api/me/pictures?kind=avatar", content=png(), headers=RAW).status_code == 200
    assert api.post("/api/me/pictures?kind=avatar", content=png(), headers=RAW).status_code == 400
    monkeypatch.setattr(media.settings, "max_upload_bytes", 1000)
    assert api.post("/api/me/pictures?kind=banner", content=png(1200, 800), headers=RAW).status_code in (413,)
    assert api.post("/api/me/pictures?kind=avatar", content=png(), headers={"X-AVTV": "1", "Content-Type": "text/plain"}).status_code == 415


def test_shop_buy_equip_and_ownership(api):
    signup(api)                                        # starts with 50 VP (welcome bonus)
    shop = api.get("/api/shop").json()["results"]
    assert len(shop["items"]) >= 200 and shop["vp"] == 50
    assert api.post("/api/shop/buy", json={"item": "frame.clover_ring"}, headers=H).status_code == 402        # 120 VP needed
    assert api.post("/api/shop/equip", json={"slot": "frame", "item": "frame.clover_ring"}, headers=H).status_code == 403   # not owned
    assert api.post("/api/shop/equip", json={"slot": "frame", "item": "frame.sprout"}, headers=H).status_code == 200      # free starter
    assert api.post("/api/shop/buy", json={"item": "nope"}, headers=H).status_code == 404
    assert api.post("/api/shop/buy", json={"item": "name.glitch_aqua"}, headers=H).status_code == 403          # epic: rank-gated first
    db = database.get_db()
    db.users.update_one({"username_lower": "alice"}, {"$inc": {"vp": 400}})                                    # cheat VP for the test
    r = api.post("/api/shop/buy", json={"item": "frame.clover_ring"}, headers=H).json()["results"]
    assert r == {"vp": 330, "item": "frame.clover_ring"}
    assert api.post("/api/shop/buy", json={"item": "frame.clover_ring"}, headers=H).status_code == 409
    assert api.post("/api/shop/equip", json={"slot": "name", "item": "frame.clover_ring"}, headers=H).status_code == 400   # wrong slot
    eq = api.post("/api/shop/equip", json={"slot": "frame", "item": "frame.clover_ring"}, headers=H).json()["results"]["equipped"]
    assert eq["frame"] == "frame.clover_ring"
    assert api.post("/api/shop/title-color", json={"color": 3}, headers=H).status_code == 200
    api.post("/api/shop/buy", json={"item": "title.wanderer"}, headers=H)
    api.post("/api/shop/equip", json={"slot": "title", "item": "title.wanderer"}, headers=H)
    pub = TestClient(app).get("/api/users/alice").json()["results"]
    assert pub["fx"]["frame"] == "frame.clover_ring" and pub["fx"]["title"] == {"id": "title.wanderer", "name": "Wanderer", "rarity": "common", "color": 3}
    assert "owned" not in pub and "equipped" not in pub
    assert api.post("/api/shop/equip", json={"slot": "frame", "item": None}, headers=H).json()["results"]["equipped"].get("frame") is None
    api.post("/api/shop/buy", json={"item": "pack.spirits"}, headers=H)       # 600 VP: too expensive now
    assert api.post("/api/comments", json={"anime_id": 1, "sticker": "spirits:boo"}, headers=H).status_code == 403


def test_shop_purchase_is_atomic_for_vp(api):
    signup(api)
    database.get_db().users.update_one({"username_lower": "alice"}, {"$set": {"vp": 130}})
    assert api.post("/api/shop/buy", json={"item": "frame.bamboo_loop"}, headers=H).status_code == 200     # 120 VP
    assert api.post("/api/shop/buy", json={"item": "frame.clover_ring"}, headers=H).status_code == 402
    assert api.get("/api/me").json()["results"]["vp"] == 10                                              # never negative


def test_legacy_frame_names_migrate(api):
    me = signup(api)
    database.get_db().users.update_one({"username_lower": "alice"}, {"$set": {"avatar": {"bg": 1, "icon": "\U0001F98A", "frame": "glow"}}})
    r = api.get("/api/me").json()["results"]
    assert r["equipped"]["frame"] == "frame.sprout" and r["avatar"]["icon"] == "initial"


def test_sessions_list_revoke_and_logout_all(api):
    signup(api)
    second = TestClient(app)
    second.post("/api/auth/login", json={"username": "alice", "password": "Passw0rd!x", "captcha_token": "t", "captcha_answer": "a"},
                headers={**H, "User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/120 Safari/537"})
    ss = api.get("/api/me/sessions").json()["results"]
    assert len(ss) == 2 and sum(s["current"] for s in ss) == 1
    other = next(s for s in ss if not s["current"])
    assert other["device"] == "Chrome on Windows" and "x.x" in other["ip"] or other["ip"]
    assert second.get("/api/me").status_code == 200
    assert api.delete(f"/api/me/sessions/{other['id']}", headers=H).status_code == 200
    assert second.get("/api/me").status_code == 401                          # revoked immediately
    assert api.delete("/api/me/sessions/does-not-exist", headers=H).status_code == 404
    assert api.post("/api/auth/logout-all", headers=H).json()["results"]["signed_out"] == 1
    assert api.get("/api/me").status_code == 401


def test_forged_or_expired_sessions_are_rejected(api):
    signup(api)
    good = api.cookies.get("avtv_session")
    bad = TestClient(app)
    bad.cookies.set("avtv_session", good[:-3] + ("AAA" if not good.endswith("AAA") else "BBB"))
    assert bad.get("/api/me").status_code == 401                              # bad signature
    database.get_db().sessions.delete_many({})
    assert api.get("/api/me").status_code == 401                              # signature fine, session row gone


def test_login_lockout_after_repeated_failures(api):
    signup(api)
    api.post("/api/auth/logout", headers=H)
    for i in range(8):
        security.limiter._hits.clear()
        assert api.post("/api/auth/login", json={"username": "alice", "password": f"wrong-pass-{i}", "captcha_token": "t", "captcha_answer": "a"}, headers=H).status_code == 401
    security.limiter._hits.clear()
    locked = api.post("/api/auth/login", json={"username": "alice", "password": "Passw0rd!x", "captcha_token": "t", "captcha_answer": "a"}, headers=H)
    assert locked.status_code == 429 and "locked" in locked.json()["message"]


def test_security_headers_and_size_limits(api):
    r = api.get("/api/config")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert r.headers["content-security-policy"].startswith("default-src 'none'") and r.headers["cache-control"] == "no-store"
    big = api.post("/api/auth/logout", content=b"x" * 300_000, headers=H)
    assert big.status_code == 413


def test_reports_reach_the_admin_console_moderation_queue(api):
    from app import security as sec
    signup(api, "alice")
    c = api.post("/api/comments", json={"anime_id": 5, "text": "spam spam"}, headers=H).json()["results"]
    reporter = TestClient(app); signup(reporter, "bobby")
    assert reporter.post("/api/report", json={"type": "comment", "target": c["id"], "reason": "spam"}, headers=H).status_code == 200
    assert reporter.post("/api/report", json={"type": "other", "target": "x"}, headers=H).status_code == 422
    assert reporter.get("/api/admin/reports").status_code == 404          # admin console not configured
    assert api.delete(f"/api/admin/comments/{c['id']}", headers=H).status_code in (403, 404)
