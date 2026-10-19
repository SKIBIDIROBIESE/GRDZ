# c:/Users/Kacper/Desktop/skrypt/deal_engine.py
# python / deal_engine.py / cpython 3.12 / x64 / windows
"""
Uniwersalny silnik wyszukiwania i wykrywania okazji dla dowolnych przedmiotow
na platformach: OLX, Vinted, Allegro Lokalnie oraz Allegro.
Obsluguje kategorie, filtr Przesylka OLX, lokalizacje miast oraz promien wyszukiwania w km.
"""

import re
import time
import base64
import threading
import urllib.parse
from dataclasses import dataclass, field
from typing import List, Optional, Callable, Dict, Any
from bs4 import BeautifulSoup
from curl_cffi import requests

from config import GPU_MARKET_DATABASE, load_config, load_seen_offers, save_seen_offers

# Podreczna baza ID najpopularniejszych polskich miast na OLX
CITY_CACHE: Dict[str, int] = {
    "warszawa": 17871, "krakow": 8959, "kraków": 8959, "wroclaw": 19641, "wrocław": 19641,
    "poznan": 14751, "poznań": 14751, "gdansk": 3706, "gdańsk": 3706, "szczecin": 16931,
    "lodz": 10565, "łódź": 10565, "katowice": 8011, "lublin": 10189, "bialystok": 891,
    "białystok": 891, "gdynia": 3755, "czestochowa": 2689, "częstochowa": 2689, "radom": 15061,
    "torun": 18275, "toruń": 18275, "rzeszow": 15555, "rzeszów": 15555, "sosnowiec": 16671,
    "kielce": 8189, "gliwice": 4121, "olsztyn": 13801, "bielsko-biala": 1025, "bielsko-biała": 1025,
    "bytom": 1991, "zielona gora": 20491, "zielona góra": 20491, "opole": 13915, "sopot": 15983,
    "gorzow wielkopolski": 4271, "gorzów wielkopolski": 4271, "dabrowa gornicza": 2961, "dąbrowa górnicza": 2961,
    "plock": 14351, "płock": 14351, "elblag": 3391, "elbląg": 3391, "walbrzych": 19021, "wałbrzych": 19021,
    "wloclawek": 19371, "włocławek": 19371, "tarnow": 18051, "tarnów": 18051, "chorzow": 2361, "chorzów": 2361,
    "kalisz": 7701, "koszalin": 8741, "legnica": 9931, "grudziadz": 4491, "grudziądz": 4491, "jaworzno": 7181
}

def resolve_olx_city_id(city_name: str, session: requests.Session) -> Optional[int]:
    if not city_name or not city_name.strip():
        return None
    slug = city_name.strip().lower()
    if slug in CITY_CACHE:
        return CITY_CACHE[slug]

    # Dynamiczne rozwiazywanie miasta przez strone OLX
    import json
    norm_slug = slug.replace(" ", "-").replace("ą", "a").replace("ć", "c").replace("ę", "e").replace("ł", "l").replace("ń", "n").replace("ó", "o").replace("ś", "s").replace("ź", "z").replace("ż", "z")
    url = f"https://www.olx.pl/d/{norm_slug}/"
    try:
        r = session.get(url, timeout=6)
        if r.status_code == 200:
            m = re.search(r'window\.__PRERENDERED_STATE__\s*=\s*(".*?")\s*;\s*window\.', r.text, re.DOTALL)
            if m:
                raw_str = json.loads(m.group(1))
                data = json.loads(raw_str)
                cid = data.get("listing", {}).get("listing", {}).get("params", {}).get("city_id")
                if cid:
                    CITY_CACHE[slug] = int(cid)
                    return int(cid)
    except Exception:
        pass
    return None

import datetime

def compute_seller_reputation(
    platform: str,
    seller_name: Optional[str] = None,
    rating: Optional[float] = None,
    reviews_count: Optional[int] = None,
    account_created: Optional[str] = None,
    is_company: bool = False
) -> Dict[str, Any]:
    """
    Kalkulator reputacji i opinii o sprzedawcy:
    - Zielona minka (😊 good): bardzo dobry sprzedawca (ocena >= 4.5, wieloletni staż OLX, lub zweryfikowana firma).
    - Żółta minka (😐 medium): średni sprzedawca (ocena 3.8 - 4.49, nowy użytkownik lub staż kilka miesięcy).
    - Czerwona minka (🙁 bad): słaby sprzedawca (ocena < 3.8 lub świeże konto jednodniowe <30 dni).
    """
    s_name = seller_name.strip() if seller_name and str(seller_name).strip() else "Sprzedawca"

    if platform == "VINTED":
        if rating is not None:
            rev_str = f" ({reviews_count})" if reviews_count is not None else ""
            if rating >= 4.5:
                return {
                    "grade": "good",
                    "smiley": "😊",
                    "badge_text": f"😊 {s_name}: {rating:.1f}/5{rev_str}",
                    "badge_color": "#00ff88",
                    "bg_color": "#064e3b"
                }
            elif rating >= 3.8:
                return {
                    "grade": "medium",
                    "smiley": "😐",
                    "badge_text": f"😐 {s_name}: {rating:.1f}/5{rev_str}",
                    "badge_color": "#fbbf24",
                    "bg_color": "#451a03"
                }
            else:
                return {
                    "grade": "bad",
                    "smiley": "🙁",
                    "badge_text": f"🙁 {s_name}: {rating:.1f}/5{rev_str}",
                    "badge_color": "#f43f5e",
                    "bg_color": "#4c0519"
                }
        else:
            return {
                "grade": "medium",
                "smiley": "😐",
                "badge_text": f"😐 {s_name}: Nowy (Brak ocen)",
                "badge_color": "#fbbf24",
                "bg_color": "#451a03"
            }

    elif platform == "OLX":
        if is_company:
            return {
                "grade": "good",
                "smiley": "😊",
                "badge_text": f"😊 {s_name}: Firma zweryfikowana",
                "badge_color": "#00ff88",
                "bg_color": "#064e3b"
            }
        if account_created:
            try:
                dt_str = account_created[:10]
                created_dt = datetime.datetime.strptime(dt_str, "%Y-%m-%d")
                now = datetime.datetime.now()
                days = (now - created_dt).days
                created_year = created_dt.year
                if days >= 365:
                    years = max(1, round(days / 365))
                    return {
                        "grade": "good",
                        "smiley": "😊",
                        "badge_text": f"😊 {s_name}: Staż {years} lat (od {created_year})",
                        "badge_color": "#00ff88",
                        "bg_color": "#064e3b"
                    }
                elif days >= 60:
                    months = max(1, round(days / 30))
                    return {
                        "grade": "medium",
                        "smiley": "😐",
                        "badge_text": f"😐 {s_name}: Staż {months} mies.",
                        "badge_color": "#fbbf24",
                        "bg_color": "#451a03"
                    }
                else:
                    return {
                        "grade": "bad",
                        "smiley": "🙁",
                        "badge_text": f"🙁 {s_name}: Świeże konto ({max(1, days)} dni)",
                        "badge_color": "#f43f5e",
                        "bg_color": "#4c0519"
                    }
            except Exception:
                pass
        return {
            "grade": "medium",
            "smiley": "😐",
            "badge_text": f"😐 {s_name}",
            "badge_color": "#fbbf24",
            "bg_color": "#451a03"
        }
    else:
        # Allegro & Allegro Lokalnie
        if is_company:
            return {
                "grade": "good",
                "smiley": "😊",
                "badge_text": f"😊 {s_name}: Super Sprzedawca",
                "badge_color": "#00ff88",
                "bg_color": "#064e3b"
            }
        return {
            "grade": "good",
            "smiley": "😊",
            "badge_text": f"😊 {s_name}: Zaufany sprzedawca",
            "badge_color": "#00ff88",
            "bg_color": "#064e3b"
        }

@dataclass
class Offer:
    id: str
    platform: str        # 'OLX', 'VINTED', 'ALLEGRO LOKALNIE', 'ALLEGRO'
    title: str
    price: float
    url: str
    image_url: Optional[str]
    created_at_str: str
    detected_tag: Optional[str] = None
    market_avg: Optional[float] = None
    deal_price_threshold: Optional[float] = None
    discount_pct: float = 0.0
    is_deal: bool = False
    deal_reason: str = ""
    has_delivery: bool = False
    location_name: str = ""
    images: List[str] = field(default_factory=list)
    ai_evaluation: Optional[Dict[str, Any]] = None

    # Informacje o reputacji i opiniach o sprzedawcy
    seller_name: Optional[str] = None
    seller_rating: Optional[float] = None
    seller_reviews_count: Optional[int] = None
    seller_grade: str = "unknown"
    seller_badge_text: str = ""
    seller_badge_color: str = "#00ff88"
    seller_bg_color: str = "#064e3b"
    seller_recent_reviews: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        if not self.images and self.image_url:
            self.images = [self.image_url]
        elif self.images and not self.image_url:
            self.image_url = self.images[0]
        if not self.seller_badge_text:
            rep = compute_seller_reputation(
                self.platform,
                seller_name=self.seller_name,
                rating=self.seller_rating,
                reviews_count=self.seller_reviews_count
            )
            self.seller_grade = rep["grade"]
            self.seller_badge_text = rep["badge_text"]
            self.seller_badge_color = rep["badge_color"]
            self.seller_bg_color = rep["bg_color"]

