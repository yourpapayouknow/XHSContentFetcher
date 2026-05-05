from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .deepseek import generate_markdown_with_deepseek
from .fetcher import FetchedNote, XhsFetcher
from .markdown_writer import build_note_filename, write_markdown_note
from .media import MediaDownloader
from .ocr_engine import OcrResult, run_ocr_on_images
from .url_parser import ShareContext, parse_share_context
from .video_tools import extract_uniform_frames, maybe_downscale_to_1080


@dataclass
class WorkflowOptions:
    output_root: Path
    max_comment_pages: int = 20
    top_like_count: int = 10
    top_reply_count: int = 10
    max_sub_comments: int = 5
    frame_count: int = 8
    skip_ocr: bool = False
    skip_llm: bool = False
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"


@dataclass
class WorkflowResult:
    share_context: ShareContext
    fetched_note: FetchedNote
    note_path: Path
    image_paths: list[Path]
    video_path: Path | None
    frame_paths: list[Path]
    ocr_results: list[OcrResult]
    llm_used: bool


def run_pipeline(
    url: str,
    cookies: dict[str, str],
    options: WorkflowOptions,
) -> WorkflowResult:
    share_context = parse_share_context(url)
    fetcher = XhsFetcher(cookies=cookies)
    fetched = fetcher.fetch(
        share_context,
        max_comment_pages=options.max_comment_pages,
        top_like_count=options.top_like_count,
        top_reply_count=options.top_reply_count,
        max_sub_comments=options.max_sub_comments,
    )
    note_card = fetched.note_card

    note_slug = build_note_filename(note_card, share_context.note_id)
    note_dir = options.output_root / note_slug
    assets_dir = note_dir / "assets"
    note_path = note_dir / f"{note_slug}.md"
    images_dir = assets_dir / "images"
    video_dir = assets_dir / "video"
    frames_dir = assets_dir / "frames"

    with MediaDownloader() as downloader:
        image_paths = downloader.download_images(note_card, images_dir)
        video_path: Path | None = None
        frame_paths: list[Path] = []
        if note_card.get("type") == "video":
            raw_video = downloader.download_video(note_card, video_dir)
            scaled_video = video_dir / "video_1080p.mp4"
            video_path = maybe_downscale_to_1080(raw_video, scaled_video)
            frame_paths = extract_uniform_frames(video_path, frames_dir, frame_count=options.frame_count)

    ocr_results: list[OcrResult] = []
    if not options.skip_ocr and image_paths:
        ocr_results = run_ocr_on_images(image_paths)

    image_rel_paths = [path.relative_to(note_dir).as_posix() for path in image_paths]
    frame_rel_paths = [path.relative_to(note_dir).as_posix() for path in frame_paths]
    video_rel_path = video_path.relative_to(note_dir).as_posix() if video_path else None

    llm_markdown: str | None = None
    llm_used = False
    if not options.skip_llm:
        if not options.deepseek_api_key.strip():
            raise RuntimeError("未提供 DeepSeek API Key，无法生成学习报告。")
        llm_markdown = generate_markdown_with_deepseek(
            api_key=options.deepseek_api_key,
            base_url=options.deepseek_base_url,
            model=options.deepseek_model,
            share_context=share_context,
            note_card=note_card,
            comments=fetched.comments,
            top_liked_comments=fetched.top_liked_comments,
            top_replied_comments=fetched.top_replied_comments,
            sub_comments_map=fetched.sub_comments_map,
            ocr_results=ocr_results,
            image_rel_paths=image_rel_paths,
            frame_rel_paths=frame_rel_paths,
            video_rel_path=video_rel_path,
        )
        llm_used = True

    write_markdown_note(
        note_path=note_path,
        share_context=share_context,
        note_card=note_card,
        llm_markdown=llm_markdown,
        top_liked_comments=fetched.top_liked_comments,
        top_replied_comments=fetched.top_replied_comments,
        image_paths=image_paths,
        frame_paths=frame_paths,
        video_path=video_path,
        ocr_results=ocr_results,
    )

    return WorkflowResult(
        share_context=share_context,
        fetched_note=fetched,
        note_path=note_path,
        image_paths=image_paths,
        video_path=video_path,
        frame_paths=frame_paths,
        ocr_results=ocr_results,
        llm_used=llm_used,
    )
