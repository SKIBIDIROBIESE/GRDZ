# c:/Users/Kacper/Desktop/skrypt/gui.py
# python / gui.py / cpython 3.12 / x64 / windows
"""
GRDZ_SNIPE — Profesjonalny kombajn i monitor okazji cenowych
dla serwisow OLX, Vinted, Allegro Lokalnie oraz Allegro.
Nowoczesny interfejs CustomTkinter w stylistyce Obsidian Black & Neon Violet,
z dedykowana ikona, zakladkami, modulem Ulubione Wyszukiwania (Presets),
wyborem kategorii, filtrem Przesylka OLX oraz lokalizacja i promieniem w km.
"""

import os
import sys
import time
import webbrowser
import io
import gc
import threading
import collections
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
import customtkinter as ctk
from PIL import Image
from typing import Dict, Any, List, Optional, Callable
from curl_cffi import requests

from config import (
    load_config, save_config, CATEGORIES_MAP, DISTANCE_OPTIONS,
    load_favorites, save_favorites, calculate_vinted_offer_price
)
from deal_engine import MonitorEngine, Offer, Notifier, fetch_offer_images, AIOfferEvaluator
from auth_engine import get_auth_engine, AuthEngine


class ImageLoader:
    """Wielowątkowy, wysoce zoptymalizowany loader zdjęć ofert z pulą sesji HTTP i buforem LRU."""
    _cache: Dict[str, ctk.CTkImage] = {}
    _lock = threading.Lock()
    _executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="img_loader")
    _pending_urls = set()
    _session: Optional[requests.Session] = None
    _MAX_CACHE_SIZE = 250

    @classmethod
    def _get_session(cls) -> requests.Session:
        if cls._session is None:
            cls._session = requests.Session(impersonate="chrome124")
        return cls._session

    @classmethod
    def clear_cache(cls) -> int:
        with cls._lock:
            count = len(cls._cache)
            cls._cache.clear()
            cls._pending_urls.clear()
        gc.collect()
        return count

    @classmethod
    def load_image(cls, url: Optional[str], size=(96, 96), on_ready: Optional[Callable[[ctk.CTkImage], None]] = None) -> Optional[ctk.CTkImage]:
        if not url or not str(url).strip():
            return None
        clean_url = str(url).strip()
        cache_key = f"{clean_url}_{size[0]}x{size[1]}"
        with cls._lock:
            if cache_key in cls._cache:
                return cls._cache[cache_key]
            if cache_key in cls._pending_urls:
                return None
            cls._pending_urls.add(cache_key)

        def _worker():
            try:
                s = cls._get_session()
                r = s.get(
                    clean_url,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                    timeout=8
                )
                if r.status_code == 200:
                    pil_img = Image.open(io.BytesIO(r.content))
                    if pil_img.mode not in ("RGB", "RGBA"):
                        pil_img = pil_img.convert("RGBA")
                    pil_img.thumbnail(size, Image.Resampling.LANCZOS)
                    ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=pil_img.size)
                    with cls._lock:
                        if len(cls._cache) >= cls._MAX_CACHE_SIZE:
                            cls._cache.pop(next(iter(cls._cache)), None)
                        cls._cache[cache_key] = ctk_img
                    if on_ready:
                        on_ready(ctk_img)
            except Exception:
                pass
            finally:
                with cls._lock:
                    cls._pending_urls.discard(cache_key)

        cls._executor.submit(_worker)
        return None

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

def _patch_customtkinter_smooth_scroll():
    """
    Zaawansowany, bezbłędny silnik przewijania CustomTkinter dla Windows/macOS/Linux:
    1. Likwiduje w 100% efekt 'hall of mirrors' (powielanie przycisków, czarne pasy, zielone smugi)
       przez usunięcie destrukcyjnego update_idletasks() podczas obsługi zdarzeń kółka myszy.
    2. Agreguje impulsy kółka myszy (delta coalescing) i wykonuje synchroniczny skok w cyklu
       after_idle, synchronizując bufor GDI BitBlt ze strumieniem klatek Windows.
    3. Zapewnia naturalny, płynny krok (ok. 30px na kliknięcie kółka) bez zacięć i bez lagów.
    """
    def _optimized_mouse_wheel_all(self, event):
        if not self._check_if_valid_scroll(event.widget):
            return

        if not hasattr(self, "_wheel_acc_y"):
            self._wheel_acc_y = 0
            self._wheel_acc_x = 0
            self._wheel_scheduled = False

        delta = getattr(event, "delta", 0)
        num = getattr(event, "num", 0)

        # Normalizacja delty dla różnych platform systemowych
        if sys.platform.startswith("win"):
            eff_delta = delta
        elif sys.platform == "darwin":
            eff_delta = -delta * 8
        else:
            eff_delta = 120 if num == 5 else (-120 if num == 4 else delta)

        is_horizontal = getattr(self, "_shift_pressed", False) or getattr(self, "_orientation", "vertical") == "horizontal"
        if is_horizontal:
            self._wheel_acc_x += eff_delta
        else:
            self._wheel_acc_y += eff_delta

        if not self._wheel_scheduled:
            self._wheel_scheduled = True
            def _flush():
                self._wheel_scheduled = False
                canvas = getattr(self, "_parent_canvas", None)
                if not canvas or not canvas.winfo_exists():
                    return

                # Obsługa przewijania pionowego
                if self._wheel_acc_y != 0:
                    dy = self._wheel_acc_y
                    self._wheel_acc_y = 0
                    if canvas.yview() != (0.0, 1.0):
                        steps = -int(dy / 4)
                        if steps != 0:
                            canvas.yview("scroll", steps, "units")

                # Obsługa przewijania poziomego
                if self._wheel_acc_x != 0:
                    dx = self._wheel_acc_x
                    self._wheel_acc_x = 0
                    if canvas.xview() != (0.0, 1.0):
                        steps = -int(dx / 4)
                        if steps != 0:
                            canvas.xview("scroll", steps, "units")

            self.after_idle(_flush)

    ctk.CTkScrollableFrame._mouse_wheel_all = _optimized_mouse_wheel_all

    _orig_scrollable_init = ctk.CTkScrollableFrame.__init__
    def _patched_scrollable_init(self, *args, **kwargs):
        _orig_scrollable_init(self, *args, **kwargs)
        if hasattr(self, "_scrollbar") and hasattr(self, "_parent_canvas"):
            def _sync_yview(*a):
                self._parent_canvas.yview(*a)
            self._scrollbar.configure(command=_sync_yview)

    ctk.CTkScrollableFrame.__init__ = _patched_scrollable_init

_patch_customtkinter_smooth_scroll()

# =========================================================================
# SYSTEM MOTYWÓW WIZUALNYCH GRDZ_SNIPE PRO
# =========================================================================
THEMES: Dict[str, Dict[str, Any]] = {
    "Obsydianowy Fiolet (Domyślny)": {
        "id": "obsidian_purple",
        "name": "Obsydianowy Fiolet (Domyślny)",
        "icon": "🟣",
        "desc": "Klasyczny, cybernetyczny fiolet na głębokim obsydianowym tle.",
        "bg_window": "#07050f",
        "bg_header": "#0d091e",
        "bg_tabview": "#0f0b21",
        "bg_card": "#15102b",
        "bg_card_deal": "#0d211a",
        "bg_section": "#140f29",
        "bg_feed_scroll": "#0a0717",
        "border_card": "#2d1f52",
        "border_deal": "#00ff88",
        "border_glow": "#a855f7",
        "accent_purple": "#a855f7",
        "accent_purple_hover": "#9333ea",
        "accent_violet": "#7c3aed",
        "accent_fuchsia": "#d946ef",
        "accent_mint": "#00ff88",
        "accent_cyan": "#38bdf8",
        "accent_amber": "#fbbf24",
        "accent_orange": "#ff6d00",
        "accent_red": "#f43f5e",
        "text_main": "#ffffff",
        "text_lavender": "#ede9fe",
        "text_muted": "#a78bfa",
        "text_dim": "#63528a",
        "swatches": ["#07050f", "#15102b", "#a855f7", "#00ff88"],
    },
    "Czarno-Pomarańczowy (Cyber Flame)": {
        "id": "cyber_flame",
        "name": "Czarno-Pomarańczowy (Cyber Flame)",
        "icon": "🔥",
        "desc": "Czysta czerń i agresywny, neonowy pomarańcz w stylu wyścigowym.",
        "bg_window": "#080604",
        "bg_header": "#110b06",
        "bg_tabview": "#140e08",
        "bg_card": "#1c1209",
        "bg_card_deal": "#261304",
        "bg_section": "#170f07",
        "bg_feed_scroll": "#060402",
        "border_card": "#45240c",
        "border_deal": "#ff7700",
        "border_glow": "#ff8800",
        "accent_purple": "#ff7700",
        "accent_purple_hover": "#ea580c",
        "accent_violet": "#f97316",
        "accent_fuchsia": "#fb923c",
        "accent_mint": "#ffaa00",
        "accent_cyan": "#fdba74",
        "accent_amber": "#f59e0b",
        "accent_orange": "#ff6d00",
        "accent_red": "#ef4444",
        "text_main": "#ffffff",
        "text_lavender": "#ffedd5",
        "text_muted": "#fb923c",
        "text_dim": "#7c2d12",
        "swatches": ["#080604", "#1c1209", "#ff7700", "#ffaa00"],
    },
    "Żółto-Granatowy (Navy Cyber Gold)": {
        "id": "navy_gold",
        "name": "Żółto-Granatowy (Navy Cyber Gold)",
        "icon": "⚡",
        "desc": "Głęboki granat marynarki wojennej z elektrycznym, złotym neonem.",
        "bg_window": "#050a17",
        "bg_header": "#0a1329",
        "bg_tabview": "#0b1630",
        "bg_card": "#101e40",
        "bg_card_deal": "#0c2738",
        "bg_section": "#0e1a38",
        "bg_feed_scroll": "#040813",
        "border_card": "#1e356b",
        "border_deal": "#facc15",
        "border_glow": "#fbbf24",
        "accent_purple": "#fbbf24",
        "accent_purple_hover": "#eab308",
        "accent_violet": "#38bdf8",
        "accent_fuchsia": "#fde047",
        "accent_mint": "#4ade80",
        "accent_cyan": "#38bdf8",
        "accent_amber": "#f59e0b",
        "accent_orange": "#f97316",
        "accent_red": "#f87171",
        "text_main": "#ffffff",
        "text_lavender": "#e0f2fe",
        "text_muted": "#93c5fd",
        "text_dim": "#3b82f6",
        "swatches": ["#050a17", "#101e40", "#fbbf24", "#38bdf8"],
    },
    "Cyber Szmaragd / Matrix (Emerald Void)": {
        "id": "emerald_matrix",
        "name": "Cyber Szmaragd / Matrix (Emerald Void)",
        "icon": "💚",
        "desc": "Ciemna zieleń terminala hakerskiego i jaskrawy neonowy szmaragd.",
        "bg_window": "#030805",
        "bg_header": "#07120a",
        "bg_tabview": "#09170d",
        "bg_card": "#0c2113",
        "bg_card_deal": "#082618",
        "bg_section": "#0b1c11",
        "bg_feed_scroll": "#020604",
        "border_card": "#163d23",
        "border_deal": "#00ff88",
        "border_glow": "#10b981",
        "accent_purple": "#10b981",
        "accent_purple_hover": "#059669",
        "accent_violet": "#00ff88",
        "accent_fuchsia": "#34d399",
        "accent_mint": "#00ff88",
        "accent_cyan": "#2dd4bf",
        "accent_amber": "#a3e635",
        "accent_orange": "#f59e0b",
        "accent_red": "#f43f5e",
        "text_main": "#ffffff",
        "text_lavender": "#d1fae5",
        "text_muted": "#6ee7b7",
        "text_dim": "#047857",
        "swatches": ["#030805", "#0c2113", "#10b981", "#00ff88"],
    },
    "Synthwave Neon 1984 (Miami Vice)": {
        "id": "synthwave_84",
        "name": "Synthwave Neon 1984 (Miami Vice)",
        "icon": "🌴",
        "desc": "Nocne retro Miami lat 80., gorący neonowy róż i laserowy cyjan.",
        "bg_window": "#0c0717",
        "bg_header": "#150c26",
        "bg_tabview": "#170e2b",
        "bg_card": "#21123d",
        "bg_card_deal": "#0f2838",
        "bg_section": "#1b0f33",
        "bg_feed_scroll": "#080410",
        "border_card": "#441a6b",
        "border_deal": "#00f0ff",
        "border_glow": "#ff2a85",
        "accent_purple": "#ff2a85",
        "accent_purple_hover": "#db146d",
        "accent_violet": "#7928ca",
        "accent_fuchsia": "#ff007f",
        "accent_mint": "#00f0ff",
        "accent_cyan": "#00f0ff",
        "accent_amber": "#fde047",
        "accent_orange": "#ff6d00",
        "accent_red": "#ff4757",
        "text_main": "#ffffff",
        "text_lavender": "#ffe4f1",
        "text_muted": "#f472b6",
        "text_dim": "#831843",
        "swatches": ["#0c0717", "#21123d", "#ff2a85", "#00f0ff"],
    },
    "Dracula Dark (Vampire Crimson)": {
        "id": "dracula_crimson",
        "name": "Dracula Dark (Vampire Crimson)",
        "icon": "🩸",
        "desc": "Gotycki grafit i krwisty, purpurowy karmazyn z lawendowym akcentem.",
        "bg_window": "#0d0b10",
        "bg_header": "#17121c",
        "bg_tabview": "#19141f",
        "bg_card": "#241a2b",
        "bg_card_deal": "#2e121b",
        "bg_section": "#1f1726",
        "bg_feed_scroll": "#08060a",
        "border_card": "#452445",
        "border_deal": "#f43f5e",
        "border_glow": "#e11d48",
        "accent_purple": "#f43f5e",
        "accent_purple_hover": "#be123c",
        "accent_violet": "#a855f7",
        "accent_fuchsia": "#fb7185",
        "accent_mint": "#34d399",
        "accent_cyan": "#38bdf8",
        "accent_amber": "#fbbf24",
        "accent_orange": "#fb923c",
        "accent_red": "#e11d48",
        "text_main": "#ffffff",
        "text_lavender": "#fce7f3",
        "text_muted": "#f472b6",
        "text_dim": "#881337",
        "swatches": ["#0d0b10", "#241a2b", "#f43f5e", "#a855f7"],
    }
}

# Inicjalizacja domyślnego motywu
THEME = dict(THEMES["Obsydianowy Fiolet (Domyślny)"])

class CyberModal:
    @staticmethod
    def _create_base(parent, title: str, width: int = 460, height: int = 220) -> ctk.CTkToplevel:
        modal = ctk.CTkToplevel(parent)
        modal.title(title)
        modal.configure(fg_color="#07050f")
        modal.resizable(False, False)
        modal.transient(parent)

        try:
            app_dir = getattr(parent, "app_dir", None)
            if not app_dir:
                app_dir = os.path.dirname(os.path.abspath(__file__))
            ico_path = os.path.join(app_dir, "icon.ico")
            if os.path.exists(ico_path):
                modal.iconbitmap(ico_path)
        except Exception:
            pass

        try:
            parent.update_idletasks()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            if pw > 100 and ph > 100:
                x = px + (pw - width) // 2
                y = py + (ph - height) // 2
            else:
                x = (parent.winfo_screenwidth() - width) // 2
                y = (parent.winfo_screenheight() - height) // 2
        except Exception:
            x = 250
            y = 250

        modal.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")
        modal.grab_set()
        modal.focus_force()
        return modal

    @staticmethod
    def show_info(parent, title: str, message: str, icon_symbol: str = "✨"):
        modal = CyberModal._create_base(parent, title, width=460, height=210)

        card = ctk.CTkFrame(modal, fg_color="#120c24", corner_radius=14, border_width=1, border_color="#3c2666")
        card.pack(fill="both", expand=True, padx=12, pady=12)

        top_row = ctk.CTkFrame(card, fg_color="transparent")
        top_row.pack(fill="x", padx=18, pady=(16, 6))

        ctk.CTkLabel(top_row, text=icon_symbol, font=ctk.CTkFont(size=22)).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(
            top_row, 
            text=title, 
            font=ctk.CTkFont(size=15, weight="bold"), 
            text_color="#ede9fe"
        ).pack(side="left")

        msg_lbl = ctk.CTkLabel(
            card, 
            text=message, 
            font=ctk.CTkFont(size=12), 
            text_color="#c4b5fd", 
            wraplength=400, 
            justify="left"
        )
        msg_lbl.pack(fill="x", padx=20, pady=(4, 16))

        def close_win(event=None):
            modal.destroy()

        btn_ok = ctk.CTkButton(
            card,
            text="Rozumiem",
            width=130,
            height=32,
            fg_color=THEME["accent_purple"],
            hover_color=THEME["accent_purple_hover"],
            font=ctk.CTkFont(size=12, weight="bold"),
            corner_radius=8,
            command=close_win
        )
        btn_ok.pack(pady=(0, 12))
        btn_ok.focus_set()
        modal.bind("<Return>", close_win)
        modal.bind("<Escape>", close_win)
        parent.wait_window(modal)

    @staticmethod
    def show_warning(parent, title: str, message: str):
        CyberModal.show_info(parent, title, message, icon_symbol="⚠️")

    @staticmethod
    def show_error(parent, title: str, message: str):
        CyberModal.show_info(parent, title, message, icon_symbol="❌")

    @staticmethod
    def show_confirm(parent, title: str, message: str, confirm_text: str = "Tak, usuń", cancel_text: str = "Anuluj") -> bool:
        modal = CyberModal._create_base(parent, title, width=460, height=220)
        result = {"confirmed": False}

        card = ctk.CTkFrame(modal, fg_color="#120c24", corner_radius=14, border_width=1, border_color="#4a152d")
        card.pack(fill="both", expand=True, padx=12, pady=12)

        top_row = ctk.CTkFrame(card, fg_color="transparent")
        top_row.pack(fill="x", padx=18, pady=(16, 6))

        ctk.CTkLabel(top_row, text="🗑️", font=ctk.CTkFont(size=22)).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(
            top_row, 
            text=title, 
            font=ctk.CTkFont(size=15, weight="bold"), 
            text_color="#fca5a5"
        ).pack(side="left")

        msg_lbl = ctk.CTkLabel(
            card, 
            text=message, 
            font=ctk.CTkFont(size=12), 
            text_color="#ede9fe", 
            wraplength=400, 
            justify="left"
        )
        msg_lbl.pack(fill="x", padx=20, pady=(4, 16))

        btn_box = ctk.CTkFrame(card, fg_color="transparent")
        btn_box.pack(pady=(0, 12))

        def on_confirm(event=None):
            result["confirmed"] = True
            modal.destroy()

        def on_cancel(event=None):
            result["confirmed"] = False
            modal.destroy()

        btn_yes = ctk.CTkButton(
            btn_box,
            text=confirm_text,
            width=125,
            height=32,
            fg_color="#881337",
            hover_color="#be123c",
            text_color="#ffffff",
            font=ctk.CTkFont(size=12, weight="bold"),
            corner_radius=8,
            command=on_confirm
        )
        btn_yes.pack(side="left", padx=8)

        btn_no = ctk.CTkButton(
            btn_box,
            text=cancel_text,
            width=110,
            height=32,
            fg_color="#21183c",
            hover_color="#362562",
            font=ctk.CTkFont(size=12),
            corner_radius=8,
            command=on_cancel
        )
        btn_no.pack(side="left", padx=8)

        btn_no.focus_set()
        modal.bind("<Escape>", on_cancel)
        modal.bind("<Return>", on_confirm)
        parent.wait_window(modal)
        return result["confirmed"]


class CyberLicenseModal:
    """
    Cybernetyczne okno autoryzacji KeyAuth w stylistyce aplikacji.
    Wymusza weryfikację aktywnego klucza licencyjnego z powiązaniem do HWID.
    """
    def __init__(self, parent, auth_engine: Any, on_success: Optional[Callable[[], None]] = None, allow_cancel: bool = False):
        self.parent = parent
        self.auth_engine = auth_engine
        self.on_success = on_success
        self.allow_cancel = allow_cancel
        self.success = False

        self.modal = CyberModal._create_base(parent, "GRDZ_SNIPE // Weryfikacja Licencji KeyAuth", width=540, height=480)
        self._build_ui()

        if not allow_cancel:
            self.modal.protocol("WM_DELETE_WINDOW", self._on_force_exit)
        else:
            self.modal.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_force_exit(self):
        try:
            self.modal.destroy()
        except Exception:
            pass
        if not self.success:
            try:
                self.parent.destroy()
            except Exception:
                pass
            sys.exit(0)

    def _on_close(self):
        try:
            self.modal.destroy()
        except Exception:
            pass

    def _build_ui(self):
        card = ctk.CTkFrame(self.modal, fg_color="#0e0a1f", corner_radius=14, border_width=1, border_color="#3c2666")
        card.pack(fill="both", expand=True, padx=12, pady=12)

        # Header
        top_bar = ctk.CTkFrame(card, fg_color="transparent")
        top_bar.pack(fill="x", padx=20, pady=(18, 8))

        ctk.CTkLabel(
            top_bar,
            text="⚡ KEYAUTH LICENSING GATE",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#f97316"
        ).pack(anchor="w")

        ctk.CTkLabel(
            top_bar,
            text="Wprowadź swój unikalny klucz licencyjny, aby uzyskać dostęp do funkcji programu.",
            font=ctk.CTkFont(size=11),
            text_color="#a78bfa"
        ).pack(anchor="w", pady=(3, 0))

        # HWID Box
        hwid_box = ctk.CTkFrame(card, fg_color="#150f2b", corner_radius=10, border_width=1, border_color="#2c1e4a")
        hwid_box.pack(fill="x", padx=20, pady=(10, 8))

        ctk.CTkLabel(
            hwid_box,
            text="Twój unikalny identyfikator sprzętowy (HWID):",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="#c4b5fd"
        ).pack(anchor="w", padx=14, pady=(10, 4))

        hwid_row = ctk.CTkFrame(hwid_box, fg_color="transparent")
        hwid_row.pack(fill="x", padx=14, pady=(0, 10))

        hwid_str = self.auth_engine.hwid if self.auth_engine else "UNKNOWN-HWID"
        hwid_entry = ctk.CTkEntry(
            hwid_row,
            fg_color="#080512",
            border_color="#3c2666",
            text_color="#38bdf8",
            font=ctk.CTkFont(size=11, family="Consolas"),
            height=32
        )
        hwid_entry.insert(0, hwid_str)
        hwid_entry.configure(state="readonly")
        hwid_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        def copy_hwid():
            self.parent.clipboard_clear()
            self.parent.clipboard_append(hwid_str)
            self.lbl_feedback.configure(text="✓ Skopiowano HWID do schowka!", text_color="#10b981")

        btn_copy = ctk.CTkButton(
            hwid_row,
            text="Kopiuj HWID",
            width=90,
            height=32,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#3c2666",
            hover_color="#53378b",
            command=copy_hwid
        )
        btn_copy.pack(side="right")

        # License Key Row
        key_box = ctk.CTkFrame(card, fg_color="transparent")
        key_box.pack(fill="x", padx=20, pady=(6, 4))

        ctk.CTkLabel(
            key_box,
            text="Klucz Licencyjny:",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#ede9fe"
        ).pack(anchor="w", pady=(0, 4))

        self.entry_key = ctk.CTkEntry(
            key_box,
            placeholder_text="np. SNIPE-PRO-DEV-2026",
            fg_color="#080512",
            border_color="#a855f7",
            text_color="#ffffff",
            font=ctk.CTkFont(size=13, family="Consolas", weight="bold"),
            height=38
        )
        initial_key = self.auth_engine.license_key if self.auth_engine else ""
        if initial_key:
            self.entry_key.insert(0, initial_key)
        self.entry_key.pack(fill="x")

        # Feedback text
        self.lbl_feedback = ctk.CTkLabel(
            card,
            text="Wpisz klucz i kliknij 'Aktywuj Licencję'.",
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8",
            wraplength=480
        )
        self.lbl_feedback.pack(fill="x", padx=20, pady=(8, 12))

        # Buttons
        btn_box = ctk.CTkFrame(card, fg_color="transparent")
        btn_box.pack(fill="x", padx=20, pady=(0, 14))

        self.btn_activate = ctk.CTkButton(
            btn_box,
            text="⚡ Aktywuj Licencję",
            height=38,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#f97316",
            hover_color="#ea580c",
            text_color="#ffffff",
            command=self._start_verification
        )
        self.btn_activate.pack(side="left", fill="x", expand=True, padx=(0, 8))

        btn_admin = ctk.CTkButton(
            btn_box,
            text="🌐 Panel Administratora",
            height=38,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#1e293b",
            hover_color="#334155",
            text_color="#cbd5e1",
            command=lambda: webbrowser.open(self.auth_engine.auth_server_url)
        )
        btn_admin.pack(side="right")

    def _start_verification(self):
        key = self.entry_key.get().strip()
        if not key:
            self.lbl_feedback.configure(text="Podaj klucz licencyjny przed weryfikacją.", text_color="#ef4444")
            return

        self.btn_activate.configure(state="disabled", text="Weryfikacja...")
        self.lbl_feedback.configure(text="Łączenie z serwerem licencji...", text_color="#38bdf8")

        def _worker():
            ok, msg = self.auth_engine.verify_license(key)
            self.parent.after(0, lambda: self._on_verify_done(ok, msg, key))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_verify_done(self, ok: bool, msg: str, key: str):
        self.btn_activate.configure(state="normal", text="⚡ Aktywuj Licencję")
        if ok:
            self.success = True
            self.lbl_feedback.configure(text=f"✓ {msg}", text_color="#10b981")
            self.auth_engine.license_key = key
            self.parent.cfg["license_key"] = key
            save_config(self.parent.cfg)
            if self.on_success:
                try:
                    self.on_success()
                except Exception:
                    pass
            self.parent.after(800, self._on_close)
        else:
            self.lbl_feedback.configure(text=f"✕ {msg}", text_color="#ef4444")


