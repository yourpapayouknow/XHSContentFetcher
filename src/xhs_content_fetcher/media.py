from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from .utils import ensure_dir, unique_keep_order

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    )
}


def _guess_extension(content_type: str, url: str, body: bytes) -> str:
    if content_type:
        normalized = content_type.split(";")[0].strip()
        guessed = mimetypes.guess_extension(normalized)
        if guessed:
            return guessed
    if len(body) >= 12:
        if body[:3] == b"\xFF\xD8\xFF":
            return ".jpg"
        if body[:8] == b"\x89PNG\r\n\x1a\n":
            return ".png"
        if body[:6] in (b"GIF87a", b"GIF89a"):
            return ".gif"
        if body[:2] == b"BM":
            return ".bmp"
        if body[:4] == b"RIFF" and body[8:12] == b"WEBP":
            return ".webp"
        if body[4:12] in (b"ftypavif", b"ftypavis"):
            return ".avif"
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix
    if suffix:
        return suffix
    return ".bin"


def _candidate_image_urls(image_item: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for key in ("url_default", "url_pre", "url"):
        value = str(image_item.get(key, "")).strip()
        if value.startswith("http"):
            urls.append(value)
    for info in image_item.get("info_list", []) or []:
        if not isinstance(info, dict):
            continue
        value = str(info.get("url", "")).strip()
        if value.startswith("http"):
            urls.append(value)
    return unique_keep_order(urls)


def select_best_video_stream(note_card: dict[str, Any]) -> dict[str, Any]:
    video = note_card.get("video", {}) or {}
    stream = (video.get("media", {}) or {}).get("stream", {}) or {}
    priority = ("h264", "h265", "av1", "h266")
    all_streams: list[dict[str, Any]] = []
    for codec in priority:
        for item in stream.get(codec, []) or []:
            if isinstance(item, dict):
                all_streams.append(item)
    if not all_streams:
        raise RuntimeError("未找到可下载视频流。")
    all_streams.sort(
        key=lambda s: (
            int(s.get("width", 0)) * int(s.get("height", 0)),
            int(s.get("avg_bitrate", 0)),
        ),
        reverse=True,
    )
    return all_streams[0]


class MediaDownloader:
    def __init__(self, timeout: float = 60.0):
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers=DEFAULT_HEADERS,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "MediaDownloader":
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def _download_to_stem(self, urls: list[str], output_dir: Path, stem: str) -> Path:
        ensure_dir(output_dir)
        last_error: Exception | None = None
        for url in urls:
            try:
                response = self._client.get(url)
                response.raise_for_status()
                ext = _guess_extension(
                    response.headers.get("content-type", ""),
                    str(response.url),
                    response.content,
                )
                target = output_dir / f"{stem}{ext}"
                target.write_bytes(response.content)
                return target
            except Exception as exc:  # pragma: no cover - network branch
                last_error = exc
                continue
        raise RuntimeError(f"下载失败，候选链接均不可用: {urls}") from last_error

    def download_images(self, note_card: dict[str, Any], output_dir: Path) -> list[Path]:
        image_items = note_card.get("image_list", []) or []
        downloaded: list[Path] = []
        for idx, image_item in enumerate(image_items, start=1):
            candidates = _candidate_image_urls(image_item)
            if not candidates:
                continue
            stem = f"image_{idx:02d}"
            for old_file in output_dir.glob(f"{stem}.*"):
                old_file.unlink(missing_ok=True)
            file_path = self._download_to_stem(candidates, output_dir, stem)
            downloaded.append(file_path)
        return downloaded

    def download_video(self, note_card: dict[str, Any], output_dir: Path) -> Path:
        stream = select_best_video_stream(note_card)
        candidates = [str(stream.get("master_url", "")).strip()]
        for backup in stream.get("backup_urls", []) or []:
            candidates.append(str(backup).strip())
        candidates = [item for item in unique_keep_order(candidates) if item.startswith("http")]
        if not candidates:
            raise RuntimeError("视频流缺少可下载 URL。")
        for old_file in output_dir.glob("video_raw.*"):
            old_file.unlink(missing_ok=True)
        return self._download_to_stem(candidates, output_dir, "video_raw")
