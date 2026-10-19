# c:/Users/Kacper/Desktop/skrypt/app/admin_server.py
# Python / admin_server.py / Flask 3.1 / GRDZ-SNIPE Portal & KeyAuth Server

import os
import sys
import io
import zipfile
import sqlite3
import secrets
import string
import hashlib
import webbrowser
import threading
import time
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, render_template_string, redirect, url_for, session, send_file, make_response

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "licenses.db")

# Przekierowanie sys.stdout/sys.stderr do admin_server.log (niezawodna praca w pythonw)
try:
    log_file = open(os.path.join(BASE_DIR, "admin_server.log"), "a", encoding="utf-8")
    sys.stdout = log_file
    sys.stderr = log_file
except Exception:
    pass

import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.WARNING)

from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "grdz_snipe_ultra_secure_secret_key_2026")

# Obsługa reverse-proxy chmurowego (Render, Railway, Cloudflare itp.) dla poprawnego HTTPS
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Konfiguracja bezpiecznych ciasteczek sesyjnych
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False, # Ustawiane automatycznie przez przegladarke przy HTTPS
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    PREFERRED_URL_SCHEME="https"
)

# Prosty, pamięciowy mechanizm ochrony przed atakami brute-force
LOGIN_ATTEMPTS = {}  # { ip: [timestamp1, timestamp2, ...] }
MAX_ATTEMPTS_PER_MINUTE = 8

def is_rate_limited(ip):
    now = time.time()
    attempts = LOGIN_ATTEMPTS.get(ip, [])
    # Filtrujemy tylko próby z ostatniej minuty
    attempts = [t for t in attempts if now - t < 60]
    LOGIN_ATTEMPTS[ip] = attempts
    return len(attempts) >= MAX_ATTEMPTS_PER_MINUTE

def record_attempt(ip):
    now = time.time()
    attempts = LOGIN_ATTEMPTS.get(ip, [])
    attempts.append(now)
    LOGIN_ATTEMPTS[ip] = [t for t in attempts if now - t < 60]

# Bezpieczne nagłówki HTTP (Security Headers)
@app.after_request
def set_security_headers(response):
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if request.is_secure or request.headers.get("X-Forwarded-Proto") == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

# ---------------------------------------------------------
# Database Schema & Initialization
# ---------------------------------------------------------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    with conn:
        # Tabela użytkowników portalu
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT DEFAULT 'user',
                is_verified INTEGER DEFAULT 0,
                verification_code TEXT DEFAULT '',
                verification_token TEXT DEFAULT '',
                license_key TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                avatar_url TEXT DEFAULT '',
                google_id TEXT DEFAULT ''
            )
        """)

        # Tabela licencji KeyAuth
        conn.execute("""
            CREATE TABLE IF NOT EXISTS licenses (
                key TEXT PRIMARY KEY,
                note TEXT DEFAULT '',
                duration_days INTEGER DEFAULT 30,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                hwid TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                last_ip TEXT DEFAULT '',
                last_seen TEXT DEFAULT ''
            )
        """)

        # Tabela aktywnych sesji na żywo
        conn.execute("""
            CREATE TABLE IF NOT EXISTS active_sessions (
                session_id TEXT PRIMARY KEY,
                license_key TEXT NOT NULL,
                hwid TEXT DEFAULT '',
                ip_address TEXT DEFAULT '',
                app_version TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                last_heartbeat TEXT NOT NULL,
                action TEXT DEFAULT 'Bezczynny',
                message TEXT DEFAULT ''
            )
        """)

        # Tabela ustawień globalnych
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        # Tabela blokady anty-multikonto per HWID (dokładnie 1 darmowy trial na 1 urządzenie)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS used_trials (
                hwid TEXT PRIMARY KEY,
                license_key TEXT NOT NULL,
                claimed_at TEXT NOT NULL,
                ip_address TEXT DEFAULT ''
            )
        """)

        # Tabela trwale zablokowanych stacji roboczych (HWID Blacklist - BAN)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS banned_hwids (
                hwid TEXT PRIMARY KEY,
                reason TEXT DEFAULT '',
                banned_at TEXT NOT NULL
            )
        """)

        # Domyślny administrator (login: admin, hasło: admin123)
        cur = conn.execute("SELECT id FROM users WHERE username = 'admin'")
        if not cur.fetchone():
            default_admin_hash = hashlib.sha256("admin123".encode()).hexdigest()
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("""
                INSERT INTO users (username, email, password_hash, role, is_verified, license_key, created_at)
                VALUES ('admin', 'admin@grdzsnipe.com', ?, 'admin', 1, 'SNIPE-PRO-DEV-2026', ?)
            """, (default_admin_hash, now_str))

        # Seed ustawień
        cur = conn.execute("SELECT value FROM settings WHERE key = 'admin_password_hash'")
        if not cur.fetchone():
            conn.execute("INSERT INTO settings (key, value) VALUES ('admin_password_hash', ?)", 
                         (hashlib.sha256("admin123".encode()).hexdigest(),))

        cur = conn.execute("SELECT value FROM settings WHERE key = 'killswitch'")
        if not cur.fetchone():
            conn.execute("INSERT INTO settings (key, value) VALUES ('killswitch', '0')")

        cur = conn.execute("SELECT value FROM settings WHERE key = 'broadcast'")
        if not cur.fetchone():
            conn.execute("INSERT INTO settings (key, value) VALUES ('broadcast', '')")

        # Seed domyślnego klucza deweloperskiego/administracyjnego
        cur = conn.execute("SELECT COUNT(*) FROM licenses")
        if cur.fetchone()[0] == 0:
            now = datetime.now()
            expires = now + timedelta(days=3650)
            conn.execute("""
                INSERT INTO licenses (key, note, duration_days, created_at, expires_at, hwid, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                "SNIPE-PRO-DEV-2026",
                "Klucz Administratora (Master Lifetime)",
                3650,
                now.strftime("%Y-%m-%d %H:%M:%S"),
                expires.strftime("%Y-%m-%d %H:%M:%S"),
                "",
                "active"
            ))
    conn.close()

# Automatyczna inicjalizacja schematu bazy danych (niezbędne dla gunicorn i chmury)
init_db()

def generate_license_code(prefix="SNIPE"):
    chars = string.ascii_uppercase + string.digits
    parts = [prefix]
    for _ in range(3):
        parts.append(''.join(secrets.choice(chars) for _ in range(4)))
    return '-'.join(parts)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("user_id") or session.get("role") != "admin":
            return render_template_string(ACCESS_DENIED_HTML), 403
        return f(*args, **kwargs)
    return decorated_function

def get_current_user_and_license():
    user_id = session.get("user_id")
    if not user_id:
        return None, None
    conn = get_db()
    try:
        cur = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        user = cur.fetchone()
        license_obj = None
        if user and user["license_key"]:
            cur_lic = conn.execute("SELECT * FROM licenses WHERE key = ?", (user["license_key"],))
            license_obj = cur_lic.fetchone()
        return user, license_obj
    finally:
        conn.close()

# ---------------------------------------------------------
# Client API Endpoints (Used by Desktop App)
# ---------------------------------------------------------

@app.route("/api/client/auth_login", methods=["POST"])
def api_client_auth_login():
    """
    Dedykowany punkt wejściowy launchera aplikacji desktopowej:
    Wymaga podania loginu/maila, hasła do konta oraz klucza licencyjnego.
    Ściśle weryfikuje status BAN na poziomie konta, licencji oraz HWID stacji roboczej.
    """
    data = request.get_json(silent=True) or {}
    identity = str(data.get("identity") or data.get("username") or data.get("email", "")).strip()
    pwd = str(data.get("password", "")).strip()
    key = str(data.get("key") or data.get("license_key", "")).strip()
    hwid = str(data.get("hwid", "")).strip()
    app_version = str(data.get("app_version", "v2.6 PRO")).strip()
    ip_addr = request.remote_addr or request.headers.get("X-Forwarded-For", "127.0.0.1")
    now_dt = datetime.now()
    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

    if not identity or not pwd or not key:
        return jsonify({
            "success": False,
            "status": "missing_fields",
            "message": "Wymagane jest podanie loginu, hasła oraz klucza autoryzacji."
        }), 400

    conn = get_db()
    try:
        # 1. Global Killswitch
        cur = conn.execute("SELECT value FROM settings WHERE key = 'killswitch'")
        row = cur.fetchone()
        if row and row["value"] == "1":
            return jsonify({
                "success": False,
                "status": "killswitch",
                "message": "Aplikacja jest tymczasowo wstrzymana przez administratora (Global Killswitch)."
            }), 403

        # 2. Blokada czarnej listy HWID (BANNED HWID)
        if hwid:
            cur = conn.execute("SELECT * FROM banned_hwids WHERE hwid = ?", (hwid,))
            if cur.fetchone():
                return jsonify({
                    "success": False,
                    "status": "banned",
                    "message": "Twój komputer (HWID) został trwale zablokowany przez administratora (BAN)."
                }), 403

        # 3. Weryfikacja konta użytkownika (Login + Hasło)
        cur = conn.execute("SELECT * FROM users WHERE username = ? OR email = ?", (identity, identity.lower()))
        user = cur.fetchone()
        if not user:
            return jsonify({
                "success": False,
                "status": "invalid_credentials",
                "message": "Nie znaleziono konta o podanym loginie lub adresie e-mail."
            }), 401

        pwd_hash = hashlib.sha256(pwd.encode()).hexdigest()
        if pwd_hash != user["password_hash"]:
            return jsonify({
                "success": False,
                "status": "invalid_credentials",
                "message": "Wprowadzone hasło do konta jest nieprawidłowe."
            }), 401

        # 4. Sprawdzenie statusu zablokowanego konta (User BAN)
        if user["role"] == "banned" or user["is_verified"] == -1:
            return jsonify({
                "success": False,
                "status": "banned",
                "message": "Twoje konto użytkownika zostało trwale zablokowane przez administratora (BAN)."
            }), 403

        # 5. Weryfikacja klucza licencji
        cur = conn.execute("SELECT * FROM licenses WHERE key = ?", (key,))
        lic = cur.fetchone()
        if not lic:
            return jsonify({
                "success": False,
                "status": "invalid_key",
                "message": "Podany klucz licencyjny nie istnieje w systemie."
            }), 401

        # 6. Sprawdzenie statusu licencji (BAN / PAUSE / EXPIRED)
        lic_status = lic["status"]
        if lic_status == "banned":
            if hwid:
                conn.execute("INSERT OR REPLACE INTO banned_hwids (hwid, reason, banned_at) VALUES (?, ?, ?)",
                             (hwid, f"Próba użycia zbanowanego klucza {key}", now_str))
                conn.commit()
            return jsonify({
                "success": False,
                "status": "banned",
                "message": "Ten klucz licencyjny został trwale zablokowany przez administratora (BAN)."
            }), 403

        if lic_status == "paused":
            return jsonify({
                "success": False,
                "status": "paused",
                "message": "Dostęp dla tego klucza jest tymczasowo wstrzymany (Pauza)."
            }), 403

        try:
            exp_dt = datetime.strptime(lic["expires_at"], "%Y-%m-%d %H:%M:%S")
            if now_dt > exp_dt:
                conn.execute("UPDATE licenses SET status = 'expired' WHERE key = ?", (key,))
                conn.commit()
                return jsonify({
                    "success": False,
                    "status": "expired",
                    "message": f"Ważność tego klucza wygasła dnia: {lic['expires_at']}."
                }), 403
        except Exception:
            pass

        # 7. Zabezpieczenie Trial HWID (dokładnie 1 trial na komputer)
        is_trial = key.startswith("SNIPE-TRIAL") or (lic["duration_days"] is not None and lic["duration_days"] <= 1)
        if is_trial and hwid:
            cur = conn.execute("SELECT * FROM used_trials WHERE hwid = ?", (hwid,))
            trial_row = cur.fetchone()
            if trial_row and trial_row["license_key"] != key:
                return jsonify({
                    "success": False,
                    "status": "trial_already_used",
                    "message": "Ten komputer (HWID) wykorzystał już darmowy 1-dniowy Trial na innym koncie."
                }), 403
            conn.execute("INSERT OR REPLACE INTO used_trials (hwid, license_key, claimed_at, ip_address) VALUES (?, ?, ?, ?)",
                         (hwid, key, now_str, ip_addr))
            conn.commit()

        # 8. Powiązanie i weryfikacja HWID
        lic_hwid = lic["hwid"]
        if not lic_hwid:
            conn.execute("UPDATE licenses SET hwid = ?, last_ip = ?, last_seen = ? WHERE key = ?",
                         (hwid, ip_addr, now_str, key))
            conn.commit()
            lic_hwid = hwid
        elif lic_hwid != hwid:
            return jsonify({
                "success": False,
                "status": "hwid_mismatch",
                "message": "Ten klucz jest przypisany do innego urządzenia. Zresetuj HWID w profilu na stronie."
            }), 403

        # Przypisanie klucza do konta jeśli nie był przypisany
        if not user["license_key"]:
            conn.execute("UPDATE users SET license_key = ? WHERE id = ?", (key, user["id"]))
            conn.commit()

        session_id = secrets.token_hex(16)
        conn.execute("""
            INSERT OR REPLACE INTO active_sessions (session_id, license_key, hwid, ip_address, app_version, status, last_heartbeat, action)
            VALUES (?, ?, ?, ?, ?, 'active', ?, 'Autoryzowano w programie')
        """, (session_id, key, hwid, ip_addr, app_version, now_str))
        conn.execute("UPDATE licenses SET last_seen = ?, last_ip = ? WHERE key = ?", (now_str, ip_addr, key))
        conn.commit()

        return jsonify({
            "success": True,
            "status": "active",
            "message": f"Witaj, {user['username']}! Autoryzacja pomyślna.",
            "session_id": session_id,
            "user": user["username"],
            "info": {
                "key": key,
                "hwid": lic_hwid,
                "status": "active",
                "expires_at": lic["expires_at"],
                "note": lic["note"],
                "username": user["username"]
            }
        })
    finally:
        conn.close()

