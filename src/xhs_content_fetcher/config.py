from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

APP_DIR_NAME = ".xhs-content-fetcher"
CONFIG_FILE_NAME = "config.json"


@dataclass
class AppConfig:
    cookie: str = ""
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    notes_folder: str = "XHS笔记"
    obsidian_cli_cmd: str = "obsidian"


def get_app_dir() -> Path:
    app_dir = Path.home() / APP_DIR_NAME
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def get_config_path() -> Path:
    return get_app_dir() / CONFIG_FILE_NAME


def load_config() -> AppConfig:
    config_path = get_config_path()
    if not config_path.exists():
        return AppConfig()
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AppConfig()
    if not isinstance(raw, dict):
        return AppConfig()
    return AppConfig(
        cookie=str(raw.get("cookie", "")),
        deepseek_api_key=str(raw.get("deepseek_api_key", "")),
        deepseek_base_url=str(raw.get("deepseek_base_url", "https://api.deepseek.com")),
        deepseek_model=str(raw.get("deepseek_model", "deepseek-v4-flash")),
        notes_folder=str(raw.get("notes_folder", "XHS笔记")),
        obsidian_cli_cmd=str(raw.get("obsidian_cli_cmd", "obsidian")),
    )


def save_config(config: AppConfig) -> None:
    config_path = get_config_path()
    config_path.write_text(
        json.dumps(asdict(config), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def parse_cookie_string(cookie_str: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for part in cookie_str.split(";"):
        item = part.strip()
        if not item or "=" not in item:
            continue
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            continue
        cookies[key] = value.strip()
    return cookies


def mask_cookie(cookie_str: str, head: int = 12, tail: int = 8) -> str:
    stripped = cookie_str.strip()
    if len(stripped) <= head + tail:
        return "*" * len(stripped)
    return f"{stripped[:head]}...{stripped[-tail:]}"
