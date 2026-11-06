# Adding features later

* **A switch you can flip without redeploying**: add a line to `FLAGS` in `app/flags.py`, call `flags.require(db, "my_flag")` in the endpoint, read `AVTV.flags` in the frontend (CSS class `no-<name>` is added for the built-in four). It shows up in the console under *Features* automatically.
* **A new API endpoint**: create a function in a router (`app/social.py` is a good template), use `require_user(request)`, `throttle(...)`, validate with a pydantic model, then add its first path segment to `ALLOWED` in the frontend `api/proxy.js`.
* **A new page**: add `mypage.html` (copy `recent.html`), it is served at `/mypage` automatically (clean URLs). Add the link to the drawer, keep scripts in files (no inline scripts, the CSP forbids them).
* **New shop items**: add `_deco(...)` / `_ban(...)` lines in `app/effects.py`, run `python tools/gen_effects.py <frontend>/assets/effects.css <frontend>/assets/fx-recipes.js`, add a builder in `decorations.js` / `bannerfx.js` only for brand-new families.
* **New stats in the console**: extend `telemetry.overview()` and render it in `assets/admin.js`.
* **Releasing an update to installed apps**: bump `VERSION` in `sw.js`; users get a reload toast.
* Run `pytest` (backend) before every deploy.
