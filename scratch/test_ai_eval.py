# c:/Users/Kacper/Desktop/skrypt/scratch/test_ai_eval.py
import re
from typing import Dict, Any, Optional

POPULAR_MARKET_BENCHMARKS = {
    # iPhones
    "iphone 11": 750,
    "iphone 12 mini": 950,
    "iphone 12 pro max": 1700,
    "iphone 12 pro": 1400,
    "iphone 12": 1150,
    "iphone 13 mini": 1350,
    "iphone 13 pro max": 2300,
    "iphone 13 pro": 2000,
    "iphone 13": 1600,
    "iphone 14 pro max": 2900,
    "iphone 14 pro": 2600,
    "iphone 14 plus": 2100,
    "iphone 14": 1950,
    "iphone 15 pro max": 3800,
    "iphone 15 pro": 3300,
    "iphone 15": 2700,
    "iphone 16": 3400,
    # Consoles
    "ps5": 1600,
    "playstation 5": 1600,
    "ps4 pro": 650,
    "ps4": 450,
    "xbox series x": 1400,
    "xbox series s": 750,
    "nintendo switch oled": 950,
    "nintendo switch": 650,
    "steam deck": 1350,
    # Samsung
    "s21": 800,
    "s22": 1250,
    "s23": 1850,
    "s24": 2500,
    # GPUs
    "rtx 3060 ti": 1150,
    "rtx 3060": 950,
    "rtx 3070 ti": 1450,
    "rtx 3070": 1300,
    "rtx 3080 ti": 2100,
    "rtx 3080": 1850,
    "rtx 4060 ti": 1450,
    "rtx 4060": 1150,
    "rtx 4070 ti": 2700,
    "rtx 4070": 2200,
    "rx 6600": 700,
    "rx 6650 xt": 850,
    "rx 6700 xt": 1150,
    "rx 7800 xt": 2000,
}