class CyberLightboxModal:

    """
    Nowoczesna, estetyczna przeglądarka galerii zdjęć (Cyber Lightbox)
    w stylistyce Obsidian Black & Neon Violet.
    Obsługuje:
    - Płynne powiększenie zdjęcia do dużej rozdzielczości
    - Nawigację strzałkami Lewo / Prawo (przyciski ekranowe + klawisze strzałek)
    - Pasek miniatur wszystkich zdjęć na dole z podświetleniem aktywnego
    - Licznik zdjęć [ X / N ]
    - Asynchroniczne dociąganie pełnej galerii jeśli początkowo było 1 zdjęcie
    - Przyciski szybkiej akcji (Otwórz ofertę, Raport AI)
    """
    def __init__(self, parent, offer: Offer, initial_index: int = 0, app_cfg: Optional[Dict[str, Any]] = None):
        self.parent = parent
        self.offer = offer
        self.app_cfg = app_cfg or {}
        self.images: List[str] = list(offer.images) if offer.images else ([offer.image_url] if offer.image_url else [])
        self.current_index = max(0, min(initial_index, len(self.images) - 1)) if self.images else 0
        self.thumb_buttons: List[ctk.CTkButton] = []

        self.modal = CyberModal._create_base(parent, f"Galeria GRDZ_SNIPE: {offer.title[:35]}", width=880, height=680)

        self._build_ui()
        self._show_active_image()

        if len(self.images) <= 1:
            threading.Thread(target=self._fetch_extra_gallery, daemon=True).start()

    def _fetch_extra_gallery(self):
        try:
            more_imgs = fetch_offer_images(self.offer)
            if more_imgs and len(more_imgs) > len(self.images):
                self.images = list(more_imgs)
                self.parent.after(0, self._rebuild_thumbnails)
        except Exception:
            pass

    def _build_ui(self):
        root_card = ctk.CTkFrame(
            self.modal,
            fg_color="#090615",
            corner_radius=16,
            border_width=1,
            border_color="#3c2666"
        )
        root_card.pack(fill="both", expand=True, padx=10, pady=10)

        top_bar = ctk.CTkFrame(root_card, fg_color="transparent")
        top_bar.pack(fill="x", padx=16, pady=(12, 8))

        p_col = "#064e3b" if self.offer.platform == "OLX" else ("#005b64" if self.offer.platform == "VINTED" else "#4c1d00")
        p_txt = "#34d399" if self.offer.platform == "OLX" else ("#38bdf8" if self.offer.platform == "VINTED" else "#fb923c")

        plat_lbl = ctk.CTkLabel(
            top_bar,
            text=f" {self.offer.platform} ",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=p_col,
            text_color=p_txt,
            corner_radius=6,
            height=26
        )
        plat_lbl.pack(side="left", padx=(0, 10))

        title_lbl = ctk.CTkLabel(
            top_bar,
            text=self.offer.title[:55] + ("..." if len(self.offer.title) > 55 else ""),
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#ede9fe"
        )
        title_lbl.pack(side="left", padx=(0, 10))

        price_lbl = ctk.CTkLabel(
            top_bar,
            text=f"{self.offer.price:.2f} PLN",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#00ff88"
        )
        price_lbl.pack(side="left")

        btn_close = ctk.CTkButton(
            top_bar,
            text="✕",
            width=32,
            height=32,
            fg_color="#1f1438",
            hover_color="#e11d48",
            font=ctk.CTkFont(size=14, weight="bold"),
            corner_radius=8,
            command=self.modal.destroy
        )
        btn_close.pack(side="right")

        self.lbl_counter = ctk.CTkLabel(
            top_bar,
            text="[ 0 / 0 ]",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#231742",
            text_color="#c4b5fd",
            corner_radius=6,
            height=26
        )
        self.lbl_counter.pack(side="right", padx=10)

        self.stage = ctk.CTkFrame(
            root_card,
            fg_color="#06030e",
            corner_radius=12,
            border_width=1,
            border_color="#261742"
        )
        self.stage.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        self.btn_prev = ctk.CTkButton(
            self.stage,
            text="◀",
            width=48,
            height=60,
            fg_color="#1c1236",
            hover_color="#7c3aed",
            font=ctk.CTkFont(size=20, weight="bold"),
            corner_radius=10,
            command=self.prev_image
        )
        self.btn_prev.pack(side="left", padx=12)

        self.img_container = ctk.CTkFrame(self.stage, fg_color="transparent")
        self.img_container.pack(side="left", fill="both", expand=True, pady=10)

        self.lbl_large_img = ctk.CTkLabel(
            self.img_container,
            text="🖼️ Ładowanie zdjęcia w wysokiej rozdzielczości...",
            font=ctk.CTkFont(size=13),
            text_color="#7c699b"
        )
        self.lbl_large_img.pack(expand=True)

        self.btn_next = ctk.CTkButton(
            self.stage,
            text="▶",
            width=48,
            height=60,
            fg_color="#1c1236",
            hover_color="#7c3aed",
            font=ctk.CTkFont(size=20, weight="bold"),
            corner_radius=10,
            command=self.next_image
        )
        self.btn_next.pack(side="right", padx=12)

        self.thumb_strip_frame = ctk.CTkScrollableFrame(
            root_card,
            orientation="horizontal",
            height=72,
            fg_color="#0c081c",
            corner_radius=10,
            border_width=1,
            border_color="#24183d"
        )
        self.thumb_strip_frame.pack(fill="x", padx=16, pady=(0, 8))

        self._render_thumbnail_buttons()

        action_bar = ctk.CTkFrame(root_card, fg_color="transparent")
        action_bar.pack(fill="x", padx=16, pady=(0, 8))

        btn_browser = ctk.CTkButton(
            action_bar,
            text="🌐 Otwórz ofertę w przeglądarce",
            height=34,
            fg_color=THEME["accent_violet"],
            hover_color=THEME["accent_purple_hover"],
            font=ctk.CTkFont(size=12, weight="bold"),
            corner_radius=8,
            command=self._open_url
        )
        btn_browser.pack(side="left", padx=(0, 10))

        btn_ai = ctk.CTkButton(
            action_bar,
            text="🧠 Raport AI i Szacunek Naprawy",
            height=34,
            fg_color="#1e143f",
            hover_color="#392470",
            font=ctk.CTkFont(size=12, weight="bold"),
            corner_radius=8,
            command=self._open_ai_modal
        )
        btn_ai.pack(side="left")

        lbl_hint = ctk.CTkLabel(
            action_bar,
            text="Nawigacja: Strzałki ◀ ▶ / Spacja / Esc (Zamknij)",
            font=ctk.CTkFont(size=11),
            text_color="#63528a"
        )
        lbl_hint.pack(side="right")

        self.modal.bind("<Left>", lambda e: self.prev_image())
        self.modal.bind("<Right>", lambda e: self.next_image())
        self.modal.bind("<space>", lambda e: self.next_image())
        self.modal.bind("<Escape>", lambda e: self.modal.destroy())

    def _render_thumbnail_buttons(self):
        for b in self.thumb_buttons:
            b.destroy()
        self.thumb_buttons.clear()

        for idx, url in enumerate(self.images):
            btn = ctk.CTkButton(
                self.thumb_strip_frame,
                text=f"{idx+1}",
                width=52,
                height=52,
                corner_radius=8,
                fg_color="#181033",
                hover_color="#362562",
                border_width=2 if idx == self.current_index else 1,
                border_color="#00ff88" if idx == self.current_index else "#2b1c4c",
                command=lambda i=idx: self.goto_image(i)
            )
            btn.pack(side="left", padx=4, pady=4)

            def _on_btn_thumb_loaded(ctk_img, target_btn=btn):
                def _set():
                    if target_btn.winfo_exists():
                        target_btn.configure(image=ctk_img, text="")
                self.parent.after(0, _set)

            cached = ImageLoader.load_image(url, size=(48, 48), on_ready=_on_btn_thumb_loaded)
            if cached:
                btn.configure(image=cached, text="")

            self.thumb_buttons.append(btn)

    def _rebuild_thumbnails(self):
        self._render_thumbnail_buttons()
        self._update_counter_label()

    def _show_active_image(self):
        if not self.images:
            self.lbl_large_img.configure(text="📷 Brak dostępnych zdjęć dla tej oferty.")
            self._update_counter_label()
            return

        self._update_counter_label()
        self._update_thumb_selection()

        curr_url = self.images[self.current_index]
        self.lbl_large_img.configure(image=None, text="⏳ Ładowanie zdjęcia...")

        def _on_large_loaded(ctk_img):
            def _update():
                if self.lbl_large_img.winfo_exists():
                    self.lbl_large_img.configure(image=ctk_img, text="")
            self.parent.after(0, _update)

        cached = ImageLoader.load_image(curr_url, size=(740, 440), on_ready=_on_large_loaded)
        if cached:
            self.lbl_large_img.configure(image=cached, text="")

    def _update_counter_label(self):
        total = len(self.images)
        curr = (self.current_index + 1) if total > 0 else 0
        self.lbl_counter.configure(text=f" Zdjęcie {curr} z {total} ")

    def _update_thumb_selection(self):
        for idx, btn in enumerate(self.thumb_buttons):
            if btn.winfo_exists():
                is_cur = (idx == self.current_index)
                btn.configure(
                    border_width=2 if is_cur else 1,
                    border_color="#00ff88" if is_cur else "#2b1c4c",
                    fg_color="#26174a" if is_cur else "#181033"
                )

    def prev_image(self):
        if not self.images:
            return
        self.current_index = (self.current_index - 1) % len(self.images)
        self._show_active_image()

    def next_image(self):
        if not self.images:
            return
        self.current_index = (self.current_index + 1) % len(self.images)
        self._show_active_image()

    def goto_image(self, index: int):
        if 0 <= index < len(self.images):
            self.current_index = index
            self._show_active_image()

    def _open_url(self):
        try:
            webbrowser.open(self.offer.url)
        except Exception:
            pass

    def _open_ai_modal(self):
        CyberAIModal(self.modal, self.offer, self.app_cfg)


class CyberAIModal:
    """
    Profesjonalny modal diagnostyczny AI dla oferty w GRDZ_SNIPE.
    Prezentuje szczegółową analizę opłacalności, kalkulator kosztów naprawy
    oraz strategiczną rekomendację flipperską.
    """
    def __init__(self, parent, offer: Offer, app_cfg: Optional[Dict[str, Any]] = None):
        self.parent = parent
        self.offer = offer
        self.app_cfg = app_cfg or {}
        self.ai = offer.ai_evaluation or AIOfferEvaluator.evaluate_offer(offer, self.app_cfg)

        self.modal = CyberModal._create_base(parent, f"Raport AI: {offer.title[:35]}", width=640, height=720)
        self._build_ui()

    def _build_ui(self):
        root_card = ctk.CTkFrame(
            self.modal,
            fg_color="#080512",
            corner_radius=16,
            border_width=1,
            border_color="#3c2666"
        )
        root_card.pack(fill="both", expand=True, padx=10, pady=10)

        top_bar = ctk.CTkFrame(root_card, fg_color="transparent")
        top_bar.pack(fill="x", padx=16, pady=(12, 6))

        ctk.CTkLabel(
            top_bar,
            text="🤖 Inteligentna Analiza Oferty GRDZ_SNIPE",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#ede9fe"
        ).pack(side="left")

        engine_name = self.ai.get("engine", "AI Expert Heuristics")
        ctk.CTkLabel(
            top_bar,
            text=f" {engine_name} ",
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color="#2b144d",
            text_color="#c084fc",
            corner_radius=6,
            height=22
        ).pack(side="right")

        scroll = ctk.CTkScrollableFrame(root_card, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        item_box = ctk.CTkFrame(scroll, fg_color="#120c24", corner_radius=10, border_width=1, border_color="#2a1a47")
        item_box.pack(fill="x", pady=(0, 10))

        item_header = ctk.CTkFrame(item_box, fg_color="transparent")
        item_header.pack(fill="x", padx=14, pady=(10, 4))

        ctk.CTkLabel(
            item_header,
            text=f"[{self.offer.platform}] {self.offer.title}",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#ffffff",
            anchor="w",
            wraplength=520,
            justify="left"
        ).pack(fill="x")

        price_row = ctk.CTkFrame(item_box, fg_color="transparent")
        price_row.pack(fill="x", padx=14, pady=(0, 10))

        ctk.CTkLabel(
            price_row,
            text=f"Cena w ofercie: {self.offer.price:.2f} PLN",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#00ff88"
        ).pack(side="left")

        if self.offer.location_name:
            ctk.CTkLabel(
                price_row,
                text=f"📍 {self.offer.location_name}",
                font=ctk.CTkFont(size=11),
                text_color="#a78bfa"
            ).pack(side="right")

        # Rząd z opinią i reputacją sprzedawcy
        seller_row = ctk.CTkFrame(item_box, fg_color="transparent")
        seller_row.pack(fill="x", padx=14, pady=(0, 10))

        ctk.CTkLabel(
            seller_row,
            text=f"Reputacja sprzedawcy: {self.offer.seller_badge_text or 'Brak dodatkowych danych'}",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=getattr(self.offer, "seller_badge_color", "#00ff88") or "#00ff88"
        ).pack(side="left")

        # 1. Ocena opłacalności
        card_deal = ctk.CTkFrame(scroll, fg_color="#130d29", corner_radius=12, border_width=1, border_color="#362259")
        card_deal.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            card_deal,
            text="📊 1. OCENA OPŁACALNOŚCI I RYNEK",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#fbbf24"
        ).pack(anchor="w", padx=14, pady=(10, 6))

        verdict = self.ai.get("verdict_badge", "OCENA AI")
        badge_col = self.ai.get("badge_color", "#00ff88")
        badge_frame = ctk.CTkFrame(card_deal, fg_color="#0c071a", corner_radius=8, border_width=1, border_color=badge_col)
        badge_frame.pack(fill="x", padx=14, pady=(0, 8))

        ctk.CTkLabel(
            badge_frame,
            text=f"  {verdict}  ",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=badge_col,
            height=32
        ).pack(side="left", padx=10, pady=4)

        ctk.CTkLabel(
            badge_frame,
            text=self.ai.get("verdict_short", ""),
            font=ctk.CTkFont(size=11),
            text_color="#ede9fe"
        ).pack(side="left", padx=6)

        m_row = ctk.CTkFrame(card_deal, fg_color="transparent")
        m_row.pack(fill="x", padx=14, pady=(0, 10))

        m_val = self.ai.get("estimated_market_value", 0)
        ctk.CTkLabel(
            m_row,
            text=f"Szacowana wartość rynkowa: ~{m_val:.0f} PLN",
            font=ctk.CTkFont(size=12),
            text_color="#c4b5fd"
        ).pack(side="left")

        diff_pln = self.ai.get("profit_after_repair", 0)
        roi = self.ai.get("roi_pct", 0)
        prefix = "+" if diff_pln > 0 else ""
        diff_txt = f"Margines / Zysk: {prefix}{diff_pln:.0f} PLN ({prefix}{roi}%)"
        ctk.CTkLabel(
            m_row,
            text=diff_txt,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#00ff88" if diff_pln > 0 else "#f43f5e"
        ).pack(side="right")

        # 2. Stan techniczny i kosztorys naprawy
        card_repair = ctk.CTkFrame(scroll, fg_color="#130d29", corner_radius=12, border_width=1, border_color="#362259")
        card_repair.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            card_repair,
            text="🔧 2. STAN TECHNICZNY & KOSZTORYS NAPRAWY",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#38bdf8"
        ).pack(anchor="w", padx=14, pady=(10, 6))

        if self.ai.get("is_damaged"):
            d_name = self.ai.get("damage_name", "Wykryto uszkodzenie")
            ctk.CTkLabel(
                card_repair,
                text=f"⚠️ Usterka: {d_name}",
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color="#f59e0b"
            ).pack(anchor="w", padx=14, pady=(0, 6))

            grid_repair = ctk.CTkFrame(card_repair, fg_color="#0c071a", corner_radius=8, border_width=1, border_color="#24163d")
            grid_repair.pack(fill="x", padx=14, pady=(0, 8))

            def _add_cost_line(parent, label, value, highlight=False):
                r = ctk.CTkFrame(parent, fg_color="transparent")
                r.pack(fill="x", padx=12, pady=3)
                ctk.CTkLabel(r, text=label, font=ctk.CTkFont(size=11), text_color="#a78bfa").pack(side="left")
                col = "#00ff88" if highlight else "#ede9fe"
                fnt = ctk.CTkFont(size=11, weight="bold") if highlight else ctk.CTkFont(size=11)
                ctk.CTkLabel(r, text=value, font=fnt, text_color=col).pack(side="right")

            _add_cost_line(grid_repair, "• Koszt części zamiennych:", self.ai.get("repair_parts_range", "-"))
            _add_cost_line(grid_repair, "• Koszt robocizny serwisu:", self.ai.get("repair_service_range", "-"))
            _add_cost_line(grid_repair, "• Całkowity koszt naprawy:", f"~{self.ai.get('repair_total_range', '-')}")
            _add_cost_line(grid_repair, "• Całkowity wydatek (Zakup + Naprawa):", f"~{self.ai.get('total_investment', 0):.0f} PLN")
            _add_cost_line(grid_repair, "• Prognozowany zysk po naprawie:", f"{prefix}{diff_pln:.0f} PLN", highlight=True)
        else:
            good_box = ctk.CTkFrame(card_repair, fg_color="#064e3b", corner_radius=8)
            good_box.pack(fill="x", padx=14, pady=(0, 8))
            ctk.CTkLabel(
                good_box,
                text="✅ Sprzęt sprawny — brak wykrytych uszkodzeń w opisie i tytule.\nNaprawa niewymagana. Oferta gotowa do natychmiastowego użytku lub odsprzedaży.",
                font=ctk.CTkFont(size=12),
                text_color="#6ee7b7",
                justify="left"
            ).pack(anchor="w", padx=12, pady=8)

        # 3. Rekomendacja AI
        card_recom = ctk.CTkFrame(scroll, fg_color="#130d29", corner_radius=12, border_width=1, border_color="#362259")
        card_recom.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            card_recom,
            text="💡 3. STRATEGICZNA REKOMENDACJA FLIPPERSKA",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#a855f7"
        ).pack(anchor="w", padx=14, pady=(10, 4))

        ctk.CTkLabel(
            card_recom,
            text=self.ai.get("recommendation", "Brak uwag."),
            font=ctk.CTkFont(size=12),
            text_color="#ede9fe",
            wraplength=540,
            justify="left"
        ).pack(anchor="w", padx=14, pady=(0, 12))

        # 4. Historia opinii o sprzedawcy
        card_reviews = ctk.CTkFrame(scroll, fg_color="#130d29", corner_radius=12, border_width=1, border_color="#362259")
        card_reviews.pack(fill="x", pady=(0, 10))

        rev_header = ctk.CTkFrame(card_reviews, fg_color="transparent")
        rev_header.pack(fill="x", padx=14, pady=(10, 6))

        ctk.CTkLabel(
            rev_header,
            text="⭐ 4. HISTORIA OPINII O SPRZEDAWCY",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#fbbf24"
        ).pack(side="left")

        # Badge reputacji w nagłówku sekcji
        badge_txt = self.offer.seller_badge_text or "👤 Brak ocen"
        badge_fg = getattr(self.offer, "seller_bg_color", "#064e3b") or "#064e3b"
        badge_tc = getattr(self.offer, "seller_badge_color", "#00ff88") or "#00ff88"
        ctk.CTkLabel(
            rev_header,
            text=f" {badge_txt} ",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=badge_fg,
            text_color=badge_tc,
            corner_radius=6,
            height=22
        ).pack(side="right")

        past_reviews = getattr(self.offer, "seller_recent_reviews", [])
        if past_reviews:
            rev_container = ctk.CTkFrame(card_reviews, fg_color="#0c071a", corner_radius=8, border_width=1, border_color="#24163d")
            rev_container.pack(fill="x", padx=14, pady=(0, 10))

            for r_item in past_reviews[:8]:
                r_frame = ctk.CTkFrame(rev_container, fg_color="transparent")
                r_frame.pack(fill="x", padx=10, pady=5)

                top_meta = ctk.CTkFrame(r_frame, fg_color="transparent")
                top_meta.pack(fill="x")

                star_cnt = int(r_item.get("rating", 5) or 5)
                star_str = "⭐" * max(1, min(5, star_cnt))
                score_str = f"{star_str} ({r_item.get('rating', 5)}/5)"
                ctk.CTkLabel(
                    top_meta,
                    text=score_str,
                    font=ctk.CTkFont(size=11, weight="bold"),
                    text_color="#fbbf24"
                ).pack(side="left")

                author_str = f"@{r_item.get('author', 'Kupujący')}"
                date_str = f" • {r_item.get('date', '')}" if r_item.get("date") else ""
                ctk.CTkLabel(
                    top_meta,
                    text=f"{author_str}{date_str}",
                    font=ctk.CTkFont(size=10),
                    text_color="#a78bfa"
                ).pack(side="right")

                comment_text = r_item.get("comment", "")
                if comment_text:
                    ctk.CTkLabel(
                        r_frame,
                        text=f"„{comment_text}”",
                        font=ctk.CTkFont(size=11),
                        text_color="#ede9fe",
                        wraplength=520,
                        justify="left"
                    ).pack(anchor="w", padx=(6, 0), pady=(1, 2))
        else:
            no_rev_frame = ctk.CTkFrame(card_reviews, fg_color="#0c071a", corner_radius=8, border_width=1, border_color="#24163d")
            no_rev_frame.pack(fill="x", padx=14, pady=(0, 10))
            s_name = self.offer.seller_name or "tego sprzedawcy"
            ctk.CTkLabel(
                no_rev_frame,
                text=f"ℹ️ Brak zarejestrowanych komentarzy tekstowych dla użytkownika {s_name}.\nReputacja bazowa: {self.offer.seller_badge_text or 'Nowe konto lub brak publicznych ocen'}.",
                font=ctk.CTkFont(size=11),
                text_color="#a78bfa",
                justify="left"
            ).pack(anchor="w", padx=12, pady=8)

        # 5. Sekcja Google Gemini Neural AI
        gemini_key = self.app_cfg.get("gemini_api_key", "").strip() or os.environ.get("GEMINI_API_KEY", "").strip()
        if gemini_key:
            btn_gemini = ctk.CTkButton(
                scroll,
                text="🧠 Przeanalizuj ponownie przez Google Gemini 2.5 Flash",
                height=34,
                fg_color="#4f46e5",
                hover_color="#4338ca",
                font=ctk.CTkFont(size=12, weight="bold"),
                corner_radius=8,
                command=self._trigger_gemini_analysis
            )
            btn_gemini.pack(fill="x", pady=(0, 10))

        bottom_bar = ctk.CTkFrame(root_card, fg_color="transparent")
        bottom_bar.pack(fill="x", padx=14, pady=(4, 8))

        btn_browser = ctk.CTkButton(
            bottom_bar,
            text="🌐 Otwórz w przeglądarce",
            height=34,
            fg_color=THEME["accent_violet"],
            hover_color=THEME["accent_purple_hover"],
            font=ctk.CTkFont(size=12, weight="bold"),
            corner_radius=8,
            command=self._open_url
        )
        btn_browser.pack(side="left")

        btn_close = ctk.CTkButton(
            bottom_bar,
            text="Zamknij [Esc]",
            width=110,
            height=34,
            fg_color="#21183c",
            hover_color="#362562",
            font=ctk.CTkFont(size=12),
            corner_radius=8,
            command=self.modal.destroy
        )
        btn_close.pack(side="right")

        self.modal.bind("<Escape>", lambda e: self.modal.destroy())

    def _open_url(self):
        try:
            webbrowser.open(self.offer.url)
        except Exception:
            pass

    def _trigger_gemini_analysis(self):
        api_key = self.app_cfg.get("gemini_api_key", "").strip() or os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            return

        def _worker():
            res = AIOfferEvaluator.query_gemini_ai(self.offer, api_key)
            if res:
                self.offer.ai_evaluation = res
                self.ai = res
                def _refresh():
                    self.modal.destroy()
                    CyberAIModal(self.parent, self.offer, self.app_cfg)
                self.parent.after(0, _refresh)

        threading.Thread(target=_worker, daemon=True).start()

