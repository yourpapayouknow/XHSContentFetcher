from __future__ import annotations

import json
import os
import subprocess
import urllib.parse
import webbrowser
from dataclasses import dataclass
from pathlib import Path


def open_note_in_obsidian(note_path: Path, cli_cmd: str = "obsidian") -> tuple[bool, str]:
    resolved = note_path.resolve()
    vault = _find_containing_vault(resolved)
    if vault:
        rel_path = resolved.relative_to(vault.path).as_posix()
        try:
            # Official CLI format:
            # obsidian vault=<name_or_id> open path=<path_from_vault_root>
            subprocess.run(
                [cli_cmd, f"vault={vault.vault_id}", "open", f"path={rel_path}"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True, "通过 Obsidian CLI（vault + 相对 path）打开成功。"
        except Exception:
            pass

    uri = build_obsidian_open_uri(note_path)
    try:
        subprocess.run(
            [cli_cmd, uri],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True, "通过 Obsidian 命令 + URI 打开成功。"
    except Exception as exc:
        opened = webbrowser.open(uri)
        if opened:
            return True, "Obsidian CLI 不可用，已通过 obsidian:// URI 打开。"
        return False, f"Obsidian 打开失败: {exc}"


def build_obsidian_open_uri(note_path: Path) -> str:
    resolved = note_path.resolve()
    vault = _find_containing_vault(resolved)
    if vault:
        rel_path = resolved.relative_to(vault.path).as_posix()
        vault_encoded = urllib.parse.quote(vault.vault_id, safe="")
        file_encoded = urllib.parse.quote(rel_path, safe="")
        return f"obsidian://open?vault={vault_encoded}&file={file_encoded}"
    encoded = urllib.parse.quote(str(resolved).replace("\\", "/"), safe="")
    return f"obsidian://open?path={encoded}"


@dataclass
class VaultInfo:
    vault_id: str
    path: Path


def _find_containing_vault(note_path: Path) -> VaultInfo | None:
    vaults = _load_obsidian_vaults()
    matches: list[VaultInfo] = []
    for vault in vaults:
        try:
            note_path.relative_to(vault.path)
            matches.append(vault)
        except ValueError:
            continue
    if not matches:
        return None
    matches.sort(key=lambda item: len(str(item.path)), reverse=True)
    return matches[0]


def _load_obsidian_vaults() -> list[VaultInfo]:
    appdata = os.environ.get("APPDATA", "").strip()
    if not appdata:
        return []
    config_path = Path(appdata) / "obsidian" / "obsidian.json"
    if not config_path.exists():
        return []
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    vaults_raw = raw.get("vaults", {})
    if not isinstance(vaults_raw, dict):
        return []
    result: list[VaultInfo] = []
    for vault_id, item in vaults_raw.items():
        if not isinstance(item, dict):
            continue
        path_str = str(item.get("path", "")).strip()
        if not path_str:
            continue
        result.append(
            VaultInfo(
                vault_id=str(vault_id),
                path=Path(path_str).expanduser().resolve(),
            )
        )
    return result