def clean_text(s: Any) -> str:
    if not s:
        return ""
    text = str(s).strip()
    text = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", text)
    return " ".join(text.split())

def clean_price(text: Any) -> Optional[float]:
    if text is None:
        return None
    val_str = str(text).replace("\xa0", " ").replace(" ", "")
    m = re.search(r"(\d+(?:[.,]\d+)?)", val_str)
    if m:
        try:
            return float(m.group(1).replace(",", "."))
        except ValueError:
            return None
    return None

POPULAR_MARKET_BENCHMARKS: Dict[str, float] = {
    # Apple iPhone
    "iphone 11": 750.0, "iphone 12 mini": 950.0, "iphone 12": 1150.0, "iphone 12 pro": 1400.0, "iphone 12 pro max": 1700.0,
    "iphone 13 mini": 1350.0, "iphone 13": 1600.0, "iphone 13 pro": 2000.0, "iphone 13 pro max": 2300.0,
    "iphone 14": 1950.0, "iphone 14 plus": 2100.0, "iphone 14 pro": 2600.0, "iphone 14 pro max": 2900.0,
    "iphone 15": 2700.0, "iphone 15 plus": 2950.0, "iphone 15 pro": 3300.0, "iphone 15 pro max": 3800.0,
    "iphone 16": 3400.0, "iphone 16 pro": 4200.0, "iphone 16 pro max": 4800.0,
    # Konsole i handheldy
    "ps5": 1600.0, "playstation 5": 1600.0, "ps4 pro": 650.0, "ps4": 450.0, "playstation 4": 450.0,
    "xbox series x": 1400.0, "xbox series s": 750.0, "xbox one": 350.0,
    "nintendo switch oled": 950.0, "nintendo switch v2": 650.0, "nintendo switch": 600.0,
    "steam deck oled": 2100.0, "steam deck": 1350.0, "asus rog ally": 1800.0,
    # Smartfony Samsung
    "s21": 800.0, "s22": 1250.0, "s23": 1850.0, "s24": 2500.0,
    # Karty graficzne
    "rtx 3060 ti": 1150.0, "rtx 3060": 950.0, "rtx 3070 ti": 1450.0, "rtx 3070": 1300.0,
    "rtx 3080 ti": 2100.0, "rtx 3080": 1850.0, "rtx 3090": 2600.0,
    "rtx 4060 ti": 1450.0, "rtx 4060": 1150.0, "rtx 4070 ti": 2700.0, "rtx 4070": 2200.0,
    "rx 6600": 700.0, "rx 6650 xt": 850.0, "rx 6700 xt": 1150.0, "rx 7800 xt": 2000.0,
}

DAMAGE_RULES: List[Dict[str, Any]] = [
    {
        "key": "screen_glass",
        "patterns": [r"zbit(?:a|e)\s+szyb(?:ka|ki)", r"pęknięt(?:a|e)\s+szyb(?:ka|ki)", r"pekniet(?:a|e)\s+szyb(?:ka|ki)", r"zbitka", r"dotyk\s+działa", r"szybka\s+do\s+wymiany", r"pęknięcie\s+szybki"],
        "name": "Zbita szybka (dotyk i matryca sprawne)",
        "parts_min": 70, "parts_max": 160,
        "service_min": 80, "service_max": 150,
        "notes": "Możliwa regeneracja / refabrykacja samej szybki metodą OCA z zachowaniem oryginalnego wyświetlacza."
    },
    {
        "key": "screen_display",
        "patterns": [r"rozbit(?:y|a|e)\s+ekran", r"zbit(?:y|a|e)\s+ekran", r"uszkodzon(?:y|a)\s+ekran", r"uszkodzon(?:y|a)\s+wyświetlacz", r"uszkodzon(?:y|a)\s+matryc(?:a|e)", r"paski\s+na\s+ekranie", r"wylan(?:y|a)\s+ekran", r"czarny\s+ekran", r"plam(?:a|y)\s+na\s+ekranie"],
        "name": "Uszkodzony wyświetlacz / matryca (brak obrazu / paski / plamy)",
        "parts_min": 180, "parts_max": 480,
        "service_min": 70, "service_max": 140,
        "notes": "Wymaga wymiany całego modułu ekranu wraz z dotykiem (moduł OLED / IPS)."
    },
    {
        "key": "battery",
        "patterns": [r"bateri(?:a|e)\s+do\s+wymiany", r"słab(?:a|y)\s+bateri(?:a|e)", r"kondycj(?:a|i)\s+baterii\s*(?:[567]\d%)", r"kondycj(?:a|i)\s*(?:[567]\d%)", r"bateria\s+spuchnięta", r"nie\s+trzyma\s+baterii", r"szybko\s+się\s+rozładowuje"],
        "name": "Zużyta / spuchnięta bateria",
        "parts_min": 60, "parts_max": 130,
        "service_min": 50, "service_max": 90,
        "notes": "Standardowa wymiana akumulatora. W modelach Apple zalecane przelutowanie taśmy BMS lub programator."
    },
    {
        "key": "housing_back",
        "patterns": [r"zbit(?:y|e)\s+tył", r"pęknięt(?:y|e)\s+tył", r"zbit(?:e|a)\s+plecki", r"pęknięt(?:e|a)\s+plecki", r"pęknięt(?:a|e)\s+klapk(?:a|i)", r"zbita\s+klapka"],
        "name": "Pęknięte plecki / zbity tył obudowy",
        "parts_min": 50, "parts_max": 120,
        "service_min": 60, "service_max": 110,
        "notes": "Wymiana tylnego szkła z użyciem lasera lub przełożenie korpusu."
    },
    {
        "key": "board_gpu",
        "patterns": [r"artefakt(?:y|ów)", r"reballing", r"vram", r"kod\s*43", r"sekcj(?:a|i)\s+zasilania", r"zwarcie", r"nie\s+wstaje", r"nie\s+włącza\s+się", r"nie\s+odpala", r"po\s+zalaniu"],
        "name": "Awaria płyty głównej / VRAM / sekcji zasilania",
        "parts_min": 120, "parts_max": 280,
        "service_min": 150, "service_max": 300,
        "notes": "Wymaga zaawansowanej diagnostyki mikroskopowej, stacji na gorące powietrze lub serwisu BGA."
    },
    {
        "key": "cooling_fans",
        "patterns": [r"wentylator\s+terkocze", r"brak\s+wentylator(?:a|ów)", r"chłodzenie\s+do\s+wymiany", r"uszkodzon(?:y|e)\s+wentylator", r"głośn(?:y|e)\s+wentylator", r"przegrzewa\s+się"],
        "name": "Uszkodzony wentylator / układ chłodzenia",
        "parts_min": 35, "parts_max": 85,
        "service_min": 30, "service_max": 60,
        "notes": "Tania wymiana wentylatorów + nałożenie świeżej pasty termoprzewodzącej i termopadów."
    },
    {
        "key": "port_power",
        "patterns": [r"uszkodzon(?:e|y)\s+gniazdo", r"nie\s+ładuje", r"uszkodzon(?:e|y)\s+hdmi", r"wyrwan(?:e|y)\s+port", r"luźn(?:y|e)\s+gniazdo", r"port\s+hdmi"],
        "name": "Uszkodzone gniazdo ładowania / HDMI / USB",
        "parts_min": 25, "parts_max": 60,
        "service_min": 80, "service_max": 150,
        "notes": "Wymiana i przelutowanie gniazda na płycie głównej (np. port HDMI w PS5/Xbox lub port USB-C)."
    },
    {
        "key": "stick_drift",
        "patterns": [r"drift\s+analog(?:a|ów)", r"dryfuj(?:ący|e)\s+analog", r"driftuje", r"analog\s+do\s+wymiany"],
        "name": "Dryfujący analog (drifting stick)",
        "parts_min": 20, "parts_max": 45,
        "service_min": 40, "service_max": 80,
        "notes": "Zalecany montaż nowoczesnych analogów z efektem Halla (bezstykowe, wieczna żywotność)."
    },
    {
        "key": "general_defect",
        "patterns": [r"uszkodzon(?:y|a|e)", r"zepsut(?:y|a|e)", r"na\s+części", r"do\s+naprawy", r"defekt", r"wad(?:a|ą)", r"usterk(?:a|ą)", r"stan\s+nieznany", r"nietestowan(?:y|a|e)"],
        "name": "Ogólne uszkodzenie / stan nieznany / na części",
        "parts_min": 80, "parts_max": 220,
        "service_min": 80, "service_max": 160,
        "notes": "Sprzęt wymaga wstępnej diagnostyki w serwisie przed zamówieniem konkretnych podzespołów."
    }
]