DAMAGE_RULES = [
    {
        "key": "screen_glass",
        "patterns": [r"zbit(?:a|e)\s+szyb(?:ka|ki)", r"pęknięt(?:a|e)\s+szyb(?:ka|ki)", r"pekniet(?:a|e)\s+szyb(?:ka|ki)", r"zbitka", r"dotyk\s+działa", r"szybka\s+do\s+wymiany"],
        "name": "Zbita szybka (dotyk i matryca sprawne)",
        "parts_min": 70, "parts_max": 160,
        "service_min": 80, "service_max": 150,
        "notes": "Możliwa refabrykacja samej szybki z zachowaniem oryginalnego wyświetlacza."
    },
    {
        "key": "screen_display",
        "patterns": [r"rozbit(?:y|a|e)\s+ekran", r"zbit(?:y|a|e)\s+ekran", r"uszkodzon(?:y|a)\s+ekran", r"uszkodzon(?:y|a)\s+wyświetlacz", r"uszkodzon(?:y|a)\s+matryc(?:a|e)", r"paski\s+na\s+ekranie", r"wylan(?:y|a)\s+ekran", r"czarny\s+ekran", r"plam(?:a|y)\s+na\s+ekranie"],
        "name": "Uszkodzony wyświetlacz / matryca (brak obrazu / paski)",
        "parts_min": 180, "parts_max": 480,
        "service_min": 70, "service_max": 140,
        "notes": "Wymaga wymiany całego modułu wyświetlacza wraz z dotykiem."
    },
    {
        "key": "battery",
        "patterns": [r"bateri(?:a|e)\s+do\s+wymiany", r"słab(?:a|y)\s+bateri(?:a|e)", r"kondycj(?:a|i)\s+baterii\s*(?:[567]\d%)", r"kondycj(?:a|i)\s*(?:[567]\d%)", r"bateria\s+spuchnięta", r"nie\s+trzyma\s+baterii", r"szybko\s+się\s+rozładowuje"],
        "name": "Zużyta / spuchnięta bateria",
        "parts_min": 60, "parts_max": 130,
        "service_min": 50, "service_max": 90,
        "notes": "Prosta wymiana akumulatora. W modelach Apple zalecane przelutowanie BMS lub zaprogramowanie kondycji."
    },
    {
        "key": "housing_back",
        "patterns": [r"zbit(?:y|e)\s+tył", r"pęknięt(?:y|e)\s+tył", r"zbit(?:e|a)\s+plecki", r"pęknięt(?:e|a)\s+plecki", r"pęknięt(?:a|e)\s+klapk(?:a|i)"],
        "name": "Pęknięte plecki / zbity tył obudowy",
        "parts_min": 50, "parts_max": 120,
        "service_min": 60, "service_max": 110,
        "notes": "Wymiana tylnej szybki (laserowo lub po demontażu korpusu)."
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
        "notes": "Tania i łatwa wymiana wentylatorów + nałożenie nowej pasty termoprzewodzącej."
    },
    {
        "key": "port_power",
        "patterns": [r"uszkodzon(?:e|y)\s+gniazdo", r"nie\s+ładuje", r"uszkodzon(?:e|y)\s+hdmi", r"wyrwan(?:e|y)\s+port", r"luźn(?:y|e)\s+gniazdo"],
        "name": "Uszkodzone gniazdo ładowania / HDMI / USB",
        "parts_min": 25, "parts_max": 60,
        "service_min": 80, "service_max": 150,
        "notes": "Wymiana gniazda na płycie głównej. Standardowa naprawa w konsolach (PS5/Xbox) i telefonach."
    },
    {
        "key": "stick_drift",
        "patterns": [r"drift\s+analog(?:a|ów)", r"dryfuj(?:ący|e)\s+analog", r"driftuje", r"analog\s+do\s+wymiany"],
        "name": "Dryfujący analog (drifting stick)",
        "parts_min": 20, "parts_max": 45,
        "service_min": 40, "service_max": 80,
        "notes": "Zalecany montaż nowoczesnych analogów z efektem Halla (odpornych na zużycie)."
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

def analyze_offer_ai(title: str, price: float, expected_market: float = 0) -> Dict[str, Any]:
    t_low = title.lower()
    
    # 1. Wykrycie uszkodzenia
    detected_damage = None
    for rule in DAMAGE_RULES:
        for pat in rule["patterns"]:
            if re.search(pat, t_low):
                detected_damage = rule
                break
        if detected_damage:
            break

    # 2. Szacowanie wartosci rynkowej
    market_val = expected_market
    if market_val <= 0:
        for bench_key, val in sorted(POPULAR_MARKET_BENCHMARKS.items(), key=lambda x: len(x[0]), reverse=True):
            if re.search(r"\b" + re.escape(bench_key) + r"\b", t_low):
                market_val = float(val)
                break

    if market_val <= 0:
        if detected_damage:
            market_val = max(price * 2.1, price + 350)
        else:
            market_val = price * 1.15

    is_damaged = detected_damage is not None

    if is_damaged:
        d = detected_damage
        repair_parts_avg = (d["parts_min"] + d["parts_max"]) / 2
        repair_serv_avg = (d["service_min"] + d["service_max"]) / 2
        total_repair_min = d["parts_min"] + d["service_min"]
        total_repair_max = d["parts_max"] + d["service_max"]
        total_repair_avg = (total_repair_min + total_repair_max) / 2
        
        total_investment = price + total_repair_avg
        profit_after_repair = round(market_val - total_investment)
        roi_pct = round((profit_after_repair / total_investment) * 100) if total_investment > 0 else 0
        
        if profit_after_repair >= 160:
            verdict_badge = "🟢 BARDZO OPŁACA SIĘ NAPRAWIĆ"
            verdict_short = f"Zysk po naprawie: +{profit_after_repair} zł (+{roi_pct}%)"
            recommendation = (
                f"Świetna okazja flipperska! Zakup za {price:.0f} zł + części i robocizna (~{total_repair_avg:.0f} zł) "
                f"to łącznie ok. {total_investment:.0f} zł. Po naprawie sprzęt jest wart ok. {market_val:.0f} zł, "
                f"co daje około {profit_after_repair} zł czystego zysku. {d['notes']}"
            )
        elif profit_after_repair > 20:
            verdict_badge = "🟡 UMIARKOWANIE OPŁACALNA NAPRAWA"
            verdict_short = f"Zysk po naprawie: ok. +{profit_after_repair} zł"
            recommendation = (
                f"Opłacalne przy naprawie własnej lub tanich częściach. Całkowity koszt (~{total_investment:.0f} zł) "
                f"zostawia ok. {profit_after_repair} zł marży względem wartości sprawnego (~{market_val:.0f} zł). {d['notes']}"
            )
        else:
            verdict_badge = "🔴 NIEOPŁACALNA NAPRAWA"
            verdict_short = f"Ryzyko straty: {abs(profit_after_repair)} zł"
            recommendation = (
                f"Odradzamy zakup pod kątem naprawy. Koszt sprzętu i serwisu ({total_investment:.0f} zł) "
                f"przekracza lub zrównuje się z rynkową ceną sprawnego egzemplarza ({market_val:.0f} zł)."
            )

        return {
            "is_profitable": profit_after_repair > 50,
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
            "badge_color": "#00ff88" if profit_after_repair >= 160 else ("#fbbf24" if profit_after_repair > 20 else "#f43f5e")
        }
    else:
        diff = round(market_val - price)
        disc_pct = round((diff / market_val) * 100) if market_val > 0 else 0

        if disc_pct >= 25:
            verdict_badge = "🟢 SUPER OKAZJA"
            verdict_short = f"Cena -{disc_pct}% vs rynek (oszczędzasz ~{diff} zł)"
            recommendation = (
                f"Znakomita cena! Egzemplarz sprawny, wyceniony {disc_pct}% poniżej typowej ceny rynkowej "
                f"(~{market_val:.0f} zł). Bardzo wysoka opłacalność zarówno do użytku, jak i natychmiastowej odsprzedaży."
            )
            bcol = "#00ff88"
            prof = True
        elif disc_pct >= 10:
            verdict_badge = "🟢 OPŁACALNA OFERTA"
            verdict_short = f"Poniżej średniej o {disc_pct}% (~{diff} zł taniej)"
            recommendation = (
                f"Dobra, uczciwa okazja. Cena jest o {disc_pct}% niższa od rynkowej normy (~{market_val:.0f} zł). "
                f"Warto rozważyć zakup."
            )
            bcol = "#34d399"
            prof = True
        elif disc_pct >= -8:
            verdict_badge = "🟡 CENA STANDARDOWA"
            verdict_short = f"Cena rynkowa (~{market_val:.0f} zł)"
            recommendation = (
                f"Oferta w normalnym przedziale rynkowym. Brak marży pod flipowanie, ale dobra, jeśli szukasz sprzętu dla siebie."
            )
            bcol = "#fbbf24"
            prof = False
        else:
            verdict_badge = "🔴 NIEOPŁACALNE"
            verdict_short = f"Powyżej rynku o {abs(disc_pct)}% (+{abs(diff)} zł)"
            recommendation = (
                f"Cena jest wyższa od rynkowej (~{market_val:.0f} zł) o {abs(disc_pct)}%. Proponujemy złożyć kontrofertę lub poczekać."
            )
            bcol = "#f43f5e"
            prof = False

        return {
            "is_profitable": prof,
            "verdict_badge": verdict_badge,
            "verdict_short": verdict_short,
            "is_damaged": False,
            "damage_name": "Sprzęt sprawny / brak widocznych uszkodzeń",
            "repair_parts_range": "0 zł",
            "repair_service_range": "0 zł",
            "repair_total_range": "Naprawa niewymagana",
            "repair_total_avg": 0,
            "estimated_market_value": market_val,
            "total_investment": price,
            "profit_after_repair": diff,
            "roi_pct": disc_pct,
            "recommendation": recommendation,
            "badge_color": bcol
        }

if __name__ == "__main__":
    tests = [
        ("iPhone 13 128GB zbita szybka dotyk dziala", 800.0),
        ("Karta graficzna RTX 3070 8GB artefakty nie wstaje", 350.0),
        ("Playstation 5 PS5 z napedem uszkodzone gniazdo hdmi", 600.0),
        ("Samsung Galaxy S22 128gb sprawny stan bdb", 950.0),
        ("Nintendo Switch V2 ladowarka gra drift analoga", 320.0),
        ("iPhone 11 64GB bateria do wymiany 72%", 400.0),
        ("Karta graficzna RX 6650 XT 8GB nowa gwarancja", 750.0),
    ]
    for t, p in tests:
        res = analyze_offer_ai(t, p)
        print(f"\n[{res['verdict_badge']}] {t} ({p} zł)")
        print(f"-> {res['verdict_short']}")
        if res['is_damaged']:
            print(f"   Usterka: {res['damage_name']} | Koszt naprawy: {res['repair_total_range']}")
        print(f"   Porada: {res['recommendation']}")
