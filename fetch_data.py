#!/usr/bin/env python3
"""
fetch_data.py — builds data.json for the Frontier Watch dashboard.

What it does each run:
  1. Pulls a live quote for the one PUBLIC name (SpaceX / SPCX) from Finnhub.
  2. Pulls recent dated news for every company from Google News RSS
     (free, no key, and every item links to its original source = verifiable).
  3. Writes data.json, which index.html reads.

Set your Finnhub key as an environment variable named FINNHUB_KEY.
Get a free key at https://finnhub.io  (free tier is fine for one ticker).
"""

import os, re, json, datetime, urllib.parse, urllib.request, xml.etree.ElementTree as ET

FINNHUB_KEY = os.environ.get("FINNHUB_KEY", "")

# --- One public company: ticker the live-quote card reads ---
PUBLIC = [{"ticker": "SPCX", "name": "SpaceX", "exchange": "Nasdaq"}]

# --- Private companies: name + a precise news query + a manual valuation/source ---
# Update the "valuation" / "lastRound" / "source" fields by hand when a new round is reported.
PRIVATE = [
    {"name": "OpenAI", "query": "OpenAI IPO OR funding OR valuation",
     "status": "Filed confidential S-1", "valuation": "~$852B (private, mid-2026)",
     "lastRound": "IPO targeted Q4 2026 / 2027", "source": "https://www.reuters.com/"},
    {"name": "Anthropic", "query": "Anthropic IPO OR funding OR valuation",
     "status": "Filed confidential S-1", "valuation": "~$900B target",
     "lastRound": "Raising ~$30B+; IPO as early as Oct 2026", "source": "https://www.ft.com/"},
    {"name": "Databricks", "query": "Databricks funding OR valuation OR IPO",
     "status": "Private", "valuation": "~$134B", "lastRound": "No S-1 filed yet",
     "source": "https://www.reuters.com/"},
    {"name": "Safe Superintelligence (SSI)", "query": "Safe Superintelligence Ilya Sutskever funding",
     "status": "Private", "valuation": "Verify latest", "lastRound": "Verify latest",
     "source": "https://www.google.com/search?q=Safe+Superintelligence+funding"},
    {"name": "Binance", "query": "Binance exchange news",
     "status": "Private (crypto exchange)", "valuation": "Not publicly listed",
     "lastRound": "No public equity", "source": "https://www.google.com/search?q=Binance+news"},
    {"name": "TikTok / ByteDance", "query": "ByteDance TikTok valuation OR ownership",
     "status": "Private", "valuation": "Verify latest", "lastRound": "Watch US-ownership developments",
     "source": "https://www.google.com/search?q=ByteDance+valuation"},
    {"name": "Altera", "query": "Altera FPGA Silver Lake Intel",
     "status": "Private", "valuation": "$8.75B (2025 deal)",
     "lastRound": "Silver Lake 51% / Intel 49%, Sep 2025", "source": "https://www.intc.com/"},
    {"name": "Vantage Data Centers (N. America)", "query": "Vantage Data Centers funding North America",
     "status": "Private", "valuation": "Verify latest", "lastRound": "$10B+ incremental funding (2023)",
     "source": "https://www.google.com/search?q=Vantage+Data+Centers"},
    {"name": "Khazna Data Centers", "query": "Khazna Data Centers funding G42",
     "status": "Private", "valuation": "Verify latest (G42-backed)",
     "lastRound": "$2.62B financing facility (2025)",
     "source": "https://www.datacenterdynamics.com/en/news/khazna-data-centers-bags-26bn-bank-financing/"},
    {"name": "Campus AI", "query": "Campus AI startup funding",
     "status": "Private", "valuation": "Verify latest", "lastRound": "Verify latest",
     "source": "https://www.google.com/search?q=Campus+AI+startup"},
]

# --- Macro: broad news that can move these AI / space / data-center / crypto names ---
# Each query is fetched separately and merged; the dashboard sorts newest-first,
# keeps only the last 72 hours, and shows the top items.
MACRO_QUERIES = [
    "Federal Reserve interest rate decision",
    "AI chip export controls Nvidia China",
    "AI regulation policy US EU",
    "tech IPO market Nasdaq",
    "AI data center power energy",
    "cryptocurrency regulation SEC",
    "semiconductor industry demand",
]

UA = {"User-Agent": "Mozilla/5.0 (FrontierWatch/1.0)"}


