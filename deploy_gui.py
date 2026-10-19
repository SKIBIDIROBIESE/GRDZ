# c:/Users/Kacper/Desktop/skrypt/deploy_gui.py
# Python / deploy_gui.py / CustomTkinter / Cloud Deployment Assistant

import os
import sys
import subprocess
import threading
import webbrowser
import zipfile
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class DeployApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("GRDZ_SNIPE // Kreator Hostingu Chmurowego 24/7 (HTTPS + SSL)")
        self.geometry("740x620")
        self.resizable(False, False)

        # Nagłówek
        self.header_frame = ctk.CTkFrame(self, corner_radius=12, fg_color="#0e1424", border_width=1, border_color="#1e293b")
        self.header_frame.pack(fill="x", padx=20, pady=(20, 14))

        self.lbl_title = ctk.CTkLabel(
            self.header_frame,
            text="⚡ GRDZ_SNIPE - WDROŻENIE DO CHMURY 24/7",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#f97316"
        )
        self.lbl_title.pack(anchor="w", padx=16, pady=(12, 4))

        self.lbl_sub = ctk.CTkLabel(
            self.header_frame,
            text="Dzięki temu portal będzie działać 24/7 z bezpieczną zieloną kłódką (HTTPS SSL)\ni każdy będzie mógł na niego wchodzić bez włączonego Twojego komputera.",
            font=ctk.CTkFont(size=12),
            text_color="#94a3b8",
            justify="left"
        )
        self.lbl_sub.pack(anchor="w", padx=16, pady=(0, 12))

        # Kontener kroków
        self.steps_frame = ctk.CTkFrame(self, corner_radius=12, fg_color="#0e1424", border_width=1, border_color="#1e293b")
        self.steps_frame.pack(fill="both", expand=True, padx=20, pady=(0, 14))

        # KROK 1
        self.lbl_s1 = ctk.CTkLabel(
            self.steps_frame,
            text="KROK 1: Utwórz darmowe repozytorium na GitHub",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#ffffff"
        )
        self.lbl_s1.pack(anchor="w", padx=16, pady=(14, 4))

        self.btn_open_gh = ctk.CTkButton(
            self.steps_frame,
            text="🌐 Otwórz stronę GitHub.com/new w przeglądarce",
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=36,
            command=self.open_github_new
        )
        self.btn_open_gh.pack(fill="x", padx=16, pady=(0, 12))

        # KROK 2
        self.lbl_s2 = ctk.CTkLabel(
            self.steps_frame,
            text="KROK 2: Wklej adres swojego nowego repozytorium GitHub",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#ffffff"
        )
        self.lbl_s2.pack(anchor="w", padx=16, pady=(8, 4))

        self.entry_repo = ctk.CTkEntry(
            self.steps_frame,
            placeholder_text="np. https://github.com/TwojNick/grdzsnipe-portal.git",
            height=38,
            font=ctk.CTkFont(size=13)
        )
        self.entry_repo.pack(fill="x", padx=16, pady=(0, 8))

        self.btn_push = ctk.CTkButton(
            self.steps_frame,
            text="📤 Wyślij pliki projektu do GitHub (1-Kliknięcie)",
            fg_color="#f97316",
            hover_color="#ea580c",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=38,
            command=self.start_git_push
        )
        self.btn_push.pack(fill="x", padx=16, pady=(0, 14))

        # KROK 3
        self.lbl_s3 = ctk.CTkLabel(
            self.steps_frame,
            text="KROK 3: Uruchom darmowy hosting na Render.com",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#ffffff"
        )
        self.lbl_s3.pack(anchor="w", padx=16, pady=(6, 4))

        self.btn_open_render = ctk.CTkButton(
            self.steps_frame,
            text="🚀 Otwórz Dashboard Render.com (New Web Service)",
            fg_color="#10b981",
            hover_color="#059669",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=36,
            command=self.open_render_dashboard
        )
        self.btn_open_render.pack(fill="x", padx=16, pady=(0, 14))

        # Alternatywa: Paczka ZIP
        self.btn_make_zip = ctk.CTkButton(
            self.steps_frame,
            text="📦 Opcja bez Git: Wygeneruj gotową paczkę ZIP na Pulpit (dla PythonAnywhere / Railway)",
            fg_color="#334155",
            hover_color="#475569",
            font=ctk.CTkFont(size=12),
            height=32,
            command=self.make_cloud_zip
        )
        self.btn_make_zip.pack(fill="x", padx=16, pady=(0, 14))

        # Pasek statusu
        self.status_box = ctk.CTkTextbox(self, height=80, font=ctk.CTkFont(family="Consolas", size=11))
        self.status_box.pack(fill="x", padx=20, pady=(0, 16))
        self.log("[*] Asystent gotowy. Postępuj zgodnie z krokami 1, 2 i 3 powyżej.")

    def log(self, text: str):
        self.status_box.insert("end", text + "\n")
        self.status_box.see("end")

    def open_github_new(self):
        webbrowser.open("https://github.com/new")
        self.log("[*] Otwarto stronę tworzenia repozytorium GitHub w Twojej przeglądarce.")

    def open_render_dashboard(self):
        webbrowser.open("https://dashboard.render.com/")
        self.log("[*] Otwarto Render.com. Wybierz 'New +' -> 'Web Service' i wskaż swoje repozytorium.")

    def start_git_push(self):
        repo_url = self.entry_repo.get().strip()
        if not repo_url:
            messagebox.showwarning("Brak adresu", "Wklej adres repozytorium GitHub przed wysłaniem plików!")
            return

        self.btn_push.configure(state="disabled", text="⏳ Wysyłanie do GitHub...")
        threading.Thread(target=self._push_worker, args=(repo_url,), daemon=True).start()

    def _push_worker(self, repo_url: str):
        try:
            self.log(f"[*] Konfiguracja zdalnego repozytorium: {repo_url}")
            subprocess.run(["git", "remote", "remove", "origin"], cwd=BASE_DIR, capture_output=True)
            res1 = subprocess.run(["git", "remote", "add", "origin", repo_url], cwd=BASE_DIR, capture_output=True, text=True)
            if res1.returncode != 0 and "already exists" not in res1.stderr:
                self.log(f"[!] Błąd remote add: {res1.stderr}")

            subprocess.run(["git", "branch", "-M", "main"], cwd=BASE_DIR, capture_output=True)

            self.log("[*] Trwa wysyłanie plików (git push)... Jeśli pojawi się okno logowania GitHub, zatwierdź je.")
            res2 = subprocess.run(["git", "push", "-u", "origin", "main"], cwd=BASE_DIR, capture_output=True, text=True)

            if res2.returncode == 0:
                self.log("=====================================================")
                self.log("✓ SUKCES! Pliki portalu zostały pomyślnie wysłane do GitHub.")
                self.log("[*] Teraz kliknij KROK 3, aby wdrożyć na Render.com w 60 sekund!")
                self.log("=====================================================")
                messagebox.showinfo("Sukces!", "Pliki zostały pomyślnie wysłane do GitHub!\nPrzejdź teraz do Kroku 3 na Render.com.")
            else:
                self.log(f"[!] Błąd podczas git push:\n{res2.stderr or res2.stdout}")
                messagebox.showerror("Błąd wysyłania", f"Wystąpił błąd podczas wysyłania do GitHub:\n{res2.stderr or res2.stdout}")
        except Exception as e:
            self.log(f"[!] Błąd: {e}")
            messagebox.showerror("Błąd", str(e))
        finally:
            self.btn_push.configure(state="normal", text="📤 Wyślij pliki projektu do GitHub (1-Kliknięcie)")

    def make_cloud_zip(self):
        desktop_dir = os.path.join(os.path.expanduser("~"), "Desktop")
        out_zip = os.path.join(desktop_dir, "GRDZ_SNIPE_CLOUD_READY.zip")

        try:
            with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                # Dołączamy pliki root
                for f in ["wsgi.py", "Procfile", "render.yaml", "requirements.txt", ".gitignore"]:
                    p = os.path.join(BASE_DIR, f)
                    if os.path.exists(p):
                        zf.write(p, arcname=f)

                # Dołączamy folder app
                app_dir = os.path.join(BASE_DIR, "app")
                for root, _, files in os.walk(app_dir):
                    if "__pycache__" in root:
                        continue
                    for file in files:
                        if file.endswith((".pyc", ".log")):
                            continue
                        full_p = os.path.join(root, file)
                        rel_p = os.path.relpath(full_p, BASE_DIR)
                        zf.write(full_p, arcname=rel_p)

            self.log(f"✓ Utworzono paczkę ZIP na Pulpicie: {out_zip}")
            messagebox.showinfo("Paczka Utworzona", f"Gotowa paczka do wgrania na hosting znajduje się na Pulpicie:\n\n{out_zip}")
        except Exception as e:
            self.log(f"[!] Błąd tworzenia ZIP: {e}")
            messagebox.showerror("Błąd", str(e))


if __name__ == "__main__":
    app = DeployApp()
    app.mainloop()
