#!/usr/bin/env python3
"""
fetch_data.py — builds data.json for the Project Megatron dashboard.

Each run:
  1. Live quote for the one PUBLIC name (SpaceX / SPCX) from Finnhub.
  2. For every company: general press news + news from the company's OWN website
     (a domain-restricted search), merged. All via Google News RSS — free, no key,
     every item links to its original source = verifiable.
  3. A macro feed of broad market news, one story per topic.
  4. Writes data.json, which index.html reads.

Set your Finnhub key as an environment variable named FINNHUB_KEY.
Free key: https://finnhub.io
"""

import os, json, datetime, urllib.parse, urllib.request, xml.etree.ElementTree as ET

FINNHUB_KEY = os.environ.get("FINNHUB_KEY", "")

# One public company. 'domain' powers the "their own website" search.
PUBLIC = [{"ticker": "SPCX", "name": "SpaceX", "exchange": "Nasdaq",
           "query": "SpaceX", "domain": "spacex.com"}]

# Private companies. 'query' = general press search, 'domain' = their own site.
# Leave domain "" if unknown — that company just skips the own-site search.
PRIVATE = [
    {"name": "OpenAI", "query": "OpenAI", "domain": "openai.com",
     "status": "Filed confidential S-1", "valuation": "~$852B (private, mid-2026)",
     "lastRound": "IPO targeted Q4 2026 / 2027", "source": "https://www.reuters.com/"},
    {"name": "Anthropic", "query": "Anthropic", "domain": "anthropic.com",
     "status": "Filed confidential S-1", "valuation": "~$900B target",
     "lastRound": "Raising ~$30B+; IPO as early as Oct 2026", "source": "https://www.ft.com/"},
    {"name": "Databricks", "query": "Databricks", "domain": "databricks.com",
     "status": "Private", "valuation": "~$134B", "lastRound": "No S-1 filed yet",
     "source": "https://www.reuters.com/"},
    {"name": "Safe Superintelligence (SSI)", "query": "Safe Superintelligence", "domain": "ssi.inc",
     "status": "Private", "valuation": "Verify latest", "lastRound": "Verify latest",
     "source": "https://www.google.com/search?q=Safe+Superintelligence+funding"},
    {"name": "Binance", "query": "Binance", "domain": "binance.com",
     "status": "Private (crypto exchange)", "valuation": "Not publicly listed",
     "lastRound": "No public equity", "source": "https://www.google.com/search?q=Binance+news"},
    {"name": "TikTok / ByteDance", "query": "TikTok ByteDance", "domain": "newsroom.tiktok.com",
     "status": "Private", "valuation": "Verify latest", "lastRound": "Watch US-ownership developments",
     "source": "https://www.google.com/search?q=ByteDance+valuation"},
    {"name": "Altera", "query": "Altera FPGA", "domain": "altera.com",
     "status": "Private", "valuation": "$8.75B (2025 deal)",
     "lastRound": "Silver Lake 51% / Intel 49%, Sep 2025", "source": "https://www.intc.com/"},
    {"name": "Vantage Data Centers (N. America)", "query": "Vantage Data Centers", "domain": "vantage-dc.com",
     "status": "Private", "valuation": "Verify latest", "lastRound": "$10B+ incremental funding (2023)",
     "source": "https://www.google.com/search?q=Vantage+Data+Centers"},
    {"name": "Khazna Data Centers", "query": "Khazna Data Centers", "domain": "khaznadatacenters.com",
     "status": "Private", "valuation": "Verify latest (G42-backed)",
     "lastRound": "$2.62B financing facility (2025)",
     "source": "https://www.datacenterdynamics.com/en/news/khazna-data-centers-bags-26bn-bank-financing/"},
    {"name": "Campus AI", "query": "Campus AI", "domain": "",
     "status": "Private", "valuation": "Verify latest", "lastRound": "Verify latest",
     "source": "https://www.google.com/search?q=Campus+AI+startup"},
]

# Macro: broad news that can move these AI / space / data-center / crypto names.
MACRO_QUERIES = [
    "Federal Reserve interest rate decision",
    "AI chip export controls Nvidia China",
    "AI regulation policy US EU",
    "tech IPO market Nasdaq",
    "AI data center power energy",
    "cryptocurrency regulation SEC",
    "semiconductor industry demand",
]

UA = {"User-Agent": "Mozilla/5.0 (ProjectMegatron/1.0)"}


def get_quote(ticker):
    if not FINNHUB_KEY:
        return None
    url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={FINNHUB_KEY}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
            q = json.load(r)
        if not q.get("c"):
            return None
        return {"price": q.get("c"), "previousClose": q.get("pc"),
                "change": q.get("d"), "changePct": q.get("dp")}
    except Exception as e:
        print("quote error", ticker, e)
        return None


def clean_title(t):
    # Drop a trailing " - Source" / " | Source" that Google appends.
    for sep in (" - ", " | ", " — ", " – "):
        if sep in t:
            head, tail = t.rsplit(sep, 1)
            if 0 < len(tail) <= 45:
                t = head
    return t.strip()


def get_news(query, limit=4):
    """Google News RSS search. De-dupes near-identical headlines within the result."""
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
                date = pub[:10]
            key = title.lower()[:55]
            if not title or key in seen:
                continue
            seen.add(key)
            items.append({"date": date, "headline": title, "source": source, "url": link})
            if len(items) >= limit:
                break
    except Exception as e:
        print("news error", query, e)
    return items


def company_news(query, domain, limit=6):
    """Merge general press with the company's OWN-site results, de-duped."""
    merged, seen = [], set()
    for batch in (get_news(query, 4), get_news(f"site:{domain}", 4) if domain else []):
        for it in batch:
            key = it["headline"].lower()[:55]
            if key in seen:
                continue
            seen.add(key)
            merged.append(it)
    merged.sort(key=lambda x: x.get("date", ""), reverse=True)
    return merged[:limit]


def get_macro(per_topic=1, total=8):
    """One story per topic so the band spans different subjects."""
    seen, out = set(), []
    for q in MACRO_QUERIES:
        kept = 0
        for it in get_news(q, per_topic + 2):
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
                 "price": None, "previousClose": None, "change": None, "changePct": None}
        q = get_quote(c["ticker"])
        if q:
            entry.update(q)
        entry["news"] = company_news(c["query"], c["domain"], 6)
        data["public"].append(entry)

    for c in PRIVATE:
        data["private"].append({
            "name": c["name"], "status": c["status"], "valuation": c["valuation"],
            "lastRound": c["lastRound"], "source": c["source"],
            "news": company_news(c["query"], c["domain"], 6),
        })

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print("Wrote data.json:", len(data["macro"]), "macro,",
          len(data["public"]), "public,", len(data["private"]), "private.")


if __name__ == "__main__":
    main()
