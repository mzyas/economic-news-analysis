import unittest

from tools.email_render import (
    build_combined_email_html,
    inline_format,
    md_to_html,
    md_to_plain,
    slim_news_tables,
)

TREND_ROWS = [
    {
        "name": "S&P 500",
        "name_zh": "标普500",
        "last_price": 7722.72,
        "change_1d": 0.73,
        "unit_1d": "%",
        "change_1w": -0.27,
        "unit_1w": "%",
        "change_1m": 0.73,
        "unit_1m": "%",
        "direction": "→",
    },
]

BRIEFING_WITH_TREND = (
    "> **部分成功**：本报告基于当前可用内容生成。\n"
    "\n"
    "## 市场趋势表\n"
    "*数据截至 2026-10-05 00:00:00+09:00*\n"
    "\n"
    "| 资产 | 最新价 | 日变化 | 周变化 | 月变化 | 方向 |\n"
    "|------|-------|--------|--------|--------|------|\n"
    "| S&P 500 | 7,722.72 | % +0.73 | % -0.27 | % +0.73 | → |\n"
    "\n"
    "今日资讯主线\n"
    "1. **中国｜经济增长：PMI 重返扩张** — 制造业PMI升至50.1%。\n"
)

NEWS_TABLE = (
    "| 重要性 | 地区 | 主题 | 新闻内容 | 核心信号 | 关注资产 |\n"
    "|---|---|---|---|---|---|\n"
    "| ★★ | 美国 | 通胀、就业 | **招聘放缓**；美国9月新增就业岗位少于此前水平，失业率小幅上升，劳动力市场降温迹象明显。；"
    "来源：NYT Economy [发布页](https://example.com/a)；🕒 2天前 | "
    "9月美国新增就业少于此前水平，就业增长放缓；失业率小幅上升，劳动力市场转入低速档；"
    "通胀持续对市场施压并推高成本，价格压力未解；就业走弱与通胀黏性并存，政策宽松路径存在不确定性 | "
    "美国国债、美股、USD、黄金 |\n"
)


class TrendDedupTests(unittest.TestCase):
    def test_combined_html_keeps_single_trend_table(self):
        html = build_combined_email_html(
            trend_rows=TREND_ROWS,
            briefing_markdown=BRIEFING_WITH_TREND,
            as_of="2026-10-05 00:00:00+09:00",
            has_news_items=True,
            version="0.9.0",
            report_date="2026-10-05",
        )
        self.assertEqual(html.count("市场趋势表"), 1)
        self.assertEqual(html.count("7,722.72"), 1)
        self.assertIn("今日资讯主线", html)

    def test_combined_html_skips_empty_briefing_section(self):
        html = build_combined_email_html(
            trend_rows=TREND_ROWS,
            briefing_markdown="## 市场趋势表\n\n| 资产 | 最新价 |\n|---|---|\n| S&P 500 | 7,722.72 |\n",
            as_of="2026-10-05",
            has_news_items=True,
            version="0.9.0",
            report_date="2026-10-05",
        )
        self.assertNotIn("今日重点新闻", html)

    def test_trend_only_document_is_not_stripped(self):
        plain = md_to_plain(BRIEFING_WITH_TREND)
        self.assertIn("S&P 500", plain)
        self.assertIn("资产", plain)


class NewsTableSlimTests(unittest.TestCase):
    def test_columns_merged_region_into_topic(self):
        html = md_to_html(NEWS_TABLE)
        self.assertNotIn("<th>地区</th>", html)
        self.assertIn("<th>主题</th>", html)
        self.assertIn("<td>美国<br>通胀、就业</td>", html)
        self.assertNotIn("美国·", html)
        self.assertEqual(html.count("<th>"), 5)

    def test_importance_stars_become_text_grade(self):
        def grade(stars: str) -> str:
            row = f"| {stars} | 美国 | 通胀 | 标题；来源：X；🕒 今天 | 信号 | 黄金 |"
            header = "| 重要性 | 地区 | 主题 | 新闻内容 | 核心信号 | 关注资产 |"
            out = slim_news_tables(f"{header}\n|---|---|---|---|---|---|\n{row}")
            return out.split("\n")[-1].split("|")[1].strip()

        self.assertEqual(grade("★★★"), "高")
        self.assertEqual(grade("★★"), "中")
        self.assertEqual(grade("★"), "低")
        self.assertEqual(grade("高"), "高")
        self.assertNotIn("★", md_to_html(NEWS_TABLE))

    def test_assets_split_onto_separate_lines(self):
        html = md_to_html(NEWS_TABLE)
        self.assertIn("<td>美国国债<br>美股<br>USD<br>黄金</td>", html)
        self.assertNotIn("美股、", html)

    def test_news_cell_drops_summary_prose(self):
        html = md_to_html(NEWS_TABLE)
        self.assertIn("<strong>招聘放缓</strong>", html)
        self.assertIn("NYT Economy", html)
        self.assertIn("example.com/a", html)
        self.assertIn("🕒 2天前", html)
        self.assertNotIn("劳动力市场降温迹象明显", html)

    def test_core_signal_truncated_at_clause_boundary(self):
        html = md_to_html(NEWS_TABLE)
        self.assertNotIn("政策宽松路径存在不确定性", html)
        self.assertIn("就业增长放缓；", html)
        self.assertIn("…", html)

    def test_slim_is_idempotent(self):
        from tools.email_render import slim_news_tables

        once = slim_news_tables(NEWS_TABLE)
        self.assertEqual(slim_news_tables(once), once)

    def test_plain_text_also_slimmed(self):
        plain = md_to_plain(NEWS_TABLE)
        self.assertNotIn("地区", plain)
        self.assertIn("美国 通胀、就业", plain)
        self.assertNotIn("<br>", plain)


