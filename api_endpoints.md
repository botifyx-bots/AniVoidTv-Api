# AniVoid API: Endpoints & Frontend Integration Guide

Base URL (replace with yours):

```
Local:   http://localhost:8000
Render:  https://<your-service>.onrender.com
```

Interactive docs (Swagger UI) are always available at `/docs`.

> The JSON samples below are **illustrative**: ids, titles and posters are placeholders, only the shapes are exact.

---

## 1. Conventions

| Topic | Behaviour |
|---|---|
| Success | `{ "success": true, "results": ... }` |
| Error | `{ "success": false, "message": "..." }` |
| `id` | Always the **official AniKoto id** (the same `id` the official `anikotoapi.site/series/{id}` endpoint expects) |
| Credits | No creator/credit fields in any response |
| CORS | Controlled by the `CORS_ORIGINS` env var (`*` by default). Set it to your frontend domain in production |
| Caching | Search 5 min, schedule 10 min, top-ten 10 min (server side, configurable). `completed`/`upcoming` come from JSON files rebuilt weekly |

### Status codes

| Code | Meaning |
|---|---|
| 200 | OK |
| 400 | Missing/invalid `keyword` or `date` |
| 401 | Wrong `X-Admin-Token` (admin route only) |
| 422 | Invalid `page` / `per_page` (e.g. `per_page=500`, `page=0`). FastAPI returns `{ "detail": [...] }` here |
| 502 | The source site could not be reached/scraped (and no local fallback available) |
| 503 | `completed.json` / `upcoming.json` not built yet (first crawl still running) |

### Optional response header

`X-Data-Source: local-catalog`: sent by `/api/search` and `/api/random` when the source site was unreachable and the answer came from the local catalog instead. The shape is identical, so the frontend needs no special handling.

---

## 2. Endpoints

### 2.1 `GET /api/search`

Search anime by keyword.

| Param | Type | Required | Notes |
|---|---|---|---|
| `keyword` | string | yes | max 200 chars |
| `page` | int | no | default `1`, 30 results per page |

```
GET /api/search?keyword=solo+leveling&page=1
```

```json
{
  "success": true,
  "results": {
    "totalPages": 1,
    "data": [
      { "id": 6224, "poster": "https://cdn.anipixcdn.co/thumbnail/53adb...png", "title": "Solo Leveling" },
      { "id": 7457, "poster": "https://cdn.anipixcdn.co/thumbnail/4b5ed...jpg", "title": "Solo Leveling Season 2: Arise from the Shadow" }
    ],
    "pagination": {
      "currentPage": 1, "totalPages": 1, "totalItems": 2,
      "itemsPerPage": 30, "hasNext": false, "hasPrev": false
    }
  }
}
```

Errors: `400 {"success":false,"message":"Keyword is required"}`

---

### 2.2 `GET /api/schedule`

Anime airing on a given date.

| Param | Type | Required | Notes |
|---|---|---|---|
| `date` | string | yes | `YYYY-MM-DD` |

```
GET /api/schedule?date=2026-10-24
```

```json
{
  "success": true,
  "results": [
    {
      "slug": "a-wild-last-boss-appeared-season-2",
      "id": 9029,
      "title": "A Wild Last Boss Appeared! Season 2",
      "japaneseTitle": "Yasei no Last Boss ga Arawareta! 2nd Season",
      "poster": "https://cdn.anipixcdn.co/thumbnail/d2c40...jpg",
      "time": "10:00",
      "episode_no": 6
    }
  ]
}
```

Notes for the frontend:
- `id` and `poster` are matched by title. If a show can't be matched, `id` is `null` and `poster` is `""`. Render a placeholder image and don't make that card clickable.
- `time` is passed through as the source site provides it (a plain string). Display it as-is.
- `slug` here is generated from the title, so **don't use it for routing**; use `id`.
- An empty day returns `"results": []`.

Errors: `400` for a missing or malformed date.

---

### 2.3 `GET /api/random`

One random anime. No params. Don't cache this on the frontend.

```json
{
  "success": true,
  "results": {
    "id": 2008,
    "title": "Air: The Movie",
    "poster": "https://cdn.anipixcdn.co/thumbnail/57baf...jpg",
    "type": "Movie"
  }
}
```

