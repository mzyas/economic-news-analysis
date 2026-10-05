#!/usr/bin/env python3
"""Render a markdown briefing as himalaya MML.

Usage:
    python tools/email_render.py briefing.md --from a@example.com \
      --to b@example.com --subject "财经消息 日报"
    python tools/email_render.py briefing.md -o out.mml --from a@example.com \
      --to b@example.com --subject "财经消息 日报"
"""

import argparse
import re
import sys
from pathlib import Path
from collections.abc import Sequence


NEWS_TABLE_HEADER = ["重要性", "地区", "主题", "新闻内容", "核心信号", "关注资产"]


def _split_md_row(line: str) -> list[str]:
    return [c.strip() for c in line.split("|")[1:-1]]


def _trim_news_cell(cell: str) -> str:
    """Keep the title, source and timestamp clauses; drop the summary prose."""
    clauses = cell.split("；")
    kept = [c for i, c in enumerate(clauses) if i == 0 or "来源：" in c or "🕒" in c]
    return "；".join(kept) if kept else cell


def _truncate_signal(cell: str, limit: int = 40) -> str:
    """Trim a 核心信号 cell to <= limit chars, cutting at clause boundaries."""
    if len(cell) <= limit:
        return cell
    out: list[str] = []
    total = 0
    for part in cell.split("；"):
        add = len(part) + (1 if out else 0)
        if total + add > limit:
            break
        out.append(part)
        total += add
    if not out:
        return cell[: limit - 1] + "…"
    return "；".join(out) + "…"


def slim_news_tables(text: str) -> str:
    """Slim the 6-column news tables for email bodies: merge 地区 into 主题
    (6 cols → 5), drop summary prose from 新闻内容, truncate 核心信号.
    Idempotent — slimmed tables no longer match the header pattern."""
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("|") and _split_md_row(line) == NEWS_TABLE_HEADER:
            out.append("| 重要性 | 主题 | 新闻内容 | 核心信号 | 关注资产 |")
            i += 1
            if i < len(lines) and re.match(r"^\|[\s\-:|]+\|$", lines[i]):
                i += 1
            while i < len(lines) and lines[i].strip().startswith("|"):
                row = _split_md_row(lines[i])
                if len(row) == 6:
                    topic = f"{row[1]}·{row[2]}" if row[1] else row[2]
                    row = [
                        row[0],
                        topic,
                        _trim_news_cell(row[3]),
                        _truncate_signal(row[4]),
                        row[5],
                    ]
                out.append("| " + " | ".join(row) + " |")
                i += 1
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def _strip_trend_section(text: str) -> str:
    """Remove the '## 市场趋势表' markdown section (heading + as-of line +
    table) — build_combined_email_html already renders it as a styled table."""
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        if re.match(r"^##\s*市场趋势表\s*$", lines[i]):
            i += 1
            while i < len(lines):
                s = lines[i].strip()
                italic = (
                    s.startswith("*") and s.endswith("*")
                    and not s.startswith("**") and len(s) > 1
                )
                if s == "" or s.startswith("|") or italic:
                    i += 1
                    continue
                break
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


def md_to_html(text: str) -> str:
    """Minimal markdown → HTML converter for briefing format."""
    text = slim_news_tables(text)
    lines = text.split("\n")
    html_lines = []
    in_table = False
    in_paragraph = False

    i = 0
    while i < len(lines):
        line = lines[i]

        # Horizontal rule (21 asterisks)
        if re.match(r"^\*{10,}$", line.strip()):
            if in_table:
                html_lines.append("</tbody></table>")
                in_table = False
            html_lines.append("<hr>")
            i += 1
            continue

        # Heading
        m = re.match(r"^(#{1,3})\s+(.*)", line)
        if m:
            if in_table:
                html_lines.append("</tbody></table>")
                in_table = False
            level = len(m.group(1))
            content = inline_format(m.group(2))
            html_lines.append(f"<h{level}>{content}</h{level}>")
            i += 1
            continue

        # Table
        if "|" in line and line.strip().startswith("|"):
            if not in_table:
                html_lines.append('<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse">')
                html_lines.append("<thead>")
                in_table = True
                # First row is header
                cells = [c.strip() for c in line.split("|")[1:-1]]
                html_lines.append("<tr>" + "".join(f"<th>{inline_format(c)}</th>" for c in cells) + "</tr>")
                html_lines.append("</thead><tbody>")
                i += 1
                # Skip separator row (|---|---|)
                if i < len(lines) and re.match(r"^\|[\s\-:|]+\|$", lines[i]):
                    i += 1
                continue
            else:
                # Data row
                cells = [c.strip() for c in line.split("|")[1:-1]]
                html_lines.append("<tr>" + "".join(f"<td>{inline_format(c)}</td>" for c in cells) + "</tr>")
                i += 1
                continue

        # End table if blank line after table rows
        if in_table and line.strip() == "":
            html_lines.append("</tbody></table>")
            in_table = False

        # List item
        m = re.match(r"^[-•·]\s+(.*)", line)
        if m:
            content = inline_format(m.group(1))
            html_lines.append(f"<li>{content}</li>")
            i += 1
            continue

        # Empty line
        if line.strip() == "":
            html_lines.append("<br>")
            i += 1
            continue

        # Regular text
        html_lines.append(f"<p>{inline_format(line)}</p>")
        i += 1

    if in_table:
        html_lines.append("</tbody></table>")

    return "\n".join(html_lines)


