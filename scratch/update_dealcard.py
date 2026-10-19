# c:/Users/Kacper/Desktop/skrypt/scratch/update_dealcard.py
import re

new_dealcard_code = '''class DealCard(ctk.CTkFrame):
    def __init__(self, master, offer: Offer, on_discord_send=None, on_vinted_offer=None, show_image: bool = True, app_cfg: Optional[Dict[str, Any]] = None, **kwargs):
        border_col = THEME["border_deal"] if offer.is_deal else THEME["border_card"]
        bg_col = THEME["bg_card_deal"] if offer.is_deal else THEME["bg_card"]
        
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
        main_box = ctk.CTkFrame(self, fg_color="transparent")
        main_box.pack(fill="x", padx=14, pady=12)

        # 1. Kolumna ze zdjęciami z lewej strony (Główne zdjęcie + Miniatury reszty zdjęć)
        if self.show_image:
            photo_col = ctk.CTkFrame(main_box, fg_color="transparent", width=108)
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
                text="🖼️\\nŁadowanie...",
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
                self.lbl_thumb.configure(text="📷\\nBrak zdjęcia", text_color="#4f3f6d")

            # 1b. Pasek miniatur pozostałych zdjęć pod głównym zdjęciem
            self.mini_strip = ctk.CTkFrame(photo_col, fg_color="transparent", width=104, height=30)
            self.mini_strip.pack(anchor="n", pady=(5, 0))

            self._render_mini_thumbnails()

            # Dociąganie pełnej galerii w tle jeśli początkowo mamy tylko 1 zdjęcie
            if len(self.offer.images) <= 1 and self.offer.platform in ("VINTED", "ALLEGRO LOKALNIE", "ALLEGRO"):
                threading.Thread(target=self._fetch_extra_images_async, daemon=True).start()

        # 2. Prawa kolumna z treścią ogłoszenia i analizą AI
        details = ctk.CTkFrame(main_box, fg_color="transparent")
        details.pack(side="left", fill="both", expand=True)

        # 2a. Górny pasek: Badge platformy, Etykieta okazji, Lokalizacja, Dostawa, Czas
        top_frame = ctk.CTkFrame(details, fg_color="transparent")
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

        # 2c. Cena i opis okazji
        price_frame = ctk.CTkFrame(details, fg_color="transparent")
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

        ai_inner = ctk.CTkFrame(ai_box, fg_color="transparent")
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

        # 2e. Przyciski akcji
        action_frame = ctk.CTkFrame(details, fg_color="transparent")
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

    def _fetch_extra_images_async(self):
        try:
            extra = fetch_offer_images(self.offer)
            if extra and len(extra) > 1:
                self.offer.images = extra
                def _update():
                    self._render_mini_thumbnails()
                    if hasattr(self, "btn_gallery") and self.btn_gallery.winfo_exists():
                        self.btn_gallery.configure(text=f"🖼️ Galeria ({len(extra)})")
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
            CyberModal.show_error(self.winfo_toplevel(), "Błąd Przeglądarki", f"Nie można otworzyć linku w przeglądarce:\\n{e}")

    def _copy_url(self):
        self.clipboard_clear()
        self.clipboard_append(self.offer.url)
        self.update()'''

target_path = r"c:\Users\Kacper\Desktop\skrypt\app\gui.py"
with open(target_path, "r", encoding="utf-8") as f:
    content = f.read()

# Szukamy starego DealCard do _TabViewCompat
pattern = r"class DealCard\(ctk\.CTkFrame\):.*?(?=\nclass _TabViewCompat)"
match = re.search(pattern, content, flags=re.DOTALL)
if not match:
    print("Nie znaleziono wzorca DealCard!")
else:
    print(f"Znaleziono stary DealCard: {len(match.group(0))} znakow")
    updated = content[:match.start()] + new_dealcard_code + content[match.end():]
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(updated)
    print("Pomyślnie zaktualizowano DealCard w gui.py!")
