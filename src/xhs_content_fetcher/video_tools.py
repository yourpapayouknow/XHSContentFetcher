from __future__ import annotations

import json
import shutil
from pathlib import Path

from .utils import ensure_dir, run_command


def _require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"未找到可执行文件 `{name}`，请先安装后重试。")
    return path


def ffprobe_video(video_path: Path) -> dict:
    ffprobe_bin = _require_binary("ffprobe")
    result = run_command(
        [
            ffprobe_bin,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(video_path),
        ]
    )
    return json.loads(result.stdout)


def get_video_dimensions(video_path: Path) -> tuple[int, int]:
    probe = ffprobe_video(video_path)
    streams = probe.get("streams", [])
    for stream in streams:
        if stream.get("codec_type") == "video":
            return int(stream.get("width", 0)), int(stream.get("height", 0))
    return 0, 0


def get_video_duration(video_path: Path) -> float:
    probe = ffprobe_video(video_path)
    fmt = probe.get("format", {})
    try:
        return float(fmt.get("duration", 0.0))
    except (TypeError, ValueError):
        return 0.0


def maybe_downscale_to_1080(input_path: Path, output_path: Path) -> Path:
    width, height = get_video_dimensions(input_path)
    if width <= 0 or height <= 0:
        return input_path

    if width >= height:
        should_scale = height > 1080
        scale_filter = "scale=-2:1080"
    else:
        should_scale = width > 1080
        scale_filter = "scale=1080:-2"

    if not should_scale:
        return input_path

    ffmpeg_bin = _require_binary("ffmpeg")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_command(
        [
            ffmpeg_bin,
            "-y",
            "-i",
            str(input_path),
            "-vf",
            scale_filter,
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "22",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            str(output_path),
        ]
    )
    return output_path


def extract_uniform_frames(video_path: Path, output_dir: Path, frame_count: int = 8) -> list[Path]:
    ffmpeg_bin = _require_binary("ffmpeg")
    ensure_dir(output_dir)

    duration = get_video_duration(video_path)
    if duration <= 0:
        return []

    frame_paths: list[Path] = []
    for idx in range(frame_count):
        second = duration * (idx + 1) / (frame_count + 1)
        frame_path = output_dir / f"frame_{idx + 1:02d}.jpg"
        run_command(
            [
                ffmpeg_bin,
                "-y",
                "-ss",
                f"{second:.3f}",
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(frame_path),
            ],
            check=True,
        )
        if frame_path.exists():
            frame_paths.append(frame_path)
    return frame_paths
