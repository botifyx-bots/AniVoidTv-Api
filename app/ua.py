"""Tiny user-agent classifier (platform / browser / device kind). No third-party deps."""

BOTS = ("bot", "crawl", "spider", "slurp", "preview", "headless", "curl/", "wget", "python-requests", "monitor", "uptime", "lighthouse", "facebookexternalhit")


def parse_ua(ua: str) -> dict:
    u = ua or ""
    low = u.lower()
    if not u or any(b in low for b in BOTS):
        return {"bot": True, "os": "Bot", "browser": "Bot", "kind": "bot"}
    os_ = next((n for k, n in (("Android", "Android"), ("iPhone", "iOS"), ("iPad", "iPadOS"), ("CrOS", "ChromeOS"), ("Windows", "Windows"), ("Mac OS", "macOS"), ("Linux", "Linux")) if k in u), "Other")
    browser = next((n for k, n in (("SamsungBrowser/", "Samsung Internet"), ("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"), ("CriOS/", "Chrome"), ("Safari/", "Safari")) if k in u), "Other")
    if os_ == "iPadOS" or ("Android" in u and "Mobile" not in u):
        kind = "tablet"
    elif os_ in ("Android", "iOS") or "Mobile" in u:
        kind = "mobile"
    else:
        kind = "desktop"
    return {"bot": False, "os": os_, "browser": browser, "kind": kind}
