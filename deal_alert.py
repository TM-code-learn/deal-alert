"""Veille de bons plans jeux vidéo : site web (docs/) + alertes Telegram.

Usage :
  python deal_alert.py          # exécution normale
  python deal_alert.py --test   # vérifie les flux sans rien envoyer ni écrire
"""
import html
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import feedparser
import requests

BASE = Path(__file__).parent
CONFIG = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
SEEN_FILE = BASE / "seen.json"
DEALS_FILE = BASE / "docs" / "deals.json"
MAX_SEEN = 5000
MAX_ALERTS_PER_RUN = 15
TEST_MODE = "--test" in sys.argv
NOW = datetime.now(timezone.utc)

CATEGORY_RULES = [
    ("PlayStation", ["ps5", "ps4", "playstation", "psn", "dualsense", "ps vr2", "ps portal", "ps plus"]),
    ("Xbox", ["xbox", "game pass", "series x", "series s"]),
    ("Nintendo", ["switch", "nintendo", "eshop", "joy-con", "amiibo"]),
    ("Accessoires", ["manette", "casque", "clavier", "souris", "tapis", "ecran", "headset", "volant",
                     "carte micro sd", "chargeur", "support", "sac", "housse"]),
    ("PC", ["steam", "pc", "epic games", "gog", "ubisoft connect", "ea app", "steam deck",
            "rog ally", "legion go", "carte graphique", "rtx", "radeon"]),
]
FEED_CATEGORY = {"playstation": "PlayStation", "xbox": "Xbox", "nintendo": "Nintendo",
                 "nintendo-switch": "Nintendo", "jeux-pc": "PC", "accessoires-gaming": "Accessoires"}
PC_MERCHANTS = {"steam", "epic games", "gog", "fanatical", "kinguin", "instant gaming", "humble bundle",
                "gamesplanet", "ubisoft store", "ea"}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text.lower())


def contains(text: str, term: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(normalize(term))}(?![a-z0-9])", text) is not None


def any_term(text: str, terms) -> bool:
    return any(contains(text, t) for t in terms)


def parse_price(raw: str):
    if not raw:
        return None
    if "gratuit" in raw.lower():
        return 0.0
    m = re.search(r"(\d[\d\s]*(?:[.,]\d{1,2})?)", raw)
    return float(re.sub(r"\s", "", m.group(1)).replace(",", ".")) if m else None


def feed_slug(url: str) -> str:
    m = re.search(r"/groupe/([^/?#]+)", url)
    return m.group(1) if m else ""


def categorize(text: str, merchant: str, slug: str) -> str:
    if slug in FEED_CATEGORY and slug != "accessoires-gaming":
        return FEED_CATEGORY[slug]
    for cat, terms in CATEGORY_RULES:
        if any_term(text, terms):
            return cat
    if normalize(merchant) in PC_MERCHANTS:
        return "PC"
    return FEED_CATEGORY.get(slug, "Autres")


def big_image(url: str) -> str:
    return re.sub(r"/re/\d+x\d+/", "/re/300x300/", url or "")


def entry_to_deal(e, slug: str) -> dict:
    title = e.get("title", "")
    tag = re.search(r"<pepper:merchant\b[^>]*>", e.get("_raw", ""))
    tag = tag.group(0) if tag else ""
    name_m, price_m = re.search(r'name="([^"]*)"', tag), re.search(r'price="([^"]*)"', tag)
    merchant = html.unescape(name_m.group(1)) if name_m else ""
    price_raw = html.unescape(price_m.group(1)) if price_m else ""
    image = ""
    if e.get("media_content"):
        image = e["media_content"][0].get("url", "")
    elif e.get("media_thumbnail"):
        image = e["media_thumbnail"][0].get("url", "")
    try:
        published = parsedate_to_datetime(e.get("published", "")).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        published = NOW.isoformat()
    text = normalize(f"{title} {e.get('summary', '')}")
    return {
        "id": e.get("id") or e.get("link"),
        "title": title,
        "link": e.get("link", ""),
        "merchant": merchant or "Autre",
        "price_label": price_raw,
        "price": parse_price(price_raw),
        "image": big_image(image),
        "category": categorize(text, merchant, slug),
        "published": published,
        "_text": text,
    }



def load_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def send_telegram(message: str) -> None:
    token, chat_id = os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"]
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
        timeout=20,
    )
    r.raise_for_status()


def main() -> None:
    seen = load_json(SEEN_FILE, [])
    seen_set = set(seen)
    site = load_json(DEALS_FILE, {"deals": []})
    deals = {d["id"]: d for d in site["deals"]}
    first_run = not SEEN_FILE.exists() or not DEALS_FILE.exists()
    new_ids, alerts = [], []
    max_price = CONFIG.get("max_price")

    feeds = [(u, True) for u in CONFIG["theme_feeds"]] + [(u, False) for u in CONFIG["general_feeds"]]
    for url, is_theme in feeds:
        slug = feed_slug(url)
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (deal-alert bot)"}, timeout=30)
        raw_items = {}
        for item in (re.findall(r"<item>(.*?)</item>", r.text, re.S) if r.ok else []):
            g = re.search(r"<guid[^>]*>(.*?)</guid>", item, re.S)
            if g:
                raw_items[html.unescape(g.group(1).strip())] = item
        feed = feedparser.parse(r.content if r.ok else b"")
        print(f"[{len(feed.entries):>3} entrées] {url}")
        if not feed.entries:
            print("   ⚠️  Flux vide ou invalide : vérifie l'URL dans config.json")
        for e in feed.entries:
            e["_raw"] = raw_items.get(e.get("id", ""), "")
            deal = entry_to_deal(e, slug)
            uid, text = deal["id"], deal.pop("_text")
            if not uid or any_term(text, CONFIG["exclude"]):
                continue
            if not is_theme and not any_term(text, CONFIG["keywords"]):
                continue
            if max_price and deal["price"] and deal["price"] > max_price:
                continue
            if uid not in deals:
                deal["first_seen"] = NOW.isoformat()
                deals[uid] = deal
            if uid not in seen_set:
                seen_set.add(uid)
                new_ids.append(uid)
                if any_term(text, CONFIG["alert_keywords"]):
                    alerts.append(deal)

    cutoff = (NOW - timedelta(days=CONFIG.get("site_days_kept", 45))).isoformat()
    kept = sorted((d for d in deals.values() if d["first_seen"] >= cutoff),
                  key=lambda d: d["published"], reverse=True)[:2000]
    print(f"Site : {len(kept)} deals. Nouveaux : {len(new_ids)}. Alertes : {len(alerts)}.")

    if TEST_MODE:
        for d in alerts[:20]:
            print(f"🎮 [{d['category']}] {d['merchant']} {d['price_label']} {d['title']}")
        return

    if first_run:
        print("1re exécution : deals mémorisés sans alerte Telegram (évite le spam).")
    elif CONFIG.get("telegram_enabled", True):
        for d in alerts[:MAX_ALERTS_PER_RUN]:
            price = f" — <b>{html.escape(d['price_label'])}</b>" if d["price_label"] else ""
            send_telegram(f"🎮 <b>{html.escape(d['title'])}</b>\n{html.escape(d['merchant'])}{price}\n{d['link']}")

    DEALS_FILE.parent.mkdir(exist_ok=True)
    DEALS_FILE.write_text(json.dumps({"updated": NOW.isoformat(), "deals": kept}, ensure_ascii=False),
                          encoding="utf-8")
    SEEN_FILE.write_text(json.dumps((seen + new_ids)[-MAX_SEEN:]))


if __name__ == "__main__":
    main()