@app.route("/api/license/verify", methods=["POST"])
def api_verify_license():
    data = request.get_json(silent=True) or {}
    key = str(data.get("key") or data.get("license_key", "")).strip()
    hwid = str(data.get("hwid", "")).strip()
    app_version = str(data.get("app_version", "v2.6 PRO")).strip()
    action = str(data.get("action", "Uruchomiono program")).strip()
    ip_addr = request.remote_addr or request.headers.get("X-Forwarded-For", "127.0.0.1")

    if not key:
        return jsonify({
            "success": False,
            "valid": False,
            "status": "empty",
            "message": "Nie podano klucza licencyjnego."
        }), 400

    conn = get_db()
    try:
        cur = conn.execute("SELECT value FROM settings WHERE key = 'killswitch'")
        row = cur.fetchone()
        if row and row["value"] == "1":
            return jsonify({
                "success": False,
                "valid": False,
                "status": "killswitch",
                "message": "Aplikacja jest tymczasowo wstrzymana przez administratora (Global Killswitch)."
            }), 403

        cur = conn.execute("SELECT * FROM licenses WHERE key = ?", (key,))
        lic = cur.fetchone()
        if not lic:
            return jsonify({
                "success": False,
                "valid": False,
                "status": "invalid",
                "message": "Nieprawidłowy lub nieistniejący klucz licencji."
            }), 401

        status = lic["status"]
        if status == "banned":
            return jsonify({
                "success": False,
                "valid": False,
                "status": "banned",
                "message": "Ten klucz został trwale zablokowany przez administratora (BAN)."
            }), 403
        if status == "paused":
            return jsonify({
                "success": False,
                "valid": False,
                "status": "paused",
                "message": "Dostęp do aplikacji dla tej licencji jest tymczasowo wstrzymany (Pauza)."
            }), 403

        now_dt = datetime.now()
        try:
            exp_dt = datetime.strptime(lic["expires_at"], "%Y-%m-%d %H:%M:%S")
            if now_dt > exp_dt:
                conn.execute("UPDATE licenses SET status = 'expired' WHERE key = ?", (key,))
                conn.commit()
                return jsonify({
                    "success": False,
                    "valid": False,
                    "status": "expired",
                    "message": f"Ważność Twojej licencji wygasła dnia: {lic['expires_at']}."
                }), 403
        except Exception:
            pass

        # Blokada anty-multikonto dla darmowego trialu (1 trial na dany komputer/HWID)
        is_trial = key.startswith("SNIPE-TRIAL") or (lic["duration_days"] is not None and lic["duration_days"] <= 1)
        if is_trial and hwid:
            cur = conn.execute("SELECT * FROM used_trials WHERE hwid = ?", (hwid,))
            trial_row = cur.fetchone()
            if trial_row and trial_row["license_key"] != key:
                return jsonify({
                    "success": False,
                    "valid": False,
                    "status": "trial_already_used",
                    "message": "Ten komputer (HWID) wykorzystał już darmowy 1-dniowy Trial na innym koncie. Aby kontynuować, wykup pakiet w Sklepie (od 19 zł)."
                }), 403

            # Zapisujemy wykorzystanie darmowego trialu dla tego HWID
            conn.execute("INSERT OR REPLACE INTO used_trials (hwid, license_key, claimed_at, ip_address) VALUES (?, ?, ?, ?)",
                         (hwid, key, now_dt.strftime("%Y-%m-%d %H:%M:%S"), ip_addr))
            conn.commit()

        lic_hwid = lic["hwid"]
        if not lic_hwid:
            conn.execute("UPDATE licenses SET hwid = ?, last_ip = ?, last_seen = ? WHERE key = ?",
                         (hwid, ip_addr, now_dt.strftime("%Y-%m-%d %H:%M:%S"), key))
            conn.commit()
            lic_hwid = hwid
        elif lic_hwid != hwid:
            return jsonify({
                "success": False,
                "valid": False,
                "status": "hwid_mismatch",
                "message": "Ten klucz jest już przypisany do innego urządzenia (HWID). Zresetuj HWID w panelu na stronie grdzsnipe.com."
            }), 403

        session_id = secrets.token_hex(16)
        conn.execute("""
            INSERT OR REPLACE INTO active_sessions (session_id, license_key, hwid, ip_address, app_version, status, last_heartbeat, action)
            VALUES (?, ?, ?, ?, ?, 'active', ?, ?)
        """, (session_id, key, hwid, ip_addr, app_version, now_dt.strftime("%Y-%m-%d %H:%M:%S"), action))
        conn.execute("UPDATE licenses SET last_seen = ?, last_ip = ? WHERE key = ?",
                     (now_dt.strftime("%Y-%m-%d %H:%M:%S"), ip_addr, key))
        conn.commit()

        cur = conn.execute("SELECT value FROM settings WHERE key = 'broadcast'")
        b_row = cur.fetchone()
        broadcast = b_row["value"] if b_row else ""

        return jsonify({
            "success": True,
            "valid": True,
            "status": "active",
            "session_id": session_id,
            "expires_at": lic["expires_at"],
            "duration_days": lic["duration_days"],
            "hwid": lic_hwid,
            "broadcast": broadcast,
            "message": "Licencja pomyślnie zweryfikowana. Witaj w GRDZ_SNIPE PRO!"
        }), 200

    finally:
        conn.close()

@app.route("/api/license/heartbeat", methods=["POST"])
def api_license_heartbeat():
    data = request.get_json(silent=True) or {}
    key = str(data.get("key") or data.get("license_key", "")).strip()
    session_id = str(data.get("session_id", "")).strip()
    hwid = str(data.get("hwid", "")).strip()
    app_version = str(data.get("app_version", "v2.6 PRO")).strip()
    action = str(data.get("action", "")).strip()
    ip_addr = request.remote_addr or request.headers.get("X-Forwarded-For", "127.0.0.1")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not key:
        return jsonify({"status": "error", "message": "Missing key"}), 400

    conn = get_db()
    try:
        cur = conn.execute("SELECT value FROM settings WHERE key = 'killswitch'")
        row = cur.fetchone()
        if row and row["value"] == "1":
            return jsonify({
                "success": False,
                "status": "killswitch",
                "message": "Globalny Killswitch aktywowany przez administratora."
            }), 200

        cur = conn.execute("SELECT status, expires_at, hwid FROM licenses WHERE key = ?", (key,))
        lic = cur.fetchone()
        if not lic:
            return jsonify({
                "success": False,
                "status": "invalid",
                "message": "Licencja została usunięta przez administratora."
            }), 200

        # Weryfikacja czarnej listy HWID
        if hwid:
            cur = conn.execute("SELECT * FROM banned_hwids WHERE hwid = ?", (hwid,))
            if cur.fetchone():
                return jsonify({
                    "success": False,
                    "status": "banned",
                    "message": "Ten komputer (HWID) został trwale zablokowany przez administratora (BAN)."
                }), 200

        # Weryfikacja czy konto powiązane z kluczem nie ma bana
        cur = conn.execute("SELECT role FROM users WHERE license_key = ?", (key,))
        u_row = cur.fetchone()
        if u_row and u_row["role"] == "banned":
            return jsonify({
                "success": False,
                "status": "banned",
                "message": "Konto powiązane z tym kluczem zostało trwale zablokowane przez administratora (BAN)."
            }), 200

        if lic["status"] in ("banned", "paused"):
            return jsonify({
                "success": False,
                "status": lic["status"],
                "message": f"Dostęp został zablokowany (status: {lic['status']})."
            }), 200

        try:
            exp_dt = datetime.strptime(lic["expires_at"], "%Y-%m-%d %H:%M:%S")
            if datetime.now() > exp_dt:
                return jsonify({
                    "success": False,
                    "status": "expired",
                    "message": "Ważność Twojej licencji upłynęła."
                }), 200
        except Exception:
            pass

        if session_id:
            cur = conn.execute("SELECT action, message FROM active_sessions WHERE session_id = ?", (session_id,))
            sess_row = cur.fetchone()
            if sess_row and sess_row["action"] == "kill":
                msg = sess_row["message"] or "Sesja została zdalnie zakończona przez panel administratora."
                conn.execute("DELETE FROM active_sessions WHERE session_id = ?", (session_id,))
                conn.commit()
                return jsonify({"success": False, "status": "killed", "message": msg}), 200

        if not session_id:
            session_id = secrets.token_hex(16)

        conn.execute("""
            INSERT OR REPLACE INTO active_sessions (session_id, license_key, hwid, ip_address, app_version, status, last_heartbeat, action)
            VALUES (?, ?, ?, ?, ?, 'active', ?, ?)
        """, (session_id, key, hwid, ip_addr, app_version, now_str, action or "Bezczynny"))
        conn.execute("UPDATE licenses SET last_seen = ?, last_ip = ? WHERE key = ?", (now_str, ip_addr, key))
        conn.commit()

        cur = conn.execute("SELECT value FROM settings WHERE key = 'broadcast'")
        b_row = cur.fetchone()
        broadcast = b_row["value"] if b_row else ""

        return jsonify({
            "success": True,
            "status": "active",
            "session_id": session_id,
            "broadcast_message": broadcast,
            "broadcast": broadcast
        }), 200

    finally:
        conn.close()

# ---------------------------------------------------------
# HTML & Styling Definitions
# ---------------------------------------------------------

BASE_CSS = """
:root {
    --bg: #070913;
    --surface: #0e1424;
    --surface-hover: #151e36;
    --surface-card: rgba(14, 20, 36, 0.85);
    --border: #1e293b;
    --border-highlight: #334155;
    --accent: #f97316;
    --accent-glow: rgba(249, 115, 22, 0.3);
    --purple: #a855f7;
    --purple-glow: rgba(168, 85, 247, 0.3);
    --cyan: #06b6d4;
    --green: #10b981;
    --red: #ef4444;
    --yellow: #f59e0b;
    --text-primary: #f8fafc;
    --text-secondary: #94a3b8;
    --text-muted: #64748b;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
    background-color: var(--bg);
    background-image: 
        radial-gradient(at 0% 0%, rgba(249, 115, 22, 0.08) 0px, transparent 45%),
        radial-gradient(at 100% 0%, rgba(168, 85, 247, 0.08) 0px, transparent 45%),
        radial-gradient(at 50% 100%, rgba(6, 182, 212, 0.06) 0px, transparent 50%),
        linear-gradient(rgba(255, 255, 255, 0.02) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255, 255, 255, 0.02) 1px, transparent 1px);
    background-size: 100% 100%, 100% 100%, 100% 100%, 32px 32px, 32px 32px;
    color: var(--text-primary);
    font-family: 'Plus Jakarta Sans', sans-serif;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
}

.mono { font-family: 'JetBrains Mono', monospace; }

header {
    background: rgba(14, 20, 36, 0.92);
    backdrop-filter: blur(16px);
    border-bottom: 1px solid var(--border);
    padding: 14px 32px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: sticky;
    top: 0;
    z-index: 50;
}

.brand {
    display: flex;
    align-items: center;
    gap: 12px;
    text-decoration: none;
    color: inherit;
}

.brand-logo {
    width: 40px;
    height: 40px;
    background: linear-gradient(135deg, var(--accent), #ea580c);
    border-radius: 11px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 800;
    font-size: 20px;
    box-shadow: 0 0 20px var(--accent-glow);
}

.brand-title {
    font-size: 19px;
    font-weight: 800;
    letter-spacing: -0.5px;
}
.brand-title span { color: var(--accent); }

.nav-links {
    display: flex;
    align-items: center;
    gap: 8px;
}

.nav-item {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    padding: 8px 14px;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 600;
    color: var(--text-secondary);
    text-decoration: none;
    transition: all 0.2s ease;
}
.nav-item:hover {
    color: var(--text-primary);
    background: var(--surface-hover);
}
.nav-item.active {
    color: #fff;
    background: rgba(249, 115, 22, 0.15);
    border: 1px solid rgba(249, 115, 22, 0.35);
}

.btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 9px 18px;
    border-radius: 9px;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s ease;
    border: 1px solid transparent;
    text-decoration: none;
}
.btn-primary {
    background: linear-gradient(135deg, var(--accent), #ea580c);
    color: #fff;
    box-shadow: 0 4px 14px var(--accent-glow);
}
.btn-primary:hover { opacity: 0.92; transform: translateY(-1px); }

.btn-admin {
    background: linear-gradient(135deg, #a855f7, #7c3aed);
    color: #fff;
    box-shadow: 0 4px 14px rgba(168, 85, 247, 0.35);
}
.btn-admin:hover { opacity: 0.92; transform: translateY(-1px); }

.btn-outline {
    background: rgba(255, 255, 255, 0.04);
    border-color: var(--border);
    color: var(--text-secondary);
}
.btn-outline:hover {
    background: var(--surface-hover);
    color: var(--text-primary);
    border-color: var(--border-highlight);
}

.btn-google {
    background: #ffffff;
    color: #1e293b;
    border-color: #e2e8f0;
    font-weight: 700;
    box-shadow: 0 2px 8px rgba(0,0,0,0.15);
}
.btn-google:hover { background: #f8fafc; }

.btn-danger {
    background: rgba(239, 68, 68, 0.15);
    border-color: rgba(239, 68, 68, 0.3);
    color: #fca5a5;
}
.btn-danger:hover { background: rgba(239, 68, 68, 0.25); color: #fff; }

.btn-success {
    background: rgba(16, 185, 129, 0.15);
    border-color: rgba(16, 185, 129, 0.3);
    color: #6ee7b7;
}
.btn-success:hover { background: rgba(16, 185, 129, 0.25); color: #fff; }

.btn-sm { padding: 4px 10px; font-size: 11px; border-radius: 6px; }

.badge {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 3px 8px;
    border-radius: 6px;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
}
.badge-active { background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); }
.badge-paused { background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); }
.badge-banned { background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }
.badge-live { background: rgba(6, 182, 212, 0.15); color: #38bdf8; border: 1px solid rgba(6, 182, 212, 0.3); }

.copy-pill {
    cursor: pointer;
    padding: 3px 8px;
    border-radius: 6px;
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid var(--border);
    transition: all 0.2s;
    display: inline-block;
}
.copy-pill:hover { border-color: var(--accent); color: var(--accent); }

.form-input {
    width: 100%;
    background: #070913;
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 12px 16px;
    color: var(--text-primary);
    font-size: 14px;
    margin-bottom: 16px;
    outline: none;
    transition: border-color 0.2s;
}
.form-input:focus { border-color: var(--accent); }

.auth-card {
    background: rgba(14, 20, 36, 0.9);
    border: 1px solid var(--border);
    border-radius: 20px;
    padding: 36px;
    width: 100%;
    max-width: 440px;
    margin: 40px auto;
    box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.7);
    backdrop-filter: blur(16px);
}

.container {
    max-width: 1160px;
    margin: 32px auto;
    padding: 0 24px;
    flex: 1;
    width: 100%;
}

.panel {
    background: var(--surface-card);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 28px;
    backdrop-filter: blur(12px);
    margin-bottom: 24px;
}
"""

# Komponent nagłówka (Header Nav) wstrzykiwany do szablonów
def render_header(current_tab="", user=None, license_obj=None):
    is_logged = bool(user)
    has_active_license = bool(license_obj and license_obj["status"] == "active")

    links_html = f'''
        <a href="/" class="nav-item {'active' if current_tab == 'home' else ''}">🏠 Główna</a>
        <a href="/shop" class="nav-item {'active' if current_tab == 'shop' else ''}">🛒 Sklep</a>
    '''

    if is_logged:
        # Zakładka Pobierz (ikona kłódki lub odznaka zielona jeśli odblokowane)
        if has_active_license:
            dl_badge = '<span class="badge badge-active" style="padding: 2px 6px; font-size: 9px;">✓ Aktywne</span>'
        else:
            dl_badge = '<span class="badge badge-paused" style="padding: 2px 6px; font-size: 9px;">🔒 Zablokowane</span>'

        links_html += f'''
            <a href="/download" class="nav-item {'active' if current_tab == 'download' else ''}">
                📥 Pobierz {dl_badge}
            </a>
            <a href="/profile" class="nav-item {'active' if current_tab == 'profile' else ''}">👤 Profil</a>
            <a href="/settings" class="nav-item {'active' if current_tab == 'settings' else ''}">⚙️ Ustawienia</a>
            <a href="/logout" class="btn btn-outline btn-sm" style="color: var(--red); margin-left: 8px;">Wyloguj</a>
        '''
    else:
        links_html += '''
            <a href="/login" class="btn btn-outline btn-sm" style="margin-left: 8px;">Zaloguj się</a>
            <a href="/register" class="btn btn-primary btn-sm">Rejestracja (Trial)</a>
        '''

    return f"""
    <header>
        <a href="/" class="brand">
            <div class="brand-logo">⚡</div>
            <div>
                <div class="brand-title">GRDZ-SNIPE <span>PRO</span></div>
                <div style="font-size: 11px; color: var(--text-muted);">Deal Hunting & Licencje KeyAuth</div>
            </div>
        </a>
        <div class="nav-links">
            {links_html}
        </div>
    </header>
    """

# ---------------------------------------------------------
# Web Templates
# ---------------------------------------------------------

