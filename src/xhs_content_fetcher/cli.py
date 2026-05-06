from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .config import AppConfig, load_config, mask_cookie, parse_cookie_string, save_config
from .obsidian import open_note_in_obsidian
from .workflow import WorkflowOptions, run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xhs-fetch",
        description="输入小红书分享链接，输出可直接导入 Obsidian 的学习报告笔记。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="执行完整抓取与笔记生成流程")
    run_parser.add_argument("url", help="小红书分享链接（图文/视频均可）")
    run_parser.add_argument("--cookie", default="", help="小红书 Cookie 字符串")
    run_parser.add_argument("--output-root", default="output", help="输出根目录（不指定 vault 时生效）")
    run_parser.add_argument("--vault-dir", default="", help="Obsidian Vault 目录（指定后将直接输出到该目录）")
    run_parser.add_argument("--notes-folder", default="", help="Vault 内笔记目录，默认读取配置")
    run_parser.add_argument("--max-comment-pages", type=int, default=20, help="评论抓取最大分页数")
    run_parser.add_argument("--top-like-count", type=int, default=10, help="高赞评论保留条数")
    run_parser.add_argument("--top-reply-count", type=int, default=10, help="高回复评论保留条数")
    run_parser.add_argument("--max-sub-comments", type=int, default=5, help="每条高回复评论抓取的子评论上限")
    run_parser.add_argument("--frame-count", type=int, default=8, help="视频关键帧数量")
    run_parser.add_argument("--skip-ocr", action="store_true", help="跳过 OCR")
    run_parser.add_argument("--skip-llm", action="store_true", help="跳过 DeepSeek 总结，输出基础笔记")
    run_parser.add_argument("--deepseek-api-key", default="", help="DeepSeek API Key")
    run_parser.add_argument("--deepseek-base-url", default="", help="DeepSeek API Base URL")
    run_parser.add_argument("--deepseek-model", default="", help="DeepSeek 模型名")
    run_parser.add_argument("--open-obsidian", action="store_true", help="生成后尝试调用 Obsidian CLI 打开笔记")
    run_parser.add_argument("--obsidian-cli-cmd", default="", help="Obsidian CLI 命令名，默认 obsidian")

    config_parser = subparsers.add_parser("config", help="管理本地配置")
    config_sub = config_parser.add_subparsers(dest="config_command", required=True)

    cfg_set_cookie = config_sub.add_parser("set-cookie", help="保存 Cookie 到本地配置")
    cfg_set_cookie.add_argument("--cookie", required=True, help="Cookie 字符串")

    cfg_clear_cookie = config_sub.add_parser("clear-cookie", help="清空本地 Cookie")
    cfg_clear_cookie.set_defaults(dummy=True)

    cfg_set_key = config_sub.add_parser("set-deepseek-key", help="保存 DeepSeek API Key")
    cfg_set_key.add_argument("--api-key", required=True, help="DeepSeek API Key")

    cfg_show = config_sub.add_parser("show", help="查看当前配置")
    cfg_show.set_defaults(dummy=True)

    return parser


def _resolve_cookie(raw_cookie: str, config: AppConfig) -> dict[str, str]:
    cookie_str = raw_cookie.strip() or os.getenv("XHS_COOKIE", "").strip() or config.cookie.strip()
    if not cookie_str:
        raise RuntimeError(
            "未提供 Cookie。请通过 --cookie 传入，或执行 `xhs-fetch config set-cookie --cookie \"...\"` 保存。"
        )
    cookies = parse_cookie_string(cookie_str)
    if not cookies.get("a1"):
        raise RuntimeError("Cookie 缺少 `a1` 字段，请重新登录后复制完整 Cookie。")
    return cookies


def _run_config(args: argparse.Namespace) -> int:
    config = load_config()
    cmd = args.config_command
    if cmd == "set-cookie":
        config.cookie = args.cookie.strip()
        save_config(config)
        print("Cookie 已保存到本地配置。")
        return 0
    if cmd == "clear-cookie":
        config.cookie = ""
        save_config(config)
        print("本地 Cookie 已清空。")
        return 0
    if cmd == "set-deepseek-key":
        config.deepseek_api_key = args.api_key.strip()
        save_config(config)
        print("DeepSeek API Key 已保存到本地配置。")
        return 0
    if cmd == "show":
        masked_cookie = mask_cookie(config.cookie) if config.cookie else "(empty)"
        masked_key = mask_cookie(config.deepseek_api_key) if config.deepseek_api_key else "(empty)"
        print(f"cookie: {masked_cookie}")
        print(f"deepseek_api_key: {masked_key}")
        print(f"deepseek_base_url: {config.deepseek_base_url}")
        print(f"deepseek_model: {config.deepseek_model}")
        print(f"notes_folder: {config.notes_folder}")
        print(f"obsidian_cli_cmd: {config.obsidian_cli_cmd}")
        return 0
    raise RuntimeError(f"未知 config 子命令: {cmd}")


def _run_pipeline(args: argparse.Namespace) -> int:
    config = load_config()
    cookies = _resolve_cookie(args.cookie, config)

    notes_folder = (args.notes_folder or config.notes_folder).strip() or "XHS笔记"
    if args.vault_dir.strip():
        output_root = Path(args.vault_dir).expanduser().resolve() / notes_folder
    else:
        output_root = Path(args.output_root).expanduser().resolve()

    deepseek_api_key = (
        args.deepseek_api_key.strip()
        or os.getenv("DEEPSEEK_API_KEY", "").strip()
        or config.deepseek_api_key.strip()
    )
    deepseek_base_url = (args.deepseek_base_url.strip() or config.deepseek_base_url).strip()
    deepseek_model = (args.deepseek_model.strip() or config.deepseek_model).strip()

    options = WorkflowOptions(
        output_root=output_root,
        max_comment_pages=args.max_comment_pages,
        top_like_count=args.top_like_count,
        top_reply_count=args.top_reply_count,
        max_sub_comments=args.max_sub_comments,
        frame_count=args.frame_count,
        skip_ocr=args.skip_ocr,
        skip_llm=args.skip_llm,
        deepseek_api_key=deepseek_api_key,
        deepseek_base_url=deepseek_base_url,
        deepseek_model=deepseek_model,
    )
    result = run_pipeline(args.url, cookies, options)

    print("处理完成：")
    print(f"- note_id: {result.share_context.note_id}")
    print(f"- 笔记文件: {result.note_path}")
    print(f"- 图片数量: {len(result.image_paths)}")
    print(f"- 评论数量: {len(result.fetched_note.comments)}")
    if result.video_path:
        print(f"- 视频文件: {result.video_path}")
        print(f"- 关键帧数量: {len(result.frame_paths)}")
    if result.ocr_results:
        print(f"- OCR 图片数量: {len(result.ocr_results)}")
    print(f"- DeepSeek 生成: {'是' if result.llm_used else '否'}")

    if args.open_obsidian:
        cli_cmd = (args.obsidian_cli_cmd or config.obsidian_cli_cmd).strip() or "obsidian"
        ok, msg = open_note_in_obsidian(result.note_path, cli_cmd=cli_cmd)
        print(f"- Obsidian 打开: {'成功' if ok else '失败'} ({msg})")
    return 0


def main(argv: list[str] | None = None) -> int:
    # Load environment variables from project root .env if present.
    load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "config":
            return _run_config(args)
        if args.command == "run":
            return _run_pipeline(args)
        parser.print_help()
        return 1
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
