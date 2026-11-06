# Security guide

No website can honestly be called "unhackable". What this project does is stack many independent defences so one mistake is not enough, and give you a checklist for the parts only you can do.

## What the code already does
* **Backend only talks to your Vercel proxy.** With `PROXY_SECRET` set, every `/api` call without the secret gets a bare 403 (`REQUIRE_PROXY`). Direct internet traffic to Render is rejected. Only `/health` and `/heartbeat` stay public for uptime monitors.
* **Admin console is separate from member accounts**: own login (username + scrypt-hashed password + mandatory TOTP 2FA), own HttpOnly `SameSite=Strict` cookie, CSRF token on every write, 30 min idle / 8 h absolute timeout, 5 wrong attempts lock the source IP for 30 min, one-time codes (no replay), generic error messages, optional IP allow-list, invisible (404) when not configured, full audit log. UI path is `/AnimeVoid` (no `/admin`).
* **Members**: scrypt passwords, common-password blocklist, revocable DB sessions (list + sign out per device / everywhere), account lockout after repeated failures, server-issued single-use captchas, per-IP and per-user rate limits, `__Host-` cookies, CSRF header.
* **Uploads** are fully decoded and re-encoded (metadata stripped, size and pixel limits), served with `nosniff` and a sandbox CSP.
* **Headers/CSP** on both Vercel and Render: no inline scripts, HSTS, frame/embed protection, strict referrer policy, no wildcard CORS, `/docs` hidden in production.
* **Proxy** allow-lists API areas, blocks cross-site writes (`Sec-Fetch-Site`/`Origin`), limits body size, forwards the real client IP/country only with the shared secret.
* **Analytics are anonymous**: random device id, device type, country, installed-app flag. No IP addresses stored.

## What only you can do (checklist)
1. Render env: `SESSION_SECRET` (64 random chars), `PROXY_SECRET`, `MONGODB_URI`, `DISABLE_DOCS=true`, `COOKIE_SECURE=true`; same `PROXY_SECRET` + `BACKEND_URL` on Vercel.
2. `python tools/admin_setup.py` on your computer, then set `ADMIN_USERNAME`, `ADMIN_PASSWORD_HASH`, `ADMIN_TOTP_SECRET` on Render and add the secret to an authenticator app. Optionally `ADMIN_IPS`.
3. MongoDB Atlas: restrict Network Access to Render's outbound IPs (not 0.0.0.0/0 if you can), strong DB user, enable backups.
4. Turn on **2FA for GitHub, Vercel, Render, MongoDB Atlas, Google Cloud and your email**. Most real-world breaches come from these accounts, not from the code.
5. Never commit secrets or `.env`; the Google *client secret* file must never be in the repo (rotate it if it ever was).
6. Keep dependencies updated (`pip list --outdated`, Dependabot), watch the console's **Security** tab for red items and failed logins.
7. Edit `.well-known/security.txt` with your real contact.
