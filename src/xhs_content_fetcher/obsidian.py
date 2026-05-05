from __future__ import annotations

import subprocess
import urllib.parse
import webbrowser
from pathlib import Path


def open_note_in_obsidian(note_path: Path, cli_cmd: str = "obsidian") -> tuple[bool, str]:
    try:
        subprocess.run(
            [cli_cmd, "open", f"path={note_path.resolve()}"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True, "通过 Obsidian CLI 打开成功。"
    except Exception as exc:
        uri = build_obsidian_open_uri(note_path)
        opened = webbrowser.open(uri)
        if opened:
            return True, "Obsidian CLI 不可用，已通过 obsidian:// URI 打开。"
        return False, f"Obsidian 打开失败: {exc}"


def build_obsidian_open_uri(note_path: Path) -> str:
    encoded = urllib.parse.quote(str(note_path.resolve()).replace("\\", "/"), safe="")
    return f"obsidian://open?path={encoded}"