def get_quote(ticker):
    """Live quote from Finnhub: current, previous close, change, % change."""
    if not FINNHUB_KEY:
        return None
    url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={FINNHUB_KEY}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
            q = json.load(r)
        if not q.get("c"):
            return None
        return {
            "price": q.get("c"), "previousClose": q.get("pc"),
            "change": q.get("d"), "changePct": q.get("dp"),
            "volume": q.get("v", None),
        }
    except Exception as e:
        print("quote error", ticker, e)
        return None


def clean_title(t):
    """Remove a trailing ' - Source' / ' | Source' that Google appends to titles."""
    t = re.sub(r"\s+[-–—|]\s+[^-–—|]{1,45}$", "", t).strip()
    return t


def _fetch_page(url, timeout=8):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.geturl(), r.read(250000).decode("utf-8", "ignore")


def get_summary(url, max_len=180):
    """Resolve the Google redirect to the real article, then read that page's own
    meta description. Returns (summary, resolved_url). Fails quietly to ('', url)."""
    if not url:
        return "", url
    final, page = url, ""
    try:
        final, page = _fetch_page(url)
    except Exception:
        return "", url

    # If we're still on a Google page, dig the real publisher link out of the HTML.
    if "google.com" in (final or ""):
        m = re.search(r'href="(https?://(?!news\.google|www\.google|google|accounts\.google|policies\.google)[^"]+)"', page)
        if m:
            try:
                final, page = _fetch_page(m.group(1))
            except Exception:
                pass

    summary = ""
    patterns = [
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:description["\']',
    ]
    for p in patterns:
        m = re.search(p, page, re.I)
        if m:
            s = re.sub(r"\s+", " ", m.group(1)).strip()
            for a, b in [("&amp;", "&"), ("&#39;", "'"), ("&quot;", '"'),
                         ("&nbsp;", " "), ("&rsquo;", "’"), ("&ldquo;", "“"), ("&rdquo;", "”")]:
                s = s.replace(a, b)
            summary = (s[:max_len].rsplit(" ", 1)[0] + "…") if len(s) > max_len else s
            break
    return summary, (final if final and "google.com" not in final else url)


def get_news(query, limit=3, with_summary=True):
    """Recent dated news via Google News RSS. Each item links to the original publisher.
    De-dupes near-identical headlines and attaches a one-line publisher summary."""
    q = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    items, seen = [], set()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
            root = ET.fromstring(r.read())
        for it in root.iter("item"):
            title = clean_title((it.findtext("title") or "").strip())
            link = (it.findtext("link") or "").strip()
            pub = (it.findtext("pubDate") or "").strip()
            src_el = it.find("{http://news.google.com}source") or it.find("source")
            source = (src_el.text.strip() if src_el is not None and src_el.text else "Google News")
            try:
                date = datetime.datetime.strptime(pub[:25], "%a, %d %b %Y %H:%M:%S").strftime("%Y-%m-%d")
            except Exception:
                date = pub[:16]
            key = title.lower()[:55]
            if not title or key in seen:
                continue
            seen.add(key)
            summary, resolved = (get_summary(link) if with_summary else ("", link))
            items.append({"date": date, "headline": title, "source": source,
                          "url": resolved or link, "summary": summary})
            if len(items) >= limit:
                break
    except Exception as e:
        print("news error", query, e)
    return items


def get_macro(per_topic=1, total=8):
    """One story per topic so the band spans different subjects, not several takes
    on the same event. Newest-first across topics."""
    seen, out = set(), []
    for q in MACRO_QUERIES:
        kept = 0
        for it in get_news(q, per_topic + 2):   # pull a few, keep the freshest non-dupes
            key = it["headline"].lower()[:55]
            if key in seen:
                continue
            seen.add(key)
            out.append(it)
            kept += 1
            if kept >= per_topic:
                break
    out.sort(key=lambda x: x.get("date", ""), reverse=True)
    return out[:total]


def main():
    data = {"updated": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "macro": [], "public": [], "private": []}

    data["macro"] = get_macro()

    for c in PUBLIC:
        entry = {"ticker": c["ticker"], "name": c["name"], "exchange": c["exchange"],
                 "price": None, "previousClose": None, "change": None,
                 "changePct": None, "volume": None}
        q = get_quote(c["ticker"])
        if q:
            entry.update(q)
        entry["news"] = get_news(c["name"] + " stock OR launch OR Starlink", 5)
        data["public"].append(entry)

    for c in PRIVATE:
        data["private"].append({
            "name": c["name"], "status": c["status"], "valuation": c["valuation"],
            "lastRound": c["lastRound"], "source": c["source"],
            "news": get_news(c["query"], 5),
        })

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print("Wrote data.json:", len(data["macro"]), "macro,",
          len(data["public"]), "public,", len(data["private"]), "private.")


if __name__ == "__main__":
    main()