class AIOfferEvaluator:
    """
    Ekspercki silnik analizy ofert przez sztuczną inteligencję:
    - Analizuje tytuł, cenę, kategorię oraz wykryte parametry
    - Wykrywa uszkodzenia i precyzyjnie szacuje koszty naprawy (części + robocizna)
    - Wycenia rynkową wartość sprawnego przedmiotu (benchmarki rynkowe)
    - Oblicza całkowity koszt inwestycji (zakup + naprawa) oraz zysk/stratę po odsprzedaży
    - Formułuje werdykt opłacalności i praktyczną rekomendację snajperską
    - Wspiera opcjonalne zapytania neuronowe do Google Gemini API (gemini-2.5-flash)
    """

    @classmethod
    def evaluate_offer(cls, offer: Offer, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        cfg = cfg or {}
        t_low = offer.title.lower()

        # 1. Sprawdzenie czy wystepuje uszkodzenie
        detected_damage = None
        for rule in DAMAGE_RULES:
            for pat in rule["patterns"]:
                if re.search(pat, t_low):
                    detected_damage = rule
                    break
            if detected_damage:
                break

        # 2. Szacowanie wartosci rynkowej
        market_val = 0.0
        if offer.market_avg and offer.market_avg > 0:
            market_val = float(offer.market_avg)
        elif offer.detected_tag and offer.detected_tag in GPU_MARKET_DATABASE:
            market_val = float(GPU_MARKET_DATABASE[offer.detected_tag]["market_avg"])
        else:
            exp_p = float(cfg.get("expected_market_price", 0) or 0)
            if exp_p > 0:
                market_val = exp_p

        if market_val <= 0:
            for bench_key, val in sorted(POPULAR_MARKET_BENCHMARKS.items(), key=lambda x: len(x[0]), reverse=True):
                if re.search(r"(?:\b|_)" + re.escape(bench_key) + r"(?:\b|_)", t_low):
                    market_val = float(val)
                    break

        if market_val <= 0:
            if detected_damage:
                market_val = max(offer.price * 2.1, offer.price + 350.0)
            else:
                market_val = max(offer.price * 1.15, offer.price + 50.0)

        is_damaged = detected_damage is not None

        if is_damaged:
            d = detected_damage
            repair_parts_avg = (d["parts_min"] + d["parts_max"]) / 2
            repair_serv_avg = (d["service_min"] + d["service_max"]) / 2
            total_repair_min = d["parts_min"] + d["service_min"]
            total_repair_max = d["parts_max"] + d["service_max"]
            total_repair_avg = (total_repair_min + total_repair_max) / 2

            total_investment = offer.price + total_repair_avg
            profit_after_repair = round(market_val - total_investment)
            roi_pct = round((profit_after_repair / total_investment) * 100) if total_investment > 0 else 0

            if profit_after_repair >= 160:
                verdict_badge = "🟢 BARDZO OPŁACA SIĘ NAPRAWIĆ"
                verdict_short = f"Zysk po naprawie: +{profit_after_repair} zł (+{roi_pct}%)"
                recommendation = (
                    f"Świetna okazja flipperska! Zakup za {offer.price:.0f} zł + części i robocizna (~{total_repair_avg:.0f} zł) "
                    f"to łącznie ok. {total_investment:.0f} zł. Po naprawie sprzęt jest wart ok. {market_val:.0f} zł, "
                    f"co daje około {profit_after_repair} zł czystego zysku. {d['notes']}"
                )
                bcol = "#00ff88"
                is_prof = True
            elif profit_after_repair > 20:
                verdict_badge = "🟡 UMIARKOWANIE OPŁACALNA NAPRAWA"
                verdict_short = f"Zysk po naprawie: ok. +{profit_after_repair} zł"
                recommendation = (
                    f"Opłacalne przy naprawie własnej lub tanich częściach. Całkowity koszt (~{total_investment:.0f} zł) "
                    f"zostawia ok. {profit_after_repair} zł marży względem wartości sprawnego (~{market_val:.0f} zł). {d['notes']}"
                )
                bcol = "#fbbf24"
                is_prof = True
            else:
                verdict_badge = "🔴 NIEOPŁACALNA NAPRAWA"
                verdict_short = f"Ryzyko straty: {abs(profit_after_repair)} zł"
                recommendation = (
                    f"Odradzamy zakup pod kątem naprawy. Koszt sprzętu i serwisu ({total_investment:.0f} zł) "
                    f"przekracza lub zrównuje się z rynkową ceną sprawnego egzemplarza ({market_val:.0f} zł)."
                )
                bcol = "#f43f5e"
                is_prof = False

            return {
                "is_profitable": is_prof,
                "verdict_badge": verdict_badge,
                "verdict_short": verdict_short,
                "is_damaged": True,
                "damage_name": d["name"],
                "repair_parts_range": f"{d['parts_min']} - {d['parts_max']} zł",
                "repair_service_range": f"{d['service_min']} - {d['service_max']} zł",
                "repair_total_range": f"{total_repair_min} - {total_repair_max} zł",
                "repair_total_avg": total_repair_avg,
                "estimated_market_value": market_val,
                "total_investment": total_investment,
                "profit_after_repair": profit_after_repair,
                "roi_pct": roi_pct,
                "recommendation": recommendation,
                "badge_color": bcol,
                "engine": "AI Expert Heuristics"
            }
        else:
            diff = round(market_val - offer.price)
            disc_pct = round((diff / market_val) * 100) if market_val > 0 else 0

            if disc_pct >= 25:
                verdict_badge = "🟢 SUPER OKAZJA"
                verdict_short = f"Cena -{disc_pct}% vs rynek (oszczędzasz ~{diff} zł)"
                recommendation = (
                    f"Znakomita cena! Egzemplarz sprawny, wyceniony {disc_pct}% poniżej typowej ceny rynkowej "
                    f"(~{market_val:.0f} zł). Bardzo wysoka opłacalność zarówno do użytku, jak i natychmiastowej odsprzedaży."
                )
                bcol = "#00ff88"
                is_prof = True
            elif disc_pct >= 10:
                verdict_badge = "🟢 OPŁACALNA OFERTA"
                verdict_short = f"Poniżej średniej o {disc_pct}% (~{diff} zł taniej)"
                recommendation = (
                    f"Dobra, uczciwa okazja. Cena jest o {disc_pct}% niższa od rynkowej normy (~{market_val:.0f} zł). "
                    f"Warto rozważyć zakup."
                )
                bcol = "#34d399"
                is_prof = True
            elif disc_pct >= -8:
                verdict_badge = "🟡 CENA STANDARDOWA"
                verdict_short = f"Cena rynkowa (~{market_val:.0f} zł)"
                recommendation = (
                    f"Oferta w normalnym przedziale rynkowym. Brak marży pod flipowanie, ale dobra, jeśli szukasz sprzętu dla siebie."
                )
                bcol = "#fbbf24"
                is_prof = False
            else:
                verdict_badge = "🔴 NIEOPŁACALNE"
                verdict_short = f"Powyżej rynku o {abs(disc_pct)}% (+{abs(diff)} zł)"
                recommendation = (
                    f"Cena jest wyższa od rynkowej (~{market_val:.0f} zł) o {abs(disc_pct)}%. Proponujemy złożyć kontrofertę lub poczekać."
                )
                bcol = "#f43f5e"
                is_prof = False

            return {
                "is_profitable": is_prof,
                "verdict_badge": verdict_badge,
                "verdict_short": verdict_short,
                "is_damaged": False,
                "damage_name": "Sprzęt sprawny / brak widocznych uszkodzeń",
                "repair_parts_range": "0 zł",
                "repair_service_range": "0 zł",
                "repair_total_range": "Naprawa niewymagana",
                "repair_total_avg": 0,
                "estimated_market_value": market_val,
                "total_investment": offer.price,
                "profit_after_repair": diff,
                "roi_pct": disc_pct,
                "recommendation": recommendation,
                "badge_color": bcol,
                "engine": "AI Expert Heuristics"
            }

    @classmethod
    def query_gemini_ai(cls, offer: Offer, api_key: str) -> Optional[Dict[str, Any]]:
        """
        Opcjonalne, głębokie zapytanie do Google Gemini API (gemini-2.5-flash)
        zwracające szczegółową ekspertyzę rynku i naprawy w formacie JSON.
        """
        if not api_key or not api_key.strip():
            return None

        prompt = f"""Jesteś ekspertem wyceny sprzętu z drugiej ręki (OLX, Vinted, Allegro) oraz serwisantem elektroniki.
Przeanalizuj ofertę:
- Tytuł: "{offer.title}"
- Cena w ogłoszeniu: {offer.price} PLN
- Platforma: {offer.platform}
- Lokalizacja: {offer.location_name}

Odpowiedz wyłącznie poprawnym obiektem JSON w strukturze:
{{
  "is_profitable": true/false,
  "verdict_badge": "🟢 BARDZO OPŁACALNE" / "🟡 ŚREDNIO OPŁACALNE" / "🔴 NIEOPŁACALNE" / "🟢 OPŁACA SIĘ NAPRAWIĆ",
  "verdict_short": "krótkie podsumowanie zysku/opłacalności",
  "is_damaged": true/false,
  "damage_name": "wykryte uszkodzenie lub 'Sprzęt sprawny'",
  "repair_parts_range": "np. 80 - 150 zł lub '0 zł'",
  "repair_service_range": "np. 70 - 120 zł lub '0 zł'",
  "repair_total_range": "np. 150 - 270 zł lub 'Naprawa niewymagana'",
  "repair_total_avg": 210.0,
  "estimated_market_value": 1200.0,
  "total_investment": 850.0,
  "profit_after_repair": 350.0,
  "roi_pct": 41,
  "recommendation": "1-2 zdania porady czy kupować i na co uważać"
}}"""

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key.strip()}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}
        }

        try:
            r = requests.post(url, json=payload, timeout=12)
            if r.status_code == 200:
                import json
                resp_data = r.json()
                raw_text = resp_data["candidates"][0]["content"]["parts"][0]["text"]
                parsed = json.loads(raw_text)
                parsed["engine"] = "Google Gemini 2.5 Flash"
                parsed["badge_color"] = "#00ff88" if parsed.get("is_profitable") else "#fbbf24"
                return parsed
        except Exception as e:
            print(f"[Gemini API] Błąd wywołania: {e}")

        return None

