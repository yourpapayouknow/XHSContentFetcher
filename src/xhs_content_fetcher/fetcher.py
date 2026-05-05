from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from xhs_cli.client import XhsClient

from .url_parser import ShareContext
from .utils import to_int


@dataclass
class FetchedNote:
    note_card: dict[str, Any]
    comments: list[dict[str, Any]]
    top_liked_comments: list[dict[str, Any]]
    top_replied_comments: list[dict[str, Any]]
    sub_comments_map: dict[str, list[dict[str, Any]]]


def sort_comments_by_like(comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        comments,
        key=lambda c: (
            to_int(c.get("like_count", 0)),
            to_int(c.get("sub_comment_count", 0)),
        ),
        reverse=True,
    )


def sort_comments_by_reply(comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        comments,
        key=lambda c: (
            to_int(c.get("sub_comment_count", 0)),
            to_int(c.get("like_count", 0)),
        ),
        reverse=True,
    )


def extract_note_card(detail: dict[str, Any]) -> dict[str, Any]:
    items = detail.get("items", [])
    if not items:
        raise RuntimeError("帖子详情为空，无法提取 note_card。")
    note_card = items[0].get("note_card", {})
    if not note_card:
        raise RuntimeError("未在返回结果中找到 note_card。")
    return note_card


class XhsFetcher:
    def __init__(self, cookies: dict[str, str], request_delay: float = 0.6, max_retries: int = 3):
        self.cookies = dict(cookies)
        self.request_delay = request_delay
        self.max_retries = max_retries

    def _fetch_comments(
        self,
        client: XhsClient,
        context: ShareContext,
        max_pages: int,
    ) -> list[dict[str, Any]]:
        all_comments: list[dict[str, Any]] = []
        cursor = ""
        for _ in range(max_pages):
            data = client.get_comments(
                context.note_id,
                cursor=cursor,
                xsec_token=context.xsec_token,
                xsec_source=context.xsec_source,
            )
            page_comments = data.get("comments", []) or []
            all_comments.extend(page_comments)
            has_more = bool(data.get("has_more"))
            cursor = str(data.get("cursor", "") or "")
            if not has_more or not cursor:
                break
        return all_comments

    def _fetch_sub_comments(
        self,
        client: XhsClient,
        context: ShareContext,
        top_replied_comments: list[dict[str, Any]],
        max_sub_comments: int,
    ) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {}
        for comment in top_replied_comments:
            comment_id = str(comment.get("id", "")).strip()
            if not comment_id:
                continue
            if to_int(comment.get("sub_comment_count", 0)) <= 0:
                continue
            try:
                data = client.get_sub_comments(
                    context.note_id,
                    comment_id,
                    cursor="",
                )
                result[comment_id] = (data.get("comments", []) or [])[:max_sub_comments]
            except Exception:
                # 某些评论在子评论接口会触发风控或返回空错误，忽略不阻断主流程。
                continue
        return result

    def fetch(
        self,
        context: ShareContext,
        max_comment_pages: int = 20,
        top_like_count: int = 10,
        top_reply_count: int = 10,
        max_sub_comments: int = 5,
    ) -> FetchedNote:
        with XhsClient(
            cookies=self.cookies.copy(),
            request_delay=self.request_delay,
            max_retries=self.max_retries,
        ) as client:
            detail = client.get_note_detail(
                context.note_id,
                xsec_token=context.xsec_token,
                xsec_source=context.xsec_source,
            )
            note_card = extract_note_card(detail)
            comments = self._fetch_comments(client, context, max_comment_pages)
            top_liked = sort_comments_by_like(comments)[:top_like_count]
            top_replied = sort_comments_by_reply(comments)[:top_reply_count]
            sub_comments_map = self._fetch_sub_comments(
                client,
                context,
                top_replied,
                max_sub_comments=max_sub_comments,
            )
            return FetchedNote(
                note_card=note_card,
                comments=comments,
                top_liked_comments=top_liked,
                top_replied_comments=top_replied,
                sub_comments_map=sub_comments_map,
            )
