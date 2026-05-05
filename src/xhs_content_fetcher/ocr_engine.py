from __future__ import annotations

import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class OcrResult:
    image_path: Path
    text: str


class PaddleOcrEngine:
    def __init__(self, lang: str = "ch"):
        os.environ.setdefault("FLAGS_use_mkldnn", "0")
        os.environ.setdefault("ONEDNN_MAX_CPU_ISA", "DEFAULT")

        try:
            from paddleocr import PaddleOCR  # type: ignore
        except ImportError as exc:  # pragma: no cover - env dependent
            raise RuntimeError(
                "未安装 paddleocr。请执行 `pip install paddleocr` 后重试。"
            ) from exc
        self._ocr = None
        init_attempts = [
            {"lang": lang, "use_angle_cls": True, "show_log": False, "enable_mkldnn": False},
            {"lang": lang, "use_textline_orientation": True, "enable_mkldnn": False},
            {"lang": lang, "enable_mkldnn": False},
            {"lang": lang},
        ]
        last_error: Exception | None = None
        for kwargs in init_attempts:
            try:
                self._ocr = PaddleOCR(**kwargs)
                break
            except Exception as exc:  # pragma: no cover - depends on paddleocr version
                last_error = exc
                continue
        if self._ocr is None:
            raise RuntimeError(f"PaddleOCR 初始化失败: {last_error}")

    @staticmethod
    def _extract_text(raw: Any) -> str:
        lines: list[str] = []

        def walk(node: Any) -> None:
            if node is None:
                return
            if isinstance(node, str):
                stripped = node.strip()
                if stripped:
                    lines.append(stripped)
                return
            if isinstance(node, dict):
                for key in ("rec_text", "text"):
                    value = node.get(key)
                    if isinstance(value, str) and value.strip():
                        lines.append(value.strip())
                for value in node.values():
                    walk(value)
                return
            if isinstance(node, (list, tuple)):
                if len(node) == 2 and isinstance(node[1], (list, tuple)) and node[1]:
                    candidate = node[1][0]
                    if isinstance(candidate, str) and candidate.strip():
                        lines.append(candidate.strip())
                for item in node:
                    walk(item)
                return

        walk(raw)
        unique: list[str] = []
        seen: set[str] = set()
        for line in lines:
            if re.match(r"^[A-Za-z]:\\", line):
                continue
            if "/tmp/" in line or "\\tmp\\" in line.lower():
                continue
            if "xhs_ocr_" in line:
                continue
            if line not in seen:
                seen.add(line)
                unique.append(line)
        return "\n".join(unique)

    def run(self, image_path: Path) -> OcrResult:
        source_path = image_path
        with tempfile.TemporaryDirectory(prefix="xhs_ocr_") as temp_dir:
            temp_path = Path(temp_dir) / f"input{image_path.suffix or '.img'}"
            shutil.copyfile(image_path, temp_path)
            source_path = temp_path
            try:
                raw = self._ocr.ocr(str(source_path), cls=True)
            except Exception:
                raw = self._ocr.ocr(str(source_path))
        return OcrResult(image_path=image_path, text=self._extract_text(raw))


def run_ocr_on_images(image_paths: list[Path], lang: str = "ch") -> list[OcrResult]:
    if not image_paths:
        return []
    engine = PaddleOcrEngine(lang=lang)
    results: list[OcrResult] = []
    for image_path in image_paths:
        results.append(engine.run(image_path))
    return results