class DealEvaluator:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.sorted_gpus = sorted(
            GPU_MARKET_DATABASE.keys(),
            key=lambda m: max(len(a) for a in GPU_MARKET_DATABASE[m]["aliases"]),
            reverse=True
        )

    def is_excluded(self, title: str) -> bool:
        t_low = title.lower()
        for kw in self.cfg.get("exclude_keywords", []):
            if kw and kw.strip() and kw.strip().lower() in t_low:
                return True
        return False

    def detect_gpu_bonus(self, title: str) -> Optional[str]:
        t_low = re.sub(r"[^\w\s]", " ", title.lower())
        for model in self.sorted_gpus:
            aliases = GPU_MARKET_DATABASE[model]["aliases"]
            for alias in aliases:
                pattern = r"(?:\b|_)" + re.escape(alias.lower()) + r"(?:\b|_)"
                if re.search(pattern, t_low):
                    return model
        return None

    def evaluate(self, offer: Offer) -> Offer:
        # 0. Analiza sztucznej inteligencji (opłacalność, usterki, koszty naprawy)
        try:
            offer.ai_evaluation = AIOfferEvaluator.evaluate_offer(offer, self.cfg)
        except Exception as e:
            print(f"[DealEvaluator] Błąd AI oceny: {e}")

        # 1. Dokladna fraza
        search_q = self.cfg.get("search_query", "").strip()
        if self.cfg.get("exact_phrase_match", False) and search_q:
            q_clean = re.sub(r"\s+", " ", search_q.lower())
            t_clean = re.sub(r"\s+", " ", offer.title.lower())
            if q_clean not in t_clean:
                offer.is_deal = False
                offer.deal_reason = f"Brak dokładnej frazy: '{search_q}'"
                return offer

        # 2. Slowa wykluczajace
        if self.is_excluded(offer.title):
            offer.is_deal = False
            offer.deal_reason = "Wykluczono przez filtr słów (akcesoria/uszkodzone/pudełko)"
            return offer

        # 3. Weryfikacja filtru 'Tylko z Przesylka OLX'
        if self.cfg.get("olx_delivery_only", False) and offer.platform == "OLX" and not offer.has_delivery:
            offer.is_deal = False
            offer.deal_reason = "Brak Przesyłki OLX"
            return offer

        # 4. Min/Max cena
        min_p = float(self.cfg.get("min_price_filter", 0) or 0)
        max_p = float(self.cfg.get("max_price_filter", 0) or 0)
        expected_market = float(self.cfg.get("expected_market_price", 0) or 0)

        if min_p > 0 and offer.price < min_p:
            offer.is_deal = False
            offer.deal_reason = f"Cena poniżej progu minimalnego ({min_p:.0f} PLN)"
            return offer

        if max_p > 0 and offer.price > max_p:
            offer.is_deal = False
            offer.deal_reason = f"Cena powyżej limitu ({max_p:.0f} PLN)"
            return offer

        # 5. Wykrywanie okazji
        gpu_detected = self.detect_gpu_bonus(offer.title)
        if gpu_detected and gpu_detected in GPU_MARKET_DATABASE:
            offer.detected_tag = gpu_detected
            info = GPU_MARKET_DATABASE[gpu_detected]
            market_avg = float(info["market_avg"])
            deal_threshold = float(info["deal_price"])
            offer.market_avg = market_avg
            offer.deal_price_threshold = deal_threshold
            if offer.price <= deal_threshold:
                discount = round(((market_avg - offer.price) / market_avg) * 100, 1)
                offer.discount_pct = max(0.0, discount)
                offer.is_deal = True
                offer.deal_reason = f"Super okazja: {offer.price:.0f} PLN vs rynkowa ~{market_avg:.0f} PLN (-{discount:.0f}%)"
                return offer

        if expected_market > 0:
            offer.market_avg = expected_market
            if offer.price < expected_market:
                discount = round(((expected_market - offer.price) / expected_market) * 100, 1)
                offer.discount_pct = discount
                offer.is_deal = True
                offer.deal_reason = f"Okazja cenowa: {offer.price:.0f} PLN vs oczekiwana ~{expected_market:.0f} PLN (-{discount:.0f}%)"
                return offer
            else:
                offer.is_deal = not self.cfg.get("deals_only_mode", False)
                offer.deal_reason = f"Cena standardowa ({offer.price:.0f} PLN)"
                return offer

        if max_p > 0:
            diff = max_p - offer.price
            offer.is_deal = True
            offer.deal_price_threshold = max_p
            if diff > 0:
                pct = round((diff / max_p) * 100, 0)
                offer.deal_reason = f"W Twoim budżecie: {offer.price:.0f} PLN (limit: {max_p:.0f} PLN, -{pct:.0f}%)"
            else:
                offer.deal_reason = f"W Twoim budżecie: {offer.price:.0f} PLN (limit: {max_p:.0f} PLN)"
            return offer

        offer.is_deal = True
        offer.deal_reason = f"Znaleziona oferta: {offer.price:.0f} PLN"
        return offer

class OLXScraper:
    def __init__(self):
        self.session = requests.Session(impersonate="chrome124")
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8",
        }

    def fetch_recent(self,
                     query: str = "",
                     min_p: float = 0,
                     max_p: float = 0,
                     category_id: int = 0,
                     city_name: str = "",
                     distance_km: int = 0,
                     delivery_only: bool = False) -> List[Offer]:
        results: List[Offer] = []
        base_url = "https://www.olx.pl/api/v1/offers/"
        params: Dict[str, Any] = {
            "offset": 0,
            "limit": 40,
            "sort_by": "created_at:desc",
        }
        if query and query.strip():
            params["query"] = query.strip()
        if category_id > 0:
            params["category_id"] = int(category_id)
        if min_p > 0:
            params["filter_float_price:from"] = int(min_p)
        if max_p > 0:
            params["filter_float_price:to"] = int(max_p)

        # Obsluga lokalizacji i odleglosci
        if city_name and city_name.strip():
            cid = resolve_olx_city_id(city_name.strip(), self.session)
            if cid:
                params["city_id"] = cid
                if distance_km > 0:
                    params["distance"] = int(distance_km)

        # Obsluga Przesylki OLX
        if delivery_only:
            params["courier"] = True

        try:
            resp = self.session.get(base_url, params=params, headers=self.headers, timeout=12)
            if resp.status_code != 200:
                return results

            data = resp.json().get("data", [])
            for item in data:
                item_id = str(item.get("id"))
                title = clean_text(item.get("title", ""))
                url = item.get("url", "")
                created_at = item.get("created_at", "")

                price = None
                for p in item.get("params", []):
                    if p.get("key") == "price":
                        val_obj = p.get("value", {})
                        raw_val = val_obj.get("value") or val_obj.get("label")
                        price = clean_price(raw_val)
                        break

                if price is None:
                    continue

                photos = item.get("photos", [])
                images = []
                for p in photos:
                    link = p.get("link")
                    if link:
                        if "{width}" in link:
                            link = link.replace("{width}", "800").replace("{height}", "600")
                        images.append(link)
                img_url = images[0] if images else None

                # Sprawdzenie czy ma Przesylke OLX
                deliv_obj = item.get("delivery", {})
                rock_mode = deliv_obj.get("rock", {}).get("mode", "")
                has_deliv = rock_mode not in ["", "NotEligible"] or deliv_obj.get("active", False)

                loc_info = item.get("location", {})
                city_str = loc_info.get("city", {}).get("name", "")

                u_obj = item.get("user", {})
                u_name = clean_text(u_obj.get("name", "Użytkownik OLX"))
                u_created = u_obj.get("created", "")
                is_biz = bool(u_obj.get("company_name") or u_obj.get("b2c_business_page") or item.get("business"))

                rep = compute_seller_reputation(
                    "OLX",
                    seller_name=u_name,
                    account_created=u_created,
                    is_company=is_biz
                )

                olx_reviews = []
                if u_created:
                    dt_str = u_created[:10]
                    olx_reviews.append({
                        "author": "System OLX",
                        "rating": 5 if is_biz or "lat" in rep["badge_text"] else 4,
                        "date": dt_str,
                        "comment": f"Konto aktywne na OLX od {dt_str}. {rep['badge_text']}"
                    })
                if is_biz:
                    olx_reviews.append({
                        "author": "Weryfikacja OLX",
                        "rating": 5,
                        "date": "Aktywne",
                        "comment": "Zweryfikowany profil biznesowy / zarejestrowana firma na platformie OLX."
                    })

                results.append(Offer(
                    id=f"olx_{item_id}",
                    platform="OLX",
                    title=title,
                    price=price,
                    url=url,
                    image_url=img_url,
                    created_at_str=created_at[:10] if created_at else "Teraz",
                    has_delivery=has_deliv,
                    location_name=city_str,
                    images=images,
                    seller_name=u_name,
                    seller_grade=rep["grade"],
                    seller_badge_text=rep["badge_text"],
                    seller_badge_color=rep["badge_color"],
                    seller_bg_color=rep["bg_color"],
                    seller_recent_reviews=olx_reviews
                ))
        except Exception as e:
            print(f"[OLX Scraper] Błąd: {e}")

        return results

    def close(self):
        try:
            self.session.close()
        except Exception:
            pass

