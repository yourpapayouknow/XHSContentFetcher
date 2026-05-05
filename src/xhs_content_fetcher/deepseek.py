from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openai import OpenAI

from .ocr_engine import OcrResult
from .url_parser import ShareContext
from .utils import to_int

TEMPLATE_CANDIDATE_FILES = (
    "Tempate.md",
    "Template.md",
    "template.md",
)


SYSTEM_PROMPT = """你是我的学习型研究助理，现在要代我写学习笔记报告。

写作身份与口吻：
1. 全文统一使用第一人称口吻。
2. 不要对读者说“你/大家/我们来”，不要教学腔。
3. 语气自然、克制、直给，避免口号式和模板式表达。

内容质量要求：
1. 重点是“解读”和“拆解知识点”，不是复述原文。
2. 禁止直接照搬，应该按块整理梳理，保持逻辑。
3. 每个关键知识点至少讲清：是什么、为什么。
4. 评论区要提炼“共识-分歧-可执行动作”，不能只罗列评论。
5. 严禁编造素材中不存在的事实、数据、结论。

图文要求：
1. 必须图文并茂，图片/视频帧要内嵌在对应分析段落中。
2. 每张图（或关键帧）后紧跟解释，不允许把所有图堆到文末清单。
3. 图片只允许使用提供的相对路径，格式 `![](assets/...)`。

输出要求：
1. 只输出 Markdown 正文，不要三引号代码块。
2. 保持强逻辑分点结构，标题清晰，便于复盘。
"""


def load_template_text() -> str:
    for name in TEMPLATE_CANDIDATE_FILES:
        path = Path.cwd() / name
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    raise RuntimeError(
        "未找到模板文件。请在项目根目录放置 Tempate.md（或 Template.md / template.md）。"
    )


def _simplify_comment(comment: dict[str, Any]) -> dict[str, Any]:
    user = comment.get("user_info", {}) or {}
    return {
        "id": str(comment.get("id", "")),
        "user": str(user.get("nickname", "匿名")),
        "content": str(comment.get("content", "")).strip(),
        "like_count": to_int(comment.get("like_count", 0)),
        "reply_count": to_int(comment.get("sub_comment_count", 0)),
        "ip_location": str(comment.get("ip_location", "")),
    }


def _build_assets_payload(
    image_rel_paths: list[str],
    frame_rel_paths: list[str],
    video_rel_path: str | None,
    ocr_results: list[OcrResult],
) -> dict[str, Any]:
    ocr_by_name = {
        item.image_path.name: item.text.strip()
        for item in ocr_results
        if item.text.strip()
    }
    images = [
        {
            "path": rel_path,
            "ocr_text": ocr_by_name.get(Path(rel_path).name, ""),
        }
        for rel_path in image_rel_paths
    ]
    frames = [{"path": rel_path} for rel_path in frame_rel_paths]
    return {
        "images": images,
        "video_frames": frames,
        "video_file": video_rel_path or "",
    }


def build_user_prompt(
    share_context: ShareContext,
    note_card: dict[str, Any],
    comments: list[dict[str, Any]],
    top_liked_comments: list[dict[str, Any]],
    top_replied_comments: list[dict[str, Any]],
    sub_comments_map: dict[str, list[dict[str, Any]]],
    ocr_results: list[OcrResult],
    image_rel_paths: list[str],
    frame_rel_paths: list[str],
    video_rel_path: str | None,
) -> str:
    user = note_card.get("user", {}) or {}
    assets = _build_assets_payload(
        image_rel_paths=image_rel_paths,
        frame_rel_paths=frame_rel_paths,
        video_rel_path=video_rel_path,
        ocr_results=ocr_results,
    )
    payload = {
        "source": {
            "input_url": share_context.input_url,
            "resolved_url": share_context.resolved_url,
            "note_id": share_context.note_id,
            "xsec_source": share_context.xsec_source,
        },
        "post": {
            "type": note_card.get("type"),
            "title": note_card.get("title", ""),
            "desc": note_card.get("desc", ""),
            "author": user.get("nickname", ""),
            "author_id": user.get("user_id", ""),
            "ip_location": note_card.get("ip_location", ""),
            "publish_time": note_card.get("time", 0),
            "stats": note_card.get("interact_info", {}),
            "tags": [tag.get("name", "") for tag in note_card.get("tag_list", []) if isinstance(tag, dict)],
        },
        "comments": {
            "total": len(comments),
            "top_liked": [_simplify_comment(c) for c in top_liked_comments],
            "top_replied": [_simplify_comment(c) for c in top_replied_comments],
            "sub_comments_map": {
                key: [_simplify_comment(item) for item in value]
                for key, value in sub_comments_map.items()
            },
        },
        "assets": assets,
    }
    template_text = load_template_text()

    return (
        "下面是抓取到的结构化数据（JSON）。\n"
        "要求：\n"
        "1) 严格按我给的模板章节与顺序输出。\n"
        "2) 只基于数据写，不要编造。\n"
        "3) 不要大段照搬原文。\n"
        "4) 必须第一人称口吻。\n"
        "5) 模板中出现 `assets.images[*].path` 时，请替换为真实图片路径并内联图片。\n"
        "6) 模板中出现“缩放50%”时，使用 `<img src=\"路径\" width=\"50%\" />`。\n"
        "7) 模板中出现 `assets.video_frames[*].path` 时，替换为真实关键帧路径并内联。\n"
        "8) 如果是图文帖子，没有视频就省略视频小节。\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "下面是我指定的模板，请严格遵循：\n\n"
        f"{template_text}\n"
    )


def generate_markdown_with_deepseek(
    api_key: str,
    base_url: str,
    model: str,
    share_context: ShareContext,
    note_card: dict[str, Any],
    comments: list[dict[str, Any]],
    top_liked_comments: list[dict[str, Any]],
    top_replied_comments: list[dict[str, Any]],
    sub_comments_map: dict[str, list[dict[str, Any]]],
    ocr_results: list[OcrResult],
    image_rel_paths: list[str],
    frame_rel_paths: list[str],
    video_rel_path: str | None,
) -> str:
    client = OpenAI(api_key=api_key, base_url=base_url)
    prompt = build_user_prompt(
        share_context=share_context,
        note_card=note_card,
        comments=comments,
        top_liked_comments=top_liked_comments,
        top_replied_comments=top_replied_comments,
        sub_comments_map=sub_comments_map,
        ocr_results=ocr_results,
        image_rel_paths=image_rel_paths,
        frame_rel_paths=frame_rel_paths,
        video_rel_path=video_rel_path,
    )
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        reasoning_effort="max",
        extra_body={"thinking": {"type": "enabled"}},
    )
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("DeepSeek 返回为空，未生成 Markdown。")
    return content.strip()