---

### 2.4 `GET /api/top-ten`

Top 10 lists for today, this week and this month. No params.

```json
{
  "success": true,
  "results": {
    "today": [
      { "id": 9101, "title": "Wistoria: Wand and Sword Season 2", "rank": 1, "poster": "https://cdn.anipixcdn.co/thumbnail/4739d...jpg" }
    ],
    "week":  [ { "id": 1,    "title": "One Piece", "rank": 1, "poster": "https://..." } ],
    "month": [ { "id": 1,    "title": "One Piece", "rank": 1, "poster": "https://..." } ]
  }
}
```

Notes:
- Each list is ordered by `rank` (1 to 10).
- A list can be empty, and `id` can be `null` for a brand-new title not yet in the catalog (rare; it fixes itself after the next catalog top-up). Guard for it.

---

### 2.5 `GET /api/completed`  and  `GET /api/upcoming`

Paginated lists served from `completed.json` (status *Finished Airing*) and `upcoming.json` (status *Not yet aired*). Rebuilt every Sunday.

| Param | Type | Default | Notes |
|---|---|---|---|
| `page` | int | `1` | `>= 1` |
| `per_page` | int | `20` | `1`–`100` |

```
GET /api/completed?page=1&per_page=24
GET /api/upcoming?page=2&per_page=24
```

```json
{
  "success": true,
  "results": {
    "updated_at": "2026-10-25T00:03:41Z",
    "data": [
      {
        "id": 1234,
        "title": "Example Anime",
        "alternative": "Example Alt Title",
        "titles": "",
        "native": "例",
        "slug": "example-anime-abc12",
        "rating": "PG-13",
        "poster": "https://cdn.anipixcdn.co/thumbnail/...jpg",
        "is_sub": 12,
        "description": "…",
        "aired": "Jan 5, 2024 to Mar 22, 2024",
        "season": "winter",
        "year": 2024,
        "duration": "24 min",
        "status": "Finished Airing",
        "score": "7.56",
        "mal_id": "12345",
        "episodes": "12",
        "ani_id": "67890",
        "source": "manga",
        "s_id": 111111,
        "background_image": "https://...",
        "updated_at": "2026-10-24 13:45:49",
        "next_air_schedule_time": null,
        "next_air_ep": null,
        "terms_by_type": {
          "genre": ["Action", "Fantasy"],
          "producers": ["..."],
          "studios": ["..."],
          "type": ["TV"]
        }
      }
    ],
    "pagination": {
      "currentPage": 1, "totalPages": 120, "totalItems": 2400,
      "itemsPerPage": 20, "hasNext": true, "hasPrev": false
    }
  }
}
```

Each item is the full row from the official `recent-anime` API (same field names), so anything you used from the official list works here too. `503` is returned until the first crawl has produced the files.

---

### 2.6 Utility endpoints

| Endpoint | Purpose |
|---|---|
| `GET` / `HEAD /heartbeat` (alias `/health`) | Keep-alive for UptimeRobot, returns `{"ok":true,"status":"alive","time":"..."}` |
| `GET /api/status` | Last crawl info, next scheduled crawl, catalog size, file sizes |
| `POST /api/admin/refresh` | Start a crawl now. Header `X-Admin-Token: <ADMIN_TOKEN>`. Returns `202` |
| `GET /` | Lists the endpoints |

Don't call `/api/admin/refresh` from the browser; it needs the secret token.

---

## 3. Episodes & streams (official API, not ours)

Our API gives you lists and ids. For **episodes and embed links** use the official endpoint with the same `id`:

```
GET https://anikotoapi.site/series/{id}
-> { anime: {...}, episodes: [ { ..., embed_url: { sub, dub } } ] }
```

Limit: 60 requests per IP per 120 s. If you call it from the browser, that limit applies to **each visitor's IP** (fine). If you call it from your own server, cache results.

---

## 4. Frontend integration examples

### 4.1 Tiny API client (works in any JS/TS frontend)