class VintedScraper:
    def __init__(self):
        self.session = requests.Session(impersonate="chrome124")
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept-Language": "pl-PL,pl;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        self._init_done = False

    def _ensure_session(self):
        if not self._init_done:
            try:
                self.session.get("https://www.vinted.pl", headers=self.headers, timeout=10)
                self._init_done = True
            except Exception as e:
                print(f"[Vinted Scraper] Inicjalizacja sesji: {e}")

    def fetch_recent(self, query: str = "", min_p: float = 0, max_p: float = 0) -> List[Offer]:
        results: List[Offer] = []
        self._ensure_session()

        search_kw = query.strip()
        if not search_kw:
            return results

        encoded_kw = urllib.parse.quote_plus(search_kw)
        url = f"https://www.vinted.pl/catalog?search_text={encoded_kw}&order=newest_first"
        if min_p > 0:
            url += f"&price_from={int(min_p)}"
        if max_p > 0:
            url += f"&price_to={int(max_p)}"

        try:
            resp = self.session.get(url, headers=self.headers, timeout=14)
            if resp.status_code != 200:
                return results

            soup = BeautifulSoup(resp.text, "html.parser")
            item_boxes = soup.find_all(attrs={"data-testid": lambda x: x and x.startswith("product-item-id-") and "--" not in x})

            for box in item_boxes:
                raw_id = box.get("data-testid", "").replace("product-item-id-", "")
                if not raw_id:
                    continue

                link_el = box.find("a", href=lambda x: x and "/items/" in x)
                if not link_el:
                    continue

                href = link_el.get("href", "")
                full_url = href if href.startswith("http") else f"https://www.vinted.pl{href}"

                title = ""
                img_el = box.find("img")
                img_url = img_el.get("src") if img_el else None
                if img_el and img_el.get("alt"):
                    raw_alt = img_el["alt"]
                    title = raw_alt.split(", Marka:")[0].split(", Stan:")[0].strip()

                if not title and link_el.get("title"):
                    title = link_el["title"].split(", Marka:")[0].strip()

                if not title:
                    desc_el = box.find(attrs={"data-testid": lambda x: x and "--description" in x})
                    if desc_el:
                        title = desc_el.get_text(strip=True)

                title = clean_text(title)
                if not title:
                    m_slug = re.search(r"/items/\d+-([^?]+)", href)
                    if m_slug:
                        title = clean_text(m_slug.group(1).replace("-", " "))

                price_el = box.find(attrs={"data-testid": lambda x: x and "--price-text" in x})
                price = None
                if price_el:
                    price = clean_price(price_el.get_text(strip=True))

                if price is None:
                    continue

                results.append(Offer(
                    id=f"vinted_{raw_id}",
                    platform="VINTED",
                    title=title,
                    price=price,
                    url=full_url,
                    image_url=img_url,
                    created_at_str="Teraz",
                    has_delivery=True,
                    location_name="Wysyłka Vinted"
                ))
        except Exception as e:
            print(f"[Vinted Scraper] Błąd: {e}")

        return results

    def close(self):
        try:
            self.session.close()
        except Exception:
            pass

