# c:/Users/Kacper/Desktop/skrypt/app/auth_engine.py
# python / auth_engine.py / cpython 3.12 / x64 / windows
"""
Silnik licencjonowania KeyAuth & Zarzadzania Dostepem dla GRDZ_SNIPE.
Obsluguje:
1. Generowanie unikalnego, stalego identyfikatora sprzetowego (HWID).
2. Weryfikacje licencji przez dedykowany serwer KeyAuth Admin Dashboard oraz KeyAuth API.
3. Watek sygnalu zycia (Heartbeat) na zywo raportujacy status, IP i biezaca czynnosc.
4. Natychmiastowa reakcje na pauze, ban, przedawnienie oraz Global Killswitch.
"""

import os
import sys
import time
import json
import hashlib
import threading
from typing import Dict, Any, Optional, Callable, Tuple
from curl_cffi import requests


class AuthResult:
    """Uniwersalny obiekt wyniku autoryzacji wspierajacy rozpakowywanie i dostep slownikowy."""
    def __init__(self, success: bool, message: str, status: str = "", info: Optional[Dict[str, Any]] = None):
        self.success = bool(success)
        self.message = str(message)
        self.status = str(status)
        self.info = info or {}

    def __bool__(self) -> bool:
        return self.success

    def __iter__(self):
        return iter((self.success, self.message))

    def __getitem__(self, item: str) -> Any:
        if item == "success":
            return self.success
        if item == "message":
            return self.message
        if item == "status":
            return self.status
        if item == "info":
            return self.info
        return self.info.get(item)

    def get(self, key: str, default: Any = None) -> Any:
        if key == "success":
            return self.success
        if key == "message":
            return self.message
        if key == "status":
            return self.status
        if key == "info":
            return self.info
        return self.info.get(key, default)


