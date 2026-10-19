# c:/Users/Kacper/Desktop/skrypt/config.py
# python / config.py / cpython 3.12 / x64 / windows
"""
Uniwersalna konfiguracja monitora okazji dla dowolnych przedmiotow
na platformach: OLX, Vinted, Allegro Lokalnie oraz Allegro.
Zawiera mapowanie kategorii, opcje dostawy (Przesylka OLX) oraz lokalizacji i promienia km.
"""

import json
import os
from typing import Dict, Any, List

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
SEEN_FILE = os.path.join(BASE_DIR, "seen_offers.json")

CATEGORIES_MAP: Dict[str, int] = {
    "Wszystkie kategorie (Uniwersalne)": 0,
    "Elektronika (Ogólna)": 99,
    "Komputery i Laptopy": 443,
    "Karty graficzne": 2184,
    "Telefony i Smartfony": 1461,
    "Gry i Konsole": 93,
    "Moda i Ubrania": 87,
    "Dla Dzieci / Zabawki / LEGO": 88,
    "Sport i Hobby": 767,
    "Dom i Ogród": 628,
    "Motoryzacja": 5,
}

DISTANCE_OPTIONS: List[str] = [
    "0 km (Tylko dane miasto)",
    "+5 km",
    "+10 km",
    "+15 km",
    "+30 km",
    "+50 km",
    "+75 km",
    "+100 km",
]

DEFAULT_EXCLUDE_KEYWORDS: List[str] = [
    "uszkodzon", "zepsut", "nie dziala", "nie wstaje", "na czesci",
    "pudelko", "pudełko", "samo pudelko", "sam karton", "box only",
    "etui", "case", "pokrowiec", "szklo", "szkło", "folia",
    "plakat", "brelok", "naklejka", "instrukcja", "sama ladowarka", "sam kabel"
]

DEFAULT_CONFIG: Dict[str, Any] = {
    "search_query": "iphone",
    "exact_phrase_match": False,
    "selected_category": "Wszystkie kategorie (Uniwersalne)",
    "category_id": 0,
    "olx_delivery_only": False,             # Przesylka OLX
    "city_name": "",                        # Puste = cala Polska
    "city_id": 0,
    "distance_km": 0,                       # Promien w km
    "min_price_filter": 50,
    "max_price_filter": 0,
    "expected_market_price": 0,
    "deals_only_mode": False,
    "track_olx": True,
    "track_vinted": True,
    "track_allegro_lokalnie": True,
    "track_allegro": True,
    "allegro_client_id": "",
    "allegro_client_secret": "",
    "scan_interval_sec": 30,
    "sound_alerts": True,
    "desktop_notifications": True,
    "discord_webhook_url": "",
    "exclude_keywords": DEFAULT_EXCLUDE_KEYWORDS,
    "vinted_session_cookie": "",
    "vinted_user_login": "",
    "vinted_is_logged_in": False,
    "vinted_auto_offer_enabled": False,
    "vinted_discount_percent": 10.0,
    "vinted_max_auto_offers_per_hour": 10,
    "show_item_images": True,
    "gemini_api_key": "",
    "selected_theme": "Obsydianowy Fiolet (Domyślny)",
    "max_feed_cards": 50,
    "enable_image_prefetch": True,
    "license_key": "",
    "auth_server_url": "http://127.0.0.1:5000",
    "keyauth_app_name": "",
    "keyauth_owner_id": "",
    "keyauth_secret": "",
    "keyauth_version": "1.0",
}

def calculate_vinted_offer_price(original_price: float, discount_pct: float) -> float:
    """
    Oblicza proponowana cene na Vinted z uwzglednieniem rabatu procentowego.
    Przyklad: 10% z 50 PLN -> 45.0 PLN.
    """
    if original_price <= 0:
        return 0.0
    discount_pct = min(max(discount_pct, 1.0), 40.0)  # Vinted dopuszcza max 40% rabatu
    discount_amount = original_price * (discount_pct / 100.0)
    proposed = round(original_price - discount_amount)
    return max(1.0, float(proposed))