_gallery_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="gallery_fetcher")

class DealCard(ctk.CTkFrame):
    def __init__(self, master, offer: Offer, on_discord_send=None, on_vinted_offer=None, show_image: bool = True, app_cfg: Optional[Dict[str, Any]] = None, **kwargs):
        border_col = THEME["border_deal"] if offer.is_deal else THEME["border_card"]
        bg_col = THEME["bg_card_deal"] if offer.is_deal else THEME["bg_card"]
        self.bg_col = bg_col
        
        super().__init__(
            master,
            corner_radius=12,
            border_width=2 if offer.is_deal else 1,
            border_color=border_col,
            fg_color=bg_col,
            **kwargs
        )
        self.offer = offer
        self.on_discord_send = on_discord_send
        self.on_vinted_offer = on_vinted_offer
        self.show_image = show_image
        self.app_cfg = app_cfg or {}
        self.ai = offer.ai_evaluation or AIOfferEvaluator.evaluate_offer(offer, self.app_cfg)
        self._build_ui()

    def _build_ui(self):
        # Lekki kontener nadrzędny bez narzutu Canvas (natywny tk.Frame)
        main_box = tk.Frame(self, bg=self.bg_col)
        main_box.pack(fill="x", padx=14, pady=12)

        # 1. Kolumna ze zdjęciami z lewej strony (Główne zdjęcie + Miniatury reszty zdjęć)
        if self.show_image:
            photo_col = tk.Frame(main_box, bg=self.bg_col, width=108)
            photo_col.pack(side="left", padx=(0, 14), anchor="n")

            # 1a. Główne zdjęcie (104x104)
            self.thumb_box = ctk.CTkFrame(
                photo_col,
                width=104,
                height=104,
                corner_radius=10,
                fg_color="#0e091e",
                border_width=1,
                border_color="#362359",
                cursor="hand2"
            )
            self.thumb_box.pack(anchor="n")
            self.thumb_box.pack_propagate(False)

            self.lbl_thumb = ctk.CTkLabel(
                self.thumb_box,
                text="🖼️\nŁadowanie...",
                font=ctk.CTkFont(size=10),
                text_color="#635283",
                cursor="hand2"
            )
            self.lbl_thumb.pack(expand=True)
            self.lbl_thumb.bind("<Button-1>", lambda e: self._open_lightbox(0))
            self.thumb_box.bind("<Button-1>", lambda e: self._open_lightbox(0))

            def _on_img_loaded(ctk_img):
                def _update():
                    if hasattr(self, "lbl_thumb") and self.lbl_thumb.winfo_exists():
                        self.lbl_thumb.configure(image=ctk_img, text="")
                self.after(0, _update)

            if self.offer.image_url:
                cached = ImageLoader.load_image(self.offer.image_url, size=(100, 100), on_ready=_on_img_loaded)
                if cached:
                    self.lbl_thumb.configure(image=cached, text="")
            else:
                self.lbl_thumb.configure(text="📷\nBrak zdjęcia", text_color="#4f3f6d")

            # 1b. Pasek miniatur pozostałych zdjęć pod głównym zdjęciem (lekki tk.Frame)
            self.mini_strip = tk.Frame(photo_col, bg=self.bg_col, width=104, height=30)
            self.mini_strip.pack(anchor="n", pady=(5, 0))

            self._render_mini_thumbnails()

            # Dociąganie pełnej galerii w tle w dedykowanej puli wątków (bez zamrażania CPU/UI)
            if len(self.offer.images) <= 1 and self.offer.platform in ("VINTED", "ALLEGRO LOKALNIE", "ALLEGRO"):
                _gallery_executor.submit(self._fetch_extra_images_async)

        # 2. Prawa kolumna z treścią ogłoszenia i analizą AI (lekki tk.Frame)
        details = tk.Frame(main_box, bg=self.bg_col)
        details.pack(side="left", fill="both", expand=True)

        # 2a. Górny pasek: Badge platformy, Etykieta okazji, Lokalizacja, Dostawa, Czas (lekki tk.Frame)
        top_frame = tk.Frame(details, bg=self.bg_col)
        top_frame.pack(fill="x", pady=(0, 6))

        if self.offer.platform == "VINTED":
            plat_color = "#005b64"
            plat_txt = "#38bdf8"
        elif self.offer.platform == "ALLEGRO LOKALNIE":
            plat_color = "#4c1d00"
            plat_txt = "#fb923c"
        elif self.offer.platform == "ALLEGRO":
            plat_color = "#3b1600"
            plat_txt = "#f97316"
        else: # OLX
            plat_color = "#064e3b"
            plat_txt = "#34d399"

        plat_badge = ctk.CTkLabel(
            top_frame,
            text=f" {self.offer.platform} ",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=plat_color,
            text_color=plat_txt,
            corner_radius=6,
            height=24
        )
        plat_badge.pack(side="left", padx=(0, 6))

        if self.offer.has_delivery:
            deliv_badge = ctk.CTkLabel(
                top_frame,
                text=" 📦 Przesyłka ",
                font=ctk.CTkFont(size=11, weight="bold"),
                fg_color="#064e3b",
                text_color="#6ee7b7",
                corner_radius=6,
                height=24
            )
            deliv_badge.pack(side="left", padx=(0, 6))

        if self.offer.location_name:
            loc_badge = ctk.CTkLabel(
                top_frame,
                text=f" 📍 {self.offer.location_name} ",
                font=ctk.CTkFont(size=11),
                text_color="#c4b5fd",
                fg_color="#20173d",
                corner_radius=6,
                height=24
            )
            loc_badge.pack(side="left", padx=(0, 6))

        if self.offer.is_deal:
            if self.offer.discount_pct > 0:
                disc_text = f"🔥 OKAZJA -{self.offer.discount_pct:.0f}%"
            elif self.offer.deal_price_threshold and self.offer.price <= self.offer.deal_price_threshold:
                disc_text = "🎯 W TWOIM PROGU"
            else:
                disc_text = "✨ WYKRYTA OKAZJA"

            deal_badge = ctk.CTkLabel(
                top_frame,
                text=f" {disc_text} ",
                font=ctk.CTkFont(size=11, weight="bold"),
                fg_color="#064e3b",
                text_color="#00ff88",
                corner_radius=6,
                height=24
            )
            deal_badge.pack(side="left", padx=(0, 6))

        # Minka i opinia o sprzedawcy (Zielona 😊 / Żółta 😐 / Czerwona 🙁)
        self.seller_badge = ctk.CTkLabel(
            top_frame,
            text=f" {self.offer.seller_badge_text or '👤 Sprzedawca'} ",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=getattr(self.offer, "seller_bg_color", "#064e3b") or "#064e3b",
            text_color=getattr(self.offer, "seller_badge_color", "#00ff88") or "#00ff88",
            corner_radius=6,
            height=24
        )
        self.seller_badge.pack(side="left", padx=(0, 6))

        time_label = ctk.CTkLabel(
            top_frame,
            text=f"🕒 {self.offer.created_at_str}",
            font=ctk.CTkFont(size=11),
            text_color=THEME["text_muted"]
        )
        time_label.pack(side="right")

        # 2b. Tytuł oferty
        title_label = ctk.CTkLabel(
            details,
            text=self.offer.title,
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=THEME["text_main"],
            anchor="w",
            wraplength=630 if self.show_image else 740,
            justify="left"
        )
        title_label.pack(fill="x", pady=(0, 4))

        # 2c. Cena i opis okazji (lekki tk.Frame)
        price_frame = tk.Frame(details, bg=self.bg_col)
        price_frame.pack(fill="x", pady=(0, 6))

        price_val = ctk.CTkLabel(
            price_frame,
            text=f"{self.offer.price:.2f} PLN",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=THEME["accent_mint"] if self.offer.is_deal else THEME["text_lavender"]
        )
        price_val.pack(side="left", padx=(0, 14))

        if self.offer.deal_reason:
            reason_box = ctk.CTkLabel(
                price_frame,
                text=f"🎯 {self.offer.deal_reason}",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color="#c4b5fd" if not self.offer.is_deal else "#6ee7b7"
            )
            reason_box.pack(side="left")

        # 2d. PASEK DIAGNOSTYKI AI (Opłacalność, Stan & Kosztorys Naprawy)
        ai_box = ctk.CTkFrame(
            details,
            fg_color="#0e0a1f",
            corner_radius=8,
            border_width=1,
            border_color="#311f4f"
        )
        ai_box.pack(fill="x", pady=(0, 8))

        ai_inner = tk.Frame(ai_box, bg="#0e0a1f")
        ai_inner.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(
            ai_inner,
            text="🤖 AI:",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#c084fc"
        ).pack(side="left", padx=(0, 8))

        # Badge werdyktu
        v_badge = self.ai.get("verdict_badge", "ANALIZA")
        v_col = self.ai.get("badge_color", "#00ff88")
        badge_lbl = ctk.CTkLabel(
            ai_inner,
            text=f" {v_badge} ",
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color="#18112c",
            text_color=v_col,
            corner_radius=5,
            height=20
        )
        badge_lbl.pack(side="left", padx=(0, 8))

        # Treść werdyktu (np. zysk lub usterka)
        ai_summary = self.ai.get("verdict_short", "")
        if self.ai.get("is_damaged"):
            ai_summary += f" • 🔧 Naprawa: {self.ai.get('repair_total_range')}"

        ctk.CTkLabel(
            ai_inner,
            text=ai_summary,
            font=ctk.CTkFont(size=11),
            text_color="#ede9fe",
            anchor="w"
        ).pack(side="left", fill="x", expand=True)

        btn_ai_details = ctk.CTkButton(
            ai_inner,
            text="🧠 Szczegóły AI",
            width=85,
            height=22,
            fg_color="#27194a",
            hover_color="#452783",
            font=ctk.CTkFont(size=10, weight="bold"),
            corner_radius=6,
            command=self._open_ai_modal
        )
        btn_ai_details.pack(side="right")

        # 2e. Przyciski akcji (lekki tk.Frame)
        action_frame = tk.Frame(details, bg=self.bg_col)
        action_frame.pack(fill="x")

        btn_open = ctk.CTkButton(
            action_frame,
            text="🔗 Otwórz ofertę",
            width=130,
            height=30,
            fg_color=THEME["accent_violet"],
            hover_color=THEME["accent_purple_hover"],
            font=ctk.CTkFont(size=12, weight="bold"),
            corner_radius=8,
            command=self._open_url
        )
        btn_open.pack(side="left", padx=(0, 8))

        btn_copy = ctk.CTkButton(
            action_frame,
            text="📋 Kopiuj link",
            width=95,
            height=30,
            fg_color="#241a45",
            hover_color="#362866",
            font=ctk.CTkFont(size=12),
            corner_radius=8,
            command=self._copy_url
        )
        btn_copy.pack(side="left", padx=(0, 8))

        # Przycisk Galerii
        n_imgs = len(self.offer.images)
        gal_txt = f"🖼️ Galeria ({n_imgs})" if n_imgs > 1 else "🖼️ Zdjęcie 🔍"
        self.btn_gallery = ctk.CTkButton(
            action_frame,
            text=gal_txt,
            width=110,
            height=30,
            fg_color="#1d133b",
            hover_color="#39226b",
            font=ctk.CTkFont(size=12),
            corner_radius=8,
            command=lambda: self._open_lightbox(0)
        )
        self.btn_gallery.pack(side="left", padx=(0, 8))

        if self.on_discord_send:
            btn_discord = ctk.CTkButton(
                action_frame,
                text="💬 Discord",
                width=100,
                height=30,
                fg_color="#5865f2",
                hover_color="#4752c4",
                font=ctk.CTkFont(size=12),
                corner_radius=8,
                command=lambda: self.on_discord_send(self.offer)
            )
            btn_discord.pack(side="left", padx=(0, 8))

        if self.offer.platform == "VINTED" and self.on_vinted_offer:
            btn_vinted_offer = ctk.CTkButton(
                action_frame,
                text="🤝 Złóż ofertę (-%)",
                width=125,
                height=30,
                fg_color="#0e7490",
                hover_color="#0891b2",
                font=ctk.CTkFont(size=12, weight="bold"),
                corner_radius=8,
                command=lambda: self.on_vinted_offer(self.offer)
            )
            btn_vinted_offer.pack(side="left")

    def _render_mini_thumbnails(self):
        if not hasattr(self, "mini_strip") or not self.mini_strip.winfo_exists():
            return

        for w in self.mini_strip.winfo_children():
            w.destroy()

        imgs = self.offer.images
        if len(imgs) <= 1:
            return

        rest = imgs[1:]
        max_show = 3

        for i, url in enumerate(rest[:max_show]):
            real_idx = i + 1
            btn = ctk.CTkButton(
                self.mini_strip,
                text="",
                width=28,
                height=28,
                corner_radius=5,
                fg_color="#18112c",
                hover_color="#7c3aed",
                border_width=1,
                border_color="#352254",
                command=lambda idx=real_idx: self._open_lightbox(idx)
            )
            btn.pack(side="left", padx=2)

            def _on_mini_loaded(ctk_img, b=btn):
                def _set():
                    if b.winfo_exists():
                        b.configure(image=ctk_img, text="")
                self.after(0, _set)

            cached = ImageLoader.load_image(url, size=(28, 28), on_ready=_on_mini_loaded)
            if cached:
                btn.configure(image=cached, text="")

        if len(rest) > max_show:
            left_count = len(rest) - max_show
            plus_btn = ctk.CTkButton(
                self.mini_strip,
                text=f"+{left_count}",
                width=28,
                height=28,
                corner_radius=5,
                fg_color="#241744",
                hover_color="#7c3aed",
                text_color="#c084fc",
                font=ctk.CTkFont(size=10, weight="bold"),
                command=lambda: self._open_lightbox(max_show + 1)
            )
            plus_btn.pack(side="left", padx=2)

    def _update_seller_badge(self):
        if hasattr(self, "seller_badge") and self.seller_badge.winfo_exists():
            self.seller_badge.configure(
                text=f" {self.offer.seller_badge_text or '👤 Sprzedawca'} ",
                fg_color=getattr(self.offer, "seller_bg_color", "#064e3b") or "#064e3b",
                text_color=getattr(self.offer, "seller_badge_color", "#00ff88") or "#00ff88"
            )

    def _fetch_extra_images_async(self):
        try:
            if not self.app_cfg.get("enable_image_prefetch", True):
                return
            extra = fetch_offer_images(self.offer)
            if extra and len(extra) > 1:
                self.offer.images = extra
            def _update():
                if not self.winfo_exists():
                    return
                self._render_mini_thumbnails()
                self._update_seller_badge()
                if hasattr(self, "btn_gallery") and self.btn_gallery.winfo_exists():
                    self.btn_gallery.configure(text=f"🖼️ Galeria ({len(self.offer.images)})")
            self.after(0, _update)
        except Exception:
            pass

    def _open_lightbox(self, initial_idx: int = 0):
        CyberLightboxModal(self.winfo_toplevel(), self.offer, initial_index=initial_idx, app_cfg=self.app_cfg)

    def _open_ai_modal(self):
        CyberAIModal(self.winfo_toplevel(), self.offer, app_cfg=self.app_cfg)

    def _open_url(self):
        try:
            webbrowser.open(self.offer.url)
        except Exception as e:
            CyberModal.show_error(self.winfo_toplevel(), "Błąd Przeglądarki", f"Nie można otworzyć linku w przeglądarce:\n{e}")

    def _copy_url(self):
        self.clipboard_clear()
        self.clipboard_append(self.offer.url)
        self.update()
class _TabViewCompat:
    def __init__(self, app):
        self._app = app

    def set(self, tab_name: str):
        self._app.set_active_tab(tab_name)


class DealTrackerApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("GRDZ_SNIPE — Pro Multi-Platform Deal Sniping Suite")
        self.geometry("1220x920")
        self.minsize(1060, 760)
        self.configure(fg_color=THEME["bg_window"])

        self.app_dir = os.path.dirname(os.path.abspath(__file__))
        _ico_path = os.path.join(self.app_dir, "icon.ico")
        if not os.path.exists(_ico_path):
            _ico_path = "icon.ico"
        if os.path.exists(_ico_path):
            try:
                self.iconbitmap(_ico_path)
            except Exception:
                pass

        self.cfg = load_config()
        self.favorites = load_favorites()

        # Synchronizacja motywu wizualnego z konfiguracją użytkownika
        selected_th = self.cfg.get("selected_theme", "Obsydianowy Fiolet (Domyślny)")
        if selected_th in THEMES:
            THEME.update(THEMES[selected_th])
        self.configure(fg_color=THEME["bg_window"])

        self.var_show_images = tk.BooleanVar(value=bool(self.cfg.get("show_item_images", True)))

        self.engine = MonitorEngine(
            on_offer_callback=self._on_new_offer,
            on_status_callback=self._on_status_update,
            on_stats_callback=self._on_stats_update
        )

        self.auth_engine = get_auth_engine(self.cfg)
        self.auth_engine.on_revoked_callback = self._on_license_revoked
        self.auth_engine.on_broadcast_callback = self._on_admin_broadcast

        self.cards: List[DealCard] = []
        self.offers_list: List[Offer] = []
        self._incoming_offer_queue = collections.deque()
        self._is_draining_queue = False

        self._build_top_header()
        self._build_bottom_status_bar()
        self._build_tabs()
        self._update_quick_fav_combo()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(200, self._check_startup_license)

    def _build_top_header(self):
        self.header_frame = ctk.CTkFrame(self, fg_color=THEME["bg_header"], corner_radius=0, height=74)
        self.header_frame.pack(fill="x", side="top")
        self.header_frame.pack_propagate(False)

        title_box = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        title_box.pack(side="left", padx=24, pady=10)

        _png_path = os.path.join(self.app_dir, "icon.png")
        if not os.path.exists(_png_path):
            _png_path = "icon.png"
        if os.path.exists(_png_path):
            try:
                pil_img = Image.open(_png_path)
                self.logo_ctk = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(42, 42))
                logo_lbl = ctk.CTkLabel(title_box, image=self.logo_ctk, text="")
                logo_lbl.pack(side="left", padx=(0, 12))
            except Exception:
                pass

        text_block = ctk.CTkFrame(title_box, fg_color="transparent")
        text_block.pack(side="left")

        top_row = ctk.CTkFrame(text_block, fg_color="transparent")
        top_row.pack(anchor="w")

        self.app_title = ctk.CTkLabel(
            top_row,
            text="GRDZ_SNIPE",
            font=ctk.CTkFont(family="Segoe UI", size=23, weight="bold"),
            text_color=THEME["accent_purple"]
        )
        self.app_title.pack(side="left", padx=(0, 10))

        self.badge_pro = ctk.CTkLabel(
            top_row,
            text=" v2.6 PRO ",
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color="#2b144d",
            text_color="#c084fc",
            corner_radius=6,
            height=20
        )
        self.badge_pro.pack(side="left")

        self.badge_license = ctk.CTkButton(
            top_row,
            text="⚡ LICENCJA: SPRAWDZANIE...",
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color="#1e1b4b",
            hover_color="#312e81",
            text_color="#c7d2fe",
            corner_radius=6,
            height=20,
            command=self._open_license_manager
        )
        self.badge_license.pack(side="left", padx=(8, 0))

        app_subtitle = ctk.CTkLabel(
            text_block,
            text="Autonomiczny monitor okazji: OLX • Vinted • Allegro Lokalnie • Allegro",
            font=ctk.CTkFont(size=11),
            text_color=THEME["text_muted"]
        )
        app_subtitle.pack(anchor="w")

        btn_box = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        btn_box.pack(side="right", padx=24, pady=12)

        self.btn_toggle = ctk.CTkButton(
            btn_box,
            text="▶ ROZPOCZNIJ SNIPOWANIE",
            width=230,
            height=42,
            fg_color=THEME["accent_purple"],
            hover_color=THEME["accent_purple_hover"],
            font=ctk.CTkFont(size=13, weight="bold"),
            corner_radius=10,
            command=self._toggle_monitor
        )
        self.btn_toggle.pack(side="right", padx=(12, 0))

        self.btn_scan_now = ctk.CTkButton(
            btn_box,
            text="🔄 Skanuj teraz",
            width=135,
            height=42,
            fg_color="#1f183d",
            hover_color="#2d2258",
            font=ctk.CTkFont(size=12, weight="bold"),
            corner_radius=10,
            command=self._trigger_instant_scan
        )
        self.btn_scan_now.pack(side="right")

    def _build_tabs(self):
        # Główny kontener dla paska bocznego i widoków zakładek
        self.main_body = ctk.CTkFrame(self, fg_color="transparent")
        self.main_body.pack(fill="both", expand=True, padx=0, pady=0)

        # 1. Główny kontener treści (Right Content Area)
        # Ma stały lewy margines 74px zarezerwowany na zwinięty pasek ikon,
        # dzięki czemu jego szerokość i widgety NIGDY nie są przesuwane ani przeliczane!
        self.tab_container = ctk.CTkFrame(
            self.main_body,
            fg_color=THEME["bg_tabview"],
            corner_radius=14,
            border_width=1,
            border_color="#2a1b4d"
        )
        self.tab_container.pack(fill="both", expand=True, padx=(78, 14), pady=(8, 8))
        self.tab_container.grid_rowconfigure(0, weight=1)
        self.tab_container.grid_columnconfigure(0, weight=1)

        # 2. Pasek boczny nawigacji (Sidebar Overlay)
        # Używamy .place(), aby unosił się nad kontenerem jako warstwa nakładkowa (overlay).
        # Dzięki temu zmiana szerokości paska w ogóle nie dotyka tab_container!
        self.sidebar_frame = ctk.CTkFrame(
            self.main_body,
            width=64,
            fg_color="#090514",
            corner_radius=14,
            border_width=1,
            border_color="#261742"
        )
        self.sidebar_frame.place(x=12, y=8, relheight=0.975)
        self.sidebar_frame.pack_propagate(False)
        self.sidebar_frame.lift()

        # 7 stron zakładek
        self.tab_feed = ctk.CTkFrame(self.tab_container, fg_color="transparent")
        self.tab_favorites = ctk.CTkFrame(self.tab_container, fg_color="transparent")
        self.tab_filters = ctk.CTkFrame(self.tab_container, fg_color="transparent")
        self.tab_vinted = ctk.CTkFrame(self.tab_container, fg_color="transparent")
        self.tab_notifs = ctk.CTkFrame(self.tab_container, fg_color="transparent")
        self.tab_stats = ctk.CTkFrame(self.tab_container, fg_color="transparent")
        self.tab_settings = ctk.CTkFrame(self.tab_container, fg_color="transparent")

        for tab in (self.tab_feed, self.tab_favorites, self.tab_filters, self.tab_vinted, self.tab_notifs, self.tab_stats, self.tab_settings):
            tab.grid(row=0, column=0, sticky="nsew", padx=12, pady=10)

        # Definicja zakładek z dobranymi ikonami i tytułami
        self.sidebar_tabs = [
            {
                "id": "feed",
                "icon": "🎯",
                "title": "Strumień Okazji",
                "page": self.tab_feed,
                "aliases": ["🎯  Strumień Okazji", "Strumień Okazji", "feed"]
            },
            {
                "id": "favs",
                "icon": "⭐",
                "title": "Ulubione Cele",
                "page": self.tab_favorites,
                "aliases": ["⭐  Ulubione Cele", "Ulubione Cele", "favs"]
            },
            {
                "id": "filters",
                "icon": "⚙️",
                "title": "Filtry & Kategoria",
                "page": self.tab_filters,
                "aliases": ["⚙️  Filtry & Kategoria", "Filtry & Kategoria", "filters"]
            },
            {
                "id": "vinted",
                "icon": "🤝",
                "title": "Vinted & Auto-Oferty",
                "page": self.tab_vinted,
                "aliases": ["🤝  Vinted & Auto-Oferty", "Vinted & Auto-Oferty", "vinted"]
            },
            {
                "id": "notifs",
                "icon": "🔔",
                "title": "Powiadomienia & Webhook",
                "page": self.tab_notifs,
                "aliases": ["🔔  Powiadomienia & Webhook", "Powiadomienia & Webhook", "notifs"]
            },
            {
                "id": "stats",
                "icon": "📊",
                "title": "Statystyki & Logi",
                "page": self.tab_stats,
                "aliases": ["📊  Statystyki & Logi", "Statystyki & Logi", "stats"]
            },
            {
                "id": "settings",
                "icon": "🎨",
                "title": "Motywy & Ustawienia",
                "page": self.tab_settings,
                "aliases": ["🎨  Motywy & Ustawienia", "Motywy & Ustawienia", "settings", "ustawienia", "motywy"]
            }
        ]

        self.tabview = _TabViewCompat(self)
        self.active_tab_id = "feed"
        self.sidebar_is_expanded = False
        self._sidebar_anim_id = None

        self._build_sidebar_ui()

        # Budowanie zawartości poszczególnych modułów
        self._build_tab_feed_content()
        self._build_tab_favorites_content()
        self._build_tab_filters_content()
        self._build_tab_vinted_content()
        self._build_tab_notifs_content()
        self._build_tab_stats_content()
        self._build_tab_settings_content()

        # Ustawienie domyślnie pierwszej zakładki
        self.set_active_tab("feed")

    def _build_sidebar_ui(self):
        # Górny wskaźnik panelu
        self.sidebar_top = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent", height=42)
        self.sidebar_top.pack(fill="x", padx=4, pady=(12, 6))
        self.sidebar_top.pack_propagate(False)

        self.lbl_sidebar_header = ctk.CTkLabel(
            self.sidebar_top,
            text="⚡",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=THEME["accent_purple"]
        )
        self.lbl_sidebar_header.pack(expand=True)

        # Kontener przycisków nawigacji
        self.sidebar_nav_box = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        self.sidebar_nav_box.pack(fill="both", expand=True, padx=4, pady=4)

        self.nav_buttons = {}
        self.tab_flyouts = {}
        self._active_flyout_id = None
        self._flyout_hide_after_id = None

        # Czcionki pre-renderowane
        self._font_nav_icon = ctk.CTkFont(size=18)
        self._font_flyout_title = ctk.CTkFont(size=13, weight="bold")
        self._font_header = ctk.CTkFont(size=16, weight="bold")

        for item in self.sidebar_tabs:
            tid = item["id"]
            # 1. Przycisk ikony w pasku pionowym
            btn = ctk.CTkButton(
                self.sidebar_nav_box,
                text=item["icon"],
                width=52,
                height=48,
                corner_radius=10,
                font=self._font_nav_icon,
                fg_color="transparent",
                hover_color="#1d1338",
                text_color="#c4b5fd",
                anchor="center",
                command=lambda t=tid: self.set_active_tab(t)
            )
            btn.pack(fill="x", padx=4, pady=4)
            self.nav_buttons[tid] = btn

            # 2. Indywidualna kapsuła wysuwana (Floating Flyout Pill)
            # Unosi się na współrzędnych bez ruszania kontenera z treścią
            flyout = ctk.CTkButton(
                self.main_body,
                text=f"{item['icon']}   {item['title']}",
                width=200,
                height=48,
                corner_radius=10,
                font=self._font_flyout_title,
                fg_color="#140d2b",
                hover_color="#241445",
                text_color="#ffffff",
                border_width=1,
                border_color="#7c3aed",
                anchor="w",
                command=lambda t=tid: self.set_active_tab(t)
            )
            self.tab_flyouts[tid] = flyout

            # Bindowanie zdarzeń najechania dla danego przycisku i jego kapsuły
            btn.bind("<Enter>", lambda e, t=tid: self._show_tab_flyout(t))
            btn.bind("<Leave>", lambda e, t=tid: self._schedule_hide_flyout(t))
            flyout.bind("<Enter>", lambda e, t=tid: self._cancel_hide_flyout(t))
            flyout.bind("<Leave>", lambda e, t=tid: self._schedule_hide_flyout(t))

        # Dolny wskaźnik stanu
        self.sidebar_bottom = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent", height=32)
        self.sidebar_bottom.pack(side="bottom", fill="x", padx=4, pady=(0, 8))
        self.sidebar_bottom.pack_propagate(False)

        self.lbl_sidebar_hint = ctk.CTkLabel(
            self.sidebar_bottom,
            text="⚡",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#52397c"
        )
        self.lbl_sidebar_hint.pack(expand=True)

    def _show_tab_flyout(self, tid: str):
        # Anuluj ewentualne ukrywanie
        if self._flyout_hide_after_id:
            self.after_cancel(self._flyout_hide_after_id)
            self._flyout_hide_after_id = None

        # Ukryj poprzednio otwartą kapsułę jeśli inna
        if self._active_flyout_id and self._active_flyout_id != tid:
            old_f = self.tab_flyouts.get(self._active_flyout_id)
            if old_f:
                old_f.place_forget()

        btn = self.nav_buttons.get(tid)
        flyout = self.tab_flyouts.get(tid)
        if not btn or not flyout:
            return

        self._active_flyout_id = tid
        # Oblicz pozycję Y względem main_body
        y_pos = btn.winfo_y() + self.sidebar_nav_box.winfo_y() + self.sidebar_frame.winfo_y()

        is_active = (tid == self.active_tab_id)
        if is_active:
            flyout.configure(
                fg_color=THEME["accent_violet"],
                hover_color=THEME["accent_purple_hover"],
                border_color="#d946ef",
                border_width=2
            )
        else:
            flyout.configure(
                fg_color="#181033",
                hover_color="#2b1a52",
                border_color="#7c3aed",
                border_width=1
            )

        flyout.place(x=72, y=y_pos)
        flyout.lift()

    def _schedule_hide_flyout(self, tid: str):
        if self._flyout_hide_after_id:
            self.after_cancel(self._flyout_hide_after_id)
        self._flyout_hide_after_id = self.after(50, lambda: self._hide_flyout(tid))

    def _cancel_hide_flyout(self, tid: str):
        if self._flyout_hide_after_id:
            self.after_cancel(self._flyout_hide_after_id)
            self._flyout_hide_after_id = None

    def _hide_flyout(self, tid: str):
        flyout = self.tab_flyouts.get(tid)
        if flyout:
            flyout.place_forget()
        if self._active_flyout_id == tid:
            self._active_flyout_id = None

    def _refresh_sidebar_buttons(self):
        for item in self.sidebar_tabs:
            tid = item["id"]
            btn = self.nav_buttons.get(tid)
            if not btn:
                continue
            is_active = (tid == self.active_tab_id)
            if is_active:
                btn.configure(
                    fg_color=THEME["accent_violet"],
                    hover_color=THEME["accent_purple_hover"],
                    text_color="#ffffff",
                    border_width=1,
                    border_color="#a855f7"
                )
            else:
                btn.configure(
                    fg_color="transparent",
                    hover_color="#1d1338",
                    text_color="#c4b5fd",
                    border_width=0
                )

    def set_active_tab(self, tab_key: str):
        matched = None
        key_low = tab_key.strip().lower()
        for item in self.sidebar_tabs:
            if item["id"] == key_low:
                matched = item
                break
            for a in item["aliases"]:
                if key_low in a.lower() or a.lower() in key_low:
                    matched = item
                    break
            if matched:
                break
        if not matched:
            matched = self.sidebar_tabs[0]

        self.active_tab_id = matched["id"]
        matched["page"].tkraise()
        self._refresh_sidebar_buttons()

    # --- ZAKŁADKA 1: STRUMIEŃ OKAZJI ---
    def _build_tab_feed_content(self):
        kpi_frame = ctk.CTkFrame(self.tab_feed, fg_color="transparent")
        kpi_frame.pack(fill="x", pady=(4, 10))

        self.kpi_status = self._create_kpi_card(kpi_frame, "STATUS SNIPERA", "⏹ ZATRZYMANY", "#94a3b8")
        self.kpi_status.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.kpi_deals = self._create_kpi_card(kpi_frame, "WYKRYTE OKAZJE", "0", THEME["accent_mint"])
        self.kpi_deals.pack(side="left", fill="x", expand=True, padx=6)

        self.kpi_scanned = self._create_kpi_card(kpi_frame, "PRZESZUKANE AUKCJE", "0", THEME["accent_cyan"])
        self.kpi_scanned.pack(side="left", fill="x", expand=True, padx=6)

        self.kpi_time = self._create_kpi_card(kpi_frame, "OSTATNI SKAN", "-", THEME["accent_amber"])
        self.kpi_time.pack(side="left", fill="x", expand=True, padx=(6, 0))

        summary_bar = ctk.CTkFrame(self.tab_feed, fg_color="#140f29", corner_radius=10, height=40, border_width=1, border_color="#281c47")
        summary_bar.pack(fill="x", pady=(0, 8))
        summary_bar.pack_propagate(False)

        self.lbl_target_summary = ctk.CTkLabel(
            summary_bar,
            text=self._get_summary_text(),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#c4b5fd"
        )
        self.lbl_target_summary.pack(side="left", padx=14)

        btn_fav_quick = ctk.CTkButton(
            summary_bar,
            text="⭐ Zapisz jako cel",
            width=130,
            height=26,
            fg_color="#3b1b66",
            hover_color="#51268c",
            font=ctk.CTkFont(size=11, weight="bold"),
            corner_radius=8,
            command=self._prompt_add_favorite
        )
        btn_fav_quick.pack(side="right", padx=(0, 8))

        btn_clear = ctk.CTkButton(
            summary_bar,
            text="Wyczyść feed",
            width=95,
            height=26,
            fg_color="#221844",
            hover_color="#36256c",
            font=ctk.CTkFont(size=11),
            corner_radius=8,
            command=self._clear_deals
        )
        btn_clear.pack(side="right", padx=(0, 8))

        self.switch_show_images = ctk.CTkSwitch(
            summary_bar,
            text="🖼️ Zdjęcia",
            variable=self.var_show_images,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#6ee7b7",
            progress_color=THEME["accent_mint"],
            command=self._on_toggle_images
        )
        self.switch_show_images.pack(side="right", padx=(0, 14))

        # Scrollable Feed
        self.scroll_feed = ctk.CTkScrollableFrame(
            self.tab_feed,
            fg_color=THEME["bg_feed_scroll"],
            corner_radius=12,
            border_width=1,
            border_color="#221742"
        )
        self.scroll_feed.pack(fill="both", expand=True)

        self.empty_label = ctk.CTkLabel(
            self.scroll_feed,
            text="Oczekiwanie na pierwsze skanowanie...\nKliknij 'ROZPOCZNIJ SNIPOWANIE' lub 'Skanuj teraz'",
            font=ctk.CTkFont(size=14),
            text_color=THEME["text_muted"]
        )
        self.empty_label.pack(pady=70)

    def _get_summary_text(self) -> str:
        q = self.cfg.get('search_query', 'iphone')
        cat = self.cfg.get('selected_category', 'Wszystkie')
        city = self.cfg.get('city_name', '')
        city_str = f" | 📍 {city}" if city else ""
        deliv_str = " | 📦 Przesyłka OLX" if self.cfg.get('olx_delivery_only', False) else ""
        return f"🎯 Cel: '{q}' [{cat}] | Min: {self.cfg.get('min_price_filter', 0):.0f} PLN | Maks: {self.cfg.get('max_price_filter', 0):.0f} PLN{city_str}{deliv_str}"

    # --- ZAKŁADKA 2: ULUBIONE CELE (PRESETS) ---
    def _build_tab_favorites_content(self):
        container = ctk.CTkFrame(self.tab_favorites, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=10, pady=10)

        # Gorny pasek akcji ulubionych
        top_fav = ctk.CTkFrame(container, fg_color=THEME["bg_section"], corner_radius=12, border_width=1, border_color="#281c47", height=50)
        top_fav.pack(fill="x", pady=(0, 10))
        top_fav.pack_propagate(False)

        ctk.CTkLabel(
            top_fav,
            text="⭐ Twoje Zapisane Cele i Wyszukiwania",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#fbbf24"
        ).pack(side="left", padx=16)

        btn_add_fav = ctk.CTkButton(
            top_fav,
            text="➕ Dodaj obecne filtry do ulubionych",
            height=32,
            fg_color=THEME["accent_purple"],
            hover_color=THEME["accent_purple_hover"],
            font=ctk.CTkFont(size=12, weight="bold"),
            corner_radius=8,
            command=self._prompt_add_favorite
        )
        btn_add_fav.pack(side="right", padx=14)

        # Kontener kart ulubionych
        self.scroll_favs = ctk.CTkScrollableFrame(
            container,
            fg_color=THEME["bg_feed_scroll"],
            corner_radius=12,
            border_width=1,
            border_color="#221742"
        )
        self.scroll_favs.pack(fill="both", expand=True)

        self._render_favorites_list()

    def _render_favorites_list(self):
        for w in self.scroll_favs.winfo_children():
            w.destroy()

        if not self.favorites:
            lbl_empty = ctk.CTkLabel(
                self.scroll_favs,
                text="Brak zapisanych ulubionych.\nUstaw swoje filtry i kliknij '➕ Dodaj obecne filtry do ulubionych'!",
                font=ctk.CTkFont(size=14),
                text_color=THEME["text_muted"]
            )
            lbl_empty.pack(pady=60)
            return

        for idx, fav in enumerate(self.favorites):
            card = ctk.CTkFrame(
                self.scroll_favs,
                fg_color=THEME["bg_card"],
                corner_radius=12,
                border_width=1,
                border_color="#2d1f52"
            )
            card.pack(fill="x", padx=6, pady=6)

            # Rząd 1: Nazwa + Tagi
            r1 = ctk.CTkFrame(card, fg_color="transparent")
            r1.pack(fill="x", padx=14, pady=(10, 4))

            name_lbl = ctk.CTkLabel(
                r1,
                text=fav.get("name", "Nienazwany cel"),
                font=ctk.CTkFont(size=15, weight="bold"),
                text_color="#ede9fe"
            )
            name_lbl.pack(side="left", padx=(0, 10))

            cat_lbl = ctk.CTkLabel(
                r1,
                text=f" 📂 {fav.get('selected_category', 'Wszystkie')} ",
                font=ctk.CTkFont(size=11),
                fg_color="#251a44",
                text_color="#c4b5fd",
                corner_radius=6,
                height=22
            )
            cat_lbl.pack(side="left", padx=(0, 6))

            if fav.get("exact_phrase_match", False):
                exact_lbl = ctk.CTkLabel(
                    r1,
                    text=" Exact Match ",
                    font=ctk.CTkFont(size=11, weight="bold"),
                    fg_color="#311956",
                    text_color="#d8b4fe",
                    corner_radius=6,
                    height=22
                )
                exact_lbl.pack(side="left", padx=(0, 6))

            if fav.get("olx_delivery_only", False):
                del_lbl = ctk.CTkLabel(
                    r1,
                    text=" 📦 Przesyłka OLX ",
                    font=ctk.CTkFont(size=11, weight="bold"),
                    fg_color="#064e3b",
                    text_color="#6ee7b7",
                    corner_radius=6,
                    height=22
                )
                del_lbl.pack(side="left", padx=(0, 6))

            if fav.get("city_name"):
                dist_str = f" +{fav.get('distance_km')}km" if fav.get('distance_km', 0) > 0 else ""
                loc_lbl = ctk.CTkLabel(
                    r1,
                    text=f" 📍 {fav.get('city_name')}{dist_str} ",
                    font=ctk.CTkFont(size=11),
                    fg_color="#1e1838",
                    text_color="#a78bfa",
                    corner_radius=6,
                    height=22
                )
                loc_lbl.pack(side="left")

            # Rząd 2: Parametry wyszukiwania i kwoty
            r2 = ctk.CTkFrame(card, fg_color="transparent")
            r2.pack(fill="x", padx=14, pady=(0, 8))

            query_text = f"Szukana fraza: '{fav.get('search_query', '')}'"
            min_p = fav.get('min_price_filter', 0)
            max_p = fav.get('max_price_filter', 0)
            price_text = f" | Cena: {min_p:.0f} - {max_p:.0f} PLN" if max_p > 0 else f" | Min: {min_p:.0f} PLN"

            desc_lbl = ctk.CTkLabel(
                r2,
                text=f"{query_text}{price_text}",
                font=ctk.CTkFont(size=12),
                text_color=THEME["text_muted"]
            )
            desc_lbl.pack(side="left")

            # Rząd 3: Przyciski akcji
            r3 = ctk.CTkFrame(card, fg_color="transparent")
            r3.pack(fill="x", padx=14, pady=(0, 10))

            btn_load_run = ctk.CTkButton(
                r3,
                text="▶ Szukaj tego celu teraz",
                width=170,
                height=28,
                fg_color=THEME["accent_purple"],
                hover_color=THEME["accent_purple_hover"],
                font=ctk.CTkFont(size=12, weight="bold"),
                corner_radius=8,
                command=lambda f=fav: self._load_favorite_and_run(f)
            )
            btn_load_run.pack(side="left", padx=(0, 10))

            btn_load_form = ctk.CTkButton(
                r3,
                text="✏️ Załaduj do filtrów",
                width=140,
                height=28,
                fg_color="#241a45",
                hover_color="#362866",
                font=ctk.CTkFont(size=12),
                corner_radius=8,
                command=lambda f=fav: self._load_favorite_to_form(f)
            )
            btn_load_form.pack(side="left", padx=(0, 10))

            btn_delete = ctk.CTkButton(
                r3,
                text="🗑️ Usuń",
                width=80,
                height=28,
                fg_color="#3f1322",
                hover_color="#5c1c32",
                text_color="#fca5a5",
                font=ctk.CTkFont(size=12),
                corner_radius=8,
                command=lambda i=idx: self._delete_favorite(i)
            )
            btn_delete.pack(side="right")

    def _update_quick_fav_combo(self, select_name: str = None):
        if hasattr(self, "combo_quick_fav"):
            fav_names = [f.get("name", "Cel") for f in self.favorites] if self.favorites else ["Brak ulubionych"]
            self.combo_quick_fav.configure(values=fav_names)
            if select_name and select_name in fav_names:
                self.combo_quick_fav.set(select_name)
            elif fav_names:
                self.combo_quick_fav.set(fav_names[0])

    def _prompt_add_favorite(self):
        modal = CyberModal._create_base(self, "Zapisz jako Ulubiony Cel", width=480, height=265)

        card = ctk.CTkFrame(modal, fg_color="#120c24", corner_radius=14, border_width=1, border_color="#3c2666")
        card.pack(fill="both", expand=True, padx=12, pady=12)

        top_row = ctk.CTkFrame(card, fg_color="transparent")
        top_row.pack(fill="x", padx=16, pady=(16, 6))

        ctk.CTkLabel(top_row, text="⭐", font=ctk.CTkFont(size=22)).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(
            top_row,
            text="Zapisz Obecne Filtry do Ulubionych",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#fbbf24"
        ).pack(side="left")

        ctk.CTkLabel(
            card,
            text="Wpisz nazwę dla tego celu (np. iPhone 15 Warszawa):",
            font=ctk.CTkFont(size=12),
            text_color=THEME["text_muted"]
        ).pack(anchor="w", padx=18, pady=(0, 8))

        cur_query = self.entry_query.get().strip() or "Cel"
        entry_fav_name = ctk.CTkEntry(
            card, 
            width=420, 
            height=36, 
            corner_radius=8,
            border_color="#4c268a",
            fg_color="#0c071a",
            text_color="#ffffff",
            font=ctk.CTkFont(size=12)
        )
        entry_fav_name.insert(0, f"🎯 {cur_query}")
        entry_fav_name.pack(padx=18, pady=(0, 16))
        entry_fav_name.focus_set()
        entry_fav_name.select_range(0, "end")

        def save_fav(event=None):
            fav_name = entry_fav_name.get().strip()
            if not fav_name:
                fav_name = f"🎯 {cur_query}"

            try:
                min_p = float(self.entry_min_price.get().strip()) if self.entry_min_price.get().strip() else 0.0
            except ValueError:
                min_p = 0.0
            try:
                max_p = float(self.entry_max_price.get().strip()) if self.entry_max_price.get().strip() else 0.0
            except ValueError:
                max_p = 0.0
            try:
                exp_p = float(self.entry_market_price.get().strip()) if self.entry_market_price.get().strip() else 0.0
            except ValueError:
                exp_p = 0.0

            selected_cat = self.combo_category.get()
            cat_id = CATEGORIES_MAP.get(selected_cat, 0)

            dist_str = self.combo_dist.get()
            import re
            m_dist = re.search(r"\d+", dist_str)
            dist_km = int(m_dist.group(0)) if m_dist else 0

            raw_exc = self.entry_exclude.get().split(",")
            exclude_list = [w.strip() for w in raw_exc if w.strip()]

            new_preset = {
                "name": fav_name,
                "search_query": self.entry_query.get().strip(),
                "exact_phrase_match": self.var_exact.get(),
                "selected_category": selected_cat,
                "category_id": cat_id,
                "min_price_filter": min_p,
                "max_price_filter": max_p,
                "expected_market_price": exp_p,
                "city_name": self.entry_city.get().strip(),
                "distance_km": dist_km,
                "olx_delivery_only": self.var_olx_deliv.get(),
                "deals_only_mode": self.var_deals_only.get(),
                "track_olx": self.var_olx.get(),
                "track_vinted": self.var_vinted.get(),
                "track_allegro_lokalnie": self.var_allegro_lokalnie.get(),
                "track_allegro": self.var_allegro.get(),
                "exclude_keywords": exclude_list
            }

            # Sprawdz czy cel o danej nazwie juz istnieje (porownanie bez wzgledu na wielkosc liter i prefiksy)
            norm_name = fav_name.strip().lower()
            norm_no_prefix = norm_name.lstrip("🎯").lstrip("⭐").strip()

            existing_idx = None
            for idx, f in enumerate(self.favorites):
                fn = f.get("name", "").strip().lower()
                fn_no_prefix = fn.lstrip("🎯").lstrip("⭐").strip()
                if norm_name == fn or (norm_no_prefix and norm_no_prefix == fn_no_prefix):
                    existing_idx = idx
                    break

            if existing_idx is not None:
                self.favorites[existing_idx] = new_preset
                save_favorites(self.favorites)
                self._render_favorites_list()
                self._update_quick_fav_combo(select_name=fav_name)
                modal.destroy()
                self._on_status_update(f"Zaktualizowano cel '{fav_name}' w ulubionych.")
                CyberModal.show_info(
                    self, 
                    "Zaktualizowano Cel", 
                    f"Istniejący cel '{fav_name}' został pomyślnie zaktualizowany o nowe filtry!", 
                    icon_symbol="💾"
                )
            else:
                self.favorites.insert(0, new_preset)
                save_favorites(self.favorites)
                self._render_favorites_list()
                self._update_quick_fav_combo(select_name=fav_name)
                modal.destroy()
                self._on_status_update(f"Zapisano '{fav_name}' do ulubionych celów.")
                CyberModal.show_info(
                    self, 
                    "Zapisano Cel", 
                    f"Cel '{fav_name}' został dodany do Twojej listy ulubionych!", 
                    icon_symbol="⭐"
                )

        btn_box = ctk.CTkFrame(card, fg_color="transparent")
        btn_box.pack(pady=(0, 10))

        btn_save = ctk.CTkButton(
            btn_box,
            text="💾 Zapisz Cel",
            width=135,
            height=32,
            fg_color=THEME["accent_purple"],
            hover_color=THEME["accent_purple_hover"],
            font=ctk.CTkFont(size=12, weight="bold"),
            corner_radius=8,
            command=save_fav
        )
        btn_save.pack(side="left", padx=8)

        def on_cancel(event=None):
            modal.destroy()

        btn_cancel = ctk.CTkButton(
            btn_box,
            text="Anuluj",
            width=100,
            height=32,
            fg_color="#21183c",
            hover_color="#362562",
            font=ctk.CTkFont(size=12),
            corner_radius=8,
            command=on_cancel
        )
        btn_cancel.pack(side="left", padx=8)

        modal.bind("<Return>", save_fav)
        modal.bind("<Escape>", on_cancel)
        self.wait_window(modal)

    def _load_favorite_to_form(self, fav: Dict[str, Any]):
        self.entry_query.delete(0, "end")
        self.entry_query.insert(0, fav.get("search_query", ""))

        self.var_exact.set(fav.get("exact_phrase_match", False))

        cat = fav.get("selected_category", "Wszystkie kategorie (Uniwersalne)")
        if cat in CATEGORIES_MAP:
            self.combo_category.set(cat)

        self.entry_city.delete(0, "end")
        self.entry_city.insert(0, fav.get("city_name", ""))

        dist = fav.get("distance_km", 0)
        dist_match = f"+{dist} km" if dist > 0 else "0 km (Tylko dane miasto)"
        self.combo_dist.set(dist_match)

        self.var_olx_deliv.set(fav.get("olx_delivery_only", False))

        min_p = fav.get("min_price_filter", 0)
        self.entry_min_price.delete(0, "end")
        self.entry_min_price.insert(0, str(int(min_p)) if min_p > 0 else "")

        max_p = fav.get("max_price_filter", 0)
        self.entry_max_price.delete(0, "end")
        self.entry_max_price.insert(0, str(int(max_p)) if max_p > 0 else "")

        exp_p = fav.get("expected_market_price", 0)
        self.entry_market_price.delete(0, "end")
        self.entry_market_price.insert(0, str(int(exp_p)) if exp_p > 0 else "")

        self.var_deals_only.set(fav.get("deals_only_mode", False))

        self.var_olx.set(fav.get("track_olx", True))
        self.var_vinted.set(fav.get("track_vinted", True))
        self.var_allegro_lokalnie.set(fav.get("track_allegro_lokalnie", True))
        self.var_allegro.set(fav.get("track_allegro", True))

        self.entry_exclude.delete(0, "end")
        self.entry_exclude.insert(0, ", ".join(fav.get("exclude_keywords", [])))

        self._update_quick_fav_combo(select_name=fav.get("name"))
        self.tabview.set("⚙️  Filtry & Kategoria")
        self._on_status_update(f"Załadowano cel '{fav.get('name')}' do formularza.")

    def _load_favorite_and_run(self, fav: Dict[str, Any]):
        self._load_favorite_to_form(fav)
        self._apply_settings(notify=False)
        self.tabview.set("🎯  Strumień Okazji")
        self._trigger_instant_scan()

    def _delete_favorite(self, idx: int):
        if 0 <= idx < len(self.favorites):
            fav_name = self.favorites[idx].get("name", "Nienazwany cel")
            confirmed = CyberModal.show_confirm(
                self,
                "Usuń z Ulubionych",
                f"Czy na pewno chcesz usunąć cel:\n'{fav_name}' z listy ulubionych?",
                confirm_text="Tak, usuń",
                cancel_text="Anuluj"
            )
            if not confirmed:
                return
            removed = self.favorites.pop(idx)
            save_favorites(self.favorites)
            self._render_favorites_list()
            self._update_quick_fav_combo()
            self._on_status_update(f"Usunięto '{removed.get('name')}' z ulubionych.")

    # --- ZAKŁADKA 3: FILTRY & KATEGORIA ---
    def _build_tab_filters_content(self):
        container = ctk.CTkScrollableFrame(self.tab_filters, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=10, pady=10)

        # Szybki pasek ulubionych na samej górze
        quick_fav_box = ctk.CTkFrame(container, fg_color=THEME["bg_section"], corner_radius=12, border_width=1, border_color="#281c47")
        quick_fav_box.pack(fill="x", pady=(0, 14), padx=6)

        ctk.CTkLabel(
            quick_fav_box,
            text="⭐ Szybkie Wczytanie z Ulubionych Celów",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#fbbf24"
        ).pack(anchor="w", padx=18, pady=(12, 6))

        row_fav_quick = ctk.CTkFrame(quick_fav_box, fg_color="transparent")
        row_fav_quick.pack(fill="x", padx=18, pady=(0, 12))

        fav_names = [f.get("name", "Cel") for f in self.favorites] if self.favorites else ["Brak ulubionych"]
        self.combo_quick_fav = ctk.CTkComboBox(
            row_fav_quick,
            values=fav_names,
            width=280,
            height=32,
            corner_radius=8,
            border_color="#3c2666",
            button_color=THEME["accent_violet"]
        )
        if fav_names:
            self.combo_quick_fav.set(fav_names[0])
        self.combo_quick_fav.pack(side="left", padx=(0, 10))

        def load_from_combo():
            selected_name = self.combo_quick_fav.get()
            for f in self.favorites:
                if f.get("name") == selected_name:
                    self._load_favorite_to_form(f)
                    CyberModal.show_info(
                        self, 
                        "Załadowano Cel", 
                        f"Pomyślnie załadowano filtry dla celu:\n'{selected_name}'", 
                        icon_symbol="⚡"
                    )
                    return

        def load_and_run_from_combo():
            selected_name = self.combo_quick_fav.get()
            for f in self.favorites:
                if f.get("name") == selected_name:
                    self._load_favorite_and_run(f)
                    return

        btn_load_quick = ctk.CTkButton(
            row_fav_quick,
            text="⚡ Załaduj filtry",
            width=110,
            height=32,
            fg_color=THEME["accent_violet"],
            hover_color=THEME["accent_purple_hover"],
            font=ctk.CTkFont(size=12, weight="bold"),
            corner_radius=8,
            command=load_from_combo
        )
        btn_load_quick.pack(side="left", padx=(0, 8))

        btn_run_quick = ctk.CTkButton(
            row_fav_quick,
            text="🎯 Załaduj i Szukaj",
            width=130,
            height=32,
            fg_color=THEME["accent_purple"],
            hover_color=THEME["accent_purple_hover"],
            font=ctk.CTkFont(size=12, weight="bold"),
            corner_radius=8,
            command=load_and_run_from_combo
        )
        btn_run_quick.pack(side="left", padx=(0, 8))

        btn_save_current_fav = ctk.CTkButton(
            row_fav_quick,
            text="⭐ Zapisz obecne filtry",
            width=150,
            height=32,
            fg_color="#3b1b66",
            hover_color="#51268c",
            font=ctk.CTkFont(size=12),
            corner_radius=8,
            command=self._prompt_add_favorite
        )
        btn_save_current_fav.pack(side="left")

        # Karta 1: Szukany Przedmiot & Kategoria
        box1 = ctk.CTkFrame(container, fg_color=THEME["bg_section"], corner_radius=12, border_width=1, border_color="#281c47")
        box1.pack(fill="x", pady=(0, 14), padx=6)

        ctk.CTkLabel(
            box1,
            text="🔍 Szukany Przedmiot & Kategoria",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=THEME["accent_purple"]
        ).pack(anchor="w", padx=18, pady=(14, 8))

        row1 = ctk.CTkFrame(box1, fg_color="transparent")
        row1.pack(fill="x", padx=18, pady=(0, 10))

        ctk.CTkLabel(row1, text="Szukana fraza:", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=(0, 10))
        self.entry_query = ctk.CTkEntry(
            row1,
            width=280,
            height=34,
            corner_radius=8,
            border_color="#3c2666",
            placeholder_text="np. iPhone 15, RTX 4070, LEGO Star Wars, Rower..."
        )
        self.entry_query.insert(0, self.cfg.get("search_query", "iphone"))
        self.entry_query.pack(side="left", padx=(0, 24))

        ctk.CTkLabel(row1, text="Kategoria:", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=(0, 10))
        self.combo_category = ctk.CTkComboBox(
            row1,
            values=list(CATEGORIES_MAP.keys()),
            width=260,
            height=34,
            corner_radius=8,
            border_color="#3c2666",
            button_color=THEME["accent_violet"]
        )
        self.combo_category.set(self.cfg.get("selected_category", "Wszystkie kategorie (Uniwersalne)"))
        self.combo_category.pack(side="left")

        row1_sub = ctk.CTkFrame(box1, fg_color="transparent")
        row1_sub.pack(fill="x", padx=18, pady=(0, 14))

        self.var_exact = tk.BooleanVar(value=self.cfg.get("exact_phrase_match", False))
        self.switch_exact = ctk.CTkSwitch(
            row1_sub,
            text="Szukaj dokładnie tej frazy (Exact Match - odrzuca inne warianty)",
            variable=self.var_exact,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#c4b5fd",
            progress_color=THEME["accent_purple"]
        )
        self.switch_exact.pack(side="left")

        # Karta 2: Lokalizacja & Przesyłka OLX
        box_geo = ctk.CTkFrame(container, fg_color=THEME["bg_section"], corner_radius=12, border_width=1, border_color="#281c47")
        box_geo.pack(fill="x", pady=(0, 14), padx=6)

        ctk.CTkLabel(
            box_geo,
            text="📍 Lokalizacja & Przesyłka OLX",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#c084fc"
        ).pack(anchor="w", padx=18, pady=(14, 8))

        row_geo1 = ctk.CTkFrame(box_geo, fg_color="transparent")
        row_geo1.pack(fill="x", padx=18, pady=(0, 10))

        ctk.CTkLabel(row_geo1, text="Miasto:", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=(0, 8))
        self.entry_city = ctk.CTkEntry(
            row_geo1,
            width=200,
            height=34,
            corner_radius=8,
            border_color="#3c2666",
            placeholder_text="np. Warszawa (puste = cała Polska)"
        )
        self.entry_city.insert(0, self.cfg.get("city_name", ""))
        self.entry_city.pack(side="left", padx=(0, 24))

        ctk.CTkLabel(row_geo1, text="Zasięg w km:", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=(0, 8))
        self.combo_dist = ctk.CTkComboBox(
            row_geo1,
            values=DISTANCE_OPTIONS,
            width=210,
            height=34,
            corner_radius=8,
            border_color="#3c2666",
            button_color=THEME["accent_violet"]
        )
        cur_dist = self.cfg.get("distance_km", 0)
        dist_match = f"+{cur_dist} km" if cur_dist > 0 else "0 km (Tylko dane miasto)"
        self.combo_dist.set(dist_match)
        self.combo_dist.pack(side="left")

        row_geo2 = ctk.CTkFrame(box_geo, fg_color="transparent")
        row_geo2.pack(fill="x", padx=18, pady=(0, 14))

        self.var_olx_deliv = tk.BooleanVar(value=self.cfg.get("olx_delivery_only", False))
        self.switch_olx_deliv = ctk.CTkSwitch(
            row_geo2,
            text="📦 Tylko oferty z Przesyłką OLX (Bezpieczna dostawa kurierska)",
            variable=self.var_olx_deliv,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#6ee7b7",
            progress_color=THEME["accent_mint"]
        )
        self.switch_olx_deliv.pack(side="left")

        # Karta 3: Budżet i Progi Okazji
        box2 = ctk.CTkFrame(container, fg_color=THEME["bg_section"], corner_radius=12, border_width=1, border_color="#281c47")
        box2.pack(fill="x", pady=(0, 14), padx=6)

        ctk.CTkLabel(
            box2,
            text="💰 Budżet i Progi Okazji",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=THEME["accent_mint"]
        ).pack(anchor="w", padx=18, pady=(14, 8))

        row2 = ctk.CTkFrame(box2, fg_color="transparent")
        row2.pack(fill="x", padx=18, pady=(0, 10))

        ctk.CTkLabel(row2, text="Min. PLN:", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=(0, 6))
        self.entry_min_price = ctk.CTkEntry(row2, width=95, height=32, corner_radius=8, border_color="#3c2666", placeholder_text="np. 50")
        min_p = self.cfg.get("min_price_filter", 50)
        self.entry_min_price.insert(0, str(int(min_p)) if min_p > 0 else "")
        self.entry_min_price.pack(side="left", padx=(0, 20))

        ctk.CTkLabel(row2, text="Maks. PLN (Twój limit okazji):", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=(0, 6))
        self.entry_max_price = ctk.CTkEntry(row2, width=105, height=32, corner_radius=8, border_color="#3c2666", placeholder_text="0 = brak")
        max_p = self.cfg.get("max_price_filter", 0)
        self.entry_max_price.insert(0, str(int(max_p)) if max_p > 0 else "")
        self.entry_max_price.pack(side="left", padx=(0, 20))

        ctk.CTkLabel(row2, text="Cena rynkowa (PLN):", font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 6))
        self.entry_market_price = ctk.CTkEntry(row2, width=105, height=32, corner_radius=8, border_color="#3c2666", placeholder_text="opcja")
        exp_p = self.cfg.get("expected_market_price", 0)
        self.entry_market_price.insert(0, str(int(exp_p)) if exp_p > 0 else "")
        self.entry_market_price.pack(side="left")

        row2_sub = ctk.CTkFrame(box2, fg_color="transparent")
        row2_sub.pack(fill="x", padx=18, pady=(0, 14))

        self.var_deals_only = tk.BooleanVar(value=self.cfg.get("deals_only_mode", False))
        self.switch_deals_only = ctk.CTkSwitch(
            row2_sub,
            text="Pokazuj wyłącznie oferty w progu okazji cenowej",
            variable=self.var_deals_only,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#34d399",
            progress_color=THEME["accent_mint"]
        )
        self.switch_deals_only.pack(side="left")

        # Karta 4: Serwisy
        box3 = ctk.CTkFrame(container, fg_color=THEME["bg_section"], corner_radius=12, border_width=1, border_color="#281c47")
        box3.pack(fill="x", pady=(0, 14), padx=6)

        ctk.CTkLabel(
            box3,
            text="🏪 Monitorowane Serwisy",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=THEME["accent_amber"]
        ).pack(anchor="w", padx=18, pady=(14, 8))

        row3 = ctk.CTkFrame(box3, fg_color="transparent")
        row3.pack(fill="x", padx=18, pady=(0, 14))

        self.var_olx = tk.BooleanVar(value=self.cfg.get("track_olx", True))
        self.chk_olx = ctk.CTkCheckBox(row3, text="OLX API", variable=self.var_olx, font=ctk.CTkFont(size=12, weight="bold"), text_color="#34d399", fg_color=THEME["accent_violet"])
        self.chk_olx.pack(side="left", padx=(0, 20))

        self.var_vinted = tk.BooleanVar(value=self.cfg.get("track_vinted", True))
        self.chk_vinted = ctk.CTkCheckBox(row3, text="Vinted", variable=self.var_vinted, font=ctk.CTkFont(size=12, weight="bold"), text_color="#38bdf8", fg_color=THEME["accent_violet"])
        self.chk_vinted.pack(side="left", padx=(0, 20))

        self.var_allegro_lokalnie = tk.BooleanVar(value=self.cfg.get("track_allegro_lokalnie", True))
        self.chk_allegro_lokalnie = ctk.CTkCheckBox(row3, text="Allegro Lokalnie", variable=self.var_allegro_lokalnie, font=ctk.CTkFont(size=12, weight="bold"), text_color="#fb923c", fg_color=THEME["accent_violet"])
        self.chk_allegro_lokalnie.pack(side="left", padx=(0, 20))

        self.var_allegro = tk.BooleanVar(value=self.cfg.get("track_allegro", True))
        self.chk_allegro = ctk.CTkCheckBox(row3, text="Allegro (Główne)", variable=self.var_allegro, font=ctk.CTkFont(size=12, weight="bold"), text_color="#f97316", fg_color=THEME["accent_violet"])
        self.chk_allegro.pack(side="left")

        # Karta 5: Czarna Lista Słów
        box4 = ctk.CTkFrame(container, fg_color=THEME["bg_section"], corner_radius=12, border_width=1, border_color="#281c47")
        box4.pack(fill="x", pady=(0, 14), padx=6)

        ctk.CTkLabel(
            box4,
            text="🛡️ Czarna Lista Słów (Odrzucanie śmieci i uszkodzonych)",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=THEME["accent_fuchsia"]
        ).pack(anchor="w", padx=18, pady=(14, 4))

        ctk.CTkLabel(
            box4,
            text="Wpisz słowa oddzielone przecinkami (np. uszkodzony, pudełko, etui, na części):",
            font=ctk.CTkFont(size=11),
            text_color=THEME["text_muted"]
        ).pack(anchor="w", padx=18, pady=(0, 8))

        self.entry_exclude = ctk.CTkEntry(box4, height=34, corner_radius=8, border_color="#3c2666")
        exc_str = ", ".join(self.cfg.get("exclude_keywords", []))
        self.entry_exclude.insert(0, exc_str)
        self.entry_exclude.pack(fill="x", padx=18, pady=(0, 14))

        btn_apply = ctk.CTkButton(
            container,
            text="💾 ZAPISZ I ZASTOSUJ FILTRY",
            height=44,
            fg_color=THEME["accent_purple"],
            hover_color=THEME["accent_purple_hover"],
            font=ctk.CTkFont(size=14, weight="bold"),
            corner_radius=10,
            command=lambda: self._apply_settings(notify=True)
        )
        btn_apply.pack(fill="x", padx=6, pady=(4, 16))

    # --- ZAKŁADKA: VINTED & AUTO-OFERTY ---
    def _build_tab_vinted_content(self):
        container = ctk.CTkScrollableFrame(self.tab_vinted, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=10, pady=10)

        # 1. Karta: Status konta i autoryzacja Vinted
        box_auth = ctk.CTkFrame(container, fg_color=THEME["bg_section"], corner_radius=12, border_width=1, border_color="#281c47")
        box_auth.pack(fill="x", pady=(0, 14), padx=6)

        ctk.CTkLabel(
            box_auth,
            text="🤝 Logowanie & Połączenie Konta Vinted",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#38bdf8"
        ).pack(anchor="w", padx=18, pady=(14, 4))

        # Status badge
        self.badge_vinted_status = ctk.CTkLabel(
            box_auth,
            text="⚪ Status: Niepołączono" if not self.cfg.get("vinted_is_logged_in") else f"🟢 Połączono jako @{self.cfg.get('vinted_user_login', 'Użytkownik')}",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#94a3b8" if not self.cfg.get("vinted_is_logged_in") else "#34d399"
        )
        self.badge_vinted_status.pack(anchor="w", padx=18, pady=(0, 10))

        ctk.CTkLabel(
            box_auth,
            text="Ciasteczko sesji (_vinted_fr_session):",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=THEME["text_lavender"]
        ).pack(anchor="w", padx=18, pady=(4, 2))

        cookie_row = ctk.CTkFrame(box_auth, fg_color="transparent")
        cookie_row.pack(fill="x", padx=18, pady=(0, 10))

        self.entry_vinted_cookie = ctk.CTkEntry(
            cookie_row,
            height=34,
            corner_radius=8,
            border_color="#3c2666",
            show="*",
            placeholder_text="Wklej wartość _vinted_fr_session lub cały nagłówek Cookie..."
        )
        self.entry_vinted_cookie.insert(0, self.cfg.get("vinted_session_cookie", ""))
        self.entry_vinted_cookie.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.btn_vinted_toggle_show = ctk.CTkButton(
            cookie_row,
            text="👁 Pokaż",
            width=85,
            height=34,
            fg_color="#241a45",
            hover_color="#362866",
            font=ctk.CTkFont(size=12),
            corner_radius=8,
            command=self._toggle_vinted_cookie_visibility
        )
        self.btn_vinted_toggle_show.pack(side="right")

        # Przyciski akcji autoryzacji
        auth_btn_row = ctk.CTkFrame(box_auth, fg_color="transparent")
        auth_btn_row.pack(fill="x", padx=18, pady=(0, 14))

        self.btn_vinted_auto = ctk.CTkButton(
            auth_btn_row,
            text="⚡ Zaloguj i Pobierz Automatycznie",
            height=36,
            fg_color="#0284c7",
            hover_color="#0369a1",
            font=ctk.CTkFont(size=12, weight="bold"),
            corner_radius=8,
            command=self._auto_detect_vinted_cookie
        )
        self.btn_vinted_auto.pack(side="left", padx=(0, 8))

        self.btn_vinted_paste = ctk.CTkButton(
            auth_btn_row,
            text="📋 Wklej ze Schowka",
            height=36,
            fg_color="#312e81",
            hover_color="#3730a3",
            font=ctk.CTkFont(size=12),
            corner_radius=8,
            command=self._paste_vinted_cookie
        )
        self.btn_vinted_paste.pack(side="left", padx=(0, 8))

        self.btn_vinted_verify = ctk.CTkButton(
            auth_btn_row,
            text="🔍 Sprawdź i Połącz Konto",
            height=36,
            fg_color=THEME["accent_purple"],
            hover_color=THEME["accent_purple_hover"],
            font=ctk.CTkFont(size=12, weight="bold"),
            corner_radius=8,
            command=self._verify_vinted_account
        )
        self.btn_vinted_verify.pack(side="left", padx=(0, 8))

        self.btn_vinted_disconnect = ctk.CTkButton(
            auth_btn_row,
            text="🔌 Rozłącz Konto",
            height=36,
            fg_color="#881337",
            hover_color="#be123c",
            font=ctk.CTkFont(size=12),
            corner_radius=8,
            command=self._disconnect_vinted_account
        )
        self.btn_vinted_disconnect.pack(side="left")

        # Mini przewodnik
        guide_box = ctk.CTkFrame(box_auth, fg_color="#0c0819", corner_radius=8, border_width=1, border_color="#23173d")
        guide_box.pack(fill="x", padx=18, pady=(0, 14))

        guide_text = (
            "💡 Wygodne logowanie automatyczne:\n"
            "1. Kliknij '⚡ Zaloguj i Pobierz Automatycznie' — otworzy się dedykowane okno Vinted.\n"
            "2. Zaloguj się na swoje konto (Google/Email). Program natychmiast sam pobierze sesję i połączy konto!\n"
            "3. Możesz również wkleić ciasteczko _vinted_fr_session bezpośrednio ze schowka."
        )
        ctk.CTkLabel(
            guide_box,
            text=guide_text,
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8",
            justify="left"
        ).pack(anchor="w", padx=12, pady=10)

        # 2. Karta: Automatyczne Proponowanie Cen (-% rabatu)
        box_auto = ctk.CTkFrame(container, fg_color=THEME["bg_section"], corner_radius=12, border_width=1, border_color="#281c47")
        box_auto.pack(fill="x", pady=(0, 14), padx=6)

        ctk.CTkLabel(
            box_auto,
            text="⚡ Automatyczne Negocjacje Cenowe (-%)",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=THEME["accent_mint"]
        ).pack(anchor="w", padx=18, pady=(14, 4))

        ctk.CTkLabel(
            box_auto,
            text="System automatycznie złoży ofertę cenową ze wskazanym rabatem natychmiast po znalezieniu nowej okazji na Vinted.",
            font=ctk.CTkFont(size=11),
            text_color=THEME["text_muted"]
        ).pack(anchor="w", padx=18, pady=(0, 10))

        # Switch włączenia auto-oferty
        self.var_vinted_auto = tk.BooleanVar(value=bool(self.cfg.get("vinted_auto_offer_enabled", False)))
        self.switch_vinted_auto = ctk.CTkSwitch(
            box_auto,
            text="Włącz automatyczne składanie ofert cenowych na Vinted",
            variable=self.var_vinted_auto,
            font=ctk.CTkFont(size=13, weight="bold"),
            progress_color=THEME["accent_mint"]
        )
        self.switch_vinted_auto.pack(anchor="w", padx=18, pady=(0, 14))

        # Suwak i pole % rabatu
        slider_frame = ctk.CTkFrame(box_auto, fg_color="transparent")
        slider_frame.pack(fill="x", padx=18, pady=(0, 10))

        init_pct = float(self.cfg.get("vinted_discount_percent", 10.0) or 10.0)
        self.lbl_vinted_pct_val = ctk.CTkLabel(
            slider_frame,
            text=f"Proponowany rabat: {init_pct:.0f}%",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=THEME["accent_purple"]
        )
        self.lbl_vinted_pct_val.pack(anchor="w", pady=(0, 6))

        slider_row = ctk.CTkFrame(slider_frame, fg_color="transparent")
        slider_row.pack(fill="x")

        self.slider_vinted_pct = ctk.CTkSlider(
            slider_row,
            from_=1.0,
            to=40.0,
            number_of_steps=39,
            progress_color=THEME["accent_purple"],
            button_color=THEME["accent_mint"],
            command=self._on_vinted_slider_change
        )
        self.slider_vinted_pct.set(init_pct)
        self.slider_vinted_pct.pack(side="left", fill="x", expand=True, padx=(0, 14))

        # Przyciski szybkich wartości rabatu
        quick_pct_box = ctk.CTkFrame(box_auto, fg_color="transparent")
        quick_pct_box.pack(anchor="w", padx=18, pady=(0, 10))

        ctk.CTkLabel(quick_pct_box, text="Szybki wybór:", font=ctk.CTkFont(size=11), text_color=THEME["text_muted"]).pack(side="left", padx=(0, 8))
        for p in (5, 10, 15, 20, 25, 30):
            b = ctk.CTkButton(
                quick_pct_box,
                text=f"-{p}%",
                width=50,
                height=26,
                fg_color="#21183c",
                hover_color="#362562",
                font=ctk.CTkFont(size=11),
                corner_radius=6,
                command=lambda val=p: self._set_vinted_discount_quick(val)
            )
            b.pack(side="left", padx=4)

        # Dynamiczny podgląd propozycji (np. z 50 zł -> 45 zł)
        self.lbl_vinted_preview = ctk.CTkLabel(
            box_auto,
            text=self._get_vinted_preview_string(init_pct),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#6ee7b7"
        )
        self.lbl_vinted_preview.pack(anchor="w", padx=18, pady=(4, 14))

        # Zapisz ustawienia Vinted
        btn_save_vinted = ctk.CTkButton(
            container,
            text="💾 ZAPISZ USTAWIENIA VINTED",
            height=44,
            fg_color=THEME["accent_purple"],
            hover_color=THEME["accent_purple_hover"],
            font=ctk.CTkFont(size=14, weight="bold"),
            corner_radius=10,
            command=self._save_vinted_settings
        )
        btn_save_vinted.pack(fill="x", padx=6, pady=(4, 16))

    def _toggle_vinted_cookie_visibility(self):
        if self.entry_vinted_cookie.cget("show") == "*":
            self.entry_vinted_cookie.configure(show="")
            self.btn_vinted_toggle_show.configure(text="🔒 Ukryj")
        else:
            self.entry_vinted_cookie.configure(show="*")
            self.btn_vinted_toggle_show.configure(text="👁 Pokaż")

    def _on_vinted_slider_change(self, val):
        pct = round(float(val))
        self.lbl_vinted_pct_val.configure(text=f"Proponowany rabat: {pct}%")
        self.lbl_vinted_preview.configure(text=self._get_vinted_preview_string(pct))

    def _set_vinted_discount_quick(self, pct: int):
        self.slider_vinted_pct.set(pct)
        self._on_vinted_slider_change(pct)

    def _get_vinted_preview_string(self, pct: float) -> str:
        # Przykład kalkulacji: 50 zł -> 45 zł oraz 100 zł -> 90 zł
        p50 = calculate_vinted_offer_price(50.0, pct)
        p100 = calculate_vinted_offer_price(100.0, pct)
        p200 = calculate_vinted_offer_price(200.0, pct)
        return f"💡 Podgląd: Z 50 zł zaoferuje {p50:.0f} zł | Z 100 zł zaoferuje {p100:.0f} zł | Z 200 zł zaoferuje {p200:.0f} zł"

    def _auto_detect_vinted_cookie(self):
        """Automatycznie pozyskuje ciasteczko sesji Vinted z przeglądarki lub dedykowanego okna CDP."""
        self.btn_vinted_auto.configure(text="⏳ Uruchamianie...", state="disabled")
        self._on_status_update("Szukanie aktywnej sesji Vinted...")

        def _worker():
            from deal_engine import VintedClient

            # 1. Próba natychmiastowego odczytu z baz danych przeglądarek
            found = VintedClient.auto_extract_browser_cookie()
            cookie_val = found.get("cookie") if found else None

            # 2. Sprawdzenie schowka (tylko jeśli w schowku jest autentyczne, zweryfikowane ciasteczko)
            if not cookie_val:
                try:
                    clip = self.clipboard_get().strip()
                except Exception:
                    clip = ""
                candidate = ""
                if "_vinted_fr_session=" in clip:
                    for part in clip.split(";"):
                        part = part.strip()
                        if part.startswith("_vinted_fr_session="):
                            candidate = part.split("_vinted_fr_session=")[1].strip()
                            break
                elif len(clip) >= 24 and not clip.startswith("http") and "/" not in clip and "olx" not in clip.lower():
                    candidate = clip

                if candidate and VintedClient.is_cookie_authenticated(candidate):
                    cookie_val = candidate

            # 3. Jeśli sesja nie jest jeszcze znana, uruchom okno logowania Chrome/Edge przez CDP
            if not cookie_val:
                def _status_cb(msg: str):
                    self.after(0, lambda: self._on_status_update(msg))
                    if "Otwarto okno" in msg or "Zaloguj się" in msg:
                        self.after(0, lambda: self.btn_vinted_auto.configure(text="⏳ Czekam na logowanie..."))

                cookie_val = VintedClient.launch_browser_for_cookie(on_status=_status_cb, timeout_sec=240)

            def _done():
                self.btn_vinted_auto.configure(text="⚡ Zaloguj i Pobierz Automatycznie", state="normal")
                if cookie_val:
                    self.entry_vinted_cookie.delete(0, "end")
                    self.entry_vinted_cookie.insert(0, cookie_val)
                    self._on_status_update("Pobrano ciasteczko Vinted! Łączenie z kontem...")
                    self._verify_vinted_account()
                else:
                    self._on_status_update("Anulowano automatyczne pobieranie sesji Vinted.")

            self.after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    def _paste_vinted_cookie(self):
        """Wkleja i czyści ciasteczko sesji Vinted bezpośrednio ze schowka systemowego."""
        try:
            raw = self.clipboard_get().strip()
        except Exception:
            CyberModal.show_warning(self, "Pusty Schowek", "Schowek systemowy jest pusty.")
            return

        if not raw:
            CyberModal.show_warning(self, "Pusty Schowek", "W schowku nie ma skopiowanego tekstu.")
            return

        # Odrzuć linki OLX i inne URL
        if "olx.pl" in raw.lower() or "allegro.pl" in raw.lower():
            CyberModal.show_warning(
                self,
                "Nieprawidłowa Zawartość",
                "W Twoim schowku znajduje się link z serwisu OLX/Allegro, a nie ciasteczko sesji Vinted.\n\n"
                "Skopiuj ciasteczko '_vinted_fr_session' ze strony vinted.pl."
            )
            return

        cookie_val = raw
        if "_vinted_fr_session=" in raw and "access_token_web=" not in raw:
            for part in raw.split(";"):
                part = part.strip()
                if part.startswith("_vinted_fr_session="):
                    cookie_val = part.split("_vinted_fr_session=")[1].strip()
                    break

        self.entry_vinted_cookie.delete(0, "end")
        self.entry_vinted_cookie.insert(0, cookie_val)
        self._on_status_update("Wklejono ciasteczko sesji Vinted ze schowka.")
        self._verify_vinted_account()

    def _verify_vinted_account(self):
        cookie = self.entry_vinted_cookie.get().strip()
        if not cookie:
            CyberModal.show_warning(self, "Brak Ciasteczka", "Wprowadź ciasteczko sesji _vinted_fr_session z przeglądarki.")
            return

        self.btn_vinted_verify.configure(text="⏳ Weryfikacja...", state="disabled")

        def _worker():
            self.engine.vinted_client.set_cookie(cookie)
            res = self.engine.vinted_client.verify_account()

            def _done():
                self.btn_vinted_verify.configure(text="🔍 Sprawdź i Połącz Konto", state="normal")
                if res.get("success"):
                    uname = res.get("username", "Użytkownik")
                    self.cfg["vinted_session_cookie"] = cookie
                    self.cfg["vinted_user_login"] = uname
                    self.cfg["vinted_is_logged_in"] = True
                    save_config(self.cfg)
                    self.badge_vinted_status.configure(
                        text=f"🟢 Połączono jako @{uname}",
                        text_color="#34d399"
                    )
                    self._on_status_update(f"Połączono konto Vinted: @{uname}")
                    CyberModal.show_info(
                        self,
                        "Połączono z Vinted",
                        f"Pomyślnie uwierzytelniono konto Vinted!\nZalogowano jako: @{uname}",
                        icon_symbol="🤝"
                    )
                else:
                    err = res.get("error", "Nieznany błąd autoryzacji")
                    self.badge_vinted_status.configure(
                        text="🔴 Błąd autoryzacji",
                        text_color="#f43f5e"
                    )
                    CyberModal.show_error(self, "Błąd Vinted", f"Nie udało się połączyć konta:\n{err}")

            self.after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    def _disconnect_vinted_account(self):
        confirmed = CyberModal.show_confirm(
            self,
            "Rozłącz Konto Vinted",
            "Czy na pewno chcesz usunąć zapisaną sesję Vinted?",
            confirm_text="Rozłącz",
            cancel_text="Anuluj"
        )
        if not confirmed:
            return

        self.cfg["vinted_session_cookie"] = ""
        self.cfg["vinted_user_login"] = ""
        self.cfg["vinted_is_logged_in"] = False
        self.cfg["vinted_auto_offer_enabled"] = False
        self.entry_vinted_cookie.delete(0, "end")
        self.var_vinted_auto.set(False)
        self.badge_vinted_status.configure(text="⚪ Status: Niepołączono", text_color="#94a3b8")
        save_config(self.cfg)
        self.engine.update_config(self.cfg)
        self._on_status_update("Rozłączono konto Vinted.")
        CyberModal.show_info(self, "Rozłączono", "Konto Vinted zostało odłączone.", icon_symbol="🔌")

    def _save_vinted_settings(self):
        cookie = self.entry_vinted_cookie.get().strip()
        auto_on = self.var_vinted_auto.get()
        pct = round(float(self.slider_vinted_pct.get()), 1)

        self.cfg["vinted_session_cookie"] = cookie
        self.cfg["vinted_auto_offer_enabled"] = auto_on
        self.cfg["vinted_discount_percent"] = pct

        save_config(self.cfg)
        self.engine.update_config(self.cfg)

        status_txt = f"Auto-oferty: {'WŁĄCZONE' if auto_on else 'WYŁĄCZONE'} (-{pct:.0f}%)"
        self._on_status_update(f"Zapisano ustawienia Vinted. {status_txt}")
        CyberModal.show_info(
            self,
            "Zapisano Ustawienia Vinted",
            f"Ustawienia Vinted zostały pomyślnie zaktualizowane!\n• Rabat: {pct:.0f}%\n• Automatyczne składanie: {'Aktywne' if auto_on else 'Wyłączone'}",
            icon_symbol="💾"
        )

    def _manual_vinted_offer(self, offer: Offer):
        """Wysyła ofertę ze zniżką 1 kliknięciem z poziomu karty ogłoszenia."""
        cookie = self.cfg.get("vinted_session_cookie", "").strip()
        if not cookie:
            CyberModal.show_warning(
                self,
                "Brak Sesji Vinted",
                "Przejdź do zakładki 'Vinted & Auto-Oferty' i zaloguj się przed wysłaniem oferty!"
            )
            return

        pct = float(self.cfg.get("vinted_discount_percent", 10.0) or 10.0)
        proposed = calculate_vinted_offer_price(offer.price, pct)

        confirmed = CyberModal.show_confirm(
            self,
            "Złożyć Ofertę Vinted?",
            f"Czy chcesz złożyć sprzedawcy ofertę {proposed:.0f} zł (rabat -{pct:.0f}% z {offer.price:.0f} zł) dla:\n\n{offer.title[:65]}?",
            confirm_text=f"Wyślij {proposed:.0f} zł",
            cancel_text="Anuluj"
        )
        if not confirmed:
            return

        def _send():
            self._on_status_update(f"Wysyłanie oferty {proposed:.0f} zł dla {offer.title[:35]}...")
            res = self.engine.vinted_client.send_price_offer(offer.id, proposed)

            def _show_res():
                if res.get("success"):
                    self._on_status_update(f"✅ Złożono ofertę {proposed:.0f} zł dla #{offer.id}")
                    CyberModal.show_info(
                        self,
                        "Wysłano Ofertę",
                        f"Pomyślnie wysłano propozycję ceny {proposed:.0f} PLN!\nMożesz sprawdzić konwersację w aplikacji Vinted.",
                        icon_symbol="🤝"
                    )
                else:
                    err = res.get("message", "Nieznany błąd")
                    self._on_status_update(f"❌ Błąd oferty: {err}")
                    CyberModal.show_error(self, "Błąd Oferty Vinted", f"Nie udało się wysłać oferty:\n{err}")

            self.after(0, _show_res)

        threading.Thread(target=_send, daemon=True).start()

    # --- ZAKŁADKA 4: POWIADOMIENIA & WEBHOOK ---
    def _build_tab_notifs_content(self):
        container = ctk.CTkScrollableFrame(self.tab_notifs, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=10, pady=10)

        # Discord
        box_discord = ctk.CTkFrame(container, fg_color=THEME["bg_section"], corner_radius=12, border_width=1, border_color="#281c47")
        box_discord.pack(fill="x", pady=(0, 14), padx=6)

        ctk.CTkLabel(
            box_discord,
            text="💬 Integracja Discord Webhook (Powiadomienia na telefon)",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#c084fc"
        ).pack(anchor="w", padx=18, pady=(14, 4))

        ctk.CTkLabel(
            box_discord,
            text="Wklej adres URL Discord Webhook, aby otrzymywać powiadomienia o okazjach bezpośrednio na swój serwer lub telefon:",
            font=ctk.CTkFont(size=11),
            text_color=THEME["text_muted"],
            wraplength=700,
            justify="left"
        ).pack(anchor="w", padx=18, pady=(0, 8))

        row_hook = ctk.CTkFrame(box_discord, fg_color="transparent")
        row_hook.pack(fill="x", padx=18, pady=(0, 14))

        self.entry_webhook = ctk.CTkEntry(
            row_hook,
            height=34,
            corner_radius=8,
            border_color="#3c2666",
            placeholder_text="https://discord.com/api/webhooks/..."
        )
        self.entry_webhook.insert(0, self.cfg.get("discord_webhook_url", ""))
        self.entry_webhook.pack(side="left", fill="x", expand=True, padx=(0, 12))

        btn_test_hook = ctk.CTkButton(
            row_hook,
            text="🧪 Wyślij test",
            width=120,
            height=34,
            fg_color="#5865f2",
            hover_color="#4752c4",
            font=ctk.CTkFont(size=12, weight="bold"),
            corner_radius=8,
            command=self._send_test_webhook
        )
        btn_test_hook.pack(side="right")

        # Lokalne
        box_local = ctk.CTkFrame(container, fg_color=THEME["bg_section"], corner_radius=12, border_width=1, border_color="#281c47")
        box_local.pack(fill="x", pady=(0, 14), padx=6)

        ctk.CTkLabel(
            box_local,
            text="🔔 Powiadomienia na Komputerze",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=THEME["accent_amber"]
        ).pack(anchor="w", padx=18, pady=(14, 8))

        row_local = ctk.CTkFrame(box_local, fg_color="transparent")
        row_local.pack(fill="x", padx=18, pady=(0, 14))

        self.var_sound = tk.BooleanVar(value=self.cfg.get("sound_alerts", True))
        self.switch_sound = ctk.CTkSwitch(
            row_local,
            text="Dźwiękowy alert okazji",
            variable=self.var_sound,
            font=ctk.CTkFont(size=12),
            progress_color=THEME["accent_purple"]
        )
        self.switch_sound.pack(side="left", padx=(0, 24))

        self.var_notif = tk.BooleanVar(value=self.cfg.get("desktop_notifications", True))
        self.switch_notif = ctk.CTkSwitch(
            row_local,
            text="Dymki powiadomień Windows Toast",
            variable=self.var_notif,
            font=ctk.CTkFont(size=12),
            progress_color=THEME["accent_purple"]
        )
        self.switch_notif.pack(side="left", padx=(0, 24))

        self.switch_images_settings = ctk.CTkSwitch(
            row_local,
            text="🖼️ Miniatury zdjęć ofert",
            variable=self.var_show_images,
            font=ctk.CTkFont(size=12),
            progress_color=THEME["accent_mint"],
            command=self._on_toggle_images
        )
        self.switch_images_settings.pack(side="left")

        # Częstotliwość
        box_freq = ctk.CTkFrame(container, fg_color=THEME["bg_section"], corner_radius=12, border_width=1, border_color="#281c47")
        box_freq.pack(fill="x", pady=(0, 14), padx=6)

        ctk.CTkLabel(
            box_freq,
            text="⏱️ Częstotliwość Monitorowania",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=THEME["accent_cyan"]
        ).pack(anchor="w", padx=18, pady=(14, 6))

        row_freq = ctk.CTkFrame(box_freq, fg_color="transparent")
        row_freq.pack(fill="x", padx=18, pady=(0, 14))

        ctk.CTkLabel(row_freq, text="Odstęp między sprawdzeniami:", font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 10))
        self.combo_interval = ctk.CTkComboBox(
            row_freq,
            values=["15 sekund (Agresywny)", "30 sekund (Rekomendowany)", "60 sekund", "120 sekund", "300 sekund"],
            width=240,
            height=32,
            corner_radius=8,
            border_color="#3c2666",
            button_color=THEME["accent_violet"]
        )
        cur_sec = self.cfg.get("scan_interval_sec", 30)
        match_val = f"{cur_sec} sekund (Rekomendowany)" if cur_sec == 30 else (f"{cur_sec} sekund (Agresywny)" if cur_sec == 15 else f"{cur_sec} sekund")
        self.combo_interval.set(match_val)
        self.combo_interval.pack(side="left")

        # Allegro REST API
        box_api = ctk.CTkFrame(container, fg_color=THEME["bg_section"], corner_radius=12, border_width=1, border_color="#281c47")
        box_api.pack(fill="x", pady=(0, 14), padx=6)

        ctk.CTkLabel(
            box_api,
            text="🔑 Allegro REST API (Opcjonalne)",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=THEME["accent_amber"]
        ).pack(anchor="w", padx=18, pady=(14, 4))

        ctk.CTkLabel(
            box_api,
            text="Allegro Lokalnie działa bez kluczy. Jeśli posiadasz aplikację na apps.developer.allegro.pl, wpisz klucze:",
            font=ctk.CTkFont(size=11),
            text_color=THEME["text_muted"]
        ).pack(anchor="w", padx=18, pady=(0, 8))

        ctk.CTkLabel(box_api, text="Client ID:", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=18)
        self.entry_allegro_id = ctk.CTkEntry(box_api, height=32, corner_radius=8, border_color="#3c2666")
        self.entry_allegro_id.insert(0, self.cfg.get("allegro_client_id", ""))
        self.entry_allegro_id.pack(fill="x", padx=18, pady=(2, 8))

        ctk.CTkLabel(box_api, text="Client Secret:", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=18)
        self.entry_allegro_sec = ctk.CTkEntry(box_api, height=32, corner_radius=8, border_color="#3c2666", show="*")
        self.entry_allegro_sec.insert(0, self.cfg.get("allegro_client_secret", ""))
        self.entry_allegro_sec.pack(fill="x", padx=18, pady=(2, 14))

        # Google Gemini AI API
        box_gemini = ctk.CTkFrame(container, fg_color=THEME["bg_section"], corner_radius=12, border_width=1, border_color="#281c47")
        box_gemini.pack(fill="x", pady=(0, 14), padx=6)

        ctk.CTkLabel(
            box_gemini,
            text="🧠 Google Gemini Neural AI (Opcjonalne)",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#c084fc"
        ).pack(anchor="w", padx=18, pady=(14, 4))

        ctk.CTkLabel(
            box_gemini,
            text="Wbudowany silnik ekspercki analizuje opłacalność ofert i koszty napraw w 100% offline. Jeśli chcesz dodatkowo włączyć głęboką analizę neuronową Gemini 2.5 Flash, wklej darmowy klucz Google AI Studio:",
            font=ctk.CTkFont(size=11),
            text_color=THEME["text_muted"],
            wraplength=650,
            justify="left"
        ).pack(anchor="w", padx=18, pady=(0, 8))

        ctk.CTkLabel(box_gemini, text="Klucz Gemini API:", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=18)
        self.entry_gemini_key = ctk.CTkEntry(box_gemini, height=32, corner_radius=8, border_color="#3c2666", show="*")
        self.entry_gemini_key.insert(0, self.cfg.get("gemini_api_key", ""))
        self.entry_gemini_key.pack(fill="x", padx=18, pady=(2, 14))

        btn_save_notifs = ctk.CTkButton(
            container,
            text="💾 ZAPISZ USTAWIENIA POWIADOMIEŃ",
            height=44,
            fg_color=THEME["accent_violet"],
            hover_color=THEME["accent_purple_hover"],
            font=ctk.CTkFont(size=14, weight="bold"),
            corner_radius=10,
            command=lambda: self._apply_settings(notify=True)
        )
        btn_save_notifs.pack(fill="x", padx=6, pady=(4, 16))

    # --- ZAKŁADKA 5: STATYSTYKI & LOGI ---
    def _build_tab_stats_content(self):
        container = ctk.CTkFrame(self.tab_stats, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=10, pady=10)

        plat_stats_frame = ctk.CTkFrame(container, fg_color="transparent")
        plat_stats_frame.pack(fill="x", pady=(0, 10))

        self.kpi_olx = self._create_kpi_card(plat_stats_frame, "OLX OFERTY", "0", "#34d399")
        self.kpi_olx.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.kpi_vinted = self._create_kpi_card(plat_stats_frame, "VINTED OFERTY", "0", "#38bdf8")
        self.kpi_vinted.pack(side="left", fill="x", expand=True, padx=6)

        self.kpi_lokalnie = self._create_kpi_card(plat_stats_frame, "ALLEGRO LOKALNIE", "0", "#fb923c")
        self.kpi_lokalnie.pack(side="left", fill="x", expand=True, padx=6)

        self.kpi_allegro = self._create_kpi_card(plat_stats_frame, "ALLEGRO GŁÓWNE", "0", "#f97316")
        self.kpi_allegro.pack(side="left", fill="x", expand=True, padx=(6, 0))

        log_header = ctk.CTkFrame(container, fg_color="transparent")
        log_header.pack(fill="x", pady=(0, 6))

        ctk.CTkLabel(
            log_header,
            text="📜 Dziennik Zdarzeń na Żywo (Logi Silnika)",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=THEME["text_main"]
        ).pack(side="left")

        btn_clear_log = ctk.CTkButton(
            log_header,
            text="Wyczyść logi",
            width=90,
            height=24,
            fg_color="#221844",
            hover_color="#36256c",
            font=ctk.CTkFont(size=11),
            corner_radius=6,
            command=self._clear_logs
        )
        btn_clear_log.pack(side="right")

        self.txt_logs = ctk.CTkTextbox(
            container,
            fg_color="#0a0717",
            border_width=1,
            border_color="#221742",
            corner_radius=10,
            font=ctk.CTkFont(family="Consolas", size=11),
            text_color="#e2e8f0"
        )
        self.txt_logs.pack(fill="both", expand=True)

    # --- ZAKŁADKA 7: MOTYWY & USTAWIENIA ---
    def _build_tab_settings_content(self):
        for w in self.tab_settings.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass

        container = ctk.CTkScrollableFrame(self.tab_settings, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=10, pady=10)

        # 1. Karta Licencji KeyAuth & Dostępu Administratora
        box_auth = ctk.CTkFrame(container, fg_color=THEME["bg_section"], corner_radius=12, border_width=1, border_color=THEME["border_card"])
        box_auth.pack(fill="x", pady=(0, 14), padx=6)

        auth_top_row = ctk.CTkFrame(box_auth, fg_color="transparent")
        auth_top_row.pack(fill="x", padx=18, pady=(14, 4))

        ctk.CTkLabel(
            auth_top_row,
            text="🔐 Autoryzacja KeyAuth & Dostęp do Aplikacji",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#f97316"
        ).pack(side="left")

        lic_status = "Aktywna" if self.auth_engine.is_authenticated else "Wymaga Weryfikacji"
        lic_color = "#10b981" if self.auth_engine.is_authenticated else "#f43f5e"
        badge_lic_box = ctk.CTkLabel(
            auth_top_row,
            text=f" STATUS: {lic_status.upper()} ",
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color=lic_color,
            text_color="#ffffff",
            corner_radius=6,
            height=20
        )
        badge_lic_box.pack(side="right")

        ctk.CTkLabel(
            box_auth,
            text="Dostęp do programu jest weryfikowany w czasie rzeczywistym z panelem administracyjnym.",
            font=ctk.CTkFont(size=11),
            text_color=THEME["text_muted"]
        ).pack(anchor="w", padx=18, pady=(0, 10))

        # HWID & Key row
        auth_info_grid = ctk.CTkFrame(box_auth, fg_color=THEME["bg_card"], corner_radius=10, border_width=1, border_color=THEME["border_card"])
        auth_info_grid.pack(fill="x", padx=18, pady=(0, 12))

        # HWID sub-row
        hwid_row = ctk.CTkFrame(auth_info_grid, fg_color="transparent")
        hwid_row.pack(fill="x", padx=14, pady=(10, 6))

        ctk.CTkLabel(
            hwid_row,
            text="Twój Identyfikator Sprzętowy (HWID):",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=THEME["text_lavender"]
        ).pack(side="left")

        hwid_val_box = ctk.CTkFrame(hwid_row, fg_color="transparent")
        hwid_val_box.pack(side="right")

        ctk.CTkLabel(
            hwid_val_box,
            text=self.auth_engine.hwid,
            font=ctk.CTkFont(size=11, family="Consolas", weight="bold"),
            text_color=THEME["accent_cyan"]
        ).pack(side="left", padx=(0, 8))

        def _copy_hwid():
            self.clipboard_clear()
            self.clipboard_append(self.auth_engine.hwid)
            self._on_status_update("Skopiowano HWID do schowka.")

        ctk.CTkButton(
            hwid_val_box,
            text="Kopiuj HWID",
            width=85,
            height=26,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color="#334155",
            hover_color="#475569",
            command=_copy_hwid
        ).pack(side="left")

        # License Key sub-row
        key_row = ctk.CTkFrame(auth_info_grid, fg_color="transparent")
        key_row.pack(fill="x", padx=14, pady=(6, 12))

        ctk.CTkLabel(
            key_row,
            text="Zapisany Klucz Licencyjny:",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=THEME["text_lavender"]
        ).pack(side="left")

        key_val_str = self.auth_engine.license_key or "Brak aktywnego klucza"
        ctk.CTkLabel(
            key_row,
            text=key_val_str,
            font=ctk.CTkFont(size=11, family="Consolas", weight="bold"),
            text_color="#f59e0b"
        ).pack(side="left", padx=10)

        # Action buttons row
        auth_btns_row = ctk.CTkFrame(box_auth, fg_color="transparent")
        auth_btns_row.pack(fill="x", padx=18, pady=(0, 14))

        ctk.CTkButton(
            auth_btns_row,
            text="🔑 Zmień / Aktywuj Klucz",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=THEME["accent_purple"],
            hover_color=THEME["accent_purple_hover"],
            height=32,
            command=self._open_license_manager
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            auth_btns_row,
            text="🔄 Sprawdź Licencję Teraz",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#1e293b",
            hover_color="#334155",
            height=32,
            command=self._check_startup_license
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            auth_btns_row,
            text="🌐 Otwórz Panel Administratora (Web)",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#ea580c",
            hover_color="#c2410c",
            height=32,
            command=lambda: webbrowser.open(self.auth_engine.auth_server_url)
        ).pack(side="right")

        # 2. Karta wyboru motywu (Zwinięta do listy / CTkOptionMenu)
        box_themes = ctk.CTkFrame(container, fg_color=THEME["bg_section"], corner_radius=12, border_width=1, border_color=THEME["border_card"])
        box_themes.pack(fill="x", pady=(0, 14), padx=6)

        ctk.CTkLabel(
            box_themes,
            text="🎨 Motyw Wizualny Aplikacji (Lista Motywów)",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=THEME["accent_purple"]
        ).pack(anchor="w", padx=18, pady=(14, 4))

        ctk.CTkLabel(
            box_themes,
            text="Wybierz motyw z listy rozwijanej – zmiany aplikowane są natychmiast na żywo:",
            font=ctk.CTkFont(size=11),
            text_color=THEME["text_muted"]
        ).pack(anchor="w", padx=18, pady=(0, 10))

        cur_theme_name = self.cfg.get("selected_theme", "Obsydianowy Fiolet (Domyślny)")
        if cur_theme_name not in THEMES:
            cur_theme_name = list(THEMES.keys())[0]

        theme_select_row = ctk.CTkFrame(box_themes, fg_color="transparent")
        theme_select_row.pack(fill="x", padx=18, pady=(0, 14))

        theme_names = list(THEMES.keys())
        theme_var = ctk.StringVar(value=cur_theme_name)

        theme_combo = ctk.CTkOptionMenu(
            theme_select_row,
            values=theme_names,
            variable=theme_var,
            font=ctk.CTkFont(size=12, weight="bold"),
            dropdown_font=ctk.CTkFont(size=11),
            fg_color=THEME["accent_purple"],
            button_color=THEME["accent_purple_hover"],
            button_hover_color=THEME["accent_violet"],
            dropdown_fg_color=THEME["bg_card"],
            dropdown_hover_color=THEME["accent_purple_hover"],
            dropdown_text_color=THEME["text_main"],
            width=360,
            height=36,
            command=lambda val: self.apply_theme(val)
        )
        theme_combo.pack(side="left", padx=(0, 16))

        th_info = THEMES.get(cur_theme_name, {})
        swatch_frame = ctk.CTkFrame(theme_select_row, fg_color=THEME["bg_card"], corner_radius=8, border_width=1, border_color=THEME["border_card"], height=36)
        swatch_frame.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(
            swatch_frame,
            text=f"{th_info.get('icon', '🎨')} {th_info.get('desc', '')}",
            font=ctk.CTkFont(size=11),
            text_color=THEME["text_lavender"]
        ).pack(side="left", padx=12, pady=6)

        swatches_box = ctk.CTkFrame(swatch_frame, fg_color="transparent")
        swatches_box.pack(side="right", padx=10, pady=6)
        for col in th_info.get("swatches", []):
            ctk.CTkFrame(
                swatches_box,
                width=18,
                height=18,
                corner_radius=9,
                fg_color=col,
                border_width=1,
                border_color="#ffffff" if col in ("#07050f", "#080604", "#030805", "#0c0717", "#0d0b10", "#050a17") else col
            ).pack(side="left", padx=3)

        # 2. Karta: Silnik Wydajności & Płynność
        box_perf = ctk.CTkFrame(container, fg_color=THEME["bg_section"], corner_radius=12, border_width=1, border_color=THEME["border_card"])
        box_perf.pack(fill="x", pady=(0, 14), padx=6)

        ctk.CTkLabel(
            box_perf,
            text="⚡ Zarządzanie Wydajnością i Pamięcią RAM",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=THEME["accent_mint"]
        ).pack(anchor="w", padx=18, pady=(14, 4))

        ctk.CTkLabel(
            box_perf,
            text="Skonfiguruj optymalizacje sprzętowe, aby program działał w 100% płynnie nawet przy setkach znalezionych ofert:",
            font=ctk.CTkFont(size=11),
            text_color=THEME["text_muted"]
        ).pack(anchor="w", padx=18, pady=(0, 10))

        # Row: DOM cards limit
        r_dom = ctk.CTkFrame(box_perf, fg_color="transparent")
        r_dom.pack(fill="x", padx=18, pady=6)

        ctk.CTkLabel(
            r_dom,
            text="Maksymalna liczba kart w strumieniu (DOM Capping):",
            font=ctk.CTkFont(size=12)
        ).pack(side="left")

        self.combo_dom_limit = ctk.CTkComboBox(
            r_dom,
            values=["30 ofert (Maksymalna wydajność)", "50 ofert (Zbalansowane - Rekomendowane)", "80 ofert (Większy bufor)", "120 ofert"],
            width=260,
            height=32,
            corner_radius=8,
            border_color="#3c2666",
            button_color=THEME["accent_violet"]
        )
        cur_dom = int(self.cfg.get("max_feed_cards", 50))
        match_dom = f"{cur_dom} ofert (Zbalansowane - Rekomendowane)" if cur_dom == 50 else (f"{cur_dom} ofert (Maksymalna wydajność)" if cur_dom == 30 else f"{cur_dom} ofert")
        self.combo_dom_limit.set(match_dom)
        self.combo_dom_limit.pack(side="right")

        def _on_dom_change(choice):
            m = re.search(r"\d+", choice)
            if m:
                val = int(m.group(0))
                self.cfg["max_feed_cards"] = val
                save_config(self.cfg)
                while len(self.cards) > val:
                    old_c = self.cards.pop()
                    try:
                        old_c.destroy()
                    except Exception:
                        pass
                self._on_status_update(f"Zmieniono limit kart w DOM na {val}.")

        self.combo_dom_limit.configure(command=_on_dom_change)

        # Row: RAM Cache info & Clear button
        r_cache = ctk.CTkFrame(box_perf, fg_color="transparent")
        r_cache.pack(fill="x", padx=18, pady=6)

        cache_count = len(ImageLoader._cache)
        self.lbl_cache_info = ctk.CTkLabel(
            r_cache,
            text=f"Bufor pamięci podręcznej grafik: {cache_count} miniatur w pamięci RAM",
            font=ctk.CTkFont(size=12)
        )
        self.lbl_cache_info.pack(side="left")

        def _do_clear_cache():
            cleared = ImageLoader.clear_cache()
            self.lbl_cache_info.configure(text="Bufor pamięci podręcznej grafik: 0 miniatur w pamięci RAM")
            CyberModal.show_info(self, "Zwolniono Pamięć", f"Pomyślnie wyczyszczono bufor graficzny ({cleared} miniatur).\nOdciążono pamięć podręczną RAM komputera!", icon_symbol="🧹")
            self._on_status_update(f"Zwolniono bufor pamięci ({cleared} grafik).")

        btn_purge_cache = ctk.CTkButton(
            r_cache,
            text="🧹 Zwolnij bufor RAM",
            width=160,
            height=32,
            fg_color="#27194a",
            hover_color="#3e2777",
            font=ctk.CTkFont(size=11, weight="bold"),
            corner_radius=8,
            command=_do_clear_cache
        )
        btn_purge_cache.pack(side="right")

        # Row: Prefetch toggle
        r_pref = ctk.CTkFrame(box_perf, fg_color="transparent")
        r_pref.pack(fill="x", padx=18, pady=(6, 14))

        self.var_prefetch = tk.BooleanVar(value=bool(self.cfg.get("enable_image_prefetch", True)))
        def _on_prefetch_toggle():
            self.cfg["enable_image_prefetch"] = self.var_prefetch.get()
            save_config(self.cfg)
            st = "włączone" if self.var_prefetch.get() else "wyłączone"
            self._on_status_update(f"Asynchroniczne pobieranie galerii: {st}.")

        switch_pref = ctk.CTkSwitch(
            r_pref,
            text="🖼️ Asynchroniczne pobieranie dodatkowych zdjęć galerii ofert w tle",
            variable=self.var_prefetch,
            font=ctk.CTkFont(size=12),
            progress_color=THEME["accent_mint"],
            command=_on_prefetch_toggle
        )
        switch_pref.pack(side="left")

        # 3. Karta: Szybka Diagnostyka & Test Sprawności Systemu
        box_diag = ctk.CTkFrame(container, fg_color=THEME["bg_section"], corner_radius=12, border_width=1, border_color=THEME["border_card"])
        box_diag.pack(fill="x", pady=(0, 14), padx=6)

        ctk.CTkLabel(
            box_diag,
            text="🧪 Autodiagnostyka & Test Sprawności Wszystkich Opcji",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=THEME["accent_amber"]
        ).pack(anchor="w", padx=18, pady=(14, 4))

        ctk.CTkLabel(
            box_diag,
            text="Uruchom szybki test sprawności, aby sprawdzić łączność ze wszystkimi portalami (OLX, Vinted, Allegro) oraz zweryfikować zerowe opóźnienia silnika:",
            font=ctk.CTkFont(size=11),
            text_color=THEME["text_muted"],
            wraplength=680,
            justify="left"
        ).pack(anchor="w", padx=18, pady=(0, 10))

        diag_row = ctk.CTkFrame(box_diag, fg_color="transparent")
        diag_row.pack(fill="x", padx=18, pady=(0, 14))

        self.lbl_diag_result = ctk.CTkLabel(
            diag_row,
            text="Gotowy do uruchomienia testu diagnostycznego.",
            font=ctk.CTkFont(size=11),
            text_color="#c4b5fd"
        )
        self.lbl_diag_result.pack(side="left")

        def _run_diag_async():
            self.lbl_diag_result.configure(text="⏳ Testowanie modułów w toku...", text_color=THEME["accent_amber"])
            def _worker():
                t0 = time.time()
                olx_ok = False
                vinted_ok = False
                lokalnie_ok = False
                try:
                    s = ImageLoader._get_session()
                    r1 = s.get("https://www.olx.pl/api/v1/offers/?offset=0&limit=1", timeout=5)
                    olx_ok = (r1.status_code == 200)
                except Exception:
                    pass

                try:
                    s = ImageLoader._get_session()
                    r2 = s.get("https://www.vinted.pl", timeout=5)
                    vinted_ok = (r2.status_code == 200)
                except Exception:
                    pass

                try:
                    s = ImageLoader._get_session()
                    r3 = s.get("https://allegrolokalnie.pl", timeout=5)
                    lokalnie_ok = (r3.status_code == 200)
                except Exception:
                    pass

                dt = int((time.time() - t0) * 1000)
                def _update_ui():
                    s1 = "🟢 OLX" if olx_ok else "🔴 OLX"
                    s2 = "🟢 Vinted" if vinted_ok else "🔴 Vinted"
                    s3 = "🟢 Allegro Lok." if lokalnie_ok else "🔴 Allegro Lok."
                    res_txt = f"{s1} | {s2} | {s3} | 🟢 AI Parser | 🟢 Akumulator GDI (Łączny czas testu: {dt} ms)"
                    self.lbl_diag_result.configure(text=res_txt, text_color=THEME["accent_mint"] if (olx_ok and vinted_ok) else THEME["accent_amber"])
                    self._on_status_update(f"Zakończono autodiagnostykę w {dt} ms.")
                self.after(0, _update_ui)

            threading.Thread(target=_worker, daemon=True).start()

        btn_run_diag = ctk.CTkButton(
            diag_row,
            text="⚡ Przetestuj Wszystko Teraz",
            width=210,
            height=34,
            fg_color=THEME["accent_violet"],
            hover_color=THEME["accent_purple_hover"],
            font=ctk.CTkFont(size=12, weight="bold"),
            corner_radius=8,
            command=_run_diag_async
        )
        btn_run_diag.pack(side="right")

    def apply_theme(self, theme_name: str):
        if theme_name not in THEMES:
            return
        theme_data = THEMES[theme_name]
        THEME.update(theme_data)
        self.cfg["selected_theme"] = theme_name
        save_config(self.cfg)

        # 1. Okno bazowe
        self.configure(fg_color=THEME["bg_window"])

        # 2. Nagłówek i status bar
        if hasattr(self, "header_frame"):
            self.header_frame.configure(fg_color=THEME["bg_header"])
        if hasattr(self, "app_title"):
            self.app_title.configure(text_color=THEME["accent_purple"])
        if hasattr(self, "btn_toggle") and not self.engine.is_running:
            self.btn_toggle.configure(fg_color=THEME["accent_purple"], hover_color=THEME["accent_purple_hover"])
        if hasattr(self, "bottom_frame"):
            self.bottom_frame.configure(fg_color=THEME["bg_header"])

        # 3. Kontenery główne
        if hasattr(self, "tab_container"):
            self.tab_container.configure(fg_color=THEME["bg_tabview"], border_color=THEME["border_card"])
        if hasattr(self, "sidebar_frame"):
            self.sidebar_frame.configure(fg_color=THEME["bg_window"], border_color=THEME["border_card"])

        # 4. Przewijany feed ofert i ulubionych
        if hasattr(self, "scroll_feed"):
            self.scroll_feed.configure(fg_color=THEME["bg_feed_scroll"], border_color=THEME["border_card"])
        if hasattr(self, "scroll_favs"):
            self.scroll_favs.configure(fg_color=THEME["bg_feed_scroll"], border_color=THEME["border_card"])

        # 5. Przyciski paska bocznego
        self._refresh_sidebar_buttons()

        # 6. Przeładowanie kart ofert i ulubionych
        self._refresh_all_deal_cards()
        self._render_favorites_list()

        # 7. Odświeżenie widoku ustawień
        self._build_tab_settings_content()

        self._on_status_update(f"Zastosowano nowy motyw: '{theme_name}'.")

    def _create_kpi_card(self, parent, label_text: str, val_text: str, val_color: str):
        card = ctk.CTkFrame(parent, fg_color=THEME["bg_section"], corner_radius=12, border_width=1, border_color="#281c47", height=66)
        card.pack_propagate(False)

        lbl = ctk.CTkLabel(
            card,
            text=label_text,
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=THEME["text_muted"]
        )
        lbl.pack(anchor="w", padx=14, pady=(8, 0))

        val = ctk.CTkLabel(
            card,
            text=val_text,
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=val_color
        )
        val.pack(anchor="w", padx=14, pady=(0, 6))
        card.value_label = val
        return card

    def _build_bottom_status_bar(self):
        self.bottom_frame = ctk.CTkFrame(self, fg_color=THEME["bg_header"], corner_radius=0, height=32)
        self.bottom_frame.pack(fill="x", side="bottom")
        self.bottom_frame.pack_propagate(False)

        self.lbl_status = ctk.CTkLabel(
            self.bottom_frame,
            text="🟢 GRDZ_SNIPE gotowy do pracy.",
            font=ctk.CTkFont(size=11),
            text_color=THEME["text_muted"]
        )
        self.lbl_status.pack(side="left", padx=18)

        engine_info = ctk.CTkLabel(
            self.bottom_frame,
            text="Performance Edition v2.6 PRO | Ulubione Cele • Motywy Wizualne • Przesyłka OLX • Zero Zacięć",
            font=ctk.CTkFont(size=11),
            text_color=THEME["text_dim"]
        )
        engine_info.pack(side="right", padx=18)

    def _apply_settings(self, notify: bool = False):
        try:
            min_p = float(self.entry_min_price.get().strip()) if self.entry_min_price.get().strip() else 0.0
        except ValueError:
            min_p = 0.0

        try:
            max_p = float(self.entry_max_price.get().strip()) if self.entry_max_price.get().strip() else 0.0
        except ValueError:
            max_p = 0.0

        try:
            exp_p = float(self.entry_market_price.get().strip()) if self.entry_market_price.get().strip() else 0.0
        except ValueError:
            exp_p = 0.0

        raw_int = self.combo_interval.get().split()[0]
        try:
            interval = int(raw_int)
        except ValueError:
            interval = 30

        selected_cat = self.combo_category.get()
        cat_id = CATEGORIES_MAP.get(selected_cat, 0)

        dist_str = self.combo_dist.get()
        import re
        m_dist = re.search(r"\d+", dist_str)
        dist_km = int(m_dist.group(0)) if m_dist else 0

        raw_exc = self.entry_exclude.get().split(",")
        exclude_list = [w.strip() for w in raw_exc if w.strip()]

        self.cfg["search_query"] = self.entry_query.get().strip()
        self.cfg["exact_phrase_match"] = self.var_exact.get()
        self.cfg["selected_category"] = selected_cat
        self.cfg["category_id"] = cat_id
        self.cfg["city_name"] = self.entry_city.get().strip()
        self.cfg["distance_km"] = dist_km
        self.cfg["olx_delivery_only"] = self.var_olx_deliv.get()
        self.cfg["min_price_filter"] = min_p
        self.cfg["max_price_filter"] = max_p
        self.cfg["expected_market_price"] = exp_p
        self.cfg["deals_only_mode"] = self.var_deals_only.get()
        self.cfg["exclude_keywords"] = exclude_list

        self.cfg["track_olx"] = self.var_olx.get()
        self.cfg["track_vinted"] = self.var_vinted.get()
        self.cfg["track_allegro_lokalnie"] = self.var_allegro_lokalnie.get()
        self.cfg["track_allegro"] = self.var_allegro.get()

        self.cfg["scan_interval_sec"] = interval
        self.cfg["discord_webhook_url"] = self.entry_webhook.get().strip()
        self.cfg["sound_alerts"] = self.var_sound.get()
        self.cfg["desktop_notifications"] = self.var_notif.get()

        self.cfg["allegro_client_id"] = self.entry_allegro_id.get().strip()
        self.cfg["allegro_client_secret"] = self.entry_allegro_sec.get().strip()

        if hasattr(self, "entry_vinted_cookie"):
            self.cfg["vinted_session_cookie"] = self.entry_vinted_cookie.get().strip()
        if hasattr(self, "var_vinted_auto"):
            self.cfg["vinted_auto_offer_enabled"] = self.var_vinted_auto.get()
        if hasattr(self, "slider_vinted_pct"):
            self.cfg["vinted_discount_percent"] = round(float(self.slider_vinted_pct.get()), 1)
        if hasattr(self, "var_show_images"):
            self.cfg["show_item_images"] = self.var_show_images.get()
        if hasattr(self, "entry_gemini_key"):
            self.cfg["gemini_api_key"] = self.entry_gemini_key.get().strip()

        save_config(self.cfg)
        self.engine.update_config(self.cfg)

        self.lbl_target_summary.configure(text=self._get_summary_text())
        self._on_status_update(f"Zaktualizowano filtry dla '{self.cfg['search_query']}'.")
        if notify:
            CyberModal.show_info(
                self, 
                "Zapisano Ustawienia", 
                "Ustawienia i filtry wyszukiwania zostały pomyślnie zaktualizowane!", 
                icon_symbol="💾"
            )

    def _toggle_monitor(self):
        if not self.auth_engine.is_authenticated:
            CyberModal.alert(
                self,
                "Wymagana Licencja KeyAuth",
                "Przed rozpoczęciem monitorowania musisz aktywować poprawny klucz licencyjny.",
                accent_color="#ef4444"
            )
            self._open_license_manager()
            return

        self._apply_settings()
        if not self.engine.is_running:
            self.engine.start()
            self.btn_toggle.configure(
                text="⏹ ZATRZYMAJ SNIPER",
                fg_color=THEME["accent_red"],
                hover_color="#e11d48"
            )
            self.kpi_status.value_label.configure(
                text=f"🟢 AKTYWNY ({self.cfg['scan_interval_sec']}s)",
                text_color=THEME["accent_mint"]
            )
            p_list = []
            if self.cfg.get("track_olx"): p_list.append("OLX")
            if self.cfg.get("track_vinted"): p_list.append("Vinted")
            if self.cfg.get("track_allegro_lokalnie"): p_list.append("Allegro Lok.")
            if self.cfg.get("track_allegro"): p_list.append("Allegro")
            act_str = f"🚀 Skanuje: {', '.join(p_list)}" if p_list else "🚀 Skanuje"
            self.auth_engine.set_action(act_str)
        else:
            self.engine.stop()
            self.btn_toggle.configure(
                text="▶ ROZPOCZNIJ SNIPOWANIE",
                fg_color=THEME["accent_purple"],
                hover_color=THEME["accent_purple_hover"]
            )
            self.kpi_status.value_label.configure(
                text="⏹ ZATRZYMANY",
                text_color="#94a3b8"
            )
            self.auth_engine.set_action("Bezczynny")

    def _trigger_instant_scan(self):
        self._apply_settings()
        self._on_status_update("Uruchamianie natychmiastowego skanowania...")
        threading.Thread(target=self.engine.scan_once, daemon=True).start()

    def _clear_deals(self):
        if self.cards:
            confirmed = CyberModal.show_confirm(
                self,
                "Wyczyść Feed",
                "Czy na pewno chcesz wyczyścić wszystkie pobrane okazje z widoku?",
                confirm_text="Tak, wyczyść",
                cancel_text="Anuluj"
            )
            if not confirmed:
                return

        for card in self.cards:
            try:
                card.destroy()
            except Exception:
                pass
        self.cards.clear()
        self.offers_list.clear()
        self._incoming_offer_queue.clear()
        self.empty_label = ctk.CTkLabel(
            self.scroll_feed,
            text="Feed wyczyszczony. Oczekiwanie na nowe ogłoszenia...",
            font=ctk.CTkFont(size=14),
            text_color=THEME["text_muted"]
        )
        self.empty_label.pack(pady=70)

    def _clear_logs(self):
        if self.txt_logs.get("1.0", "end").strip():
            confirmed = CyberModal.show_confirm(
                self,
                "Wyczyść Logi",
                "Czy na pewno chcesz wyczyścić zawartość konsoli zdarzeń?",
                confirm_text="Tak, wyczyść",
                cancel_text="Anuluj"
            )
            if not confirmed:
                return
        self.txt_logs.delete("1.0", "end")

    def _send_test_webhook(self):
        webhook = self.entry_webhook.get().strip()
        if not webhook:
            CyberModal.show_warning(self, "Brak Webhooka", "Wprowadź poprawny adres Discord Webhook w formularzu.")
            return

        test_offer = Offer(
            id="test_offer_1",
            platform="GRDZ_SNIPE",
            title=f"Testowe powiadomienie dla: {self.cfg.get('search_query', 'Produkt')}",
            price=1299.0,
            url="https://google.com",
            image_url="https://img.icons8.com/fluency/96/shopping-bag.png",
            created_at_str="Teraz",
            market_avg=1800.0,
            discount_pct=28.0,
            is_deal=True,
            deal_reason="Wiadomość testowa z aplikacji GRDZ_SNIPE Cyber Edition!",
            has_delivery=True,
            location_name=self.cfg.get('city_name', 'Warszawa') or 'Polska'
        )
        threading.Thread(target=Notifier.send_discord_webhook, args=(webhook, test_offer), daemon=True).start()
        CyberModal.show_info(self, "Wysłano na Discord", "Wysłano testowe powiadomienie na Twój kanał Discord!", icon_symbol="💬")

    def _on_new_offer(self, offer: Offer):
        """Asynchroniczne dodanie do kolejki renderowania z zachowaniem płynności 60 FPS."""
        self._incoming_offer_queue.append(offer)
        if not self._is_draining_queue:
            self._is_draining_queue = True
            self.after(10, self._drain_offer_queue)

    def _drain_offer_queue(self):
        """Renderowanie mikro-paczkami po 2 karty na klatkę, bez blokowania wątku głównego."""
        BATCH_SIZE = 2
        count = 0
        while self._incoming_offer_queue and count < BATCH_SIZE:
            offer = self._incoming_offer_queue.popleft()
            self._render_single_card(offer)
            count += 1

        if self._incoming_offer_queue:
            self.after(16, self._drain_offer_queue)
        else:
            self._is_draining_queue = False

    def _render_single_card(self, offer: Offer):
        if hasattr(self, "empty_label") and self.empty_label.winfo_exists():
            self.empty_label.destroy()

        card = DealCard(
            self.scroll_feed,
            offer=offer,
            on_discord_send=self._send_to_discord_manual,
            on_vinted_offer=self._manual_vinted_offer,
            show_image=self.var_show_images.get(),
            app_cfg=self.cfg
        )
        card.pack(fill="x", padx=4, pady=6, before=self.cards[0] if self.cards else None)
        self.cards.insert(0, card)
        self.offers_list.insert(0, offer)

        # Dynamiczne ograniczenie liczby aktywnych kart w DOM wg preferencji użytkownika,
        # co gwarantuje 60 FPS nawet po 24 godzinach nieprzerwanego działania.
        max_dom = int(self.cfg.get("max_feed_cards", 50))
        if len(self.cards) > max_dom:
            oldest_card = self.cards.pop()
            try:
                oldest_card.destroy()
            except Exception:
                pass

        deliv_str = " [📦 Przesyłka]" if offer.has_delivery else ""
        loc_str = f" [{offer.location_name}]" if offer.location_name else ""
        self._append_log(f"🔥 [{offer.platform}] {offer.title[:50]} za {offer.price:.2f} PLN{loc_str}{deliv_str}")

    def _render_offer_card(self, offer: Offer):
        self._on_new_offer(offer)

    def _on_toggle_images(self):
        enabled = self.var_show_images.get()
        self.cfg["show_item_images"] = enabled
        save_config(self.cfg)
        self._refresh_all_deal_cards()
        state_str = "włączone" if enabled else "wyłączone"
        self._on_status_update(f"Wyświetlanie zdjęć ofert: {state_str}.")

    def _refresh_all_deal_cards(self):
        for card in self.cards:
            try:
                card.destroy()
            except Exception:
                pass
        self.cards.clear()
        self._incoming_offer_queue.clear()
        saved_offers = list(self.offers_list)
        self.offers_list.clear()
        for off in reversed(saved_offers):
            self._on_new_offer(off)

    def _send_to_discord_manual(self, offer: Offer):
        webhook = self.entry_webhook.get().strip()
        if not webhook:
            CyberModal.show_warning(self, "Brak Webhooka", "Wprowadź adres URL Discord Webhook w zakładce 'Powiadomienia & Webhook'.")
            return
        threading.Thread(target=Notifier.send_discord_webhook, args=(webhook, offer), daemon=True).start()
        CyberModal.show_info(self, "Wysłano na Discord", f"Oferta '{offer.title[:60]}' została pomyślnie przesłana na Discord!", icon_symbol="💬")

    def _append_log(self, text: str):
        t_now = time.strftime("%H:%M:%S")
        line = f"[{t_now}] {text}\n"
        if hasattr(self, "txt_logs") and self.txt_logs.winfo_exists():
            self.txt_logs.insert("end", line)
            try:
                line_count = int(float(self.txt_logs.index("end-1c")))
                if line_count > 300:
                    self.txt_logs.delete("1.0", f"{line_count - 220}.0")
            except Exception:
                pass
            self.txt_logs.see("end")

    def _on_status_update(self, msg: str):
        def update():
            self.lbl_status.configure(text=f"🟢 {msg}")
            self._append_log(msg)
        self.after(0, update)

    def _on_stats_update(self, stats: Dict[str, Any]):
        def update():
            self.kpi_deals.value_label.configure(text=str(stats.get("deals_found", 0)))
            self.kpi_scanned.value_label.configure(text=str(stats.get("total_scanned", 0)))
            self.kpi_time.value_label.configure(text=str(stats.get("last_scan_time", "-")))

            self.kpi_olx.value_label.configure(text=str(stats.get("olx_count", 0)))
            self.kpi_vinted.value_label.configure(text=str(stats.get("vinted_count", 0)))
            self.kpi_lokalnie.value_label.configure(text=str(stats.get("lokalnie_count", 0)))
            self.kpi_allegro.value_label.configure(text=str(stats.get("allegro_count", 0)))
        self.after(0, update)

    def _open_license_manager(self):
        CyberLicenseModal(self, self.auth_engine, on_success=self._on_license_modal_success, allow_cancel=True)

    def _on_license_modal_success(self):
        self._on_license_active(self.auth_engine.license_key, "Licencja pomyślnie aktywowana.")
        self._build_tab_settings_content()

    def _check_startup_license(self):
        key = self.cfg.get("license_key", "").strip()
        if not key:
            self._prompt_license_modal(error_msg="Brak zapisanego klucza licencyjnego.")
            return

        def _worker():
            res = self.auth_engine.verify_license(key)
            if res.success:
                self.after(0, lambda: self._on_license_active(key, res.message))
            else:
                self.after(0, lambda: self._prompt_license_modal(error_msg=res.message))

        threading.Thread(target=_worker, daemon=True).start()

    def _prompt_license_modal(self, error_msg: Optional[str] = None):
        if hasattr(self, "badge_license"):
            self.badge_license.configure(
                text="✕ BRAK LICENCJI",
                fg_color="#7f1d1d",
                hover_color="#991b1b",
                text_color="#fca5a5"
            )
        CyberLicenseModal(self, self.auth_engine, on_success=self._on_license_modal_success, allow_cancel=False)

    def _on_license_active(self, key: str, msg: str):
        if hasattr(self, "badge_license"):
            self.badge_license.configure(
                text="✓ LICENCJA AKTYWNA",
                fg_color="#065f46",
                hover_color="#047857",
                text_color="#34d399"
            )
        self._on_status_update(f"KeyAuth: {msg}")

    def _on_license_revoked(self, reason: str):
        def _ui():
            if self.engine.is_running:
                self.engine.stop()
                self.btn_toggle.configure(
                    text="▶ ROZPOCZNIJ SNIPOWANIE",
                    fg_color=THEME["accent_purple"],
                    hover_color=THEME["accent_purple_hover"]
                )
                self.kpi_status.value_label.configure(text="⏹ ZABLOKOWANY", text_color="#ef4444")

            if hasattr(self, "badge_license"):
                self.badge_license.configure(
                    text="✕ BLOKADA DOSTĘPU",
                    fg_color="#7f1d1d",
                    hover_color="#991b1b",
                    text_color="#fca5a5"
                )

            CyberModal.alert(
                self,
                "Blokada Dostępu KeyAuth",
                f"Twój dostęp do programu został wstrzymany lub zablokowany przez administratora:\n\n{reason}\n\nProgram zostanie natychmiast zamknięty.",
                accent_color="#ef4444"
            )
            try:
                self.destroy()
            except Exception:
                pass
            sys.exit(0)
        self.after(0, _ui)

    def _on_admin_broadcast(self, broadcast_text: str):
        def _ui():
            CyberModal.alert(
                self,
                "📢 Komunikat Administratora",
                broadcast_text,
                accent_color="#f97316"
            )
        self.after(0, _ui)

    def _on_close(self):
        if hasattr(self, "auth_engine"):
            self.auth_engine.stop_heartbeat()
        self.engine.shutdown()
        self.destroy()