class AuthEngine:
    _instance = None
    _lock = threading.Lock()

    def __init__(self, cfg: Optional[Dict[str, Any]] = None):
        self.cfg = cfg or {}
        self.hwid = self.generate_hwid()
        self.is_authenticated = False
        self.license_info: Dict[str, Any] = {}
        self.session_id: str = ""
        self.last_heartbeat = 0
        self.heartbeat_running = False
        self._heartbeat_thread: Optional[threading.Thread] = None
        self.on_revoked_callback: Optional[Callable[[str], None]] = None
        self.on_broadcast_callback: Optional[Callable[[str], None]] = None
        self.current_action: str = "Bezczynny"

    @classmethod
    def get_instance(cls, cfg: Optional[Dict[str, Any]] = None) -> "AuthEngine":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(cfg)
            elif cfg:
                cls._instance.cfg = cfg
            return cls._instance

    @property
    def license_key(self) -> str:
        return self.cfg.get("license_key", "")

    @license_key.setter
    def license_key(self, val: str):
        self.cfg["license_key"] = val

    @property
    def auth_server_url(self) -> str:
        return self.cfg.get("auth_server_url", "http://127.0.0.1:5000").rstrip("/")

    @staticmethod
    def generate_hwid() -> str:
        """
        Generuje bezpieczny, unikalny i deterministyczny identyfikator sprzetowy (HWID)
        dla danej stacji roboczej na podstawie Windows MachineGuid i parametrow procesora/hosta.
        """
        raw_hwid_components = []

        if sys.platform.startswith("win"):
            try:
                import winreg
                key = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\Microsoft\Cryptography",
                    0,
                    winreg.KEY_READ | winreg.KEY_WOW64_64KEY
                )
                guid, _ = winreg.QueryValueEx(key, "MachineGuid")
                winreg.CloseKey(key)
                if guid:
                    raw_hwid_components.append(str(guid).strip())
            except Exception:
                pass

        c_name = os.environ.get("COMPUTERNAME", "") or os.environ.get("HOSTNAME", "")
        u_name = os.environ.get("USERNAME", "") or os.environ.get("USER", "")
        p_arch = os.environ.get("PROCESSOR_ARCHITECTURE", "")
        p_id = os.environ.get("PROCESSOR_IDENTIFIER", "")

        raw_hwid_components.extend([c_name, u_name, p_arch, p_id])
        joined = "||".join(raw_hwid_components)
        h = hashlib.sha256(joined.encode("utf-8", errors="ignore")).hexdigest().upper()
        return f"HWID-{h[:4]}-{h[4:8]}-{h[8:12]}-{h[12:16]}"

    def verify_license(self, license_key: str) -> AuthResult:
        """
        Weryfikacja klucza licencyjnego z serwerem panelu admina.
        Obsluguje klucze Master Dev Override, lokalny serwer Flask oraz KeyAuth Cloud.
        """
        key = license_key.strip()
        if not key:
            return AuthResult(
                False,
                "Wprowadź klucz licencyjny, aby odblokować program.",
                status="empty"
            )

        # Klucze Master Dev Override do celow ratunkowych i lokalnych
        if key in ("GRDZ-MASTER-KEY-2026", "GRDZ-DEV-OVERRIDE", "ADMIN-OVERRIDE", "SNIPE-MASTER-OVERRIDE"):
            self.is_authenticated = True
            self.license_info = {
                "key": key,
                "status": "active",
                "type": "Master Developer License",
                "expires_at": "Bezterminowa (Lifetime)",
                "note": "Konto Administratora / Master Dev",
                "hwid": self.hwid
            }
            self.session_id = f"master-{int(time.time())}"
            return AuthResult(
                True,
                "Licencja Master Administratora aktywna (Pełny dostęp).",
                status="active",
                info=self.license_info
            )

        urls = [self.auth_server_url]
        for extra in ["http://grdzsnipe.com", "http://127.0.0.1:5000", "http://localhost:5000", "http://127.0.0.1"]:
            if extra not in urls:
                urls.append(extra)

        app_name = self.cfg.get("keyauth_app_name", "").strip()
        owner_id = self.cfg.get("keyauth_owner_id", "").strip()
        secret = self.cfg.get("keyauth_secret", "").strip()
        version = self.cfg.get("keyauth_version", "1.0").strip()

        # 1. Dedykowany serwer KeyAuth Admin Dashboard / Portal GRDZ_SNIPE
        for server_url in urls:
            try:
                resp = requests.post(
                    f"{server_url}/api/license/verify",
                    json={
                        "key": key,
                        "license_key": key,
                        "hwid": self.hwid,
                        "app_version": "v2.6 PRO",
                        "action": self.current_action
                    },
                    headers={"Content-Type": "application/json"},
                    timeout=3
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("success") or data.get("valid"):
                        self.is_authenticated = True
                        self.session_id = data.get("session_id", "")
                        self.license_info = data.get("info", {})
                        if not self.license_info:
                            self.license_info = {
                                "key": key,
                                "hwid": data.get("hwid", self.hwid),
                                "status": data.get("status", "active"),
                                "expires_at": data.get("expires_at", "Brak danych"),
                                "note": data.get("note", "")
                            }
                        self.license_info["key"] = key
                        self._active_server_url = server_url
                        self.start_heartbeat(key)
                        return AuthResult(
                            True,
                            data.get("message", "Licencja poprawna. Dostęp przyznany!"),
                            status="active",
                            info=self.license_info
                        )
                    else:
                        self.is_authenticated = False
                        return AuthResult(
                            False,
                            data.get("message", "Niepoprawny lub zablokowany klucz licencyjny."),
                            status=data.get("status", "invalid")
                        )
                elif resp.status_code in (401, 403):
                    try:
                        data = resp.json()
                        return AuthResult(
                            False,
                            data.get("message", "Brak uprawnień lub nieprawidłowy klucz."),
                            status=data.get("status", "denied")
                        )
                    except Exception:
                        pass
            except Exception:
                continue

        # 2. Oficjalne KeyAuth Cloud API (opcjonalna integracja w chmurze)
        if app_name and owner_id and secret:
            try:
                init_url = f"https://keyauth.win/api/1.2/?type=init&name={app_name}&ownerid={owner_id}&secret={secret}&ver={version}"
                r_init = requests.get(init_url, timeout=8)
                if r_init.status_code == 200:
                    d_init = r_init.json()
                    if d_init.get("success"):
                        session_id = d_init.get("sessionid")
                        lic_url = f"https://keyauth.win/api/1.2/?type=license&key={key}&hwid={self.hwid}&sessionid={session_id}&name={app_name}&ownerid={owner_id}"
                        r_lic = requests.get(lic_url, timeout=8)
                        if r_lic.status_code == 200:
                            d_lic = r_lic.json()
                            if d_lic.get("success"):
                                self.is_authenticated = True
                                info = d_lic.get("info", {})
                                exp_ts = info.get("expiry")
                                exp_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(int(exp_ts))) if exp_ts else "Lifetime"
                                self.license_info = {
                                    "key": key,
                                    "status": "active",
                                    "type": "KeyAuth Cloud",
                                    "expires_at": exp_str,
                                    "hwid": self.hwid
                                }
                                return AuthResult(
                                    True,
                                    "Autoryzacja KeyAuth Cloud udana!",
                                    status="active",
                                    info=self.license_info
                                )
                            else:
                                return AuthResult(
                                    False,
                                    d_lic.get("message", "Klucz odrzucony przez KeyAuth."),
                                    status="rejected"
                                )
            except Exception as e_cloud:
                print(f"[KeyAuth Cloud] Błąd: {e_cloud}")

        return AuthResult(
            False,
            f"Nie można połączyć się z serwerem licencji ({server_url}).\nUpewnij się, że panel administratora jest uruchomiony (start_admin_panel.bat).",
            status="server_unreachable"
        )

    def start_heartbeat(self, key: str):
        """Uruchamia watek tla wysylajacy cykliczny sygnal obecnosci (ping) do panelu admina."""
        if self.heartbeat_running:
            return
        self.heartbeat_running = True

        def _heartbeat_worker():
            server_url = getattr(self, "_active_server_url", self.auth_server_url)
            while self.heartbeat_running:
                time.sleep(12)
                if not self.heartbeat_running:
                    break
                try:
                    resp = requests.post(
                        f"{server_url}/api/license/heartbeat",
                        json={
                            "session_id": self.session_id,
                            "key": key,
                            "license_key": key,
                            "hwid": self.hwid,
                            "app_version": "v2.6 PRO",
                            "action": self.current_action
                        },
                        headers={"Content-Type": "application/json"},
                        timeout=5
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        status = data.get("status", "active")
                        success = data.get("success", True)
                        if status in ("banned", "paused", "expired", "hwid_mismatch", "killswitch", "killed", "revoked") or not success:
                            self.is_authenticated = False
                            reason = data.get("message") or f"Licencja została zablokowana przez administratora (status: {status})."
                            if self.on_revoked_callback:
                                self.on_revoked_callback(reason)
                            break

                        # Sprawdzenie powiadomienia broadcast od administratora
                        b_msg = data.get("broadcast_message") or data.get("broadcast")
                        if b_msg and self.on_broadcast_callback:
                            self.on_broadcast_callback(b_msg)
                except Exception:
                    pass

        self._heartbeat_thread = threading.Thread(target=_heartbeat_worker, daemon=True, name="keyauth_heartbeat")
        self._heartbeat_thread.start()

    def set_action(self, action_name: str):
        """Aktualizuje biezaca czynnosc widoczna na zywo w panelu administratora."""
        self.current_action = action_name

    def stop_heartbeat(self):
        self.heartbeat_running = False


def get_auth_engine(cfg: Optional[Dict[str, Any]] = None) -> AuthEngine:
    return AuthEngine.get_instance(cfg)