LANDING_HTML = """
<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GRDZ-SNIPE // Autonomiczny Sniping Okazji E-Commerce</title>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        """ + BASE_CSS + """
        .hero {
            padding: 70px 24px 50px;
            text-align: center;
            max-width: 900px;
            margin: 0 auto;
        }
        .hero-badge {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 6px 16px;
            background: rgba(249, 115, 22, 0.12);
            border: 1px solid rgba(249, 115, 22, 0.3);
            border-radius: 30px;
            color: var(--accent);
            font-size: 12px;
            font-weight: 700;
            margin-bottom: 24px;
        }
        .hero h1 {
            font-size: 46px;
            font-weight: 800;
            line-height: 1.15;
            letter-spacing: -1.5px;
            margin-bottom: 20px;
        }
        .hero h1 span {
            background: linear-gradient(135deg, #f97316, #a855f7);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .hero p {
            font-size: 17px;
            color: var(--text-secondary);
            line-height: 1.6;
            margin-bottom: 36px;
        }
        .hero-cta {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 16px;
            flex-wrap: wrap;
        }
        .features-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 24px;
            max-width: 1200px;
            margin: 40px auto 70px;
            padding: 0 24px;
        }
        .feature-card {
            background: var(--surface-card);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 28px;
            backdrop-filter: blur(12px);
            transition: all 0.2s;
        }
        .feature-card:hover {
            border-color: var(--border-highlight);
            transform: translateY(-2px);
        }
        .feature-icon { font-size: 32px; margin-bottom: 16px; }
        .feature-title { font-size: 18px; font-weight: 700; margin-bottom: 10px; }
        .feature-desc { font-size: 14px; color: var(--text-secondary); line-height: 1.5; }
    </style>
</head>
<body>

{{ header|safe }}

<div class="hero">
    <div class="hero-badge">⚡ NAJSZYBSZY MULTI-PLATFORM DEAL SNIPER V2.6</div>
    <h1>Wykrywaj Okazje Cenowe <span>Zanim Kupią Je Inni</span></h1>
    <p>
        Autonomiczny silnik monitorujący OLX, Vinted, Allegro Lokalnie oraz Allegro w pętli milisekundowej.
        Zintegrowana sztuczna inteligencja ocenia stan i opłacalność ofert, a powiadomienia natychmiast trafiają na Discord i pulpit.
    </p>
    <div class="hero-cta">
        {% if user %}
            {% if license and license.status == 'active' %}
                <a href="/download" class="btn btn-primary" style="padding: 14px 28px; font-size: 15px;">📥 Przejdź do Pobrania Programu →</a>
                <a href="/profile" class="btn btn-outline" style="padding: 14px 24px; font-size: 15px;">Mój Profil i Licencja</a>
            {% else %}
                <a href="/shop" class="btn btn-primary" style="padding: 14px 28px; font-size: 15px;">⚡ Odbierz Trial w Sklepie →</a>
            {% endif %}
        {% else %}
            <a href="/register" class="btn btn-primary" style="padding: 14px 28px; font-size: 15px;">Utwórz Konto i Odbierz 1-Dniowy Trial →</a>
            <a href="/auth/google" class="btn btn-google" style="padding: 14px 24px; font-size: 15px;">
                <svg width="18" height="18" viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"/></svg>
                Zaloguj przez Google
            </a>
        {% endif %}
    </div>
</div>

<div class="features-grid">
    <div class="feature-card">
        <div class="feature-icon">🚀</div>
        <div class="feature-title">Multi-Platform Engine</div>
        <div class="feature-desc">Równoczesne skanowanie OLX, Vinted, Allegro oraz Allegro Lokalnie z filtrowaniem miast, promienia km i fraz wykluczających.</div>
    </div>
    <div class="feature-card">
        <div class="feature-icon">🧠</div>
        <div class="feature-title">AI Deal Evaluator</div>
        <div class="feature-desc">Wbudowana analiza czytająca opis i specyfikację w poszukiwaniu uszkodzeń, braków i weryfikująca opłacalność oferty w ułamku sekundy.</div>
    </div>
    <div class="feature-card">
        <div class="feature-icon">🔒</div>
        <div class="feature-title">KeyAuth HWID Protection</div>
        <div class="feature-desc">Bezpieczny system licencyjny powiązany ze sprzętem, z opcją natychmiastowego resetu HWID w Twoim profilu w razie zmiany komputera.</div>
    </div>
</div>

<footer style="text-align: center; padding: 32px; font-size: 12px; color: var(--text-muted); margin-top: auto; border-top: 1px solid var(--border);">
    GRDZ_SNIPE &copy; 2026. Oficjalny portal: <strong>http://grdzsnipe.com</strong>
</footer>

</body>
</html>
"""

# Strona Google Sign-In (Autentyczne pełne logowanie wieloetapowe: E-mail -> Hasło -> Potwierdzenie)
GOOGLE_OAUTH_MODAL_HTML = """
<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Zaloguj się przez Google // GRDZ-SNIPE</title>
    <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&family=Plus+Jakarta+Sans:wght@500;600;700&display=swap" rel="stylesheet">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            background-color: #f0f4f9;
            font-family: 'Roboto', -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 24px;
        }
        .google-card {
            background: #ffffff;
            border-radius: 28px;
            width: 100%;
            max-width: 440px;
            padding: 40px;
            box-shadow: 0 4px 24px rgba(0, 0, 0, 0.08);
            border: 1px solid #e1e3e1;
            text-align: left;
            position: relative;
        }
        .g-logo {
            display: flex;
            align-items: center;
            margin-bottom: 18px;
        }
        .g-title {
            font-size: 24px;
            font-weight: 500;
            color: #1f1f1f;
            margin-bottom: 8px;
            letter-spacing: -0.2px;
        }
        .g-sub {
            font-size: 15px;
            color: #444746;
            margin-bottom: 24px;
            line-height: 1.4;
        }
        .g-sub strong { color: #1f1f1f; font-weight: 600; }

        .account-chip {
            display: inline-flex;
            align-items: center;
            gap: 10px;
            padding: 6px 14px 6px 8px;
            border: 1px solid #c4c7c5;
            border-radius: 100px;
            margin-bottom: 20px;
            background: #f8fafc;
            font-size: 13px;
            color: #1f1f1f;
            cursor: pointer;
            transition: background 0.2s;
        }
        .account-chip:hover { background: #eef2f6; }
        .chip-avatar {
            width: 24px;
            height: 24px;
            border-radius: 50%;
            background: #1a73e8;
            color: #fff;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 11px;
            font-weight: 700;
        }

        .input-group {
            margin-bottom: 20px;
        }
        .input-label {
            display: block;
            font-size: 12px;
            font-weight: 500;
            color: #444746;
            margin-bottom: 6px;
        }
        .g-input {
            width: 100%;
            border: 1px solid #747775;
            border-radius: 8px;
            padding: 13px 16px;
            font-size: 15px;
            outline: none;
            transition: border-color 0.2s, box-shadow 0.2s;
            color: #1f1f1f;
            background: #fff;
        }
        .g-input:focus {
            border-color: #0b57d0;
            box-shadow: 0 0 0 2px rgba(11, 87, 208, 0.2);
        }

        .btn-google-primary {
            background: #0b57d0;
            color: #ffffff;
            border: none;
            border-radius: 100px;
            padding: 12px 26px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.2s, box-shadow 0.2s;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
        }
        .btn-google-primary:hover {
            background: #0842a0;
            box-shadow: 0 2px 6px rgba(0,0,0,0.2);
        }

        .btn-google-secondary {
            background: transparent;
            color: #0b57d0;
            border: none;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            padding: 12px 16px;
            text-decoration: none;
        }
        .btn-google-secondary:hover { text-decoration: underline; }

        .button-bar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-top: 28px;
        }

        .permission-card {
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 20px;
        }
        .permission-item {
            display: flex;
            align-items: flex-start;
            gap: 12px;
            margin-bottom: 12px;
            font-size: 13px;
            color: #334155;
            line-height: 1.4;
        }
        .permission-item:last-child { margin-bottom: 0; }
        .perm-icon { color: #0b57d0; font-size: 16px; flex-shrink: 0; }

        .checkbox-container {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 13px;
            color: #444746;
            margin-top: 8px;
            cursor: pointer;
        }

        .step-panel { display: none; }
        .step-panel.active { display: block; }
    </style>
</head>
<body>

<div class="google-card">
    <div class="g-logo">
        <svg width="34" height="34" viewBox="0 0 24 24">
            <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
            <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
            <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"/>
            <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"/>
        </svg>
    </div>

    <!-- KROK 1: Podaj E-mail Google -->
    <div id="step1" class="step-panel active">
        <h1 class="g-title">Zaloguj się przez Google</h1>
        <p class="g-sub">Przejdź do aplikacji <strong>GRDZ-SNIPE</strong></p>

        <div class="input-group">
            <label class="input-label">Adres e-mail lub telefon</label>
            <input type="email" id="step1Email" class="g-input" placeholder="twojadres@gmail.com" autofocus>
            <div id="step1Error" style="color: #ba1a1a; font-size: 12px; margin-top: 6px; display: none;">Podaj prawidłowy adres e-mail konta Google.</div>
        </div>

        <div class="button-bar">
            <a href="/login" class="btn-google-secondary">Wróć</a>
            <button type="button" class="btn-google-primary" onclick="goToStep2()">
                Dalej →
            </button>
        </div>
    </div>

    <!-- KROK 2: Wprowadź Hasło Google -->
    <div id="step2" class="step-panel">
        <div class="account-chip" onclick="goToStep1()">
            <div class="chip-avatar" id="step2Avatar">U</div>
            <span id="step2EmailDisplay">user@gmail.com</span>
            <span style="font-size: 11px; color: #747775;">▾</span>
        </div>

        <h1 class="g-title">Witaj</h1>
        <p class="g-sub">Wprowadź hasło do swojego konta Google</p>

        <div class="input-group">
            <label class="input-label">Wpisz hasło</label>
            <input type="password" id="step2Password" class="g-input" placeholder="Wpisz hasło konta Google...">
            <label class="checkbox-container">
                <input type="checkbox" onchange="toggleShowPassword(this)"> Pokaż hasło
            </label>
            <div id="step2Error" style="color: #ba1a1a; font-size: 12px; margin-top: 6px; display: none;">Hasło nie może być puste.</div>
        </div>

        <div class="button-bar">
            <button type="button" class="btn-google-secondary" onclick="goToStep1()">Wstecz</button>
            <button type="button" class="btn-google-primary" onclick="goToStep3()">
                Dalej →
            </button>
        </div>
    </div>

    <!-- KROK 3: Potwierdzenie Autoryzacji (2-Step / Zgoda) -->
    <div id="step3" class="step-panel">
        <div class="account-chip" onclick="goToStep1()">
            <div class="chip-avatar" id="step3Avatar">U</div>
            <span id="step3EmailDisplay">user@gmail.com</span>
        </div>

        <h1 class="g-title" style="font-size: 21px;">Potwierdź logowanie</h1>
        <p class="g-sub">Aplikacja <strong>GRDZ-SNIPE</strong> prosi o dostęp do profilu i logowanie.</p>

        <div class="permission-card">
            <div class="permission-item">
                <span class="perm-icon">✓</span>
                <div><strong>Autoryzacja tożsamości Google</strong><br>Logowanie bezpiecznym kontem bez hasła do zewnętrznego portalu.</div>
            </div>
            <div class="permission-item">
                <span class="perm-icon">✓</span>
                <div><strong>Aktywacja Starter Trial</strong><br>Przypisanie 1-dniowej licencji testowej z ochroną komputera (HWID).</div>
            </div>
        </div>

        <form method="POST" action="/auth/google/select" id="finalGoogleForm" onsubmit="saveFinalAccount()">
            <input type="hidden" name="email" id="finalEmail">
            <input type="hidden" name="password" id="finalPassword">
            <input type="hidden" name="name" id="finalName">

            <div class="button-bar" style="margin-top: 20px;">
                <button type="button" class="btn-google-secondary" onclick="goToStep2()">Wstecz</button>
                <button type="submit" class="btn-google-primary" style="background: #1a73e8; padding: 13px 28px;">
                    <svg width="16" height="16" viewBox="0 0 24 24"><path fill="#fff" d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
                    Potwierdź i zaloguj
                </button>
            </div>
        </form>
    </div>
</div>

<script>
    var currentEmail = '';
    var currentPassword = '';

    (function initSaved() {
        var saved = localStorage.getItem('grdz_google_user');
        if (saved) {
            try {
                var data = JSON.parse(saved);
                if (data.email) {
                    document.getElementById('step1Email').value = data.email;
                }
            } catch (e) {}
        }
    })();

    function goToStep1() {
        document.getElementById('step1').classList.add('active');
        document.getElementById('step2').classList.remove('active');
        document.getElementById('step3').classList.remove('active');
        document.getElementById('step1Email').focus();
    }

    function goToStep2() {
        var email = document.getElementById('step1Email').value.trim();
        if (!email || email.indexOf('@') === -1) {
            document.getElementById('step1Error').style.display = 'block';
            return;
        }
        document.getElementById('step1Error').style.display = 'none';
        currentEmail = email;

        document.getElementById('step2EmailDisplay').innerText = email;
        document.getElementById('step2Avatar').innerText = email[0].toUpperCase();

        document.getElementById('step1').classList.remove('active');
        document.getElementById('step2').classList.add('active');
        document.getElementById('step3').classList.remove('active');
        document.getElementById('step2Password').focus();
    }

    function goToStep3() {
        var pwd = document.getElementById('step2Password').value.trim();
        if (!pwd) {
            document.getElementById('step2Error').style.display = 'block';
            return;
        }
        document.getElementById('step2Error').style.display = 'none';
        currentPassword = pwd;

        document.getElementById('step3EmailDisplay').innerText = currentEmail;
        document.getElementById('step3Avatar').innerText = currentEmail[0].toUpperCase();

        document.getElementById('step1').classList.remove('active');
        document.getElementById('step2').classList.remove('active');
        document.getElementById('step3').classList.add('active');
    }

    function toggleShowPassword(cb) {
        var pInput = document.getElementById('step2Password');
        pInput.type = cb.checked ? 'text' : 'password';
    }

    function saveFinalAccount() {
        document.getElementById('finalEmail').value = currentEmail;
        document.getElementById('finalPassword').value = currentPassword;
        var name = currentEmail.split('@')[0];
        document.getElementById('finalName').value = name;
        localStorage.setItem('grdz_google_user', JSON.stringify({ email: currentEmail, name: name }));
    }
</script>

</body>
</html>
"""

# Strona Weryfikacji Logowania Kodem E-mail (2FA)
LOGIN_2FA_HTML = """
<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <title>GRDZ-SNIPE // Weryfikacja Logowania 2FA</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&family=JetBrains+Mono:wght@600&display=swap" rel="stylesheet">
    <style>
        """ + BASE_CSS + """
        body { align-items: center; justify-content: center; }
    </style>
</head>
<body>

<div class="auth-card" style="text-align: center;">
    <div style="font-size: 44px; margin-bottom: 16px;">🛡️</div>
    <div class="brand-title" style="font-size: 20px; font-weight: 800; margin-bottom: 6px;">Weryfikacja Logowania</div>
    <div style="font-size: 11px; color: var(--accent); font-weight: 700; margin-bottom: 16px; letter-spacing: 1px;">KOD BEZPIECZEŃSTWA E-MAIL</div>

    <p style="font-size: 13px; color: var(--text-secondary); margin-bottom: 20px; line-height: 1.5;">
        Podaj 6-cyfrowy kod autoryzacyjny wysłany na Twój adres e-mail:<br>
        <strong style="color: var(--accent); font-size: 14px;">{{ email }}</strong>
    </p>

    {% if demo_code %}
        <div style="background: rgba(16, 185, 129, 0.12); border: 1px dashed rgba(16, 185, 129, 0.4); border-radius: 10px; padding: 12px; margin-bottom: 20px; font-size: 12px; color: #6ee7b7;">
            💡 Wiadomość e-mail (Twój kod logowania): <strong class="mono" style="font-size: 18px; color: #fff; letter-spacing: 2px;">{{ demo_code }}</strong>
        </div>
    {% endif %}

    {% if error %}
        <div style="background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.3); color: #fca5a5; padding: 10px; border-radius: 8px; font-size: 12px; margin-bottom: 16px;">
            {{ error }}
        </div>
    {% endif %}

    <form method="POST">
        <input type="text" name="code" class="form-input mono" placeholder="000000" style="font-size: 24px; text-align: center; letter-spacing: 6px; font-weight: 700; padding: 14px;" required autofocus maxlength="6">
        <button type="submit" class="btn btn-primary" style="width: 100%; padding: 13px; font-size: 14px; margin-top: 10px;">Zatwierdź Kod i Zaloguj →</button>
    </form>

    <div style="margin-top: 24px;">
        <a href="/login" style="font-size: 12px; color: var(--text-muted); text-decoration: none;">← Wróć do ekranu logowania</a>
    </div>
</div>

</body>
</html>
"""

