from __future__ import annotations

import json
import re
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

REQUIRED_TOP_LEVEL_SECTIONS = [
    "## 来源",
    "## 概要",
    "## 概念详解",
    "## 详细解读",
    "## 评论区观点",
    "## 综合执行建议",
    "## 有待继续验证的问题",
]

FORBIDDEN_PLACEHOLDER_SNIPPETS = [
    "assets.images[*].path",
    "assets.video_frames[*].path",
    "`assets.images[*].path`",
    "`assets.video_frames[*].path`",
    "[[占位符]]",
]

FORBIDDEN_GENERIC_PLACEHOLDERS = [
    "观点一",
    "观点二",
    "观点三",
    "结论一",
    "结论二",
    "结论三",
    "关键概念A",
    "关键概念B",
    "评论一",
    "评论二",
    "回复1",
    "回复2",
    "步骤一",
    "步骤二",
    "步骤三",
    "问题一",
    "问题二",
    "问题三",
    "点一",
    "点二",
    "点三",
    "方法一",
    "方法二",
    "方法三",
]


SYSTEM_PROMPT = """你是我的学习型研究助理，现在要代我写学习笔记报告。

写作身份与口吻：
1. 全文统一使用第一人称口吻。
2. 不要对读者说“你/大家/我们来”，不要教学腔。
3. 语气自然、克制、直给，避免口号式和模板式表达。

内容质量要求：
1. 重点是“解读”和“拆解知识点”，不是复述原文。
2. 禁止直接照搬，应该按块整理梳理，保持逻辑。
3. 每个关键知识点至少讲清：是什么、为什么。
4. 评论区必须“按评论逐条排开”写，格式是“### 评论N（昵称）+ 该评论下的回复要点”，不要写“共识/分歧”这种聚合标题。
5. 严禁编造素材中不存在的事实、数据、结论。
6. 模板里所有“示例占位词”都必须替换成真实内容，禁止出现“关键概念A/观点一/步骤一/问题一/评论一/回复1/……”等占位表达。
7. 模板里出现省略号（……）表示要继续展开，不是停在三条；能展开的地方尽量展开到 5 条以上，除非原始素材确实不足。

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


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3:
            return "\n".join(lines[1:-1]).strip()
    return stripped


def _validate_markdown_output(markdown: str) -> list[str]:
    issues: list[str] = []
    normalized = markdown.strip()
    if not normalized:
        return ["输出为空。"]

    last_index = -1
    for section in REQUIRED_TOP_LEVEL_SECTIONS:
        idx = normalized.find(section)
        if idx == -1:
            issues.append(f"缺少必需章节：{section}")
            continue
        if idx < last_index:
            issues.append(f"章节顺序错误：{section}")
        last_index = idx

    for token in FORBIDDEN_PLACEHOLDER_SNIPPETS:
        if token in normalized:
            issues.append(f"仍保留未替换占位符：{token}")

    for token in FORBIDDEN_GENERIC_PLACEHOLDERS:
        if token in normalized:
            issues.append(f"仍保留模板示例词：{token}")

    if "### 问题A" in normalized or "### 问题B" in normalized:
        issues.append("详细解读中仍保留模板占位标题（问题A/问题B），未替换为具体问题。")

    comment_section = _extract_section(
        normalized,
        start_header="## 评论区观点",
        end_header="## 综合执行建议",
    )
    if comment_section:
        if "### 共识" in comment_section or "### 分歧" in comment_section:
            issues.append("评论区观点仍在使用“共识/分歧”聚合写法，未按评论逐条排开。")
        comment_heading_count = len(re.findall(r"(?m)^###\s*评论", comment_section))
        if comment_heading_count < 3:
            issues.append("评论区观点展开不足：至少需要 3 条“### 评论N（昵称）”。")
    else:
        issues.append("无法解析评论区观点章节。")

    summary_section = _extract_section(
        normalized,
        start_header="## 综合执行建议",
        end_header="## 有待继续验证的问题",
    )
    if summary_section:
        step_count = len(re.findall(r"(?m)^\d+\.\s", summary_section))
        if step_count < 5:
            issues.append("综合执行建议条目过少：至少需要 5 条。")

    pending_section = _extract_section(
        normalized,
        start_header="## 有待继续验证的问题",
        end_header=None,
    )
    if pending_section:
        question_count = len(re.findall(r"(?m)^\d+\.\s", pending_section))
        if question_count < 5:
            issues.append("有待继续验证的问题条目过少：至少需要 5 条。")

    if "<img " not in normalized and "![](" not in normalized:
        issues.append("缺少图片内联展示。")

    return issues


def _extract_section(text: str, start_header: str, end_header: str | None) -> str:
    start_idx = text.find(start_header)
    if start_idx == -1:
        return ""
    if not end_header:
        return text[start_idx:]
    end_idx = text.find(end_header, start_idx + len(start_header))
    if end_idx == -1:
        return text[start_idx:]
    return text[start_idx:end_idx]


def _repair_markdown_once(
    client: OpenAI,
    model: str,
    template_text: str,
    original_prompt: str,
    draft_markdown: str,
    issues: list[str],
) -> str:
    repair_prompt = (
        "你上一次输出没有严格满足模板要求，请仅输出修订后的 Markdown 正文。\n"
        "必须修复的问题：\n"
        + "\n".join(f"- {item}" for item in issues)
        + "\n\n"
        "再次强调：\n"
        "1) 必须保留模板的章节顺序与一级/二级结构。\n"
        "2) 必须替换所有占位符与示例标题，不允许原样保留。\n"
        "3) 图片/关键帧必须内联到对应说明段落。\n"
        "4) 评论区必须按“### 评论N（昵称）”逐条展开，并包含回复要点。\n"
        "5) 模板中带省略号的地方要继续展开，不要停在三条。\n"
        "6) 只输出 Markdown，不要解释。\n\n"
        "模板如下：\n"
        f"{template_text}\n\n"
        "你上一次草稿如下：\n"
        f"{draft_markdown}\n\n"
        "原始任务与数据如下：\n"
        f"{original_prompt}"
    )
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": repair_prompt},
        ],
        reasoning_effort="max",
        extra_body={"thinking": {"type": "enabled"}},
    )
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("DeepSeek 修订返回为空，未生成 Markdown。")
    return _strip_code_fences(content)


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
        "9) 评论区观点必须按评论逐条写：`### 评论1（昵称）`、`### 评论2（昵称）`……，每条下写该评论和回复要点；禁止写“共识/分歧/可执行动作”聚合小节。\n"
        "10) 模板里的占位示例词（如“关键概念A/观点一/评论一/回复1/步骤一/问题一/点一/方法一/……”）必须全部替换掉。\n"
        "11) 模板中的省略号表示继续展开：可展开部分尽量写到 5 条以上，除非数据不足。\n\n"
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
    template_text = load_template_text()
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
    cleaned = _strip_code_fences(content)
    issues = _validate_markdown_output(cleaned)
    retry = 0
    while issues and retry < 2:
        cleaned = _repair_markdown_once(
            client=client,
            model=model,
            template_text=template_text,
            original_prompt=prompt,
            draft_markdown=cleaned,
            issues=issues,
        )
        issues = _validate_markdown_output(cleaned)
        retry += 1
    if issues:
        raise RuntimeError("DeepSeek 输出仍未满足模板约束: " + "; ".join(issues))
    return cleaned.strip()
