"""Veille de bons plans jeux vidéo / consoles / accessoires -> alertes Telegram.

Usage :
  python deal_alert.py          # exécution normale (envoie les alertes)
  python deal_alert.py --test   # vérifie les flux et affiche les matchs, sans rien envoyer
"""
import html
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

import feedparser
import requests

BASE = Path(__file__).parent
CONFIG = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
SEEN_FILE = BASE / "seen.json"
MAX_SEEN = 3000
TEST_MODE = "--test" in sys.argv


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text.lower())


def contains(text: str, term: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(normalize(term))}(?![a-z0-9])", text) is not None


def extract_price(text: str):
    m = re.search(r"(\d{1,5}(?:[.,]\d{1,2})?)\s?(?:€|eur)", text or "", re.I)
    return float(m.group(1).replace(",", ".")) if m else None


def is_match(title: str, summary: str) -> bool:
    text = normalize(f"{title} {summary}")
    if any(contains(text, t) for t in CONFIG["exclude"]):
        return False
    if not any(contains(text, t) for t in CONFIG["keywords"]):
        return False
    max_price = CONFIG.get("max_price")
    price = extract_price(title)
    return not (max_price and price and price > max_price)


def load_seen() -> list:
    return json.loads(SEEN_FILE.read_text()) if SEEN_FILE.exists() else []


def send_telegram(message: str) -> None:
    token, chat_id = os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"]
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": message, "parse_mode": "HTML",
              "disable_web_page_preview": False},
        timeout=20,
    )
    r.raise_for_status()


def main() -> None:
    seen = load_seen()
    seen_set = set(seen)
    first_run = not SEEN_FILE.exists()
    new_ids, alerts = [], []

    for url in CONFIG["feeds"]:
        feed = feedparser.parse(url, agent="Mozilla/5.0 (deal-alert bot)")
        print(f"[{len(feed.entries):>3} entrées] {url}")
        if not feed.entries:
            print("   ⚠️  Flux vide ou invalide : vérifie l'URL dans config.json")
        for e in feed.entries:
            uid = e.get("id") or e.get("link")
            if not uid or uid in seen_set:
                continue
            seen_set.add(uid)
            new_ids.append(uid)
            title = e.get("title", "")
            if is_match(title, e.get("summary", "")):
                alerts.append((title, e.get("link", "")))

    if first_run and not TEST_MODE:
        print(f"1re exécution : {len(new_ids)} deals mémorisés sans alerte (évite le spam).")
    else:
        for title, link in alerts:
            print(f"🎮 {title}")
            if not TEST_MODE:
                send_telegram(f"🎮 <b>{html.escape(title)}</b>\n{link}")

    if not TEST_MODE:
        SEEN_FILE.write_text(json.dumps((seen + new_ids)[-MAX_SEEN:]))
    print(f"{len(alerts)} deal(s) correspondant(s).")


if __name__ == "__main__":
    main()