class CyberAuthLauncher(ctk.CTk):
    """
    Cybernetyczne okno startowe logowania i weryfikacji KeyAuth.
    Wymusza podanie Loginu, Hasła i Klucza Licencji przed uruchomieniem głównego okna snajpera.
    """
    def __init__(self):
        super().__init__()
        self.title("GRDZ-SNIPE // Bramka Dostępowa i Logowanie")
        self.geometry("520x640")
        self.resizable(False, False)
        self.configure(fg_color="#0a0614")

        # Ikona
        try:
            ico_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
            if os.path.exists(ico_path):
                self.iconbitmap(ico_path)
        except Exception:
            pass

        self.cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        self.cfg = {}
        if os.path.exists(self.cfg_path):
            try:
                with open(self.cfg_path, "r", encoding="utf-8") as f:
                    self.cfg = json.load(f)
            except Exception:
                pass

        self.auth_engine = get_auth_engine(self.cfg)
        self.authenticated = False
        self.user_info = {}

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Wyśrodkowanie okna na ekranie
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (w // 2)
        y = (self.winfo_screenheight() // 2) - (h // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _on_close(self):
        self.authenticated = False
        self.destroy()

    def _build_ui(self):
        card = ctk.CTkFrame(self, fg_color="#0e0a1f", corner_radius=16, border_width=1, border_color="#3c2666")
        card.pack(fill="both", expand=True, padx=14, pady=14)

        # Header
        top_bar = ctk.CTkFrame(card, fg_color="transparent")
        top_bar.pack(fill="x", padx=22, pady=(20, 10))

        ctk.CTkLabel(
            top_bar,
            text="⚡ GRDZ-SNIPE V2.6 PRO",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#f97316"
        ).pack(anchor="w")

        ctk.CTkLabel(
            top_bar,
            text="Autoryzacja dostępu: zaloguj się danymi ze strony oraz podaj klucz licencji.",
            font=ctk.CTkFont(size=11),
            text_color="#a78bfa"
        ).pack(anchor="w", pady=(2, 0))

        # HWID Info Box
        hwid_box = ctk.CTkFrame(card, fg_color="#150f2b", corner_radius=10, border_width=1, border_color="#2c1e4a")
        hwid_box.pack(fill="x", padx=22, pady=(0, 14))

        ctk.CTkLabel(
            hwid_box,
            text="TWÓJ IDENTYFIKATOR SPRZĘTOWY (HWID):",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="#71717a"
        ).pack(anchor="w", padx=12, pady=(8, 2))

        hwid_row = ctk.CTkFrame(hwid_box, fg_color="transparent")
        hwid_row.pack(fill="x", padx=12, pady=(0, 8))

        ctk.CTkLabel(
            hwid_row,
            text=self.auth_engine.hwid,
            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
            text_color="#38bdf8"
        ).pack(side="left")

        def _copy_hwid():
            self.clipboard_clear()
            self.clipboard_append(self.auth_engine.hwid)
            btn_copy.configure(text="✓ Skopiowano!")
            self.after(2000, lambda: btn_copy.configure(text="Kopiuj"))

        btn_copy = ctk.CTkButton(
            hwid_row,
            text="Kopiuj",
            width=65,
            height=24,
            font=ctk.CTkFont(size=11),
            fg_color="#1e1b4b",
            hover_color="#312e81",
            command=_copy_hwid
        )
        btn_copy.pack(side="right")

        # Form Container
        form = ctk.CTkFrame(card, fg_color="transparent")
        form.pack(fill="x", padx=22)

        # Login / Email
        ctk.CTkLabel(
            form,
            text="LOGIN LUB ADRES E-MAIL ZE STRONY",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#e2e8f0"
        ).pack(anchor="w", pady=(0, 4))

        saved_login = self.cfg.get("user_login") or self.cfg.get("login_identity", "")
        self.ent_identity = ctk.CTkEntry(
            form,
            placeholder_text="np. kgradzki lub twoj@email.com",
            height=38,
            font=ctk.CTkFont(size=13),
            fg_color="#150f2b",
            border_color="#3c2666"
        )
        self.ent_identity.pack(fill="x", pady=(0, 10))
        if saved_login:
            self.ent_identity.insert(0, saved_login)

        # Password
        ctk.CTkLabel(
            form,
            text="HASŁO DO KONTA NA STRONIE",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#e2e8f0"
        ).pack(anchor="w", pady=(0, 4))

        self.ent_password = ctk.CTkEntry(
            form,
            placeholder_text="Wpisz hasło do konta...",
            show="*",
            height=38,
            font=ctk.CTkFont(size=13),
            fg_color="#150f2b",
            border_color="#3c2666"
        )
        self.ent_password.pack(fill="x", pady=(0, 4))

        def _toggle_pwd():
            self.ent_password.configure(show="" if cb_show.get() else "*")

        cb_show = ctk.CTkCheckBox(
            form,
            text="Pokaż hasło",
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8",
            checkbox_width=16,
            checkbox_height=16,
            command=_toggle_pwd
        )
        cb_show.pack(anchor="w", pady=(0, 10))

        # License Key
        ctk.CTkLabel(
            form,
            text="KLUCZ AUTORYZACJI (KEYAUTH LICENCJA)",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#e2e8f0"
        ).pack(anchor="w", pady=(0, 4))

        saved_key = self.cfg.get("license_key", "")
        self.ent_key = ctk.CTkEntry(
            form,
            placeholder_text="np. SNIPE-TRIAL-XXXX lub SNIPE-WEEK-XXXX",
            height=38,
            font=ctk.CTkFont(family="Consolas", size=13, weight="bold"),
            fg_color="#150f2b",
            border_color="#3c2666",
            text_color="#f97316"
        )
        self.ent_key.pack(fill="x", pady=(0, 8))
        if saved_key:
            self.ent_key.insert(0, saved_key)

        # Status / Error Label
        self.lbl_status = ctk.CTkLabel(
            card,
            text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#f87171",
            wraplength=460,
            justify="center"
        )
        self.lbl_status.pack(fill="x", padx=22, pady=(4, 8))

        # Buttons
        self.btn_submit = ctk.CTkButton(
            card,
            text="⚡ ZALOGUJ I URUCHOM PROGRAM →",
            height=44,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#f97316",
            hover_color="#ea580c",
            command=self._submit
        )
        self.btn_submit.pack(fill="x", padx=22, pady=(0, 8))

        portal_url = self.auth_engine.auth_server_url
        ctk.CTkButton(
            card,
            text="🌐 Otwórz Portal / Zdobądź Klucz (grdzsnipe.com)",
            height=34,
            font=ctk.CTkFont(size=12),
            fg_color="transparent",
            border_width=1,
            border_color="#3c2666",
            hover_color="#1e1b4b",
            text_color="#a78bfa",
            command=lambda: webbrowser.open(portal_url)
        ).pack(fill="x", padx=22)

    def _submit(self):
        ident = self.ent_identity.get().strip()
        pwd = self.ent_password.get().strip()
        key = self.ent_key.get().strip()

        if not ident:
            self.lbl_status.configure(text="Podaj login lub adres e-mail do konta.", text_color="#f87171")
            self.ent_identity.focus()
            return
        if not pwd:
            self.lbl_status.configure(text="Podaj hasło do swojego konta.", text_color="#f87171")
            self.ent_password.focus()
            return
        if not key:
            self.lbl_status.configure(text="Wprowadź klucz licencyjny.", text_color="#f87171")
            self.ent_key.focus()
            return

        self.btn_submit.configure(state="disabled", text="⏳ Weryfikacja tożsamości i licencji...")
        self.lbl_status.configure(text="Łączenie z serwerem autoryzacji...", text_color="#38bdf8")

        def _worker():
            res = self.auth_engine.authenticate_user(ident, pwd, key)
            self.after(0, lambda: self._on_result(res, ident, key))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_result(self, res: Any, ident: str, key: str):
        if res.success:
            self.lbl_status.configure(text="✓ Autoryzacja udana! Uruchamianie snajpera...", text_color="#34d399")
            # Zapisujemy klucz i login w configu
            self.cfg["user_login"] = ident
            self.cfg["license_key"] = key
            try:
                with open(self.cfg_path, "w", encoding="utf-8") as f:
                    json.dump(self.cfg, f, indent=4, ensure_ascii=False)
            except Exception:
                pass

            self.authenticated = True
            self.after(300, self.destroy)
        else:
            self.btn_submit.configure(state="normal", text="⚡ ZALOGUJ I URUCHOM PROGRAM →")
            status_text = res.message or "Błąd autoryzacji."
            if "BAN" in status_text.upper() or res.status == "banned":
                status_text = f"⛔ ODMOWA DOSTĘPU (BAN):\n{status_text}"
            self.lbl_status.configure(text=status_text, text_color="#ef4444")


def run_app():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    launcher = CyberAuthLauncher()
    launcher.mainloop()

    if launcher.authenticated:
        app = DealTrackerApp()
        app.mainloop()


if __name__ == "__main__":
    run_app()