```js
// api.js
const BASE = import.meta.env?.VITE_API_BASE ?? process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

async function request(path, params = {}, { signal } = {}) {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
  ).toString();
  const res = await fetch(`${BASE}${path}${qs ? `?${qs}` : ""}`, { signal });
  const body = await res.json().catch(() => ({}));
  if (!res.ok || body.success === false) {
    const err = new Error(body.message || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return body.results;
}

export const api = {
  search:    (keyword, page = 1, opts) => request("/api/search", { keyword, page }, opts),
  schedule:  (date, opts)              => request("/api/schedule", { date }, opts),
  random:    (opts)                    => request("/api/random", {}, opts),
  topTen:    (opts)                    => request("/api/top-ten", {}, opts),
  completed: (page = 1, per_page = 24) => request("/api/completed", { page, per_page }),
  upcoming:  (page = 1, per_page = 24) => request("/api/upcoming", { page, per_page }),
};
```

`.env` for the frontend:

```
VITE_API_BASE=https://<your-service>.onrender.com        # Vite
NEXT_PUBLIC_API_BASE=https://<your-service>.onrender.com # Next.js
```

### 4.2 Search box with debounce (React)

```jsx
import { useEffect, useState } from "react";
import { api } from "./api";

export function SearchBox() {
  const [q, setQ] = useState("");
  const [items, setItems] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (q.trim().length < 2) return setItems([]);
    const ctrl = new AbortController();
    const t = setTimeout(async () => {
      try {
        const res = await api.search(q.trim(), 1, { signal: ctrl.signal });
        setItems(res.data);
        setError(null);
      } catch (e) {
        if (e.name !== "AbortError") setError(e.message);
      }
    }, 400);                       // debounce
    return () => { clearTimeout(t); ctrl.abort(); };
  }, [q]);

  return (
    <div>
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search anime…" />
      {error && <p>{error}</p>}
      <ul>
        {items.map((a) => (
          <li key={a.id}>
            <a href={`/anime/${a.id}`}><img src={a.poster} alt="" width="48" /> {a.title}</a>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

### 4.3 Top-ten tabs (Today / Week / Month)

```jsx
import { useEffect, useState } from "react";
import { api } from "./api";

export function TopTen() {
  const [data, setData] = useState(null);
  const [tab, setTab] = useState("today");

  useEffect(() => { api.topTen().then(setData).catch(console.error); }, []);
  if (!data) return <p>Loading…</p>;

  return (
    <section>
      {["today", "week", "month"].map((t) => (
        <button key={t} onClick={() => setTab(t)} disabled={tab === t}>{t}</button>
      ))}
      <ol>
        {data[tab].map((a) => (
          <li key={a.rank}>
            <span>#{a.rank}</span>
            {a.id ? <a href={`/anime/${a.id}`}>{a.title}</a> : <span>{a.title}</span>} {/* id can be null */}
            <img src={a.poster} alt="" width="40" />
          </li>
        ))}
      </ol>
    </section>
  );
}
```

### 4.4 Schedule day picker

```jsx
import { useEffect, useState } from "react";
import { api } from "./api";

const fmt = (d) => d.toISOString().slice(0, 10);              // YYYY-MM-DD
const FALLBACK = "/placeholder-poster.png";

export function Schedule() {
  const [date, setDate] = useState(fmt(new Date()));
  const [items, setItems] = useState([]);

  useEffect(() => { api.schedule(date).then(setItems).catch(() => setItems([])); }, [date]);

  return (
    <section>
      <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
      {items.length === 0 && <p>Nothing scheduled.</p>}
      {items.map((a) => {
        const card = (
          <>
            <img src={a.poster || FALLBACK} alt="" width="64" />
            <b>{a.title}</b> • EP {a.episode_no} • {a.time}
          </>
        );
        return a.id
          ? <a key={a.slug + a.time} href={`/anime/${a.id}`}>{card}</a>
          : <div key={a.slug + a.time}>{card}</div>;      // unmatched show: not clickable
      })}
    </section>
  );
}
```

`toISOString()` uses UTC; if you want the visitor's local date, build the string from `getFullYear()/getMonth()/getDate()` instead.

### 4.5 "Random anime" button

```jsx
import { api } from "./api";

export function RandomButton() {
  const go = async () => {
    const a = await api.random();
    window.location.href = `/anime/${a.id}`;
  };
  return <button onClick={go}>🎲 Random anime</button>;
}
```

### 4.6 Completed / Upcoming grid with "Load more"

```jsx
import { useEffect, useState } from "react";
import { api } from "./api";