# Pomocnicza baza referencyjna dla kart graficznych (jesli uzytkownik ich szuka)
GPU_MARKET_DATABASE: Dict[str, Dict[str, Any]] = {
    "RTX 5090": {"market_avg": 11000, "deal_price": 9000, "aliases": ["5090", "rtx5090"]},
    "RTX 5080": {"market_avg": 5800, "deal_price": 4800, "aliases": ["5080", "rtx5080"]},
    "RTX 5070": {"market_avg": 3200, "deal_price": 2600, "aliases": ["5070", "rtx5070"]},
    "RTX 4090": {"market_avg": 7500, "deal_price": 5800, "aliases": ["4090", "rtx4090"]},
    "RTX 4080": {"market_avg": 4000, "deal_price": 3300, "aliases": ["4080", "rtx4080"]},
    "RTX 4070 TI": {"market_avg": 3000, "deal_price": 2400, "aliases": ["4070 ti", "4070ti"]},
    "RTX 4070": {"market_avg": 2200, "deal_price": 1750, "aliases": ["4070", "rtx4070"]},
    "RTX 4060": {"market_avg": 1200, "deal_price": 950, "aliases": ["4060", "rtx4060"]},
    "RTX 3090": {"market_avg": 3200, "deal_price": 2500, "aliases": ["3090", "rtx3090"]},
    "RTX 3080": {"market_avg": 1750, "deal_price": 1390, "aliases": ["3080", "rtx3080"]},
    "RTX 3070": {"market_avg": 1250, "deal_price": 980, "aliases": ["3070", "rtx3070"]},
    "RTX 3060": {"market_avg": 850, "deal_price": 650, "aliases": ["3060", "rtx3060"]},
    "GTX 1660 SUPER": {"market_avg": 450, "deal_price": 330, "aliases": ["1660 super", "1660super"]},
    "RX 7800 XT": {"market_avg": 2050, "deal_price": 1650, "aliases": ["7800 xt", "7800xt"]},
    "RX 6700 XT": {"market_avg": 1150, "deal_price": 880, "aliases": ["6700 xt", "6700xt"]},
}

def load_config() -> Dict[str, Any]:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                merged = DEFAULT_CONFIG.copy()
                merged.update(data)
                return merged
        except Exception:
            return DEFAULT_CONFIG.copy()
    return DEFAULT_CONFIG.copy()

def save_config(cfg: Dict[str, Any]) -> None:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Błąd zapisu konfiguracji: {e}")

def load_seen_offers() -> set:
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data)
        except Exception:
            return set()
    return set()

def save_seen_offers(seen_set: set) -> None:
    try:
        arr = list(seen_set)[-3000:]
        with open(SEEN_FILE, "w", encoding="utf-8") as f:
            json.dump(arr, f, indent=2)
    except Exception as e:
        print(f"Błąd zapisu widzianych ofert: {e}")

FAVORITES_FILE = "favorites.json"

DEFAULT_FAVORITES: List[Dict[str, Any]] = [
    {
        "name": "📱 iPhone 15 Okazje",
        "search_query": "iPhone 15",
        "exact_phrase_match": True,
        "selected_category": "Telefony i Smartfony",
        "category_id": 1461,
        "min_price_filter": 1500,
        "max_price_filter": 2600,
        "expected_market_price": 3100,
        "city_name": "",
        "distance_km": 0,
        "olx_delivery_only": True,
        "deals_only_mode": True,
        "track_olx": True,
        "track_vinted": True,
        "track_allegro_lokalnie": True,
        "track_allegro": True,
        "exclude_keywords": ["etui", "case", "pudełko", "uszkodzony", "szkło"]
    },
    {
        "name": "🎮 PS5 Slim Okazje",
        "search_query": "PS5 Slim",
        "exact_phrase_match": False,
        "selected_category": "Gry i Konsole",
        "category_id": 93,
        "min_price_filter": 800,
        "max_price_filter": 1650,
        "expected_market_price": 2000,
        "city_name": "",
        "distance_km": 0,
        "olx_delivery_only": False,
        "deals_only_mode": True,
        "track_olx": True,
        "track_vinted": True,
        "track_allegro_lokalnie": True,
        "track_allegro": True,
        "exclude_keywords": ["gra", "pad", "gry", "uszkodzona", "pudełko"]
    },
    {
        "name": "⚡ RTX 4070 do 1800 zł",
        "search_query": "RTX 4070",
        "exact_phrase_match": True,
        "selected_category": "Karty graficzne",
        "category_id": 2184,
        "min_price_filter": 800,
        "max_price_filter": 1800,
        "expected_market_price": 2200,
        "city_name": "",
        "distance_km": 0,
        "olx_delivery_only": True,
        "deals_only_mode": True,
        "track_olx": True,
        "track_vinted": True,
        "track_allegro_lokalnie": True,
        "track_allegro": True,
        "exclude_keywords": ["uszkodzon", "pudełko", "chłodzenie", "wentylator"]
    }
]

def load_favorites() -> List[Dict[str, Any]]:
    if os.path.exists(FAVORITES_FILE):
        try:
            with open(FAVORITES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception:
            return DEFAULT_FAVORITES.copy()
    return DEFAULT_FAVORITES.copy()

def save_favorites(favs: List[Dict[str, Any]]) -> None:
    try:
        with open(FAVORITES_FILE, "w", encoding="utf-8") as f:
            json.dump(favs, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Błąd zapisu ulubionych: {e}")