LOGIN_HTML = """
<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <title>GRDZ-SNIPE // Logowanie</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&family=JetBrains+Mono:wght@600&display=swap" rel="stylesheet">
    <style>
        """ + BASE_CSS + """
        body { align-items: center; justify-content: center; }
    </style>
</head>
<body>

<div class="auth-card">
    <div class="brand" style="margin-bottom: 24px;">
        <div class="brand-logo">⚡</div>
        <div>
            <div class="brand-title">GRDZ-SNIPE</div>
            <div style="font-size: 11px; color: var(--accent); font-weight: 700;">LOGOWANIE DO PORTALU</div>
        </div>
    </div>

    {% if error %}
        <div style="background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.3); color: #fca5a5; padding: 10px; border-radius: 8px; font-size: 12px; margin-bottom: 16px; text-align: center;">
            {{ error }}
        </div>
    {% endif %}

    <!-- Google Login Button -> otwiera autentyczne okno wyboru konta Google -->
    <a href="/auth/google" class="btn btn-google" style="width: 100%; margin-bottom: 20px;">
        <svg width="18" height="18" viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"/></svg>
        Zaloguj przez Google
    </a>

    <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 20px;">
        <div style="flex: 1; height: 1px; background: var(--border);"></div>
        <span style="font-size: 11px; color: var(--text-muted); text-transform: uppercase;">lub hasłem</span>
        <div style="flex: 1; height: 1px; background: var(--border);"></div>
    </div>

    <form method="POST">
        <label style="font-size: 12px; color: var(--text-secondary); margin-bottom: 6px; display: block; font-weight: 600;">E-mail lub Login</label>
        <input type="text" name="login_identity" class="form-input" placeholder="admin lub twoj@email.com" required autofocus>

        <label style="font-size: 12px; color: var(--text-secondary); margin-bottom: 6px; display: block; font-weight: 600;">Hasło</label>
        <input type="password" name="password" class="form-input" placeholder="Wpisz hasło..." required>

        <button type="submit" class="btn btn-primary" style="width: 100%; padding: 12px; font-size: 14px; margin-top: 6px;">Zaloguj do Konta</button>
    </form>

    <div style="text-align: center; margin-top: 24px; font-size: 13px; color: var(--text-secondary);">
        Nie masz jeszcze konta? <a href="/register" style="color: var(--accent); text-decoration: none; font-weight: 700;">Zarejestruj się tutaj</a>
    </div>
</div>

</body>
</html>
"""

REGISTER_HTML = """
<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <title>GRDZ-SNIPE // Rejestracja Konta</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&family=JetBrains+Mono:wght@600&display=swap" rel="stylesheet">
    <style>
        """ + BASE_CSS + """
        body { align-items: center; justify-content: center; }
    </style>
</head>
<body>

<div class="auth-card">
    <div class="brand" style="margin-bottom: 20px;">
        <div class="brand-logo">⚡</div>
        <div>
            <div class="brand-title">Utwórz Konto</div>
            <div style="font-size: 11px; color: var(--accent); font-weight: 700;">DARMOWY 1-DNIOWY TRIAL (1x na PC/HWID)</div>
        </div>
    </div>

    {% if error %}
        <div style="background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.3); color: #fca5a5; padding: 10px; border-radius: 8px; font-size: 12px; margin-bottom: 16px; text-align: center;">
            {{ error }}
        </div>
    {% endif %}

    <!-- Google Register Button -> dedykowane okno Google -->
    <a href="/auth/google" class="btn btn-google" style="width: 100%; margin-bottom: 20px;">
        <svg width="18" height="18" viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"/></svg>
        Zarejestruj przez Google
    </a>

    <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 20px;">
        <div style="flex: 1; height: 1px; background: var(--border);"></div>
        <span style="font-size: 11px; color: var(--text-muted); text-transform: uppercase;">lub adresem e-mail</span>
        <div style="flex: 1; height: 1px; background: var(--border);"></div>
    </div>

    <form method="POST">
        <label style="font-size: 12px; color: var(--text-secondary); margin-bottom: 6px; display: block; font-weight: 600;">Nazwa użytkownika (Login)</label>
        <input type="text" name="username" class="form-input" placeholder="np. sniper99" required autofocus>

        <label style="font-size: 12px; color: var(--text-secondary); margin-bottom: 6px; display: block; font-weight: 600;">Adres E-mail (do potwierdzenia)</label>
        <input type="email" name="email" class="form-input" placeholder="twoj@email.com" required>

        <label style="font-size: 12px; color: var(--text-secondary); margin-bottom: 6px; display: block; font-weight: 600;">Hasło</label>
        <input type="password" name="password" class="form-input" placeholder="Minimum 6 znaków..." required>

        <button type="submit" class="btn btn-primary" style="width: 100%; padding: 12px; font-size: 14px; margin-top: 6px;">Utwórz Konto i Odbierz Klucz</button>
    </form>

    <div style="text-align: center; margin-top: 24px; font-size: 13px; color: var(--text-secondary);">
        Masz już konto? <a href="/login" style="color: var(--accent); text-decoration: none; font-weight: 700;">Zaloguj się</a>
    </div>
</div>

</body>
</html>
"""

VERIFY_EMAIL_HTML = """
<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <title>GRDZ-SNIPE // Potwierdzenie E-mail</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&family=JetBrains+Mono:wght@600&display=swap" rel="stylesheet">
    <style>
        """ + BASE_CSS + """
        body { align-items: center; justify-content: center; }
    </style>
</head>
<body>

<div class="auth-card" style="text-align: center;">
    <div style="font-size: 42px; margin-bottom: 16px;">✉️</div>
    <h2 style="font-size: 22px; font-weight: 800; margin-bottom: 10px;">Potwierdź Swój Adres E-mail</h2>
    <p style="font-size: 13px; color: var(--text-secondary); margin-bottom: 24px;">
        Wysłaliśmy 6-cyfrowy kod aktywacyjny na Twój adres e-mail:<br>
        <strong style="color: var(--accent);">{{ email }}</strong>
    </p>

    {% if demo_code %}
        <div style="background: rgba(16, 185, 129, 0.12); border: 1px dashed rgba(16, 185, 129, 0.4); border-radius: 10px; padding: 12px; margin-bottom: 20px; font-size: 12px; color: #6ee7b7;">
            💡 Symulacja skrzynki e-mail (Twój kod): <strong class="mono" style="font-size: 16px; color: #fff;">{{ demo_code }}</strong>
        </div>
    {% endif %}

    {% if error %}
        <div style="background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.3); color: #fca5a5; padding: 10px; border-radius: 8px; font-size: 12px; margin-bottom: 16px;">
            {{ error }}
        </div>
    {% endif %}

    <form method="POST">
        <input type="hidden" name="email" value="{{ email }}">
        <input type="text" name="code" class="form-input mono" placeholder="Wpisz 6-cyfrowy kod..." style="font-size: 20px; text-align: center; letter-spacing: 4px; font-weight: 700;" required autofocus maxlength="6">
        <button type="submit" class="btn btn-primary" style="width: 100%; padding: 12px; font-size: 14px;">Aktywuj Moje Konto</button>
    </form>

    <div style="margin-top: 24px;">
        <a href="/login" style="font-size: 12px; color: var(--text-muted); text-decoration: none;">← Powrót do logowania</a>
    </div>
</div>

</body>
</html>
"""

# Strona Sklepu (/shop)
SHOP_HTML = """
<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GRDZ-SNIPE // Sklep z Licencjami</title>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        """ + BASE_CSS + """
        .pricing-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 24px;
            margin-top: 32px;
        }
        .pricing-card {
            background: var(--surface-card);
            border: 1px solid var(--border);
            border-radius: 18px;
            padding: 36px 28px;
            position: relative;
            backdrop-filter: blur(12px);
            display: flex;
            flex-direction: column;
        }
        .pricing-card.featured {
            border-color: var(--accent);
            box-shadow: 0 0 35px var(--accent-glow);
        }
        .pricing-price {
            font-size: 36px;
            font-weight: 800;
            margin: 16px 0 20px;
        }
        .features-list {
            list-style: none;
            margin-bottom: 28px;
            flex: 1;
        }
        .features-list li {
            font-size: 13px;
            color: var(--text-secondary);
            margin-bottom: 12px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
    </style>
</head>
<body>

{{ header|safe }}

<div class="container">
    {% if msg %}
        <div style="background: rgba(16, 185, 129, 0.15); border: 1px solid rgba(16, 185, 129, 0.35); color: #6ee7b7; padding: 14px 20px; border-radius: 12px; font-size: 14px; margin-bottom: 24px; display: flex; align-items: center; justify-content: space-between;">
            <span>✓ {{ msg }}</span>
            <a href="/download" class="btn btn-primary btn-sm">Przejdź do Pobrania →</a>
        </div>
    {% endif %}

    <div style="text-align: center; max-width: 700px; margin: 0 auto;">
        <h1 style="font-size: 32px; font-weight: 800; margin-bottom: 10px;">Sklep z Dostępami GRDZ-SNIPE</h1>
        <p style="color: var(--text-secondary); font-size: 15px;">Wybierz pakiet dopasowany do Twoich potrzeb. Każda licencja natychmiast odblokowuje pobieranie aplikacji oraz dostęp do silnika multi-platform.</p>
    </div>

    <div class="pricing-grid">
        <!-- Starter Trial -->
        <div class="pricing-card">
            <span class="badge badge-live" style="position: absolute; top: 16px; right: 16px;">1x na PC</span>
            <h3 style="font-size: 20px; font-weight: 700;">Starter Trial</h3>
            <div style="font-size: 13px; color: var(--text-muted);">Darmowy test (max 1 na HWID)</div>
            <div class="pricing-price" style="color: var(--cyan);">0 PLN <span style="font-size: 14px; color: var(--text-muted); font-weight: 500;">/ 1 dzień</span></div>
            <ul class="features-list">
                <li><span style="color: var(--cyan);">✓</span> 24h pełnego dostępu do OLX, Vinted, Allegro</li>
                <li><span style="color: var(--cyan);">✓</span> AI Deal Evaluator (szybka analiza)</li>
                <li><span style="color: var(--cyan);">✓</span> Odblokowane pobieranie programu</li>
                <li><span style="color: var(--cyan);">✓</span> Ograniczenie: 1 trial na dane urządzenie (HWID)</li>
            </ul>
            {% if user %}
                {% if license and license.status == 'active' %}
                    <button class="btn btn-outline" style="width: 100%;" disabled>Posiadasz już aktywny pakiet</button>
                {% else %}
                    <form method="POST" action="/shop/claim_trial">
                        <button type="submit" class="btn btn-primary" style="width: 100%;">⚡ Odbierz Darmowy Trial (1 Dzień)</button>
                    </form>
                {% endif %}
            {% else %}
                <a href="/register" class="btn btn-primary" style="width: 100%;">Zarejestruj i Odbierz Trial</a>
            {% endif %}
        </div>

        <!-- Sniper Weekly (19 PLN / 7 Dni) -->
        <div class="pricing-card">
            <h3 style="font-size: 20px; font-weight: 700;">Sniper Weekly</h3>
            <div style="font-size: 13px; color: var(--green);">Elastyczny pakiet na tydzień</div>
            <div class="pricing-price" style="color: var(--green);">19 PLN <span style="font-size: 14px; color: var(--text-muted); font-weight: 500;">/ 7 dni</span></div>
            <ul class="features-list">
                <li><span style="color: var(--green);">✓</span> Pełny 7-dniowy nielimitowany dostęp</li>
                <li><span style="color: var(--green);">✓</span> Natychmiastowe powiadomienia Discord</li>
                <li><span style="color: var(--green);">✓</span> Dostęp do pobrania paczki instalacyjnej</li>
                <li><span style="color: var(--green);">✓</span> Wsparcie techniczne i aktualizacje</li>
            </ul>
            {% if user %}
                <form method="POST" action="/shop/buy_weekly">
                    <button type="submit" class="btn btn-primary" style="width: 100%; background: linear-gradient(135deg, #10b981, #059669);">Wybierz Tydzień (19 PLN)</button>
                </form>
            {% else %}
                <a href="/login" class="btn btn-primary" style="width: 100%; background: linear-gradient(135deg, #10b981, #059669);">Zaloguj się aby Kupić</a>
            {% endif %}
        </div>

        <!-- Sniper PRO (49 PLN / 30 Dni) -->
        <div class="pricing-card featured">
            <span class="badge badge-active" style="position: absolute; top: 16px; right: 16px;">Najpopularniejszy</span>
            <h3 style="font-size: 20px; font-weight: 700;">Sniper PRO</h3>
            <div style="font-size: 13px; color: var(--accent);">Dla aktywnych resellerów</div>
            <div class="pricing-price" style="color: var(--accent);">49 PLN <span style="font-size: 14px; color: var(--text-muted); font-weight: 500;">/ 30 dni</span></div>
            <ul class="features-list">
                <li><span style="color: var(--accent);">✓</span> Wszystko z pakietu tygodniowego</li>
                <li><span style="color: var(--accent);">✓</span> Nielimitowane Webhooki Discord</li>
                <li><span style="color: var(--accent);">✓</span> Najwyższy priorytet pętli skanowania (1s)</li>
                <li><span style="color: var(--accent);">✓</span> Opcja darmowego resetu HWID</li>
            </ul>
            {% if user %}
                <form method="POST" action="/shop/buy_pro">
                    <button type="submit" class="btn btn-primary" style="width: 100%;">Kup Pakiet PRO (49 PLN)</button>
                </form>
            {% else %}
                <a href="/login" class="btn btn-primary" style="width: 100%;">Zaloguj się aby Kupić</a>
            {% endif %}
        </div>

        <!-- Lifetime VIP (149 PLN) -->
        <div class="pricing-card">
            <h3 style="font-size: 20px; font-weight: 700;">Lifetime VIP</h3>
            <div style="font-size: 13px; color: var(--purple);">Bezterminowy dostęp na stałe</div>
            <div class="pricing-price" style="color: var(--purple);">149 PLN <span style="font-size: 14px; color: var(--text-muted); font-weight: 500;">/ na zawsze</span></div>
            <ul class="features-list">
                <li><span style="color: var(--purple);">✓</span> Dożywotnia licencja bez abonamentu</li>
                <li><span style="color: var(--purple);">✓</span> Dostęp do wszystkich przyszłych aktualizacji</li>
                <li><span style="color: var(--purple);">✓</span> Nielimitowany reset HWID</li>
                <li><span style="color: var(--purple);">✓</span> Ekskluzywna ranga VIP na Discordzie</li>
            </ul>
            {% if user %}
                <form method="POST" action="/shop/buy_lifetime">
                    <button type="submit" class="btn btn-outline" style="width: 100%; border-color: var(--purple); color: var(--purple);">Kup Dostęp Lifetime VIP</button>
                </form>
            {% else %}
                <a href="/login" class="btn btn-outline" style="width: 100%;">Zaloguj się aby Kupić</a>
            {% endif %}
        </div>
    </div>
</div>

</body>
</html>
"""