export function AnimeGrid({ kind = "completed" }) {      // "completed" | "upcoming"
  const [items, setItems] = useState([]);
  const [page, setPage] = useState(1);
  const [hasNext, setHasNext] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    api[kind](page, 24)
      .then((r) => { setItems((prev) => (page === 1 ? r.data : [...prev, ...r.data])); setHasNext(r.pagination.hasNext); })
      .catch((e) => setError(e.status === 503 ? "Data is being prepared, try again in a few minutes." : e.message));
  }, [kind, page]);

  return (
    <>
      {error && <p>{error}</p>}
      <div className="grid">
        {items.map((a) => (
          <a key={a.id} href={`/anime/${a.id}`}>
            <img src={a.poster} alt="" /><span>{a.title}</span>
            <small>{a.terms_by_type?.genre?.join(", ")} • ⭐ {a.score}</small>
          </a>
        ))}
      </div>
      {hasNext && <button onClick={() => setPage((p) => p + 1)}>Load more</button>}
    </>
  );
}
```

### 4.7 Anime detail page: our `id` → official `/series/{id}`

```js
// /anime/[id]: fetch details + episodes from the official API using the id we returned
export async function getSeries(id) {
  const res = await fetch(`https://anikotoapi.site/series/${id}`);
  if (!res.ok) throw new Error("Series not found");
  const { anime, episodes } = await res.json();
  return { anime, episodes };   // episode.embed_url.sub / .dub when available
}
```

### 4.8 Next.js (server-side fetching with revalidation)

```js
// app/page.js (App Router)
const BASE = process.env.NEXT_PUBLIC_API_BASE;

export default async function Home() {
  const res = await fetch(`${BASE}/api/top-ten`, { next: { revalidate: 600 } }); // 10 min
  const { results } = await res.json();
  return <pre>{JSON.stringify(results.today.slice(0, 3), null, 2)}</pre>;
}
```

### 4.9 Plain `fetch` / `curl` quick tests

```bash
curl "https://<your-service>.onrender.com/api/search?keyword=naruto"
curl "https://<your-service>.onrender.com/api/schedule?date=2026-10-24"
curl "https://<your-service>.onrender.com/api/completed?page=1&per_page=5"
curl -I "https://<your-service>.onrender.com/heartbeat"
```

---

## 5. Integration checklist

- [ ] Set `CORS_ORIGINS` on the server to your frontend domain(s).
- [ ] Route detail pages by **`id`** (`/anime/:id`), never by slug.
- [ ] Guard `id: null` (top-ten, schedule) and empty `poster` (schedule): show a placeholder, no link.
- [ ] Handle `503` on completed/upcoming (first crawl still running) and `502` on scraped endpoints (source site down).
- [ ] Debounce search input (300–500 ms) and cancel stale requests.
- [ ] Free Render instances sleep when idle: the first request after a sleep can take ~30–60 s. Keep it awake with an UptimeRobot monitor on `/heartbeat`, and show a loading state in the UI.
- [ ] Episodes and embed links come from the official `GET https://anikotoapi.site/series/{id}` (60 requests / IP / 120 s).

---

## 6. Accounts, profiles & community (v2)

All of these need the header **`X-AVTV: 1`** on `POST/PUT/PATCH/DELETE` and use the HttpOnly session cookie (`__Host-avtv_session`). From the browser call them through the Vercel proxy: `AVTV.api("/me")` in `assets/site.js` → `/api/v1/me`.
Errors keep `{ "success": false, "message": "..." }`. Validation errors: `422 { "success": false, "message": "Invalid input: ...", "detail": [...] }`. `401` carries `"auth_required": true`; failed captchas carry `"captcha_failed": true`. Every response has `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` and (API paths) a locked-down CSP.

