from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import parse_qs, unquote, urlparse

import httpx


@dataclass
class ShareContext:
    input_url: str
    resolved_url: str
    note_id: str
    xsec_token: str
    xsec_source: str


def _maybe_add_scheme(url: str) -> str:
    raw = url.strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    return f"https://{raw}"


def _resolve_redirect(url: str, timeout: float = 15.0) -> str:
    parsed = urlparse(url)
    if "xhslink.com" not in parsed.netloc and "xhsurl" not in parsed.netloc:
        return url
    with httpx.Client(follow_redirects=True, timeout=timeout) as client:
        response = client.get(url)
        return str(response.url)


def _unwrap_login_redirect(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.path.startswith("/login"):
        return url
    qs = parse_qs(parsed.query)
    redirect_path = qs.get("redirectPath", [""])[0]
    if not redirect_path:
        return url
    return unquote(redirect_path)


def _extract_note_id(parsed) -> str:
    parts = [part for part in parsed.path.split("/") if part]

    # Prefer an ID-like path segment first (XHS note IDs are typically 24-char lowercase hex-like strings).
    id_like = re.compile(r"^[0-9a-z]{24}$")
    for part in reversed(parts):
        if id_like.match(part):
            return part

    for idx, part in enumerate(parts):
        if part in {"explore", "item"} and idx + 1 < len(parts):
            return parts[idx + 1]
        if part == "discovery" and idx + 2 < len(parts) and parts[idx + 1] == "item":
            return parts[idx + 2]
    if parts:
        return parts[-1]
    return ""


def parse_share_context(url: str) -> ShareContext:
    normalized = _maybe_add_scheme(url)
    redirected = _resolve_redirect(normalized)
    unwrapped = _unwrap_login_redirect(redirected)
    parsed = urlparse(unwrapped)
    query = parse_qs(parsed.query)

    note_id = _extract_note_id(parsed)
    if not note_id:
        raise ValueError(f"无法从链接解析 note_id: {url}")

    xsec_token = query.get("xsec_token", [""])[0]
    xsec_source = query.get("xsec_source", ["app_share"])[0] or "app_share"
    return ShareContext(
        input_url=url.strip(),
        resolved_url=unwrapped,
        note_id=note_id,
        xsec_token=xsec_token,
        xsec_source=xsec_source,
    )