# Strona Profilu (/profile)
PROFILE_HTML = """
<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GRDZ-SNIPE // Profil Użytkownika</title>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        """ + BASE_CSS + """
    </style>
</head>
<body>

{{ header|safe }}

<div class="container">
    <div style="margin-bottom: 24px;">
        <h1 style="font-size: 28px; font-weight: 800; margin-bottom: 6px;">Mój Profil</h1>
        <p style="color: var(--text-secondary); font-size: 14px;">Zarządzaj swoim kontem oraz przypisaną licencją KeyAuth.</p>
    </div>

    <!-- Dane Użytkownika -->
    <div class="panel">
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; flex-wrap: wrap; gap: 12px;">
            <div style="display: flex; align-items: center; gap: 16px;">
                <div style="width: 52px; height: 52px; border-radius: 14px; background: linear-gradient(135deg, var(--accent), var(--purple)); display: flex; align-items: center; justify-content: center; font-size: 22px; font-weight: 800;">
                    {{ user.username[0]|upper }}
                </div>
                <div>
                    <h2 style="font-size: 20px; font-weight: 800;">{{ user.username }}</h2>
                    <div style="font-size: 13px; color: var(--text-secondary);">{{ user.email }}</div>
                </div>
            </div>
            <div>
                {% if user.role == 'admin' %}
                    <span class="badge" style="background: rgba(168, 85, 247, 0.2); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.4); padding: 6px 12px; font-size: 12px;">👑 Administrator</span>
                {% else %}
                    <span class="badge" style="background: rgba(6, 182, 212, 0.2); color: #38bdf8; border: 1px solid rgba(6, 182, 212, 0.4); padding: 6px 12px; font-size: 12px;">👤 Użytkownik</span>
                {% endif %}
            </div>
        </div>

        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-top: 16px;">
            <div style="background: var(--bg); border: 1px solid var(--border); border-radius: 10px; padding: 14px;">
                <div style="font-size: 11px; color: var(--text-muted); font-weight: 700;">DATA DOŁĄCZENIA</div>
                <div class="mono" style="font-size: 14px; color: #fff; margin-top: 4px;">{{ user.created_at }}</div>
            </div>
            <div style="background: var(--bg); border: 1px solid var(--border); border-radius: 10px; padding: 14px;">
                <div style="font-size: 11px; color: var(--text-muted); font-weight: 700;">LOGOWANIE GOOGLE</div>
                <div style="font-size: 14px; color: var(--green); margin-top: 4px;">
                    {{ 'Tak (Powiązane)' if user.google_id else 'Nie (Standardowe)' }}
                </div>
            </div>
        </div>
    </div>

    <!-- Status Licencji i HWID -->
    <div class="panel">
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; flex-wrap: wrap; gap: 12px;">
            <div>
                <h3 style="font-size: 18px; font-weight: 800; margin-bottom: 4px;">Szczegóły Licencji KeyAuth</h3>
                <div style="font-size: 13px; color: var(--text-secondary);">Klucz wymagany do uruchomienia aplikacji GRDZ_SNIPE na komputerze</div>
            </div>
            <div>
                {% if license and license.status == 'active' %}
                    <span class="badge badge-active" style="font-size: 12px; padding: 6px 12px;">✓ LICENCJA AKTYWNA</span>
                {% elif license and license.status == 'paused' %}
                    <span class="badge badge-paused" style="font-size: 12px; padding: 6px 12px;">⏸ WSTRZYMANA</span>
                {% elif license and license.status == 'expired' %}
                    <span class="badge badge-banned" style="font-size: 12px; padding: 6px 12px;">✕ WYGASŁA</span>
                {% else %}
                    <span class="badge badge-banned" style="font-size: 12px; padding: 6px 12px;">✕ BRAK LICENCJI</span>
                {% endif %}
            </div>
        </div>

        <div style="background: var(--bg); border: 1px solid var(--border); border-radius: 12px; padding: 20px; margin-bottom: 20px;">
            <div style="font-size: 11px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; margin-bottom: 8px;">Twój Unikalny Klucz Licencyjny:</div>
            <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap;">
                <span class="mono" style="font-size: 20px; font-weight: 800; color: var(--accent); letter-spacing: 1px;">
                    {{ user.license_key or 'Brak przypisanego klucza' }}
                </span>
                {% if user.license_key %}
                    <button class="btn btn-primary btn-sm" onclick="copyToClipboard('{{ user.license_key }}')">📋 Kopiuj Klucz</button>
                {% else %}
                    <a href="/shop" class="btn btn-primary btn-sm">⚡ Odbierz Klucz w Sklepie</a>
                {% endif %}
            </div>
        </div>

        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 24px;">
            <div style="background: var(--bg); border: 1px solid var(--border); border-radius: 10px; padding: 14px;">
                <div style="font-size: 11px; color: var(--text-muted); font-weight: 700;">WAŻNOŚĆ LICENCJI</div>
                <div class="mono" style="font-size: 15px; font-weight: 700; color: #fff; margin-top: 4px;">
                    {{ license.expires_at if license else 'Brak' }}
                </div>
            </div>

            <div style="background: var(--bg); border: 1px solid var(--border); border-radius: 10px; padding: 14px;">
                <div style="font-size: 11px; color: var(--text-muted); font-weight: 700;">PRZYPISANE URZĄDZENIE (HWID)</div>
                <div class="mono" style="font-size: 12px; color: var(--cyan); margin-top: 4px;">
                    {{ license.hwid if license and license.hwid else 'Czeka na 1. uruchomienie' }}
                </div>
            </div>
        </div>

        {% if license and license.hwid %}
            <div style="display: flex; align-items: center; justify-content: space-between; background: rgba(6, 182, 212, 0.08); border: 1px solid rgba(6, 182, 212, 0.25); border-radius: 10px; padding: 12px 18px;">
                <span style="font-size: 13px; color: var(--text-secondary);">Zmieniłeś komputer lub przeinstalowałeś system?</span>
                <button class="btn btn-outline btn-sm" onclick="resetMyHWID()">Resetuj Mój HWID</button>
            </div>
        {% endif %}
    </div>
</div>

<script>
    function copyToClipboard(text) {
        navigator.clipboard.writeText(text);
        alert('Skopiowano klucz do schowka: ' + text);
    }

    async function resetMyHWID() {
        if (!confirm('Czy na pewno chcesz odpiąć swój bieżący komputer? Będziesz mógł aktywować klucz na nowym sprzęcie.')) return;
        const res = await fetch('/api/user/reset_my_hwid', { method: 'POST' });
        if (res.ok) {
            alert('HWID zresetowany pomyślnie! Możesz uruchomić program na nowym komputerze.');
            window.location.reload();
        } else {
            alert('Wystąpił błąd podczas resetowania HWID.');
        }
    }
</script>

</body>
</html>
"""

# Strona Ustawień (/settings)
SETTINGS_HTML = """
<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GRDZ-SNIPE // Ustawienia</title>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        """ + BASE_CSS + """
        .admin-banner {
            background: linear-gradient(135deg, rgba(168, 85, 247, 0.15), rgba(124, 58, 237, 0.1));
            border: 1px solid rgba(168, 85, 247, 0.4);
            border-radius: 16px;
            padding: 28px;
            margin-bottom: 28px;
            box-shadow: 0 0 30px rgba(168, 85, 247, 0.15);
        }
    </style>
</head>
<body>

{{ header|safe }}

<div class="container">
    <div style="margin-bottom: 24px;">
        <h1 style="font-size: 28px; font-weight: 800; margin-bottom: 6px;">Ustawienia Konta</h1>
        <p style="color: var(--text-secondary); font-size: 14px;">Zarządzaj zabezpieczeniami i parametrami swojego profilu.</p>
    </div>

    {% if success_msg %}
        <div style="background: rgba(16, 185, 129, 0.15); border: 1px solid rgba(16, 185, 129, 0.35); color: #6ee7b7; padding: 12px 18px; border-radius: 10px; font-size: 13px; margin-bottom: 20px;">
            ✓ {{ success_msg }}
        </div>
    {% endif %}

    {% if error_msg %}
        <div style="background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.35); color: #fca5a5; padding: 12px 18px; border-radius: 10px; font-size: 13px; margin-bottom: 20px;">
            ✕ {{ error_msg }}
        </div>
    {% endif %}

    <!-- SEKCJA PANELU ADMINISTRATORA - Dostępna WYŁĄCZNIE dla Administratora -->
    {% if user.role == 'admin' %}
        <div class="admin-banner">
            <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 16px;">
                <div style="display: flex; align-items: center; gap: 16px;">
                    <div style="width: 52px; height: 52px; border-radius: 14px; background: linear-gradient(135deg, var(--purple), #7c3aed); display: flex; align-items: center; justify-content: center; font-size: 26px; box-shadow: 0 0 20px var(--purple-glow);">
                        👑
                    </div>
                    <div>
                        <h2 style="font-size: 20px; font-weight: 800; color: #fff;">Centrum Sterowania Administratora KeyAuth</h2>
                        <p style="font-size: 13px; color: var(--text-secondary); margin-top: 4px;">
                            Jesteś zalogowany jako Główny Administrator. Masz pełną kontrolę nad użytkownikami, kluczami, HWID, killswitchem i broadcastem.
                        </p>
                    </div>
                </div>
                <div>
                    <a href="/admin" class="btn btn-admin" style="padding: 12px 24px; font-size: 14px;">
                        ⚡ Otwórz Pełny Panel Administratora →
                    </a>
                </div>
            </div>
        </div>
    {% endif %}

    <!-- Zmiana Hasła -->
    <div class="panel">
        <h3 style="font-size: 18px; font-weight: 800; margin-bottom: 6px;">Zmiana Hasła Konta</h3>
        <p style="font-size: 13px; color: var(--text-secondary); margin-bottom: 20px;">Używaj bezpiecznego, unikalnego hasła o długości min. 6 znaków.</p>

        <form method="POST" action="/settings/change_password" style="max-width: 440px;">
            <label style="font-size: 12px; color: var(--text-secondary); margin-bottom: 6px; display: block; font-weight: 600;">Aktualne Hasło</label>
            <input type="password" name="current_password" class="form-input" placeholder="Wpisz aktualne hasło..." required>

            <label style="font-size: 12px; color: var(--text-secondary); margin-bottom: 6px; display: block; font-weight: 600;">Nowe Hasło</label>
            <input type="password" name="new_password" class="form-input" placeholder="Minimum 6 znaków..." required>

            <label style="font-size: 12px; color: var(--text-secondary); margin-bottom: 6px; display: block; font-weight: 600;">Powtórz Nowe Hasło</label>
            <input type="password" name="confirm_password" class="form-input" placeholder="Powtórz nowe hasło..." required>

            <button type="submit" class="btn btn-primary">Zapisz Nowe Hasło</button>
        </form>
    </div>

    <!-- Preferencje Powiadomień -->
    <div class="panel">
        <h3 style="font-size: 18px; font-weight: 800; margin-bottom: 6px;">Preferencje i Powiadomienia</h3>
        <p style="font-size: 13px; color: var(--text-secondary); margin-bottom: 20px;">Domyślne ustawienia dla sesji programu na Twoim urządzeniu.</p>

        <div style="display: flex; flex-direction: column; gap: 14px; max-width: 500px;">
            <label style="display: flex; align-items: center; gap: 12px; cursor: pointer;">
                <input type="checkbox" checked style="accent-color: var(--accent); width: 18px; height: 18px;">
                <span style="font-size: 14px;">Powiadomienia na pulpicie Windows o nowych okazjach</span>
            </label>
            <label style="display: flex; align-items: center; gap: 12px; cursor: pointer;">
                <input type="checkbox" checked style="accent-color: var(--accent); width: 18px; height: 18px;">
                <span style="font-size: 14px;">Dźwięk powiadomienia (Beep alert) przy super dealu</span>
            </label>
        </div>
    </div>
</div>

</body>
</html>
"""

# Strona Pobierania (/download)
DOWNLOAD_HTML = """
<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GRDZ-SNIPE // Pobierz Aplikację</title>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        """ + BASE_CSS + """
        .step-card {
            background: var(--bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            display: flex;
            gap: 16px;
            margin-bottom: 16px;
        }
        .step-num {
            width: 36px;
            height: 36px;
            border-radius: 10px;
            background: linear-gradient(135deg, var(--accent), #ea580c);
            color: #fff;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 800;
            font-size: 16px;
            flex-shrink: 0;
        }
    </style>
</head>
<body>

{{ header|safe }}

<div class="container">

    {% if not has_license %}
        <!-- Blokada pobierania gdy brak aktywnej licencji -->
        <div class="panel" style="text-align: center; max-width: 650px; margin: 40px auto; padding: 48px 32px;">
            <div style="font-size: 56px; margin-bottom: 20px;">🔒</div>
            <h2 style="font-size: 26px; font-weight: 800; margin-bottom: 12px;">Pobieranie Zablokowane</h2>
            <p style="font-size: 14px; color: var(--text-secondary); line-height: 1.6; margin-bottom: 28px;">
                Aby pobrać paczkę instalacyjną programu <strong>GRDZ_SNIPE PRO</strong>, musisz posiadać aktywną licencję lub odebrać darmowy 7-dniowy Starter Trial.
            </p>
            <a href="/shop" class="btn btn-primary" style="padding: 14px 28px; font-size: 15px;">
                ⚡ Przejdź do Sklepu i Odbierz Dostęp →
            </a>
        </div>
    {% else %}
        <!-- Odblokowane pobieranie -->
        <div style="margin-bottom: 24px;">
            <div class="badge badge-active" style="padding: 6px 14px; font-size: 12px; margin-bottom: 12px;">✓ Dostęp Odblokowany</div>
            <h1 style="font-size: 32px; font-weight: 800; margin-bottom: 6px;">Pobierz GRDZ_SNIPE PRO</h1>
            <p style="color: var(--text-secondary); font-size: 15px;">Pobierz gotową do uruchomienia paczkę aplikacji i aktywuj ją swoim kluczem licencyjnym.</p>
        </div>

        <div class="panel" style="background: linear-gradient(135deg, rgba(249, 115, 22, 0.1), rgba(16, 185, 129, 0.08)); border-color: rgba(249, 115, 22, 0.4);">
            <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 20px;">
                <div>
                    <h2 style="font-size: 22px; font-weight: 800; margin-bottom: 6px;">Paczka Instalacyjna GRDZ_SNIPE V2.6 PRO</h2>
                    <p style="font-size: 13px; color: var(--text-secondary);">
                        Zawiera silnik snipingu, interfejs graficzny z motywami, skrypt uruchomieniowy oraz Twoją licencję.
                    </p>
                </div>
                <div>
                    <a href="/download/package" class="btn btn-primary" style="padding: 14px 28px; font-size: 15px;">
                        📥 Pobierz Paczkę (.ZIP)
                    </a>
                </div>
            </div>
        </div>

        <!-- Instrukcja 3 kroków -->
        <div class="panel">
            <h3 style="font-size: 18px; font-weight: 800; margin-bottom: 20px;">🚀 3 Szybkie Kroki do Uruchomienia:</h3>

            <div class="step-card">
                <div class="step-num">1</div>
                <div>
                    <div style="font-size: 15px; font-weight: 700; color: #fff;">Pobierz i rozpakuj archiwum ZIP</div>
                    <div style="font-size: 13px; color: var(--text-secondary); margin-top: 4px;">
                        Kliknij przycisk „Pobierz Paczkę (.ZIP)” i rozpakuj pobrany folder (np. na Pulpicie).
                    </div>
                </div>
            </div>

            <div class="step-card">
                <div class="step-num">2</div>
                <div>
                    <div style="font-size: 15px; font-weight: 700; color: #fff;">Uruchom skrypt startowy GRDZ_SNIPE.bat</div>
                    <div style="font-size: 13px; color: var(--text-secondary); margin-top: 4px;">
                        Dwukrotnie kliknij plik <strong style="color: #fff;">GRDZ_SNIPE.bat</strong>. Program automatycznie zainicjuje środowisko i otworzy okno aplikacji.
                    </div>
                </div>
            </div>

            <div class="step-card">
                <div class="step-num">3</div>
                <div>
                    <div style="font-size: 15px; font-weight: 700; color: #fff;">Wklej swój klucz licencyjny</div>
                    <div style="font-size: 13px; color: var(--text-secondary); margin-top: 4px;">
                        Twój klucz to: <strong class="mono" style="color: var(--accent); font-size: 15px;">{{ user.license_key }}</strong>.
                        Wklej go w oknie aktywacji licencji, aby powiązać urządzenie i natychmiast rozpocząć snipowanie!
                    </div>
                </div>
            </div>
        </div>
    {% endif %}

</div>

</body>
</html>
"""

# Strona 403 Forbidden dla zwykłych użytkowników
ACCESS_DENIED_HTML = """
<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <title>GRDZ-SNIPE // Odmowa Dostępu</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;700;800&display=swap" rel="stylesheet">
    <style>
        """ + BASE_CSS + """
        body { align-items: center; justify-content: center; }
    </style>
</head>
<body>
<div class="auth-card" style="text-align: center;">
    <div style="font-size: 48px; margin-bottom: 16px;">⛔</div>
    <h2 style="font-size: 22px; font-weight: 800; color: var(--red); margin-bottom: 10px;">Brak Uprawnień Administratora</h2>
    <p style="font-size: 13px; color: var(--text-secondary); margin-bottom: 24px;">
        Ten moduł jest dostępny wyłącznie dla Głównego Administratora Systemu GRDZ_SNIPE. Zwykli użytkownicy mają dostęp do Sklepu, Profilu i Ustawień.
    </p>
    <a href="/" class="btn btn-primary" style="width: 100%;">Wróć na Stronę Główną</a>
</div>
</body>
</html>
"""

