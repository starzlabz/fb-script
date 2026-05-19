from __future__ import annotations

import base64
import datetime as dt
import getpass
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization

from license_public_key import PUBLIC_KEY_PEM


APP_NAME = "FacebookPageScheduler"
LICENSE_VERSION = "FPS1"


@dataclass(frozen=True)
class LicenseInfo:
    name: str
    device_id: str
    issued_at: str
    expires_at: Optional[str]
    license_id: str


def b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def get_user_data_dir() -> str:
    if sys.platform == "win32":
        root = (
            os.getenv("LOCALAPPDATA")
            or os.getenv("APPDATA")
            or os.path.expanduser(r"~\AppData\Local")
        )
    elif sys.platform == "darwin":
        root = os.path.expanduser("~/Library/Application Support")
    else:
        root = os.getenv("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")

    return os.path.join(root, APP_NAME)


def get_license_path() -> str:
    return os.path.join(get_user_data_dir(), "license.json")


def read_windows_machine_guid() -> Optional[str]:
    if sys.platform != "win32":
        return None

    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
            return str(value).strip() or None
    except Exception:
        return None


def read_macos_hardware_uuid() -> Optional[str]:
    if sys.platform != "darwin":
        return None

    try:
        output = subprocess.check_output(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except Exception:
        return None

    for line in output.splitlines():
        if "IOPlatformUUID" not in line or "=" not in line:
            continue

        _, value = line.split("=", 1)
        return value.strip().strip('"') or None

    return None


def read_linux_machine_id() -> Optional[str]:
    if sys.platform.startswith(("win", "darwin")):
        return None

    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                value = f.read().strip()
        except OSError:
            continue

        if value:
            return value

    return None


def get_device_fingerprint_parts() -> list[str]:
    parts = [
        read_windows_machine_guid(),
        read_macos_hardware_uuid(),
        read_linux_machine_id(),
        platform.node(),
        socket.gethostname(),
        getpass.getuser(),
    ]
    return [part.strip() for part in parts if part and part.strip()]


def get_device_id() -> str:
    raw = "|".join(get_device_fingerprint_parts() or [platform.platform(), APP_NAME])
    digest = hashlib.sha256(f"{APP_NAME}|{raw}".encode("utf-8")).digest()
    compact = base64.b32encode(digest).decode("ascii").rstrip("=")[:20]
    return "-".join(compact[index:index + 4] for index in range(0, len(compact), 4))


def get_public_key():
    if not PUBLIC_KEY_PEM.strip():
        raise ValueError("License public key is not configured. Run license_tool.py init-keys first.")

    return serialization.load_pem_public_key(PUBLIC_KEY_PEM.encode("utf-8"))


def parse_license_token(license_token: str) -> tuple[dict[str, Any], bytes, str]:
    token = "".join(license_token.strip().split())
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != LICENSE_VERSION:
        raise ValueError("License format is not valid.")

    payload_segment = parts[1]
    signature = b64url_decode(parts[2])
    try:
        payload = json.loads(b64url_decode(payload_segment).decode("utf-8"))
    except Exception as exc:
        raise ValueError("License payload is not valid.") from exc

    if not isinstance(payload, dict):
        raise ValueError("License payload is not valid.")

    return payload, signature, payload_segment


def verify_license_token(
    license_token: str,
    expected_device_id: Optional[str] = None,
    today: Optional[dt.date] = None,
) -> LicenseInfo:
    payload, signature, payload_segment = parse_license_token(license_token)
    public_key = get_public_key()

    try:
        public_key.verify(signature, payload_segment.encode("ascii"))
    except InvalidSignature as exc:
        raise ValueError("License signature is not valid.") from exc

    required_fields = {"name", "device_id", "issued_at", "license_id"}
    if not required_fields.issubset(payload):
        raise ValueError("License is missing required fields.")

    device_id = str(payload["device_id"]).strip()
    expected_device_id = expected_device_id or get_device_id()
    if device_id != expected_device_id:
        raise ValueError("This license belongs to a different device.")

    expires_at = payload.get("expires_at")
    if expires_at:
        try:
            expires_date = dt.date.fromisoformat(str(expires_at))
        except ValueError as exc:
            raise ValueError("License expiration date is not valid.") from exc

        today = today or dt.date.today()
        if expires_date < today:
            raise ValueError("This license has expired.")

    return LicenseInfo(
        name=str(payload["name"]).strip(),
        device_id=device_id,
        issued_at=str(payload["issued_at"]).strip(),
        expires_at=str(expires_at).strip() if expires_at else None,
        license_id=str(payload["license_id"]).strip(),
    )


def save_license(license_token: str) -> LicenseInfo:
    license_info = verify_license_token(license_token)
    license_path = get_license_path()
    os.makedirs(os.path.dirname(license_path), exist_ok=True)

    with open(license_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "license": license_token.strip(),
                "activated_at": dt.datetime.now().isoformat(timespec="seconds"),
            },
            f,
            indent=2,
        )
        f.write("\n")

    return license_info


def load_saved_license_token() -> Optional[str]:
    license_path = get_license_path()
    if not os.path.exists(license_path):
        return None

    try:
        with open(license_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None

    license_token = data.get("license") if isinstance(data, dict) else None
    if not isinstance(license_token, str) or not license_token.strip():
        return None

    return license_token


def get_saved_license_info() -> Optional[LicenseInfo]:
    license_token = load_saved_license_token()
    if not license_token:
        return None

    return verify_license_token(license_token)