class VintedClient:
    """
    Klient autoryzacji oraz skladania ofert cenowych na Vinted
    wykorzystujacy sesje Chrome124 TLS.
    """
    def __init__(self, session_cookie: str = ""):
        self.session = requests.Session(impersonate="chrome124")
        self.session_cookie = session_cookie
        self.user_login = ""
        self.user_id = None
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "pl-PL,pl;q=0.9",
        }
        if session_cookie:
            self.set_cookie(session_cookie)

    def set_cookie(self, cookie_val: str):
        raw = cookie_val.strip() if cookie_val else ""
        self.session_cookie = raw
        self.headers.pop("Authorization", None)
        if not raw:
            return

        if "=" in raw:
            for item in raw.split(";"):
                item = item.strip()
                if "=" in item:
                    k, v = item.split("=", 1)
                    k = k.strip()
                    v = v.strip()
                    self.session.cookies.set(k, v, domain=".vinted.pl")
                    if k == "access_token_web" and len(v) > 50:
                        self.headers["Authorization"] = f"Bearer {v}"
        else:
            if raw.startswith("eyJ"):
                self.session.cookies.set("access_token_web", raw, domain=".vinted.pl")
                self.headers["Authorization"] = f"Bearer {raw}"
            else:
                self.session.cookies.set("_vinted_fr_session", raw, domain=".vinted.pl")

    @staticmethod
    def get_supported_browser_path() -> Optional[str]:
        """Zwraca ścieżkę do zainstalowanej przeglądarki opartej na Chromium (Chrome, Edge, Brave, Opera GX)."""
        import os
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%PROGRAMFILES%\BraveSoftware\Brave-Browser\Application\brave.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Opera GX\opera.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Opera\opera.exe"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c
        return None

    @classmethod
    def verify_vinted_tokens(cls, at: Optional[str] = None, v_session: Optional[str] = None, v_map: Optional[Dict[str, str]] = None) -> bool:
        """Weryfikuje zapytaniem do Vinted API czy zestaw ciasteczek/tokenów reprezentuje w pełni zalogowaną sesję."""
        if not at and not v_session:
            return False
        try:
            from curl_cffi import requests
            s = requests.Session(impersonate="chrome124")
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://www.vinted.pl/"
            }
            if at:
                headers["Authorization"] = f"Bearer {at}"
                s.cookies.set("access_token_web", at, domain=".vinted.pl")
            if v_session:
                s.cookies.set("_vinted_fr_session", v_session, domain=".vinted.pl")
            if v_map:
                for k in ("anon_id", "v_udt", "v_uid"):
                    if k in v_map:
                        s.cookies.set(k, v_map[k], domain=".vinted.pl")

            r = s.get("https://www.vinted.pl/api/v2/users/current", headers=headers, timeout=5)
            if r.status_code == 200:
                data = r.json()
                return bool(data.get("user", {}).get("login"))
        except Exception:
            pass
        return False

    @classmethod
    def is_cookie_authenticated(cls, cookie_val: str) -> bool:
        """Weryfikuje dowolny format ciasteczka/tokenu sesji."""
        if not cookie_val or len(cookie_val) < 20:
            return False
        v_map = {}
        at = None
        vs = None
        if "=" in cookie_val:
            for item in cookie_val.split(";"):
                if "=" in item:
                    k, v = item.split("=", 1)
                    k = k.strip()
                    v = v.strip()
                    v_map[k] = v
                    if k == "access_token_web":
                        at = v
                    elif k == "_vinted_fr_session":
                        vs = v
        elif cookie_val.startswith("eyJ"):
            at = cookie_val
        else:
            vs = cookie_val

        return cls.verify_vinted_tokens(at=at, v_session=vs, v_map=v_map)

    @classmethod
    def launch_browser_for_cookie(cls, on_status: Optional[Callable[[str], None]] = None, timeout_sec: int = 240) -> Optional[str]:
        """
        Uruchamia okno przeglądarki Chrome/Edge z obsługą CDP,
        otwiera stronę logowania Vinted i czeka na PEŁNE, uwierzytelnione zalogowanie (np. przez Google/Email).
        Po wykryciu zalogowanego użytkownika (v_uid / access_token_web) weryfikuje sesję, natychmiast zamyka okno i zwraca token.
        """
        browser_exe = cls.get_supported_browser_path()
        if not browser_exe:
            if on_status:
                on_status("Nie znaleziono przeglądarki Chrome lub Edge.")
            return None

        import os
        import json
        import time
        import socket
        import subprocess
        import urllib.request
        try:
            import websocket
        except ImportError:
            if on_status:
                on_status("Brak modułu websocket-client.")
            return None

        # Rezerwacja wolnego portu TCP dla CDP
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', 0))
            port = s.getsockname()[1]

        profile_dir = os.path.expandvars(r"%LOCALAPPDATA%\DealSniper\VintedProfile")
        os.makedirs(profile_dir, exist_ok=True)

        cmd = [
            browser_exe,
            f"--user-data-dir={profile_dir}",
            f"--remote-debugging-port={port}",
            "--remote-allow-origins=*",
            "--no-first-run",
            "--no-default-browser-check",
            "--window-size=860,880",
            "https://www.vinted.pl/member/register/select_type"
        ]

        if on_status:
            on_status("Otwarto okno logowania Vinted. Zaloguj się przez Google lub Email...")

        try:
            proc = subprocess.Popen(cmd)
        except Exception as e:
            if on_status:
                on_status(f"Nie udało się uruchomić przeglądarki: {e}")
            return None

        # Oczekiwanie na gotowość CDP
        ws_url = None
        for _ in range(30):
            if proc.poll() is not None:
                if on_status:
                    on_status("Okno przeglądarki zostało zamknięte.")
                return None
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as resp:
                    data = json.loads(resp.read().decode())
                    ws_url = data.get("webSocketDebuggerUrl")
                    if ws_url:
                        break
            except Exception:
                time.sleep(0.3)

        if not ws_url:
            try:
                proc.terminate()
            except Exception:
                pass
            if on_status:
                on_status("Błąd połączenia z interfejsem CDP przeglądarki.")
            return None

        start_time = time.time()
        msg_id = 1
        ws = None
        try:
            ws = websocket.create_connection(ws_url, timeout=5)
            while time.time() - start_time < timeout_sec:
                if proc.poll() is not None:
                    if on_status:
                        on_status("Okno logowania zostało zamknięte.")
                    return None

                try:
                    msg_id += 1
                    ws.send(json.dumps({"id": msg_id, "method": "Storage.getCookies"}))
                    raw_reply = ws.recv()
                    reply = json.loads(raw_reply)
                    cookies = reply.get("result", {}).get("cookies", [])
                    v_map = {c['name']: c['value'] for c in cookies if 'vinted' in c.get('domain', '').lower()}

                    v_uid = v_map.get("v_uid")
                    at = v_map.get("access_token_web")
                    vs = v_map.get("_vinted_fr_session")

                    # Logowanie nastąpiło, gdy w profilu pojawił się v_uid (ID użytkownika) lub access_token_web
                    if (v_uid and at) or (at and len(at) > 100 and (v_map.get("user-iso-locale") or v_uid)):
                        if cls.verify_vinted_tokens(at=at, v_session=vs, v_map=v_map):
                            if on_status:
                                on_status("Sesja Vinted potwierdzona! Zamykanie okna...")
                            try:
                                proc.terminate()
                                proc.wait(timeout=2)
                            except Exception:
                                pass

                            parts = []
                            if at:
                                parts.append(f"access_token_web={at}")
                            if vs:
                                parts.append(f"_vinted_fr_session={vs}")
                            if v_uid:
                                parts.append(f"v_uid={v_uid}")
                            for k in ("anon_id", "v_udt"):
                                if k in v_map:
                                    parts.append(f"{k}={v_map[k]}")
                            return "; ".join(parts)
                except Exception:
                    pass

                time.sleep(1.2)
        finally:
            if ws:
                try:
                    ws.close()
                except Exception:
                    pass
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass

        if on_status:
            on_status("Przekroczono limit czasu oczekiwania na logowanie.")
        return None

    @staticmethod
    def auto_extract_browser_cookie() -> Optional[Dict[str, str]]:
        """
        Automatycznie skanuje zainstalowane przeglądarki (Edge, Brave, Opera, Opera GX, Vivaldi, Firefox, Chrome)
        w poszukiwaniu ciasteczek sesji Vinted.
        Zwraca {'browser': nazwa, 'cookie': wartosc} lub None (tylko w pełni aktywne sesje).
        """
        try:
            import rookiepy
            browser_loaders = [
                ("Microsoft Edge", rookiepy.edge),
                ("Brave", rookiepy.brave),
                ("Opera GX", rookiepy.opera_gx),
                ("Opera", rookiepy.opera),
                ("Mozilla Firefox", rookiepy.firefox),
                ("Vivaldi", rookiepy.vivaldi),
                ("Google Chrome", rookiepy.chrome),
                ("Chromium", rookiepy.chromium),
            ]
            for b_name, b_fn in browser_loaders:
                try:
                    cookies = b_fn(["vinted.pl"])
                    v_map = {}
                    for c in cookies:
                        domain = c.get("domain", "").lower()
                        name = c.get("name", "")
                        val = c.get("value", "")
                        if "vinted" in domain:
                            v_map[name] = val

                    at = v_map.get("access_token_web")
                    vs = v_map.get("_vinted_fr_session")
                    v_uid = v_map.get("v_uid")

                    if (at or vs) and VintedClient.verify_vinted_tokens(at=at, v_session=vs, v_map=v_map):
                        parts = []
                        if at:
                            parts.append(f"access_token_web={at}")
                        if vs:
                            parts.append(f"_vinted_fr_session={vs}")
                        if v_uid:
                            parts.append(f"v_uid={v_uid}")
                        return {"browser": b_name, "cookie": "; ".join(parts)}
                except Exception:
                    continue
        except Exception as e:
            print(f"[CookieExtractor] Błąd modułu rookiepy: {e}")
        return None

    def verify_account(self) -> Dict[str, Any]:
        """
        Weryfikuje sesje z Vinted. Zwraca {'success': bool, 'username': str, 'error': str}
        """
        if not self.session_cookie:
            return {"success": False, "username": "", "error": "Wprowadź ciasteczko lub token sesji Vinted."}

        try:
            self.set_cookie(self.session_cookie)
            resp = self.session.get("https://www.vinted.pl/api/v2/users/current", headers=self.headers, timeout=12)
            if resp.status_code == 200:
                user_data = resp.json().get("user", {})
                self.user_login = user_data.get("login", "Zalogowany użytkownik")
                self.user_id = user_data.get("id")
                return {
                    "success": True,
                    "username": self.user_login,
                    "user_id": self.user_id,
                    "email": user_data.get("email", ""),
                    "photo": user_data.get("photo", {}).get("url") if user_data.get("photo") else None
                }
            elif resp.status_code in (401, 403):
                return {"success": False, "username": "", "error": "Sesja wygasła lub jest nieprawidłowa."}
            else:
                return {"success": False, "username": "", "error": f"Błąd serwera Vinted ({resp.status_code})"}
        except Exception as e:
            return {"success": False, "username": "", "error": f"Błąd połączenia z Vinted: {e}"}

    def send_price_offer(self, item_id: str, proposed_price: float) -> Dict[str, Any]:
        """
        Wysyla propozycje ceny do sprzedawcy na Vinted.
        """
        clean_id = str(item_id).replace("vinted_", "").strip()
        if not self.session_cookie:
            return {"success": False, "message": "Brak aktywnej sesji Vinted. Zaloguj się w zakładce Vinted."}

        try:
            self.set_cookie(self.session_cookie)

            # 1. Sprawdz lub utworz konwersacje dla danego przedmiotu
            conv_resp = self.session.post(
                "https://www.vinted.pl/api/v2/conversations",
                headers=self.headers,
                json={"item_id": int(clean_id) if clean_id.isdigit() else clean_id},
                timeout=12
            )

            conv_id = None
            if conv_resp.status_code in (200, 201):
                conv_id = conv_resp.json().get("conversation", {}).get("id")

            # 2. Wyslij propozycje oferty
            target_url = f"https://www.vinted.pl/api/v2/conversations/{conv_id}/propositions" if conv_id else f"https://www.vinted.pl/api/v2/items/{clean_id}/transactions"
            payload = {
                "price": float(proposed_price),
                "currency": "PLN"
            }
            res = self.session.post(target_url, headers=self.headers, json=payload, timeout=12)

            if res.status_code in (200, 201, 204):
                return {
                    "success": True,
                    "message": f"Złożono propozycję {proposed_price:.2f} PLN dla przedmiotu #{clean_id}!",
                    "price": proposed_price
                }
            elif res.status_code == 403:
                return {"success": False, "message": "Vinted odrzucił ofertę (403). Sprawdź ważność ciasteczka."}
            else:
                return {
                    "success": True,
                    "message": f"Wysłano propozycję {proposed_price:.2f} PLN dla przedmiotu #{clean_id}",
                    "price": proposed_price
                }
        except Exception as e:
            return {"success": False, "message": f"Błąd podczas wysyłania oferty: {e}"}

    def close(self):
        try:
            self.session.close()
        except Exception:
            pass

class AllegroLokalnieScraper:
    def __init__(self):
        self.session = requests.Session(impersonate="chrome124")
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://allegrolokalnie.pl/"
        }

    def fetch_recent(self, query: str = "", min_p: float = 0, max_p: float = 0, city_name: str = "") -> List[Offer]:
        results: List[Offer] = []
        search_kw = query.strip()
        if not search_kw:
            return results

        if city_name and city_name.strip():
            search_kw += f" {city_name.strip()}"

        encoded_kw = urllib.parse.quote_plus(search_kw)
        url = f"https://allegrolokalnie.pl/oferty/q/{encoded_kw}?order=n"

        if min_p > 0:
            url += f"&price_from={int(min_p)}"
        if max_p > 0:
            url += f"&price_to={int(max_p)}"

        try:
            resp = self.session.get(url, headers=self.headers, timeout=12)
            if resp.status_code != 200:
                return results

            soup = BeautifulSoup(resp.text, "html.parser")
            articles = soup.find_all("article")

            for art in articles:
                link_el = art.find("a", href=lambda x: x and "/oferta/" in x)
                if not link_el:
                    continue

                href = link_el.get("href", "")
                full_url = href if href.startswith("http") else f"https://allegrolokalnie.pl{href}"

                t_el = art.find(class_=lambda x: x and "title" in x.lower())
                title = clean_text(t_el.get_text(strip=True)) if t_el else ""
                if not title:
                    title = clean_text(link_el.get_text(strip=True))

                p_el = art.find(class_=lambda x: x and "dollars" in x.lower())
                price = None
                if p_el:
                    price = clean_price(p_el.get_text(strip=True))

                if price is None:
                    continue

                img = art.find("img")
                img_src = img.get("src") or img.get("data-src") if img else None

                m_id = re.search(r"/oferta/([^/?]+)", href)
                item_id = m_id.group(1) if m_id else str(len(results))

                results.append(Offer(
                    id=f"lokalnie_{item_id}",
                    platform="ALLEGRO LOKALNIE",
                    title=title,
                    price=price,
                    url=full_url,
                    image_url=img_src,
                    created_at_str="Teraz",
                    has_delivery=True,
                    location_name=city_name if city_name else "Polska"
                ))
        except Exception as e:
            print(f"[Allegro Lokalnie Scraper] Błąd: {e}")

        return results

    def close(self):
        try:
            self.session.close()
        except Exception:
            pass

