"""Ayarlar ve oturum dosyaları (~/.renkolcum veya RENKOLCUM_HOME)."""
from __future__ import annotations

import json
import os
from pathlib import Path


def home() -> Path:
    p = Path(os.environ.get("RENKOLCUM_HOME", Path.home() / ".renkolcum"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _read(name: str) -> dict:
    f = home() / name
    return json.loads(f.read_text("utf-8")) if f.exists() else {}


def _write(name: str, data: dict, private: bool = False) -> None:
    f = home() / name
    f.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")
    if private:
        os.chmod(f, 0o600)


def load_config() -> dict:
    cfg = _read("config.json")
    cfg["supabase_url"] = os.environ.get("RENKOLCUM_SUPABASE_URL", cfg.get("supabase_url", "")).rstrip("/")
    cfg["supabase_anon_key"] = os.environ.get("RENKOLCUM_SUPABASE_ANON_KEY", cfg.get("supabase_anon_key", ""))
    cfg.setdefault("instrument_serial", "SIM-0001")
    return cfg


def save_config(cfg: dict) -> None:
    _write("config.json", cfg)


def load_session() -> dict:
    return _read("session.json")


def save_session(sess: dict) -> None:
    _write("session.json", sess, private=True)


def clear_session() -> None:
    f = home() / "session.json"
    if f.exists():
        f.unlink()