def inline_format(text: str) -> str:
    """Handle inline formatting: links, bold, italic."""
    text = re.sub(r"\[([^\]]+)\]\(([^\s)]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    return text


def md_to_plain(text: str) -> str:
    """Strip markdown markers for plain text version."""
    text = slim_news_tables(text)
    text = re.sub(r"\[([^\]]+)\]\([^\s)]+\)", r"\1", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"^#{1,3}\s+", "", text, flags=re.MULTILINE)
    return text


def build_combined_email_html(
    trend_rows: list[dict],
    briefing_markdown: str | None = None,
    briefing_html: str | None = None,
    as_of: str | None = None,
    has_news_items: bool = False,
    version: str = "",
    report_date: str | None = None,
) -> str:
    from .trend_table import _direction_color, _fmt_price, _fmt_change

    """Build a full email-ready HTML body that combines trend table + optional briefing.

    Parameters
    ----------
    trend_rows : list[dict]
        The ``rows`` array from ``trend_table`` (each a TrendRow-like dict).
    briefing_markdown : str or None
        Markdown text of the briefing (used as fallback when briefing_html is None).
    briefing_html : str or None
        Pre-rendered HTML of the briefing section.
    as_of : str or None
        "Data as of" timestamp shown in the trend table header.
    has_news_items : bool
        Whether to show the news briefing section (False = skip).
    version : str
        Skill version shown in footer.
    report_date : str or None
        Date string for the email header (default: as_of[:10]).

    Returns
    -------
    str
        HTML content suitable for injection into the ``<body>`` of an MML message.
    """

    date_str = (report_date or as_of or "")[:10] if (report_date or as_of) else ""

    # ── Trend table rows ────────────────────────────────────────────────
    trend_rows_html = ""
    for r in trend_rows:
        if r.get("status") == "failed":
            trend_rows_html += (
                f"<tr style='border-bottom:1px solid #f0f0f0;'>"
                f"<td style='padding:7px 6px;font-weight:500;'>{r.get('name','')}</td>"
                f"<td colspan='5' style='padding:7px 6px;text-align:left;color:#999;'"
                f">⚠ {r.get('error') or '数据获取失败'}</td></tr>"
            )
            continue
        name_en = r.get("name", "")
        name_cn = r.get("name_zh") or ""
        name_display = f"{name_en}<br><span style='font-size:11px;color:#888;font-weight:400;'>{name_cn}</span>" if name_cn else name_en
        price = _fmt_price(r.get("last_price"), r.get("display_precision", 2))
        d1 = _fmt_change(r.get("change_1d"), r.get("unit_1d", "%"))
        w1 = _fmt_change(r.get("change_1w"), r.get("unit_1w", "%"))
        m1 = _fmt_change(r.get("change_1m"), r.get("unit_1m", "%"))
        direction = r.get("direction") or "—"
        color = _direction_color(r.get("direction_detail"))
        trend_rows_html += (
            f"<tr style='border-bottom:1px solid #f0f0f0;'>"
            f"<td style='padding:7px 6px;font-weight:500;word-break:break-word;overflow-wrap:anywhere;'>{name_display}</td>"
            f"<td style='padding:7px 6px;text-align:right;font-variant-numeric:tabular-nums;'>{price}</td>"
            f"<td style='padding:7px 6px;text-align:right;color:{'#dc3545' if (r.get('change_1d') or 0) > 0 else '#1a6fc4' if (r.get('change_1d') or 0) < 0 else '#6c757d'};'>{d1}</td>"
            f"<td style='padding:7px 6px;text-align:right;color:{'#dc3545' if (r.get('change_1w') or 0) > 0 else '#1a6fc4' if (r.get('change_1w') or 0) < 0 else '#6c757d'};'>{w1}</td>"
            f"<td style='padding:7px 6px;text-align:right;color:{'#dc3545' if (r.get('change_1m') or 0) > 0 else '#1a6fc4' if (r.get('change_1m') or 0) < 0 else '#6c757d'};'>{m1}</td>"
            f"<td style='padding:7px 6px;text-align:center;font-size:16px;color:{color};font-weight:bold;'>{direction}</td>"
            f"</tr>"
        )

    # ── Briefing section ────────────────────────────────────────────────
    briefing_html_section = ""
    if has_news_items:
        body_content = briefing_html or ""
        if not body_content and briefing_markdown:
            stripped = _strip_trend_section(briefing_markdown)
            if stripped.strip():
                body_content = md_to_html(stripped)
        if body_content.strip():
            briefing_html_section = f"""
<hr style="border:none;border-top:1px solid #e9ecef;margin:16px 0;">
<h2 style="margin:0 0 12px;font-size:15px;font-weight:600;color:#333;border-left:3px solid #3498db;padding-left:10px;">📰 今日重点新闻</h2>
{body_content}"""

    return f"""\
<h2 style="margin:0 0 12px;font-size:15px;font-weight:600;color:#333;border-left:3px solid #f1c40f;padding-left:10px;">📊 市场趋势表</h2>
<table width="100%" cellpadding="0" cellspacing="0" class="ena-trend" style="font-size:12px;border-collapse:collapse;table-layout:fixed;width:100%;">
  <colgroup><col style="width:28%"><col style="width:16%"><col style="width:14%"><col style="width:14%"><col style="width:14%"><col style="width:14%"></colgroup>
  <thead>
    <tr style="background:#f8f9fa;border-bottom:2px solid #e9ecef;">
      <th style="padding:8px 6px;text-align:left;font-weight:600;color:#555;">资产</th>
      <th style="padding:8px 6px;text-align:right;font-weight:600;color:#555;">最新价</th>
      <th style="padding:8px 6px;text-align:right;font-weight:600;color:#555;">日变化</th>
      <th style="padding:8px 6px;text-align:right;font-weight:600;color:#555;">周变化</th>
      <th style="padding:8px 6px;text-align:right;font-weight:600;color:#555;">月变化</th>
      <th style="padding:8px 6px;text-align:center;font-weight:600;color:#555;">方向</th>
    </tr>
  </thead>
  <tbody>
    {trend_rows_html}
  </tbody>
</table>
<p style="margin:8px 0 0;font-size:11px;color:#999;">数据截至 {as_of or '--'}</p>
{briefing_html_section}
<p style="margin:0;font-size:11px;color:#999;">
  由 Economic News Analysis v{version} 自动生成 ·
  数据来源: Yahoo Finance / RSS Feeds
</p>"""


def build_mml(
    md_path: Path | None,
    from_addr: str,
    to_addr: str,
    subject: str,
    attach_name: str = None,
    html_body: str | None = None,
    version: str = "",
    text_body: str | None = None,
    attachments: Sequence[Path] | None = None,
) -> str:
    """Build himalaya MML with alternative bodies and optional attachments."""
    if text_body is None:
        if md_path is None:
            raise ValueError("text_body is required when md_path is not provided")
        md_text = md_path.read_text(encoding="utf-8")
        parts = md_text.split("\n\n", 1)
        body = parts[1] if len(parts) > 1 else md_text
        plain_body = md_to_plain(body)
    else:
        body = text_body
        plain_body = text_body
    # When a pre-rendered HTML body is supplied (e.g. build_combined_email_html),
    # it already carries its own footer, so we must NOT add a second one below.
    html_provided = html_body is not None
    html_body = html_body or md_to_html(body)
    runtime_footer = (
        ""
        if html_provided
        else f'\n<p style="color: #999; font-size: 12px; margin-top: 30px;">由 Economic News Analysis Runtime v{version} 自动生成</p>'
    )

    resolved_attachments = list(attachments or (() if md_path is None else (md_path,)))
    attachment_parts = []
    for index, attachment in enumerate(resolved_attachments):
        name = attach_name if index == 0 and attach_name else attachment.name
        attachment_parts.append(
            f'<#part filename="{attachment.resolve()}" name="{name}"><#/part>'
        )
    attachment_mml = "\n".join(attachment_parts)

    mml = f"""From: {from_addr}
To: {to_addr}
Subject: {subject}

<#multipart type=mixed>
<#multipart type=alternative>
<#part type=text/plain>
{plain_body}
<#part type=text/html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
@media only screen and (max-width:600px) {{
  .ena-body {{ padding: 0 !important; background: #ffffff !important; }}
  .ena-card {{ padding: 12px !important; border-radius: 0 !important; max-width: 100% !important; }}
  .ena-trend td, .ena-trend th {{ padding: 5px 3px !important; font-size: 11px !important; }}
}}
</style></head>
<body class="ena-body" style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; padding: 12px; color: #222; background: #f4f5f7;">
<div class="ena-card" style="max-width: 860px; margin: 0 auto; background: #ffffff; padding: 18px 18px; border-radius: 6px;">
{html_body}{runtime_footer}
</div>
</body></html>
<#/multipart>
{attachment_mml}
<#/multipart>"""
    return mml


def main():
    parser = argparse.ArgumentParser(description="Render markdown as himalaya MML")
    parser.add_argument("markdown", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--name", dest="attach_name")
    parser.add_argument("--from", dest="from_addr", required=True)
    parser.add_argument("--to", dest="to_addr", required=True)
    parser.add_argument("--subject", required=True)
    args = parser.parse_args()

    if not args.markdown.exists():
        print(f"Markdown file not found: {args.markdown}", file=sys.stderr)
        return 1

    mml = build_mml(
        args.markdown,
        from_addr=args.from_addr,
        to_addr=args.to_addr,
        subject=args.subject,
        attach_name=args.attach_name,
    )

    if args.output:
        args.output.write_text(mml, encoding="utf-8")
        print(f"MML written to {args.output}")
    else:
        print(mml)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