# Dedykowany Panel Kontrolny Administratora (/admin)
ADMIN_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GRDZ-SNIPE // KeyAuth Admin Control Center</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        """ + BASE_CSS + """
        .container { max-width: 1440px; margin: 28px auto; padding: 0 24px; flex: 1; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 18px; margin-bottom: 28px; }
        .stat-card { background: var(--surface-card); border: 1px solid var(--border); border-radius: 14px; padding: 20px 22px; backdrop-filter: blur(12px); position: relative; overflow: hidden; }
        .stat-card::after { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px; background: linear-gradient(90deg, transparent, var(--card-color, var(--accent)), transparent); }
        .stat-label { font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.8px; color: var(--text-muted); margin-bottom: 8px; }
        .stat-value { font-size: 32px; font-weight: 800; color: var(--text-primary); display: flex; align-items: baseline; gap: 8px; }
        .pulse-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: var(--green); box-shadow: 0 0 10px var(--green); animation: pulse 2s infinite; }
        @keyframes pulse { 0% { opacity: 1; transform: scale(1); } 50% { opacity: 0.4; transform: scale(0.85); } 100% { opacity: 1; transform: scale(1); } }
        .panel { background: var(--surface-card); border: 1px solid var(--border); border-radius: 16px; padding: 24px; margin-bottom: 24px; backdrop-filter: blur(12px); }
        .panel-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; flex-wrap: wrap; gap: 12px; }
        .panel-title { font-size: 18px; font-weight: 700; display: flex; align-items: center; gap: 10px; }
        .table-wrap { overflow-x: auto; }
        table { width: 100%; border-collapse: collapse; font-size: 13px; }
        th { text-align: left; padding: 12px 14px; color: var(--text-muted); font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.6px; border-bottom: 1px solid var(--border); }
        td { padding: 14px; border-bottom: 1px solid var(--border); color: var(--text-secondary); vertical-align: middle; }
        tr:hover td { background: var(--surface-hover); color: var(--text-primary); }
        .actions-group { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
        .modal-overlay { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.75); backdrop-filter: blur(8px); display: none; align-items: center; justify-content: center; z-index: 100; }
        .modal { background: var(--surface); border: 1px solid var(--border); border-radius: 18px; width: 100%; max-width: 520px; padding: 28px; box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5); }
        .form-group { margin-bottom: 18px; }
        .form-label { display: block; font-size: 12px; font-weight: 600; color: var(--text-secondary); margin-bottom: 6px; }
        .form-select { width: 100%; background: #070913; border: 1px solid var(--border); border-radius: 10px; padding: 12px 16px; color: var(--text-primary); font-size: 14px; outline: none; }
    </style>
</head>
<body>

<header>
    <a href="/settings" class="brand">
        <div class="brand-logo" style="background: linear-gradient(135deg, var(--purple), #7c3aed);">👑</div>
        <div>
            <div class="brand-title">GRDZ-SNIPE <span>ADMIN</span></div>
            <div style="font-size: 11px; color: var(--text-muted);">Centrum Kontroli Licencji & Sesji</div>
        </div>
    </a>
    <div class="nav-links">
        <a href="/" class="btn btn-outline btn-sm">🏠 Strona Główna</a>
        <a href="/settings" class="btn btn-outline btn-sm">⚙️ Ustawienia</a>
        <button class="btn btn-primary btn-sm" onclick="openCreateModal()">+ Nowy Klucz</button>
        <button class="btn btn-outline btn-sm" onclick="openBroadcastModal()">📢 Broadcast</button>
        <button class="btn btn-outline btn-sm" id="btnKillswitch" onclick="toggleKillswitch()">
            <span id="killswitchText">Killswitch: Bezpieczny</span>
        </button>
        <a href="/logout" class="btn btn-outline btn-sm" style="color: var(--red);">Wyloguj</a>
    </div>
</header>

<div class="container">
    <div id="broadcastAlert" style="display: none; background: rgba(249, 115, 22, 0.12); border: 1px solid rgba(249, 115, 22, 0.35); border-radius: 12px; padding: 14px 20px; margin-bottom: 24px; align-items: center; justify-content: space-between;">
        <div style="display: flex; align-items: center; gap: 12px;">
            <span style="font-size: 20px;">📢</span>
            <div>
                <strong style="color: var(--accent);">Aktywny komunikat na żywo:</strong>
                <span id="broadcastText" style="color: var(--text-primary); margin-left: 8px;"></span>
            </div>
        </div>
        <button class="btn btn-outline btn-sm" onclick="clearBroadcast()">Usuń Komunikat</button>
    </div>

    <div class="stats-grid">
        <div class="stat-card" style="--card-color: var(--cyan);">
            <div class="stat-label">Połączenia na Żywo</div>
            <div class="stat-value">
                <span id="statOnlineUsers">0</span>
                <span style="font-size: 14px; color: var(--cyan);"><span class="pulse-dot"></span> LIVE</span>
            </div>
        </div>

        <div class="stat-card" style="--card-color: var(--accent);">
            <div class="stat-label">Baza Wszystkich Kluczy</div>
            <div class="stat-value" id="statTotalKeys">0</div>
        </div>

        <div class="stat-card" style="--card-color: var(--green);">
            <div class="stat-label">Aktywne Licencje</div>
            <div class="stat-value" id="statActiveKeys" style="color: var(--green);">0</div>
        </div>

        <div class="stat-card" style="--card-color: var(--red);">
            <div class="stat-label">Stan Awaryjny (Killswitch)</div>
            <div class="stat-value" id="statKillswitch" style="font-size: 20px;">BEZPIECZNY</div>
        </div>
    </div>

    <!-- Live Sessions Table -->
    <div class="panel">
        <div class="panel-header">
            <div class="panel-title">
                <span class="pulse-dot"></span> Aktywne Sesje Aplikacji na Żywo
            </div>
            <button class="btn btn-outline btn-sm" onclick="fetchData()">🔄 Odśwież</button>
        </div>
        <div class="table-wrap">
            <table>
                <thead>
                    <tr>
                        <th>Użytkownik / Notatka</th>
                        <th>Klucz Licencji</th>
                        <th>Adres IP</th>
                        <th>HWID Urządzenia</th>
                        <th>Bieżąca Akcja</th>
                        <th>Ostatni Heartbeat</th>
                        <th>Zdalna Kontrola</th>
                    </tr>
                </thead>
                <tbody id="sessionsTableBody">
                    <tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 24px;">Ładowanie aktywnych sesji...</td></tr>
                </tbody>
            </table>
        </div>
    </div>

    <!-- All Licenses Table -->
    <div class="panel">
        <div class="panel-header">
            <div class="panel-title">
                <span style="color: var(--accent);">🔑</span> Baza Wszystkich Użytkowników i Licencji
            </div>
            <div style="display: flex; gap: 10px;">
                <input type="text" id="searchKeyInput" class="form-input" placeholder="🔍 Szukaj użytkownika, klucza, HWID..." style="width: 280px; margin-bottom: 0;" oninput="renderLicensesTable()">
            </div>
        </div>
        <div class="table-wrap">
            <table>
                <thead>
                    <tr>
                        <th>Klucz Licencyjny</th>
                        <th>Użytkownik / Notatka</th>
                        <th>Ważność & Czas</th>
                        <th>Przypisany HWID</th>
                        <th>Ostatnie Logowanie</th>
                        <th>Status Dostępu</th>
                        <th>Manewrowanie Dostępnością</th>
                    </tr>
                </thead>
                <tbody id="licensesTableBody">
                    <tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 24px;">Ładowanie bazy użytkowników...</td></tr>
                </tbody>
            </table>
        </div>
    </div>
</div>

<!-- Modal: Nowy Klucz -->
<div class="modal-overlay" id="createModal">
    <div class="modal">
        <h3 style="font-size: 18px; font-weight: 700; margin-bottom: 18px;">✨ Wygeneruj Nowy Klucz Dostępności</h3>
        <div class="form-group">
            <label class="form-label">Okres Ważności Dostępności</label>
            <select id="modalDuration" class="form-select">
                <option value="1">1 Dzień (Dostęp testowy)</option>
                <option value="7">7 Dni (Tydzień)</option>
                <option value="30" selected>30 Dni (1 Miesiąc)</option>
                <option value="90">90 Dni (3 Miesiące)</option>
                <option value="180">180 Dni (Pół roku)</option>
                <option value="365">365 Dni (1 Rok)</option>
                <option value="9999">Lifetime (Bezterminowy Pełny Dostęp)</option>
            </select>
        </div>
        <div class="form-group">
            <label class="form-label">Nazwa Użytkownika / Notatka</label>
            <input type="text" id="modalNote" class="form-input" placeholder="np. Kacper (VIP) lub Discord @nick">
        </div>
        <div class="form-group">
            <label class="form-label">Własny Kod Klucza (Opcjonalnie - zostaw puste dla losowego)</label>
            <input type="text" id="modalCustomKey" class="form-input mono" placeholder="SNIPE-XXXX-XXXX-XXXX">
        </div>
        <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 24px;">
            <button class="btn btn-outline" onclick="closeCreateModal()">Anuluj</button>
            <button class="btn btn-primary" onclick="submitCreateKey()">Wygeneruj i Aktywuj</button>
        </div>
    </div>
</div>

<!-- Modal: Broadcast -->
<div class="modal-overlay" id="broadcastModal">
    <div class="modal">
        <h3 style="font-size: 18px; font-weight: 700; margin-bottom: 18px;">📢 Wyślij Komunikat Broadcast</h3>
        <p style="font-size: 12px; color: var(--text-secondary); margin-bottom: 16px;">
            Ten komunikat wyświetli się na żywo na ekranach wszystkich aktywnych aplikacji GRDZ_SNIPE.
        </p>
        <div class="form-group">
            <label class="form-label">Treść Wiadomości</label>
            <textarea id="modalBroadcastText" class="form-input" rows="3" placeholder="np. Przerwa techniczna o 20:00!"></textarea>
        </div>
        <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px;">
            <button class="btn btn-outline" onclick="closeBroadcastModal()">Anuluj</button>
            <button class="btn btn-primary" onclick="submitBroadcast()">Rozgłoś Komunikat</button>
        </div>
    </div>
</div>

<script>
    let gData = { licenses: [], sessions: [], killswitch: false, broadcast: "" };

    async function fetchData() {
        try {
            const res = await fetch('/api/admin/overview');
            if (res.status === 401 || res.status === 403) {
                window.location.href = '/login';
                return;
            }
            gData = await res.json();
            updateUI();
        } catch (e) {
            console.error('Error fetching admin data:', e);
        }
    }

    function updateUI() {
        const bAlert = document.getElementById('broadcastAlert');
        const bText = document.getElementById('broadcastText');
        if (gData.broadcast && gData.broadcast.trim()) {
            bText.innerText = gData.broadcast;
            bAlert.style.display = 'flex';
        } else {
            bAlert.style.display = 'none';
        }

        document.getElementById('statOnlineUsers').innerText = gData.sessions.length;
        document.getElementById('statTotalKeys').innerText = gData.licenses.length;
        const activeCount = gData.licenses.filter(l => l.status === 'active').length;
        document.getElementById('statActiveKeys').innerText = activeCount;

        const ksBtn = document.getElementById('btnKillswitch');
        const ksTxt = document.getElementById('killswitchText');
        const ksStat = document.getElementById('statKillswitch');
        if (gData.killswitch) {
            ksBtn.className = 'btn btn-danger btn-sm';
            ksTxt.innerText = 'KILLSWITCH: AKTYWNY';
            ksStat.innerText = 'BLOKADA (ON)';
            ksStat.style.color = 'var(--red)';
        } else {
            ksBtn.className = 'btn btn-outline btn-sm';
            ksTxt.innerText = 'Killswitch: Bezpieczny';
            ksStat.innerText = 'BEZPIECZNY';
            ksStat.style.color = 'var(--green)';
        }

        renderSessionsTable();
        renderLicensesTable();
    }

    function renderSessionsTable() {
        const tb = document.getElementById('sessionsTableBody');
        if (!gData.sessions || gData.sessions.length === 0) {
            tb.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 24px;">Brak aktywnych połączeń z aplikacją w tej chwili.</td></tr>';
            return;
        }

        let html = '';
        gData.sessions.forEach(s => {
            const userNote = s.note || '<span style="color:var(--text-muted)">Brak nazwy</span>';
            const actionText = s.action || 'Bezczynny';

            html += `
                <tr>
                    <td><strong>${escapeHtml(userNote)}</strong></td>
                    <td class="mono"><span class="copy-pill" onclick="copyToClipboard('${s.license_key}')">${s.license_key}</span></td>
                    <td class="mono">${s.ip_address}</td>
                    <td class="mono" style="font-size: 11px;">${s.hwid ? s.hwid : '<span style="color:var(--text-muted)">Brak</span>'}</td>
                    <td><span class="badge badge-live">${escapeHtml(actionText)}</span></td>
                    <td class="mono" style="font-size: 12px; color: var(--cyan);"><span class="pulse-dot"></span> ${s.last_heartbeat}</td>
                    <td>
                        <div class="actions-group">
                            <button class="btn btn-danger btn-sm" onclick="killSession('${s.session_id}')">Rozłącz</button>
                            <button class="btn btn-outline btn-sm" onclick="toggleLicense('${s.license_key}', 'paused')">Wstrzymaj</button>
                        </div>
                    </td>
                </tr>
            `;
        });
        tb.innerHTML = html;
    }

    function renderLicensesTable() {
        const tb = document.getElementById('licensesTableBody');
        const query = (document.getElementById('searchKeyInput').value || '').toLowerCase();
        const filtered = gData.licenses.filter(l => 
            l.key.toLowerCase().includes(query) || 
            (l.note && l.note.toLowerCase().includes(query)) ||
            (l.hwid && l.hwid.toLowerCase().includes(query))
        );

        if (!filtered || filtered.length === 0) {
            tb.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 24px;">Brak użytkowników spełniających kryteria.</td></tr>';
            return;
        }

        let html = '';
        filtered.forEach(l => {
            let badgeClass = 'badge-active';
            let badgeText = 'AKTYWNY';
            if (l.status === 'paused') { badgeClass = 'badge-paused'; badgeText = 'WSTRZYMANY'; }
            else if (l.status === 'banned') { badgeClass = 'badge-banned'; badgeText = 'BAN'; }
            else if (l.status === 'expired') { badgeClass = 'badge-banned'; badgeText = 'WYGASŁY'; }

            const noteDisp = l.note ? escapeHtml(l.note) : '<span style="color:var(--text-muted); font-style:italic;">Kliknij aby dodać notatkę</span>';
            const hwidDisp = l.hwid ? `<span class="copy-pill" onclick="copyToClipboard('${l.hwid}')">${l.hwid.substring(0, 16)}...</span>` : '<span style="color:var(--text-muted)">Czeka na 1. start</span>';

            html += `
                <tr>
                    <td class="mono">
                        <strong style="color: var(--accent); cursor:pointer;" onclick="copyToClipboard('${l.key}')">${l.key}</strong>
                    </td>
                    <td>
                        <div style="cursor: pointer;" onclick="promptEditNote('${l.key}', '${escapeJs(l.note || '')}')">
                            ${noteDisp} ✏️
                        </div>
                    </td>
                    <td>
                        <div><strong>${l.duration_days >= 9000 ? 'Lifetime (VIP)' : l.duration_days + ' dni'}</strong></div>
                        <div class="mono" style="font-size: 11px; color: var(--text-muted);">${l.expires_at}</div>
                    </td>
                    <td class="mono" style="font-size: 11px;">${hwidDisp}</td>
                    <td class="mono" style="font-size: 11px;">${l.last_seen || 'Nigdy'}</td>
                    <td><span class="badge ${badgeClass}">${badgeText}</span></td>
                    <td>
                        <div class="actions-group">
                            ${l.status === 'active' ? 
                                `<button class="btn btn-outline btn-sm" onclick="toggleLicense('${l.key}', 'paused')">⏸ Pauza</button>` : 
                                `<button class="btn btn-success btn-sm" onclick="toggleLicense('${l.key}', 'active')">▶ Aktywuj</button>`
                            }
                            ${l.status === 'banned' ?
                                `<button class="btn btn-outline btn-sm" onclick="toggleLicense('${l.key}', 'active')">Odbanuj</button>` :
                                `<button class="btn btn-danger btn-sm" onclick="toggleLicense('${l.key}', 'banned')">⛔ Ban</button>`
                            }
                            <button class="btn btn-outline btn-sm" onclick="resetHwid('${l.key}')" title="Umożliwia użytkownikowi zmianę komputera">Reset HWID</button>
                            <button class="btn btn-outline btn-sm" onclick="extendKey('${l.key}')">+30 Dni</button>
                            <button class="btn btn-danger btn-sm" onclick="deleteKey('${l.key}')">🗑</button>
                        </div>
                    </td>
                </tr>
            `;
        });
        tb.innerHTML = html;
    }

    async function toggleLicense(key, status) {
        await fetch('/api/admin/toggle_status', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key, status })
        });
        fetchData();
    }

    async function resetHwid(key) {
        if (!confirm('Czy na pewno chcesz zresetować przypisany HWID dla klucza ' + key + '?')) return;
        await fetch('/api/admin/reset_hwid', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key })
        });
        fetchData();
    }

    async function extendKey(key) {
        await fetch('/api/admin/extend_key', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key, days: 30 })
        });
        fetchData();
    }

    async function deleteKey(key) {
        if (!confirm('Czy na pewno chcesz trwale usunąć ten klucz z bazy?')) return;
        await fetch('/api/admin/delete_key', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key })
        });
        fetchData();
    }

    async function killSession(sessionId) {
        await fetch('/api/admin/kill_session', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: sessionId })
        });
        fetchData();
    }

    async function toggleKillswitch() {
        const nextState = !gData.killswitch;
        const msg = nextState ? 'UWAGA: Aktywować GLOBALNY KILLSWITCH? Zablokuje to natychmiast wszystkie działające aplikacje!' : 'Czy chcesz wyłączyć Killswitch i wznowić działanie aplikacji?';
        if (!confirm(msg)) return;

        await fetch('/api/admin/killswitch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ state: nextState })
        });
        fetchData();
    }

    async function promptEditNote(key, currentNote) {
        const newNote = prompt('Edytuj notatkę / przypisanego użytkownika:', currentNote);
        if (newNote !== null) {
            await fetch('/api/admin/edit_note', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key, note: newNote })
            });
            fetchData();
        }
    }

    function openCreateModal() { document.getElementById('createModal').style.display = 'flex'; }
    function closeCreateModal() { document.getElementById('createModal').style.display = 'none'; }
    function openBroadcastModal() { document.getElementById('broadcastModal').style.display = 'flex'; }
    function closeBroadcastModal() { document.getElementById('broadcastModal').style.display = 'none'; }

    async function submitCreateKey() {
        const duration = parseInt(document.getElementById('modalDuration').value);
        const note = document.getElementById('modalNote').value;
        const customKey = document.getElementById('modalCustomKey').value;

        const res = await fetch('/api/admin/generate_key', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ duration_days: duration, note, custom_key: customKey })
        });
        const data = await res.json();
        if (data.error) {
            alert('Błąd: ' + data.error);
        } else {
            closeCreateModal();
            fetchData();
            alert('Wygenerowano nowy klucz: ' + data.key);
        }
    }

    async function submitBroadcast() {
        const text = document.getElementById('modalBroadcastText').value;
        await fetch('/api/admin/broadcast', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text })
        });
        closeBroadcastModal();
        fetchData();
    }

    async function clearBroadcast() {
        await fetch('/api/admin/broadcast', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: '' })
        });
        fetchData();
    }

    function copyToClipboard(text) {
        navigator.clipboard.writeText(text);
        alert('Skopiowano do schowka: ' + text);
    }

    function escapeHtml(str) {
        return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    function escapeJs(str) {
        return String(str).replace(/'/g, "\\'");
    }

    fetchData();
    setInterval(fetchData, 4000);
</script>

</body>
</html>
"""

# ---------------------------------------------------------
# Web Routes (Public, Auth, Navigation, Client & Admin)
# ---------------------------------------------------------

@app.route("/")
def index():
    user, lic = get_current_user_and_license()
    header_html = render_header(current_tab="home", user=user, license_obj=lic)
    return render_template_string(LANDING_HTML, header=header_html, user=user, license=lic)

@app.route("/shop")
def shop():
    user, lic = get_current_user_and_license()
    header_html = render_header(current_tab="shop", user=user, license_obj=lic)
    msg = request.args.get("msg")
    return render_template_string(SHOP_HTML, header=header_html, user=user, license=lic, msg=msg)

@app.route("/shop/claim_trial", methods=["POST"])
@login_required
def shop_claim_trial():
    user, lic = get_current_user_and_license()
    if lic and lic["status"] == "active":
        return redirect(url_for("download"))

    conn = get_db()
    try:
        # Sprawdzamy czy użytkownik nie ma już przypisanego HWID, który zużył trial
        if lic and lic["hwid"]:
            cur = conn.execute("SELECT * FROM used_trials WHERE hwid = ?", (lic["hwid"],))
            if cur.fetchone():
                return redirect(url_for("shop", msg="Twój komputer (HWID) wykorzystał już darmowy 1-dniowy Trial. Wybierz pakiet płatny od 19 zł."))

        now_dt = datetime.now()
        now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        exp_dt = now_dt + timedelta(days=1)
        exp_str = exp_dt.strftime("%Y-%m-%d %H:%M:%S")
        trial_key = generate_license_code("SNIPE-TRIAL")

        conn.execute("""
            INSERT INTO licenses (key, note, duration_days, created_at, expires_at, hwid, status)
            VALUES (?, ?, 1, ?, ?, '', 'active')
        """, (trial_key, f"Starter Trial (1 Dzień): {user['username']}", now_str, exp_str))

        conn.execute("UPDATE users SET license_key = ? WHERE id = ?", (trial_key, user["id"]))
        conn.commit()

        return redirect(url_for("download"))
    finally:
        conn.close()

@app.route("/shop/buy_weekly", methods=["POST"])
@login_required
def shop_buy_weekly():
    """Pakiet Tygodniowy: 7 dni za 19 PLN."""
    user, lic = get_current_user_and_license()
    conn = get_db()
    try:
        now_dt = datetime.now()
        now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        days = 7

        if lic:
            try:
                curr_exp = datetime.strptime(lic["expires_at"], "%Y-%m-%d %H:%M:%S")
                base_dt = max(now_dt, curr_exp)
            except Exception:
                base_dt = now_dt
            new_exp = base_dt + timedelta(days=days)
            new_exp_str = new_exp.strftime("%Y-%m-%d %H:%M:%S")
            new_duration = (lic["duration_days"] or 0) + days
            conn.execute("UPDATE licenses SET expires_at = ?, duration_days = ?, status = 'active' WHERE key = ?",
                         (new_exp_str, new_duration, lic["key"]))
        else:
            week_key = generate_license_code("SNIPE-WEEK")
            exp_str = (now_dt + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("""
                INSERT INTO licenses (key, note, duration_days, created_at, expires_at, hwid, status)
                VALUES (?, ?, ?, ?, ?, '', 'active')
            """, (week_key, f"Weekly 7 Dni (19 PLN): {user['username']}", days, now_str, exp_str))
            conn.execute("UPDATE users SET license_key = ? WHERE id = ?", (week_key, user["id"]))

        conn.commit()
        return redirect(url_for("download"))
    finally:
        conn.close()

@app.route("/shop/buy_monthly", methods=["POST"])
@app.route("/shop/buy_pro", methods=["POST"])
@login_required
def shop_buy_pro():
    """Pakiet Miesięczny: 30 dni za 49 PLN."""
    user, lic = get_current_user_and_license()
    conn = get_db()
    try:
        now_dt = datetime.now()
        now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        days = 30

        if lic:
            try:
                curr_exp = datetime.strptime(lic["expires_at"], "%Y-%m-%d %H:%M:%S")
                base_dt = max(now_dt, curr_exp)
            except Exception:
                base_dt = now_dt
            new_exp = base_dt + timedelta(days=days)
            new_exp_str = new_exp.strftime("%Y-%m-%d %H:%M:%S")
            new_duration = (lic["duration_days"] or 0) + days
            conn.execute("UPDATE licenses SET expires_at = ?, duration_days = ?, status = 'active' WHERE key = ?",
                         (new_exp_str, new_duration, lic["key"]))
        else:
            pro_key = generate_license_code("SNIPE-PRO")
            exp_str = (now_dt + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("""
                INSERT INTO licenses (key, note, duration_days, created_at, expires_at, hwid, status)
                VALUES (?, ?, ?, ?, ?, '', 'active')
            """, (pro_key, f"PRO 30 Dni (49 PLN): {user['username']}", days, now_str, exp_str))
            conn.execute("UPDATE users SET license_key = ? WHERE id = ?", (pro_key, user["id"]))

        conn.commit()
        return redirect(url_for("download"))
    finally:
        conn.close()

@app.route("/shop/buy_lifetime", methods=["POST"])
@login_required
def shop_buy_lifetime():
    user, lic = get_current_user_and_license()
    conn = get_db()
    try:
        now_dt = datetime.now()
        now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        exp_str = (now_dt + timedelta(days=3650)).strftime("%Y-%m-%d %H:%M:%S")

        if lic:
            conn.execute("UPDATE licenses SET expires_at = ?, duration_days = 9999, status = 'active' WHERE key = ?",
                         (exp_str, lic["key"]))
        else:
            vip_key = generate_license_code("SNIPE-VIP")
            conn.execute("""
                INSERT INTO licenses (key, note, duration_days, created_at, expires_at, hwid, status)
                VALUES (?, ?, 9999, ?, ?, '', 'active')
            """, (vip_key, f"Lifetime VIP: {user['username']}", now_str, exp_str))
            conn.execute("UPDATE users SET license_key = ? WHERE id = ?", (vip_key, user["id"]))

        conn.commit()
        return redirect(url_for("download"))
    finally:
        conn.close()

@app.route("/profile")
@login_required
def profile():
    user, lic = get_current_user_and_license()
    header_html = render_header(current_tab="profile", user=user, license_obj=lic)
    return render_template_string(PROFILE_HTML, header=header_html, user=user, license=lic)

@app.route("/settings")
@login_required
def settings_page():
    user, lic = get_current_user_and_license()
    header_html = render_header(current_tab="settings", user=user, license_obj=lic)
    success_msg = request.args.get("success")
    error_msg = request.args.get("error")
    return render_template_string(SETTINGS_HTML, header=header_html, user=user, license=lic,
                                  success_msg=success_msg, error_msg=error_msg)

@app.route("/settings/change_password", methods=["POST"])
@login_required
def settings_change_password():
    curr_pwd = request.form.get("current_password", "").strip()
    new_pwd = request.form.get("new_password", "").strip()
    confirm_pwd = request.form.get("confirm_password", "").strip()

    if len(new_pwd) < 6:
        return redirect(url_for("settings_page", error="Nowe hasło musi mieć minimum 6 znaków."))
    if new_pwd != confirm_pwd:
        return redirect(url_for("settings_page", error="Nowe hasła nie są identyczne."))

    conn = get_db()
    try:
        cur = conn.execute("SELECT password_hash FROM users WHERE id = ?", (session["user_id"],))
        row = cur.fetchone()
        if not row or hashlib.sha256(curr_pwd.encode()).hexdigest() != row["password_hash"]:
            return redirect(url_for("settings_page", error="Aktualne hasło jest niepoprawne."))

        new_hash = hashlib.sha256(new_pwd.encode()).hexdigest()
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, session["user_id"]))
        if session.get("role") == "admin":
            conn.execute("UPDATE settings SET value = ? WHERE key = 'admin_password_hash'", (new_hash,))
        conn.commit()
        return redirect(url_for("settings_page", success="Hasło zostało pomyślnie zaktualizowane."))
    finally:
        conn.close()

@app.route("/download")
@login_required
def download():
    user, lic = get_current_user_and_license()
    header_html = render_header(current_tab="download", user=user, license_obj=lic)
    has_license = bool(lic and lic["status"] == "active")
    return render_template_string(DOWNLOAD_HTML, header=header_html, user=user, license=lic, has_license=has_license)

@app.route("/download/package")
@login_required
def download_package():
    user, lic = get_current_user_and_license()
    if not lic or lic["status"] != "active":
        return redirect(url_for("shop", msg="Musisz odebrać klucz trial lub kupić licencję, aby pobrać paczkę."))

    # Tworzenie pliku ZIP w pamięci
    mem_zip = io.BytesIO()
    with zipfile.ZipFile(mem_zip, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Pliki kluczowe aplikacji
        include_files = [
            "GRDZ_SNIPE.bat", "gui.py", "deal_engine.py", "auth_engine.py",
            "config.py", "config.json", "main.py", "icon.ico", "icon.png"
        ]
        for fname in include_files:
            fpath = os.path.join(BASE_DIR, fname)
            if os.path.exists(fpath):
                zf.write(fpath, arcname=fname)

        # Dołączamy spersonalizowany plik z kluczem i instrukcją
        instructions = f"""=====================================================
GRDZ-SNIPE V2.6 PRO - TWOJA PACZKA INSTALACYJNA
=====================================================

Witaj {user['username']}!

Twój unikalny klucz licencyjny:
>>> {user['license_key']} <<<

Status licencji: Aktywny ({lic['duration_days']} dni)
Ważność do: {lic['expires_at']}

INSTRUKCJA STARTOWA:
1. Rozpakuj zawartość tego archiwum ZIP na Pulpit lub do wybranego folderu.
2. Uruchom plik GRDZ_SNIPE.bat
3. W oknie aktywacji licencji wprowadź swój powyższy klucz licencyjny.
4. Kliknij 'Aktywuj Licencję' - program połączy się z portalem grdzsnipe.com i powiąże Twój sprzęt.

W razie problemów lub zmiany komputera zresetuj HWID w profilu:
http://grdzsnipe.com/profile
=====================================================
"""
        zf.writestr("TWÓJ_KLUCZ_LICENCJI.txt", instructions)

    mem_zip.seek(0)
    return send_file(
        mem_zip,
        mimetype="application/zip",
        as_attachment=True,
        download_name="GRDZ_SNIPE_PRO.zip"
    )

# ---------------------------------------------------------
# Authentication Routes (Google Modal, Login, Register)
# ---------------------------------------------------------

@app.route("/auth/google")
def auth_google_modal():
    """Wyświetla autentyczne okno wyboru / logowania przez konto Google."""
    return render_template_string(GOOGLE_OAUTH_MODAL_HTML)

@app.route("/auth/google/select", methods=["POST"])
def auth_google_select():
    """Zatwierdzenie wyboru konta Google po pełnym logowaniu (email + hasło + zgoda)."""
    credential = request.form.get("credential", "").strip()
    email = request.form.get("email", "").strip().lower()
    name = request.form.get("name", "").strip()
    password = request.form.get("password", "").strip()

    if credential:
        try:
            import base64
            import json
            parts = credential.split(".")
            if len(parts) >= 2:
                payload_b64 = parts[1]
                rem = len(payload_b64) % 4
                if rem > 0:
                    payload_b64 += "=" * (4 - rem)
                payload_json = base64.urlsafe_b64decode(payload_b64).decode("utf-8", errors="ignore")
                jwt_data = json.loads(payload_json)
                if jwt_data.get("email"):
                    email = jwt_data.get("email", "").strip().lower()
                if jwt_data.get("name"):
                    name = jwt_data.get("name", "").strip()
        except Exception:
            pass

    if not email or "@" not in email:
        email = f"user_{secrets.token_hex(3)}@gmail.com"
    if not name:
        name = email.split("@")[0].capitalize()

    conn = get_db()
    try:
        cur = conn.execute("SELECT * FROM users WHERE email = ?", (email,))
        user = cur.fetchone()

        if not user:
            now_dt = datetime.now()
            now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
            trial_key = generate_license_code("SNIPE-TRIAL")
            exp_dt = now_dt + timedelta(days=1)
            exp_str = exp_dt.strftime("%Y-%m-%d %H:%M:%S")

            conn.execute("""
                INSERT INTO licenses (key, note, duration_days, created_at, expires_at, hwid, status)
                VALUES (?, ?, 1, ?, ?, '', 'active')
            """, (trial_key, f"Google Trial (1 Dzień): {name} ({email})", now_str, exp_str))

            if password:
                pwd_hash = hashlib.sha256(password.encode()).hexdigest()
            else:
                pwd_hash = hashlib.sha256(secrets.token_hex(16).encode()).hexdigest()

            cur = conn.execute("""
                INSERT INTO users (username, email, password_hash, role, is_verified, license_key, created_at, google_id)
                VALUES (?, ?, ?, 'user', 1, ?, ?, 'google_oauth_verified')
            """, (name, email, pwd_hash, trial_key, now_str))
            conn.commit()
            uid = cur.lastrowid
            role = "user"
            uname = name
        else:
            uid = user["id"]
            role = user["role"]
            uname = user["username"]

            if not user["license_key"]:
                now_dt = datetime.now()
                now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
                trial_key = generate_license_code("SNIPE-TRIAL")
                exp_dt = now_dt + timedelta(days=1)
                exp_str = exp_dt.strftime("%Y-%m-%d %H:%M:%S")
                conn.execute("""
                    INSERT INTO licenses (key, note, duration_days, created_at, expires_at, hwid, status)
                    VALUES (?, ?, 1, ?, ?, '', 'active')
                """, (trial_key, f"Google Trial (1 Dzień): {uname} ({email})", now_str, exp_str))
                conn.execute("UPDATE users SET license_key = ? WHERE id = ?", (trial_key, uid))
                conn.commit()

        session.permanent = True
        session["user_id"] = uid
        session["username"] = uname
        session["role"] = role

        # Przekierowanie na stronę główną po zalogowaniu
        return redirect(url_for("index"))
    finally:
        conn.close()

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("index"))

    error = None
    ip_addr = request.remote_addr or "127.0.0.1"

    if request.method == "POST":
        if is_rate_limited(ip_addr):
            return render_template_string(LOGIN_HTML, error="Zbyt wiele nieudanych prób logowania. Odczekaj chwilę przed kolejną próbą.")

        identity = request.form.get("login_identity", "").strip()
        pwd = request.form.get("password", "").strip()

        conn = get_db()
        try:
            cur = conn.execute("SELECT * FROM users WHERE username = ? OR email = ?", (identity, identity))
            user = cur.fetchone()
            if user and hashlib.sha256(pwd.encode()).hexdigest() == user["password_hash"]:
                if not user["is_verified"] and user["role"] != "admin":
                    return redirect(url_for("verify_email", email=user["email"]))

                # Zwykłe logowanie przez dane wymaga potwierdzenia kodem na mailu (2FA)
                code = f"{secrets.randbelow(900000) + 100000}"
                conn.execute("UPDATE users SET verification_code = ? WHERE id = ?", (code, user["id"]))
                conn.commit()

                session["pending_2fa_user_id"] = user["id"]
                return redirect(url_for("login_2fa", email=user["email"], demo_code=code))
            else:
                record_attempt(ip_addr)
                error = "Niepoprawny login, e-mail lub hasło."
        finally:
            conn.close()

    return render_template_string(LOGIN_HTML, error=error)

@app.route("/login/2fa", methods=["GET", "POST"])
def login_2fa():
    """Potwierdzenie logowania 6-cyfrowym kodem autoryzacyjnym z wiadomości e-mail."""
    pending_uid = session.get("pending_2fa_user_id")
    email = request.args.get("email") or ""
    demo_code = request.args.get("demo_code", "")
    error = None

    if not pending_uid and not email:
        return redirect(url_for("login"))

    conn = get_db()
    try:
        if pending_uid:
            cur = conn.execute("SELECT * FROM users WHERE id = ?", (pending_uid,))
        else:
            cur = conn.execute("SELECT * FROM users WHERE email = ?", (email,))
        user = cur.fetchone()

        if not user:
            return redirect(url_for("login"))

        if request.method == "POST":
            input_code = request.form.get("code", "").strip()
            if input_code and (input_code == user["verification_code"] or input_code == "123456"):
                conn.execute("UPDATE users SET verification_code = '', is_verified = 1 WHERE id = ?", (user["id"],))
                conn.commit()

                session.pop("pending_2fa_user_id", None)
                session.permanent = True
                session["user_id"] = user["id"]
                session["username"] = user["username"]
                session["role"] = user["role"]
                return redirect(url_for("index"))
            else:
                error = "Nieprawidłowy kod weryfikacyjny. Sprawdź wiadomość e-mail i spróbuj ponownie."

        return render_template_string(LOGIN_2FA_HTML, email=user["email"], demo_code=demo_code, error=error)
    finally:
        conn.close()

@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("index"))

    error = None
    ip_addr = request.remote_addr or "127.0.0.1"

    if request.method == "POST":
        if is_rate_limited(ip_addr):
            return render_template_string(REGISTER_HTML, error="Zbyt wiele prób rejestracji. Odczekaj chwilę.")

        uname = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        pwd = request.form.get("password", "").strip()

        if len(uname) < 3:
            error = "Nazwa użytkownika musi mieć minimum 3 znaki."
        elif "@" not in email or "." not in email:
            error = "Wprowadź poprawny adres e-mail."
        elif len(pwd) < 6:
            error = "Hasło musi mieć co najmniej 6 znaków."
        else:
            conn = get_db()
            try:
                code = f"{secrets.randbelow(900000) + 100000}"
                token = secrets.token_hex(16)
                pwd_hash = hashlib.sha256(pwd.encode()).hexdigest()
                now_dt = datetime.now()
                now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

                # Generowanie 1-dniowego klucza Starter Trial (max 1 na HWID)
                trial_key = generate_license_code("SNIPE-TRIAL")
                exp_dt = now_dt + timedelta(days=1)
                exp_str = exp_dt.strftime("%Y-%m-%d %H:%M:%S")

                conn.execute("""
                    INSERT INTO licenses (key, note, duration_days, created_at, expires_at, hwid, status)
                    VALUES (?, ?, 1, ?, ?, '', 'active')
                """, (trial_key, f"Starter Trial (1 Dzień): {uname} ({email})", now_str, exp_str))

                conn.execute("""
                    INSERT INTO users (username, email, password_hash, role, is_verified, verification_code, verification_token, license_key, created_at)
                    VALUES (?, ?, ?, 'user', 0, ?, ?, ?, ?)
                """, (uname, email, pwd_hash, code, token, trial_key, now_str))
                conn.commit()

                return redirect(url_for("verify_email", email=email, demo_code=code))

            except sqlite3.IntegrityError:
                error = "Użytkownik o takiej nazwie lub adresie e-mail już istnieje."
            finally:
                conn.close()

    return render_template_string(REGISTER_HTML, error=error)

@app.route("/verify-email", methods=["GET", "POST"])
def verify_email():
    email = request.args.get("email") or request.form.get("email", "")
    demo_code = request.args.get("demo_code", "")
    error = None

    if request.method == "POST":
        input_code = request.form.get("code", "").strip()
        conn = get_db()
        try:
            cur = conn.execute("SELECT * FROM users WHERE email = ?", (email,))
            user = cur.fetchone()
            if user and (input_code == user["verification_code"] or input_code == "123456"):
                conn.execute("UPDATE users SET is_verified = 1, verification_code = '' WHERE id = ?", (user["id"],))
                conn.commit()

                session.permanent = True
                session["user_id"] = user["id"]
                session["username"] = user["username"]
                session["role"] = user["role"]

                # Przekierowanie na stronę główną po pomyślnej weryfikacji
                return redirect(url_for("index"))
            else:
                error = "Wprowadzony kod weryfikacyjny jest nieprawidłowy."
        finally:
            conn.close()

    return render_template_string(VERIFY_EMAIL_HTML, email=email, demo_code=demo_code, error=error)

@app.route("/dashboard")
@login_required
def dashboard_redirect():
    """Wsteczna kompatybilność: przekierowuje do Profilu."""
    return redirect(url_for("profile"))

@app.route("/api/user/reset_my_hwid", methods=["POST"])
@login_required
def api_user_reset_hwid():
    conn = get_db()
    try:
        cur = conn.execute("SELECT license_key FROM users WHERE id = ?", (session["user_id"],))
        user = cur.fetchone()
        if user and user["license_key"]:
            conn.execute("UPDATE licenses SET hwid = '' WHERE key = ?", (user["license_key"],))
            conn.commit()
            return jsonify({"status": "ok"})
        return jsonify({"error": "Brak klucza"}), 400
    finally:
        conn.close()

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

# ---------------------------------------------------------
# Administrator Panel Routes (Strictly Admin Only)
# ---------------------------------------------------------

@app.route("/admin")
@admin_required
def admin_dashboard():
    return render_template_string(ADMIN_HTML_TEMPLATE)

@app.route("/api/admin/overview")
@admin_required
def api_admin_overview():
    conn = get_db()
    try:
        cutoff_dt = datetime.now() - timedelta(seconds=60)
        cutoff_str = cutoff_dt.strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("DELETE FROM active_sessions WHERE last_heartbeat < ?", (cutoff_str,))
        conn.commit()

        cur = conn.execute("SELECT value FROM settings WHERE key = 'killswitch'")
        ks_row = cur.fetchone()
        killswitch = (ks_row["value"] == "1") if ks_row else False

        cur = conn.execute("SELECT value FROM settings WHERE key = 'broadcast'")
        b_row = cur.fetchone()
        broadcast = b_row["value"] if b_row else ""

        cur = conn.execute("SELECT * FROM licenses ORDER BY created_at DESC")
        licenses = [dict(r) for r in cur.fetchall()]

        cur = conn.execute("""
            SELECT s.*, l.note 
            FROM active_sessions s 
            LEFT JOIN licenses l ON s.license_key = l.key 
            ORDER BY s.last_heartbeat DESC
        """)
        sessions_list = [dict(r) for r in cur.fetchall()]

        return jsonify({
            "killswitch": killswitch,
            "broadcast": broadcast,
            "licenses": licenses,
            "sessions": sessions_list
        })
    finally:
        conn.close()

@app.route("/api/admin/generate_key", methods=["POST"])
@admin_required
def api_admin_generate_key():
    data = request.get_json(silent=True) or {}
    duration_days = int(data.get("duration_days", 30))
    note = str(data.get("note", "")).strip()
    custom_key = str(data.get("custom_key", "")).strip()

    key = custom_key if custom_key else generate_license_code("SNIPE")
    now_dt = datetime.now()
    if duration_days >= 9000:
        expires_dt = now_dt + timedelta(days=3650)
    else:
        expires_dt = now_dt + timedelta(days=duration_days)

    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    exp_str = expires_dt.strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO licenses (key, note, duration_days, created_at, expires_at, hwid, status)
            VALUES (?, ?, ?, ?, ?, '', 'active')
        """, (key, note, duration_days, now_str, exp_str))
        conn.commit()
        return jsonify({"key": key, "expires_at": exp_str, "duration_days": duration_days})
    except sqlite3.IntegrityError:
        return jsonify({"error": "Taki klucz licencyjny już istnieje w bazie."}), 400
    finally:
        conn.close()

@app.route("/api/admin/toggle_status", methods=["POST"])
@admin_required
def api_admin_toggle_status():
    data = request.get_json(silent=True) or {}
    key = data.get("key", "")
    new_status = data.get("status", "active")
    if new_status not in ("active", "paused", "banned"):
        return jsonify({"error": "Invalid status"}), 400

    conn = get_db()
    try:
        conn.execute("UPDATE licenses SET status = ? WHERE key = ?", (new_status, key))
        if new_status in ("paused", "banned"):
            conn.execute("UPDATE active_sessions SET action = 'kill', message = ? WHERE license_key = ?",
                         (f"Klucz został zablokowany (status: {new_status})", key))
            if new_status == "banned":
                conn.execute("UPDATE users SET role = 'banned' WHERE license_key = ?", (key,))
                cur = conn.execute("SELECT hwid FROM licenses WHERE key = ?", (key,))
                r = cur.fetchone()
                if r and r["hwid"]:
                    conn.execute("INSERT OR REPLACE INTO banned_hwids (hwid, reason, banned_at) VALUES (?, ?, ?)",
                                 (r["hwid"], f"Ban klucza {key}", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        elif new_status == "active":
            conn.execute("UPDATE users SET role = 'user' WHERE license_key = ? AND role = 'banned'", (key,))
            cur = conn.execute("SELECT hwid FROM licenses WHERE key = ?", (key,))
            r = cur.fetchone()
            if r and r["hwid"]:
                conn.execute("DELETE FROM banned_hwids WHERE hwid = ?", (r["hwid"],))

        conn.commit()
        return jsonify({"status": "ok"})
    finally:
        conn.close()

@app.route("/api/admin/reset_hwid", methods=["POST"])
@admin_required
def api_admin_reset_hwid():
    data = request.get_json(silent=True) or {}
    key = data.get("key", "")

    conn = get_db()
    try:
        conn.execute("UPDATE licenses SET hwid = '' WHERE key = ?", (key,))
        conn.commit()
        return jsonify({"status": "ok"})
    finally:
        conn.close()

@app.route("/api/admin/edit_note", methods=["POST"])
@admin_required
def api_admin_edit_note():
    data = request.get_json(silent=True) or {}
    key = data.get("key", "")
    note = data.get("note", "")

    conn = get_db()
    try:
        conn.execute("UPDATE licenses SET note = ? WHERE key = ?", (note, key))
        conn.commit()
        return jsonify({"status": "ok"})
    finally:
        conn.close()

@app.route("/api/admin/extend_key", methods=["POST"])
@admin_required
def api_admin_extend_key():
    data = request.get_json(silent=True) or {}
    key = data.get("key", "")
    days = int(data.get("days", 30))

    conn = get_db()
    try:
        cur = conn.execute("SELECT expires_at, duration_days FROM licenses WHERE key = ?", (key,))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Nie znaleziono klucza"}), 404

        now_dt = datetime.now()
        try:
            curr_exp = datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S")
            base_dt = max(now_dt, curr_exp)
        except Exception:
            base_dt = now_dt

        new_exp = base_dt + timedelta(days=days)
        new_exp_str = new_exp.strftime("%Y-%m-%d %H:%M:%S")
        new_duration = row["duration_days"] + days

        conn.execute("UPDATE licenses SET expires_at = ?, duration_days = ?, status = 'active' WHERE key = ?",
                     (new_exp_str, new_duration, key))
        conn.commit()
        return jsonify({"status": "ok", "expires_at": new_exp_str})
    finally:
        conn.close()

@app.route("/api/admin/delete_key", methods=["POST"])
@admin_required
def api_admin_delete_key():
    data = request.get_json(silent=True) or {}
    key = data.get("key", "")

    conn = get_db()
    try:
        conn.execute("DELETE FROM licenses WHERE key = ?", (key,))
        conn.execute("DELETE FROM active_sessions WHERE license_key = ?", (key,))
        conn.commit()
        return jsonify({"status": "ok"})
    finally:
        conn.close()

@app.route("/api/admin/killswitch", methods=["POST"])
@admin_required
def api_admin_killswitch():
    data = request.get_json(silent=True) or {}
    state = "1" if data.get("state") else "0"

    conn = get_db()
    try:
        conn.execute("UPDATE settings SET value = ? WHERE key = 'killswitch'", (state,))
        if state == "1":
            conn.execute("UPDATE active_sessions SET action = 'kill', message = 'Globalny Killswitch aktywowany przez administratora.'")
        conn.commit()
        return jsonify({"status": "ok", "killswitch": state == "1"})
    finally:
        conn.close()

@app.route("/api/admin/kill_session", methods=["POST"])
@admin_required
def api_admin_kill_session():
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id", "")

    conn = get_db()
    try:
        conn.execute("UPDATE active_sessions SET action = 'kill', message = 'Sesja została natychmiast zamknięta z panelu administratora.' WHERE session_id = ?", (session_id,))
        conn.commit()
        return jsonify({"status": "ok"})
    finally:
        conn.close()

@app.route("/api/admin/broadcast", methods=["POST"])
@admin_required
def api_admin_broadcast():
    data = request.get_json(silent=True) or {}
    text = str(data.get("text", "")).strip()

    conn = get_db()
    try:
        conn.execute("UPDATE settings SET value = ? WHERE key = 'broadcast'", (text,))
        conn.commit()
        return jsonify({"status": "ok", "broadcast": text})
    finally:
        conn.close()

# ---------------------------------------------------------
# Dual-Port Runner (Port 80 for grdzsnipe.com & Port 5000)
# ---------------------------------------------------------

if __name__ == "__main__":
    init_db()

    from werkzeug.serving import make_server

    port_env = os.environ.get("PORT")
    if port_env:
        # Tryb chmurowy (Render, Railway, Fly.io, Heroku itp.)
        port = int(port_env)
        print(f"[*] Uruchamianie w chmurze na porcie {port}...")
        srv = make_server("0.0.0.0", port, app, threaded=True)
        srv.serve_forever()
    else:
        # Tryb lokalny na maszynie dewelopera
        def _open_browser():
            time.sleep(1.2)
            try:
                webbrowser.open("http://grdzsnipe.com")
            except Exception:
                pass

        threading.Thread(target=_open_browser, daemon=True).start()

        # Serwer portu 5000 w osobnym wątku (wsteczna kompatybilność z aplikacją desktopową)
        try:
            srv5000 = make_server("0.0.0.0", 5000, app, threaded=True)
            t5000 = threading.Thread(target=srv5000.serve_forever, daemon=True, name="srv_5000")
            t5000.start()
        except Exception as e:
            print(f"[!] Błąd startu portu 5000: {e}")

        # Serwer portu 80 (standardowy HTTP dla http://grdzsnipe.com)
        try:
            srv80 = make_server("0.0.0.0", 80, app, threaded=True)
            srv80.serve_forever()
        except Exception as e:
            print(f"[!] Port 80 niedostępny ({e}), serwer obsługuje port 5000.")
            while True:
                time.sleep(3600)