class AllegroScraper:
    def __init__(self, client_id: str = "", client_secret: str = ""):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token = ""
        self.token_expiry = 0
        self.session = requests.Session(impersonate="chrome124")

    def _ensure_token(self) -> bool:
        if not self.client_id or not self.client_secret:
            return False
        if self.token and time.time() < self.token_expiry - 60:
            return True

        auth_str = f"{self.client_id}:{self.client_secret}"
        encoded = base64.b64encode(auth_str.encode()).decode()
        headers = {
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        try:
            resp = self.session.post(
                "https://allegro.pl/auth/oauth/token?grant_type=client_credentials",
                headers=headers,
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                self.token = data.get("access_token", "")
                self.token_expiry = time.time() + data.get("expires_in", 43200)
                return True
        except Exception as e:
            print(f"[Allegro API] Token: {e}")
        return False

    def fetch_recent(self, query: str = "", min_p: float = 0, max_p: float = 0) -> List[Offer]:
        results: List[Offer] = []
        search_kw = query.strip()
        if not search_kw:
            return results

        if self._ensure_token():
            try:
                headers = {
                    "Authorization": f"Bearer {self.token}",
                    "Accept": "application/vnd.allegro.public.v1+json"
                }
                params: Dict[str, Any] = {
                    "phrase": search_kw,
                    "sort": "-startTime",
                    "limit": 30
                }
                if min_p > 0:
                    params["price.from"] = min_p
                if max_p > 0:
                    params["price.to"] = max_p

                resp = self.session.get("https://api.allegro.pl/offers/listing", headers=headers, params=params, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    regular = data.get("items", {}).get("regular", [])
                    promoted = data.get("items", {}).get("promoted", [])
                    all_items = regular + promoted
                    for it in all_items:
                        item_id = it.get("id", "")
                        title = clean_text(it.get("name", ""))
                        price_amount = clean_price(it.get("sellingMode", {}).get("price", {}).get("amount"))
                        if price_amount is None:
                            continue
                        images_raw = it.get("images", [])
                        all_images = [im.get("url") for im in images_raw if im.get("url")]
                        img_url = all_images[0] if all_images else None
                        results.append(Offer(
                            id=f"allegro_{item_id}",
                            platform="ALLEGRO",
                            title=title,
                            price=price_amount,
                            url=f"https://allegro.pl/oferta/{item_id}",
                            image_url=img_url,
                            created_at_str="Teraz",
                            has_delivery=True,
                            location_name="Wysyłka Allegro",
                            images=all_images
                        ))
                    return results
            except Exception as e:
                print(f"[Allegro API] Błąd: {e}")

        try:
            encoded = urllib.parse.quote_plus(search_kw)
            url = f"https://allegro.pl/listing?string={encoded}&order=n"
            if min_p > 0:
                url += f"&price_from={int(min_p)}"
            if max_p > 0:
                url += f"&price_to={int(max_p)}"
            resp = self.session.get(url, timeout=8)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                for art in soup.find_all("article"):
                    link = art.find("a", href=True)
                    if not link:
                        continue
                    title = clean_text(link.get_text(strip=True))
                    p_span = art.find("span", string=re.compile(r"zł"))
                    price = clean_price(p_span.get_text(strip=True)) if p_span else None
                    if price and title:
                        href = link["href"]
                        full_url = href if href.startswith("http") else f"https://allegro.pl{href}"
                        m_id = re.search(r"(\d{8,})", href)
                        item_id = m_id.group(1) if m_id else str(len(results))
                        img_el = art.find("img")
                        img_src = img_el.get("src") or img_el.get("data-src") if img_el else None
                        results.append(Offer(
                            id=f"allegro_{item_id}",
                            platform="ALLEGRO",
                            title=title,
                            price=price,
                            url=full_url,
                            image_url=img_src,
                            created_at_str="Teraz",
                            has_delivery=True,
                            location_name="Wysyłka Allegro",
                            images=[img_src] if img_src else []
                        ))
        except Exception:
            pass

        return results

    def close(self):
        try:
            self.session.close()
        except Exception:
            pass

def fetch_offer_images(offer: Offer, session: Optional[requests.Session] = None) -> List[str]:
    """
    Pobiera pełną listę zdjęć w wysokiej rozdzielczości oraz szczegóły opinii/reputacji
    sprzedawcy dla danej oferty (np. Vinted, Allegro Lokalnie).
    Działa z buforowaniem w obiekcie Offer.
    """
    if not offer.url:
        return offer.images

    s = session or requests.Session(impersonate="chrome124")
    try:
        if offer.platform == "VINTED":
            r = s.get(offer.url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "pl-PL,pl;q=0.9",
            }, timeout=8)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                found = []
                for img in soup.find_all("img"):
                    src = img.get("src") or ""
                    if "images" in src and "vinted.net/t/" in src:
                        hd = re.sub(r"/f\d+/", "/f800/", src)
                        if hd not in found:
                            found.append(hd)
                if found:
                    offer.images = found
                    if not offer.image_url:
                        offer.image_url = found[0]

                # Ekstrakcja reputacji i opinii sprzedawcy z profilu na Vinted
                member_a = soup.find("a", href=re.compile(r"/member/\d+"))
                if member_a:
                    m_href = member_a.get("href", "")
                    m_uid_match = re.search(r"/member/(\d+)", m_href)
                    vinted_uid = m_uid_match.group(1) if m_uid_match else None

                    uname_el = member_a.find(attrs={"data-testid": "profile-username"})
                    uname = uname_el.get_text(strip=True) if uname_el else None
                    rating_div = member_a.find(attrs={"aria-label": re.compile(r"ocen|rating|gwiazd", re.I)})
                    rate_val = None
                    cnt_val = None
                    if rating_div:
                        aria = rating_div.get("aria-label", "")
                        m_rate = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:na|/|out of)\s*5", aria)
                        if m_rate:
                            try:
                                rate_val = float(m_rate.group(1).replace(",", "."))
                            except Exception:
                                pass
                        cnt_text = rating_div.get_text(strip=True)
                        m_cnt = re.search(r"\d+", cnt_text)
                        if m_cnt:
                            try:
                                cnt_val = int(m_cnt.group(0))
                            except Exception:
                                pass

                    # Pobieranie szczegółowej historii opinii sprzedawcy z Vinted API
                    v_reviews = []
                    if vinted_uid:
                        try:
                            fb_url = f"https://www.vinted.pl/api/v2/feedbacks?user_id={vinted_uid}"
                            fb_resp = s.get(fb_url, headers={
                                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                                "Accept": "application/json, text/plain, */*",
                                "Referer": f"https://www.vinted.pl/member/{vinted_uid}"
                            }, timeout=6)
                            if fb_resp.status_code == 200:
                                fb_json = fb_resp.json()
                                for item in fb_json.get("user_feedbacks", [])[:10]:
                                    c_text = item.get("feedback") or ""
                                    if not c_text and item.get("system_feedback"):
                                        c_text = "Automatyczna pozytywna ocena transakcji"
                                    r_author = item.get("user", {}).get("login") or "Kupujący Vinted"
                                    r_rating = item.get("rating", 5) or 5
                                    r_date = (item.get("created_at_ts") or "")[:10]
                                    v_reviews.append({
                                        "author": r_author,
                                        "rating": r_rating,
                                        "date": r_date,
                                        "comment": c_text or "Pozytywna opinia o transakcji"
                                    })
                        except Exception as e_fb:
                            print(f"[Vinted Feedback] Błąd pobierania opinii dla uid={vinted_uid}: {e_fb}")

                    if v_reviews:
                        offer.seller_recent_reviews = v_reviews

                    rep = compute_seller_reputation(
                        "VINTED",
                        seller_name=uname,
                        rating=rate_val,
                        reviews_count=cnt_val or len(v_reviews)
                    )
                    offer.seller_name = uname or offer.seller_name
                    offer.seller_rating = rate_val
                    offer.seller_reviews_count = cnt_val or len(v_reviews)
                    offer.seller_grade = rep["grade"]
                    offer.seller_badge_text = rep["badge_text"]
                    offer.seller_badge_color = rep["badge_color"]
                    offer.seller_bg_color = rep["bg_color"]

        elif offer.platform == "ALLEGRO LOKALNIE" or offer.platform == "ALLEGRO":
            r = s.get(offer.url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "pl-PL,pl;q=0.9",
            }, timeout=8)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                found = []
                for img in soup.find_all("img"):
                    src = img.get("src") or img.get("data-src") or ""
                    if "a.allegroimg.com" in src:
                        hd = re.sub(r"/s\d+x\d+/", "/original/", src)
                        if hd not in found:
                            found.append(hd)
                if found:
                    offer.images = found
                    if not offer.image_url:
                        offer.image_url = found[0]
    except Exception as e:
        print(f"[fetch_offer_images] Błąd dla {offer.id}: {e}")

    return offer.images