### Auth & sessions
| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /api/config` | – | `{accounts, google_client_id}` |
| `GET /api/auth/captcha` | – | `{token, image}` (SVG data-URI, single-use, 5 min) |
| `POST /api/auth/register` | – | `{username, password, confirm?, captcha_token, captcha_answer}` |
| `POST /api/auth/login` | – | `{username or email, password, captcha_token, captcha_answer}`; 8 wrong passwords lock that account for 15 min |
| `POST /api/auth/google` · `/api/auth/google/complete` | – | Google ID-token login (`{credential}` → `ok` or `need_username` + `ticket`) |
| `POST /api/auth/logout` · `POST /api/auth/logout-all` | – / ✔ | end this session / every session |
| `GET /api/me/sessions` · `DELETE /api/me/sessions/{id}` | ✔ | list devices (browser, OS, masked IP, last seen) / revoke one |

### Profile
| Endpoint | Purpose |
|---|---|
| `GET /api/me` | full private profile (shape below) |
| `PATCH /api/me` | any of `display_name` (2-24 chars, empty = use username), `bio` (plain text, no links), `avatar {bg 0-11, icon}`, `banner {preset: "p1".."p8"}`, `accent`, `favorites[]` (max 10), `privacy {show_list}` |
| `POST /api/me/password` · `POST /api/me/username` | `{current,new}` (signs out other devices) · `{username,password}` once per 30 days |
| `POST /api/me/checkin` · `GET /api/me/vp` | daily VP + streak · last 50 VP transactions (shop purchases are negative) |
| `GET /api/users/{username}` · `/list?status=` | public profile (no email/id; `stats.list_counts` is `null` if the list is private) |

`name` is what people see (display name or username); `username` is the unique @handle used for login and links.

### Pictures & banners
Raw bytes in the body, `Content-Type: application/octet-stream` (the site crops/resizes in the browser first). Server validates, re-encodes to WebP (avatar 384×384, banner 1500×500), strips metadata.
| Endpoint | Purpose |
|---|---|
| `POST /api/me/pictures?kind=avatar\|banner` | upload → `{id, kind, main, bytes}`; the first one of each kind becomes main. Limits: 30 avatars, 12 banners, 2.5 MB per upload, 40 MB total (env-tunable) |
| `GET /api/me/pictures` | `{avatars:[{id,main}], banners:[…], limits}` |
| `POST /api/me/pictures/{id}/main` · `DELETE /api/me/pictures/{id}` | set main / delete (main falls back to the newest remaining) |
| `GET /api/media/{id}` | public image, `Cache-Control: public, max-age=31536000, immutable` |

### Void Shop (cosmetics, 100+ effects)
`GET /api/shop` → `{vp, rank, rank_names, items[], equipped, stickers, reactions, title_colors}`. Item: `{id, kind, name, rarity, price, min_rank, owned, rank_ok, free, unlock_rank}`.
Kinds: `frame` (37 avatar effects), `name` (28 name effects), `banner` (20 animated banner overlays), `card` (16 comment/profile card styles), `title` (34), `pack` (5 sticker packs). Rarity sets the price (120 / 320 / 700 / 1500 / 3200 VP) and the minimum rank for rare+. Price-0 items unlock automatically at their rank.
| Endpoint | Purpose |
|---|---|
| `POST /api/shop/buy` | `{item}` → atomic purchase; `402` not enough VP, `403` rank too low, `409` already yours |
| `POST /api/shop/equip` | `{slot: frame\|name\|banner\|card\|title, item: id\|null}` |
| `POST /api/shop/title-color` | `{color: 0-19\|null}` |

The frontend draws `frame.*` and `banner.*` items from recipes (`assets/fx-recipes.js`, generated by `tools/gen_effects.py`) with `assets/decorations.js` / `assets/bannerfx.js`; `name.*` and `card.*` items are CSS classes (`fx-name-grad_ember`) in the generated `assets/effects.css`.

### Comments, reactions, stickers
| Endpoint | Purpose |
|---|---|
| `GET /api/comments?anime_id=&page=&sort=new\|top` · `GET /api/comments/{id}/replies` | public; `my_reaction`/`mine` filled when signed in |
| `POST /api/comments` | `{anime_id, text (0-1000), sticker?: "pack:id", parent_id?}`: needs text or a sticker; premium packs must be owned (`403`) |
| `POST /api/comments/{id}/react` | `{key: like\|love\|haha\|wow\|sad\|angry\|fire\|clap\|null}`, one reaction per user (switching replaces) |
| `DELETE /api/comments/{id}` | own comments |
| `POST /api/report` | `{type: comment\|media\|user, target, reason}` |

Comment shape: `{id, anime_id, parent_id, text, sticker, created_at, user:{username, name, avatar:{bg,icon,pic}, fx:{frame,name,card,banner,title:{id,name,rarity,color}}, rank}, reactions:{love:2}, my_reaction, reply_count, mine}`.
Sticker packs: `blobs`, `words` (free), `spirits` 600 VP, `sparks` 800 VP, `critters` 1000 VP, 8 stickers each (`app/effects.py` ⇄ `assets/stickers.js`).

### Lists, continue watching, watch stats
Unchanged from v1: `/api/list…`, `/api/continue…`, `/api/continue/merge`, `POST /api/watch/complete`.

### Moderation (token, not cookies)
Header `X-Admin-Token: <ADMIN_TOKEN>`: `GET /api/admin/reports`, `DELETE /api/admin/comments/{id}`, `DELETE /api/admin/media/{id}`, `POST /api/admin/users/{username}/ban?unban=false`. Not reachable through the Vercel proxy by design.

### `GET /api/me` (abridged)
```json
{ "success": true, "results": {
  "id": "…", "username": "alice", "name": "Alice in Wonderland", "display_name": "Alice in Wonderland", "bio": "", "joined": "…",
  "avatar": { "bg": 3, "icon": "fox", "pic": "66ab…" }, "banner": { "pic": null, "preset": "p4" }, "accent": 0,
  "fx": { "frame": "frame.ivy_wreath", "name": null, "card": null, "banner": "banner.sakura_drift", "title": { "id": "title.wanderer", "name": "Wanderer", "rarity": "common", "color": 3 } },
  "equipped": { "frame": "frame.ivy_wreath", "title": "title.wanderer", "title_color": 3 }, "owned": ["frame.clover_ring"], "packs": ["blobs", "words"],
  "vp": 62, "streak": 1, "rank": { "index": 0, "title": "Newcomer", "next_title": "Void Initiate", "next_at": 500, "progress": 12.4, "ladder": [] },
  "stats": { "episodes": 1, "hours": 0.4, "comments": 2, "list_total": 3, "list_counts": { "watching": 1, "completed": 1, "on_hold": 0, "dropped": 0, "plan_to_watch": 1 }, "pics": 1, "owned": 1 },
  "badges": [ { "id": "first_steps", "icon": "footprints", "name": "First Steps", "desc": "Create your account", "earned": true } ],
  "favorites": [], "privacy": { "show_list": true }, "pictures": ["66ab…"],
  "has_password": true, "google_linked": false, "email": null, "checked_in_today": true
} }
```
Badge/avatar `icon` values are icon **keys** (drawn by the frontend as vector icons), never emoji.


---

## 7. Site config, telemetry and the admin console (new)

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /api/config` | public | adds `flags`: `registration_enabled`, `comments_enabled`, `uploads_enabled`, `shop_enabled`, `maintenance {on,message}`, `announcement {on,text,level}` |
| `POST /api/t/ping` | public | anonymous analytics `{d: device id, t: "view"\|"beat", p: path, s: installed-app bool}` |
| `POST /api/admin/login` | – | `{username, password, otp}` -> sets admin cookie, returns CSRF token (404 if admin is not configured) |
| `POST /api/admin/logout`, `GET /api/admin/me` | admin | session |
| `GET /api/admin/overview`, `/timeseries?days=`, `/devices?filter=&page=` | admin | live devices, platforms, browsers, countries, installed apps, traffic |
| `GET /api/admin/users?q=`, `POST /api/admin/users/{u}/ban\|unban\|signout\|vp` | admin (+CSRF) | member management |
| `GET /api/admin/reports`, `POST /reports/{id}/resolve`, `DELETE /comments/{id}`, `DELETE /media/{id}` | admin | moderation |
| `GET/PUT /api/admin/flags` | admin | feature switches + announcement |
| `GET /api/admin/audit`, `/security`, `/system`, `POST /sessions/revoke-all`, `POST /crawl` | admin | audit log, hardening checklist, system |
All writes need `X-AVTV: 1` and (admin) `X-Admin-CSRF`. Maintenance mode answers member writes with `503 {maintenance: true}`.