class LinkRenderingTests(unittest.TestCase):
    def test_link_becomes_clickable_anchor(self):
        html = md_to_html("来源：NYT Economy [发布页](https://example.com/a)；🕒 2天前")
        self.assertIn('<a href="https://example.com/a">发布页</a>', html)
        self.assertNotIn("[发布页](", html)

    def test_link_anchor_inside_table_cell(self):
        html = md_to_html(
            "| 主题 | 新闻 |\n|---|---|\n| x | **标题**；来源：Y [发布页](https://e.com/b)；🕒 今天 |"
        )
        self.assertIn('<a href="https://e.com/b">发布页</a>', html)


class LinkSafetyTests(unittest.TestCase):
    def test_quote_in_url_cannot_break_out_of_href(self):
        out = inline_format('[a](https://x.com/a"onmouseover="alert(1))')
        self.assertNotIn('"onmouseover', out)
        self.assertEqual(out.count("<a "), 1)
        self.assertIn("&quot;", out)

    def test_unsafe_scheme_is_not_linked(self):
        out = inline_format("[点我](javascript:alert(1))")
        self.assertNotIn("<a", out)
        self.assertNotIn("javascript", out)
        self.assertIn("点我", out)

    def test_balanced_parentheses_kept_in_url(self):
        out = inline_format("[w](https://en.wikipedia.org/wiki/Foo_(bar))")
        self.assertEqual(out, '<a href="https://en.wikipedia.org/wiki/Foo_(bar)">w</a>')

    def test_emphasis_does_not_rewrite_url(self):
        out = inline_format("[a](https://x.com/a_*b*_c) *斜体*")
        self.assertIn('href="https://x.com/a_*b*_c"', out)
        self.assertIn("<em>斜体</em>", out)

    def test_plain_text_strips_link_with_parentheses_url(self):
        plain = md_to_plain("[w](https://en.wikipedia.org/wiki/Foo_(bar)) 结尾")
        self.assertEqual(plain, "w 结尾")


class PlainTextEscapeAndIndentTests(unittest.TestCase):
    HEADER = "| 重要性 | 地区 | 主题 | 新闻内容 | 核心信号 | 关注资产 |"

    def test_plain_text_unescapes_pipe(self):
        plain = md_to_plain("| a \\| b | c |\n|---|---|\n| x \\| y | z |")
        self.assertNotIn("\\|", plain)
        self.assertIn("x | y", plain)

    def test_indented_news_table_is_still_slimmed(self):
        table = (
            f" {self.HEADER}\n"
            " |---|---|---|---|---|---|\n"
            " | ★ | 美国 | 通胀 | 标题；摘要；来源：X；🕒 今天 | 信号 | 黄金 |\n"
        )
        out = slim_news_tables(table)
        self.assertNotIn("地区", out)
        self.assertIn("美国<br>通胀", out)
        self.assertNotIn("摘要", out)


class EscapedPipeTests(unittest.TestCase):
    def test_escaped_pipe_keeps_cell_intact_in_slimmed_table(self):
        table = (
            "| 重要性 | 地区 | 主题 | 新闻内容 | 核心信号 | 关注资产 |\n"
            "|---|---|---|---|---|---|\n"
            "| ★ | 全球 | 宏观经济 | **独家 \\| 新任AI专员**；来源：X [发布页](https://e.com/c)；🕒 今天 | "
            "来源不足，未提供核心信号。 | 来源不足 |\n"
        )
        html = md_to_html(table)
        self.assertEqual(html.count("<td>"), 5)
        self.assertIn("独家 | 新任AI专员", html)
        self.assertNotIn("\\|", html)

    def test_escaped_pipe_in_generic_table(self):
        html = md_to_html("| a \\| b | c |\n|---|---|\n| x \\| y | z |")
        self.assertEqual(html.count("<td>"), 2)
        self.assertIn("x | y", html)


if __name__ == "__main__":
    unittest.main()