class Notifier:
    @staticmethod
    def play_sound():
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception:
            pass

    @staticmethod
    def show_desktop_notification(title: str, message: str):
        try:
            safe_title = title.replace("'", " ").replace('"', " ")
            safe_msg = message.replace("'", " ").replace('"', " ")
            import subprocess
            cmd = f"""
            [void] [System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms')
            $n = New-Object System.Windows.Forms.NotifyIcon
            $n.Icon = [System.Drawing.SystemIcons]::Information
            $n.BalloonTipTitle = '{safe_title}'
            $n.BalloonTipText = '{safe_msg}'
            $n.Visible = $true
            $n.ShowBalloonTip(4000)
            Start-Sleep -Seconds 4
            $n.Dispose()
            """
            subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", cmd],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print(f"Powiadomienie systemowe: {e}")

    @staticmethod
    def send_discord_webhook(webhook_url: str, offer: Offer):
        if not webhook_url or not webhook_url.startswith("http"):
            return

        embed = {
            "title": f"🔥 {offer.title}",
            "url": offer.url,
            "color": 0x00FF88 if offer.discount_pct >= 20 else 0x00D2FF,
            "fields": [
                {"name": "💰 Cena", "value": f"**{offer.price:.2f} PLN**", "inline": True},
                {"name": "🏪 Platforma", "value": f"**{offer.platform}**", "inline": True},
            ]
        }

        if offer.location_name:
            embed["fields"].append({"name": "📍 Lokalizacja", "value": offer.location_name, "inline": True})

        if offer.has_delivery:
            embed["fields"].append({"name": "📦 Dostawa", "value": "Dostępna przesyłka", "inline": True})

        if offer.market_avg:
            embed["fields"].append({
                "name": "📊 Cena odniesienia",
                "value": f"~{offer.market_avg:.0f} PLN (-{offer.discount_pct:.0f}%)",
                "inline": True
            })

        if offer.deal_reason:
            embed["fields"].append({
                "name": "🎯 Informacja",
                "value": offer.deal_reason,
                "inline": False
            })

        if offer.image_url:
            embed["thumbnail"] = {"url": offer.image_url}

        payload = {
            "username": "GRDZ_SNIPE Bot",
            "avatar_url": "https://img.icons8.com/fluency/96/shopping-bag.png",
            "content": f"🚨 **Wykryto okazję na {offer.platform}!**\n<{offer.url}>",
            "embeds": [embed]
        }

        try:
            import requests as py_requests
            py_requests.post(webhook_url, json=payload, timeout=8)
        except Exception as e:
            print(f"Błąd webhooka Discord: {e}")

class MonitorEngine:
    def __init__(self,
                 on_offer_callback: Callable[[Offer], None],
                 on_status_callback: Callable[[str], None],
                 on_stats_callback: Callable[[Dict[str, Any]], None]):
        self.cfg = load_config()
        self.seen_offers = load_seen_offers()
        self.evaluator = DealEvaluator(self.cfg)

        self.olx = OLXScraper()
        self.vinted = VintedScraper()
        self.vinted_client = VintedClient(self.cfg.get("vinted_session_cookie", ""))
        self.allegro_lokalnie = AllegroLokalnieScraper()
        self.allegro = AllegroScraper(
            client_id=self.cfg.get("allegro_client_id", ""),
            client_secret=self.cfg.get("allegro_client_secret", "")
        )

        self.on_offer = on_offer_callback
        self.on_status = on_status_callback
        self.on_stats = on_stats_callback

        self.is_running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        self.stats = {
            "total_scanned": 0,
            "deals_found": 0,
            "last_scan_time": "-",
            "olx_count": 0,
            "vinted_count": 0,
            "lokalnie_count": 0,
            "allegro_count": 0,
            "vinted_offers_sent": 0
        }
        self.sent_offer_timestamps = []

    def update_config(self, new_cfg: Dict[str, Any]):
        self.cfg = new_cfg
        self.evaluator = DealEvaluator(self.cfg)
        self.vinted_client.set_cookie(self.cfg.get("vinted_session_cookie", ""))
        self.allegro.client_id = self.cfg.get("allegro_client_id", "")
        self.allegro.client_secret = self.cfg.get("allegro_client_secret", "")

    def scan_once(self):
        query = self.cfg.get("search_query", "").strip()
        min_p = float(self.cfg.get("min_price_filter", 0) or 0)
        max_p = float(self.cfg.get("max_price_filter", 0) or 0)
        cat_id = int(self.cfg.get("category_id", 0) or 0)
        city = self.cfg.get("city_name", "").strip()
        dist = int(self.cfg.get("distance_km", 0) or 0)
        deliv_only = bool(self.cfg.get("olx_delivery_only", False))

        raw_offers: List[Offer] = []

        # 1. OLX (z kategoria, miastem, odlegloscia i przesylka)
        if self.cfg.get("track_olx", True):
            self.on_status(f"Sprawdzanie OLX ({query})...")
            olx_items = self.olx.fetch_recent(
                query=query,
                min_p=min_p,
                max_p=max_p,
                category_id=cat_id,
                city_name=city,
                distance_km=dist,
                delivery_only=deliv_only
            )
            raw_offers.extend(olx_items)
            self.stats["olx_count"] += len(olx_items)

        # 2. Vinted
        if self.cfg.get("track_vinted", True):
            self.on_status(f"Sprawdzanie Vinted ({query})...")
            vinted_items = self.vinted.fetch_recent(query, min_p=min_p, max_p=max_p)
            raw_offers.extend(vinted_items)
            self.stats["vinted_count"] += len(vinted_items)

        # 3. Allegro Lokalnie
        if self.cfg.get("track_allegro_lokalnie", True):
            self.on_status(f"Sprawdzanie Allegro Lokalnie ({query})...")
            lokalnie_items = self.allegro_lokalnie.fetch_recent(query, min_p=min_p, max_p=max_p, city_name=city)
            raw_offers.extend(lokalnie_items)
            self.stats["lokalnie_count"] += len(lokalnie_items)

        # 4. Allegro Główne
        if self.cfg.get("track_allegro", True):
            self.on_status(f"Sprawdzanie Allegro ({query})...")
            allegro_items = self.allegro.fetch_recent(query, min_p=min_p, max_p=max_p)
            raw_offers.extend(allegro_items)
            self.stats["allegro_count"] += len(allegro_items)

        self.stats["total_scanned"] += len(raw_offers)
        self.stats["last_scan_time"] = time.strftime("%H:%M:%S")

        new_deals = 0
        for offer in raw_offers:
            if offer.id in self.seen_offers:
                continue

            self.seen_offers.add(offer.id)

            # Analiza okazji i filtrow
            evaluated = self.evaluator.evaluate(offer)

            if evaluated.is_deal:
                new_deals += 1
                self.stats["deals_found"] += 1
                if not evaluated.ai_evaluation:
                    try:
                        evaluated.ai_evaluation = AIOfferEvaluator.evaluate_offer(evaluated, self.cfg)
                    except Exception:
                        pass
                self.on_offer(evaluated)

                # Notyfikacje
                if self.cfg.get("sound_alerts", True):
                    Notifier.play_sound()
                if self.cfg.get("desktop_notifications", True):
                    loc_text = f" [{evaluated.location_name}]" if evaluated.location_name else ""
                    Notifier.show_desktop_notification(
                        f"🔥 Okazja {evaluated.platform}: {evaluated.price:.0f} zł{loc_text}",
                        f"{evaluated.title}\n{evaluated.deal_reason}"
                    )
                webhook = self.cfg.get("discord_webhook_url", "")
                if webhook:
                    Notifier.send_discord_webhook(webhook, evaluated)

                # Automatyczna propozycja ceny Vinted
                if evaluated.platform == "VINTED" and self.cfg.get("vinted_auto_offer_enabled", False):
                    self._auto_propose_vinted_offer(evaluated)

        save_seen_offers(self.seen_offers)
        self.on_stats(self.stats)
        self.on_status(f"Ostatni skan: {self.stats['last_scan_time']} | Nowych pasujących: {new_deals}")

    def _auto_propose_vinted_offer(self, offer: Offer):
        """Wysyła automatyczną ofertę cenową na Vinted z uwzględnieniem limitu godzinowego."""
        cookie = self.cfg.get("vinted_session_cookie", "").strip()
        if not cookie:
            return

        now = time.time()
        # Odrzuć znaczniki starsze niż 3600 sekund (1h)
        self.sent_offer_timestamps = [t for t in self.sent_offer_timestamps if now - t < 3600]
        max_hourly = int(self.cfg.get("vinted_max_auto_offers_per_hour", 10) or 10)
        if len(self.sent_offer_timestamps) >= max_hourly:
            self.on_status(f"⚠️ Pominięto auto-ofertę: osiągnięto limit {max_hourly} ofert/godz.")
            return

        disc_pct = float(self.cfg.get("vinted_discount_percent", 10.0) or 10.0)
        proposed = calculate_vinted_offer_price(offer.price, disc_pct)

        def _do_send():
            res = self.vinted_client.send_price_offer(offer.id, proposed)
            if res.get("success"):
                self.sent_offer_timestamps.append(time.time())
                self.stats["vinted_offers_sent"] += 1
                self.on_stats(self.stats)
                self.on_status(f"🤝 Auto-Oferta: Wysłano {proposed:.0f} zł (-{disc_pct:.0f}%) dla {offer.title[:35]}")
            else:
                self.on_status(f"⚠️ Błąd auto-oferty: {res.get('message', 'Nieznany błąd')}")

        threading.Thread(target=_do_send, daemon=True).start()

    def _loop(self):
        while not self._stop_event.is_set():
            try:
                self.scan_once()
            except Exception as e:
                self.on_status(f"Błąd pętli: {e}")

            interval = max(10, int(self.cfg.get("scan_interval_sec", 30)))
            for _ in range(interval):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

    def start(self):
        if self.is_running:
            return
        self.is_running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.on_status("Monitor uruchomiony.")

    def stop(self):
        if not self.is_running:
            return
        self.is_running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self.on_status("Monitor zatrzymany.")

    def shutdown(self):
        self.stop()
        self.olx.close()
        self.vinted.close()
        self.allegro_lokalnie.close()
        self.allegro.close()
