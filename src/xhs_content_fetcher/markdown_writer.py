from __future__ import annotations

from pathlib import Path
from typing import Any

from .ocr_engine import OcrResult
from .url_parser import ShareContext
from .utils import slugify, timestamp_now, to_int


def _build_frontmatter(share_context: ShareContext, note_card: dict[str, Any]) -> str:
    user = note_card.get("user", {}) or {}
    tags = [tag.get("name", "") for tag in note_card.get("tag_list", []) if isinstance(tag, dict) and tag.get("name")]
    tag_lines = "\n".join(f"  - {tag}" for tag in tags[:20])
    if not tag_lines:
        tag_lines = "  - xiaohongshu"
    return (
        "---\n"
        f"title: \"{note_card.get('title', 'Untitled').replace('\"', '')}\"\n"
        f"note_id: \"{share_context.note_id}\"\n"
        f"author: \"{str(user.get('nickname', '')).replace('\"', '')}\"\n"
        f"source_url: \"{share_context.resolved_url}\"\n"
        f"fetched_at: \"{timestamp_now()}\"\n"
        f"note_type: \"{note_card.get('type', '')}\"\n"
        "tags:\n"
        f"{tag_lines}\n"
        "---\n"
    )


def _fallback_markdown(
    share_context: ShareContext,
    note_card: dict[str, Any],
    top_liked_comments: list[dict[str, Any]],
    top_replied_comments: list[dict[str, Any]],
) -> str:
    title = note_card.get("title") or f"XHS_{share_context.note_id}"
    desc = note_card.get("desc", "")
    interact = note_card.get("interact_info", {}) or {}
    lines = [
        f"# {title}",
        "",
        "## 1. 内容速览",
        f"- 来源链接：{share_context.resolved_url}",
        f"- 类型：{note_card.get('type', '')}",
        f"- 点赞：{interact.get('liked_count', 0)}",
        f"- 收藏：{interact.get('collected_count', 0)}",
        f"- 评论：{interact.get('comment_count', 0)}",
        "",
        "## 2. 原文摘要",
        desc if desc else "- 无正文描述",
        "",
        "## 3. 高赞评论",
    ]
    for item in top_liked_comments[:10]:
        user = (item.get("user_info") or {}).get("nickname", "匿名")
        lines.append(f"- [{user}] {item.get('content', '')}（赞 {to_int(item.get('like_count', 0))}）")
    lines.append("")
    lines.append("## 4. 高回复评论")
    for item in top_replied_comments[:10]:
        user = (item.get("user_info") or {}).get("nickname", "匿名")
        lines.append(f"- [{user}] {item.get('content', '')}（回复 {to_int(item.get('sub_comment_count', 0))}）")
    lines.append("")
    return "\n".join(lines)


def _embed_assets_section(note_path: Path, image_paths: list[Path], frame_paths: list[Path], video_path: Path | None) -> str:
    lines: list[str] = ["## 附件素材", ""]
    if image_paths:
        lines.append("### 原始图片")
        for path in image_paths:
            rel = path.relative_to(note_path.parent).as_posix()
            lines.append(f"- ![]({rel})")
        lines.append("")
    if frame_paths:
        lines.append("### 视频关键帧")
        for path in frame_paths:
            rel = path.relative_to(note_path.parent).as_posix()
            lines.append(f"- ![]({rel})")
        lines.append("")
    if video_path:
        rel = video_path.relative_to(note_path.parent).as_posix()
        lines.append("### 视频文件")
        lines.append(f"- [{video_path.name}]({rel})")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _embed_ocr_section(note_path: Path, ocr_results: list[OcrResult]) -> str:
    if not ocr_results:
        return ""
    lines = ["## OCR 提取", ""]
    for item in ocr_results:
        if not item.text.strip():
            continue
        rel = item.image_path.relative_to(note_path.parent).as_posix()
        lines.append(f"### {item.image_path.name}")
        lines.append(f"来源：`{rel}`")
        lines.append("")
        lines.append(item.text.strip())
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def build_note_filename(note_card: dict[str, Any], note_id: str) -> str:
    title = str(note_card.get("title") or "").strip()
    if title:
        return slugify(title, fallback=note_id)
    return note_id


def write_markdown_note(
    note_path: Path,
    share_context: ShareContext,
    note_card: dict[str, Any],
    llm_markdown: str | None,
    top_liked_comments: list[dict[str, Any]],
    top_replied_comments: list[dict[str, Any]],
    image_paths: list[Path],
    frame_paths: list[Path],
    video_path: Path | None,
    ocr_results: list[OcrResult],
) -> None:
    note_path.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = _build_frontmatter(share_context, note_card)
    if llm_markdown and llm_markdown.strip():
        body = llm_markdown.strip()
        merged = f"{frontmatter}\n{body}".strip() + "\n"
    else:
        body = _fallback_markdown(
            share_context,
            note_card,
            top_liked_comments,
            top_replied_comments,
        )
        assets = _embed_assets_section(note_path, image_paths, frame_paths, video_path)
        ocr_section = _embed_ocr_section(note_path, ocr_results)
        merged = f"{frontmatter}\n{body}\n\n{assets}\n{ocr_section}".strip() + "\n"
    note_path.write_text(merged, encoding="utf-8")
