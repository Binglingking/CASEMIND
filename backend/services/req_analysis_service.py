"""需求分析报告 PDF 生成服务。

使用 fpdf2 生成带颜色/字体标注的结构化 PDF 报告：
  - 高风险问题：红色加粗
  - 中风险问题：橙色加粗
  - 低风险/建议项：蓝色斜体
  - 关键术语：黄色高亮背景
"""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

from fpdf import FPDF


# ---- 中文字体查找 ----

def _find_chinese_font() -> str | None:
    """在常见路径查找中文字体文件，返回第一个存在的路径。"""
    candidates = [
        # Windows
        "C:/Windows/Fonts/msyh.ttc",       # 微软雅黑
        "C:/Windows/Fonts/msyhbd.ttc",     # 微软雅黑粗体
        "C:/Windows/Fonts/simsun.ttc",     # 宋体
        "C:/Windows/Fonts/simhei.ttf",     # 黑体
        "C:/Windows/Fonts/STKAITI.TTF",   # 华文楷体
        # Linux
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        # macOS
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    for p in candidates:
        if Path(p).exists():
            return p
    return None


_CHINESE_FONT = _find_chinese_font()


# ---- 颜色常量 ----

COLOR_HIGH = (200, 30, 30)       # 红色 - 高风险
COLOR_MEDIUM = (220, 140, 20)    # 橙色 - 中风险
COLOR_LOW = (50, 100, 200)       # 蓝色 - 低风险/建议
COLOR_HIGHLIGHT = (255, 255, 150)  # 黄色高亮 - 关键术语
COLOR_DARK = (33, 33, 33)        # 正文深色
COLOR_GRAY = (120, 120, 130)     # 灰色辅助文字
COLOR_BG_LIGHT = (248, 248, 252)  # 浅灰背景
COLOR_WHITE = (255, 255, 255)

TYPE_LABELS = {
    "conflict": "矛盾冲突",
    "omission": "遗漏缺失",
    "logic_flaw": "逻辑漏洞",
    "risk": "风险识别",
    "ambiguity": "歧义模糊",
    "suggestion": "建议改进",
}

SEVERITY_LABELS = {
    "high": "高",
    "medium": "中",
    "low": "低",
}


# ---- PDF 生成 ----

class ReqAnalysisPDF(FPDF):
    """需求分析报告 PDF。"""

    def __init__(self, project: str):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.project = project
        self.set_auto_page_break(auto=True, margin=20)

        # 注册中文字体
        if _CHINESE_FONT:
            self.add_font("zh", "", _CHINESE_FONT, uni=True)
            self.add_font("zh", "B", _CHINESE_FONT, uni=True)  # 粗体
            self.add_font("zh", "I", _CHINESE_FONT, uni=True)  # 斜体（中文字体通常无真斜体，复用常规体）
            self.add_font("zh", "BI", _CHINESE_FONT, uni=True)  # 粗斜体
            self.font_name = "zh"
        else:
            # 无中文字体时的降级方案：使用内置字体（中文会显示为方块）
            self.font_name = "Helvetica"

    # ---------- helpers ----------

    def _severity_color(self, severity: str) -> tuple[int, int, int]:
        if severity == "high":
            return COLOR_HIGH
        if severity == "medium":
            return COLOR_MEDIUM
        return COLOR_LOW

    def _type_color(self, issue_type: str) -> tuple[int, int, int]:
        if issue_type in ("conflict", "logic_flaw", "risk"):
            return COLOR_HIGH
        if issue_type == "omission":
            return COLOR_MEDIUM
        return COLOR_LOW

    def _write_tag(self, text: str, bg_color: tuple, text_color: tuple = COLOR_WHITE):
        """绘制一个彩色标签。"""
        self.set_font(self.font_name, "B", 7)
        w = self.get_string_width(text) + 4
        x = self.get_x()
        y = self.get_y()
        self.set_fill_color(*bg_color)
        self.set_text_color(*text_color)
        self.cell(w, 5, text, border=0, ln=0, align="C", fill=True)
        self.set_text_color(*COLOR_DARK)

    def _write_section_title(self, title: str):
        """章节标题。"""
        self.ln(4)
        self.set_font(self.font_name, "B", 13)
        self.set_text_color(*COLOR_DARK)
        self.cell(0, 8, title, ln=True)
        self.set_draw_color(200, 200, 210)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(3)

    # ---------- pages ----------

    def cover_page(self):
        """封面页。"""
        self.add_page()
        self.ln(40)
        # 标题
        self.set_font(self.font_name, "B", 26)
        self.set_text_color(*COLOR_DARK)
        self.cell(0, 14, "需求分析报告", align="C", ln=True)
        self.ln(6)
        # 项目名
        self.set_font(self.font_name, "", 16)
        self.set_text_color(*COLOR_GRAY)
        self.cell(0, 10, f"项目：{self.project}", align="C", ln=True)
        self.ln(8)
        # 日期
        self.set_font(self.font_name, "", 11)
        date_str = datetime.now().strftime("%Y年%m月%d日 %H:%M")
        self.cell(0, 8, f"生成日期：{date_str}", align="C", ln=True)
        self.ln(6)
        # 分隔线
        self.set_draw_color(*COLOR_HIGH)
        self.set_line_width(0.6)
        y = self.get_y()
        self.line(50, y, self.w - 50, y)
        self.set_line_width(0.2)
        self.ln(10)
        # 说明
        self.set_font(self.font_name, "", 10)
        self.set_text_color(*COLOR_GRAY)
        self.cell(0, 7, "本报告由 AI 自动生成，用于需求评审阶段的辅助参考。", align="C", ln=True)
        self.cell(0, 7, "不同颜色标注说明见正文。", align="C", ln=True)

    def summary_section(self, summary: str):
        """总体评价。"""
        self.add_page()
        self._write_section_title("一、总体评价")
        self.set_font(self.font_name, "", 10)
        self.set_text_color(*COLOR_DARK)
        self.multi_cell(0, 6, summary)

    def statistics_section(self, stats: dict):
        """统计概览。"""
        self.ln(4)
        self._write_section_title("二、问题统计")
        high = stats.get("high", 0)
        medium = stats.get("medium", 0)
        low = stats.get("low", 0)
        total = stats.get("total", high + medium + low)

        # 统计卡片
        self.set_font(self.font_name, "B", 10)
        card_w = 50
        gap = 4
        start_x = (self.w - (card_w * 3 + gap * 2)) / 2

        items = [
            ("高风险", high, COLOR_HIGH),
            ("中风险", medium, COLOR_MEDIUM),
            ("低风险", low, COLOR_LOW),
        ]
        for label, count, color in items:
            self.set_xy(start_x, self.get_y())
            self.set_fill_color(*color)
            self.set_text_color(*COLOR_WHITE)
            self.set_font(self.font_name, "B", 18)
            self.cell(card_w, 14, str(count), border=0, ln=0, align="C", fill=True)
            start_x += card_w + gap

        self.ln(16)
        self.set_text_color(*COLOR_GRAY)
        self.set_font(self.font_name, "", 9)
        self.cell(0, 5, f"合计发现 {total} 个问题", align="C", ln=True)
        self.ln(4)

    def color_legend(self):
        """颜色标注说明。"""
        self._write_section_title("标注说明")
        legends = [
            ("■ 高风险问题（红色加粗）", COLOR_HIGH, "B"),
            ("■ 中风险问题（橙色加粗）", COLOR_MEDIUM, "B"),
            ("■ 低风险/建议项（蓝色）", COLOR_LOW, ""),
            ("■ 高亮背景 = 关键术语/重点内容", COLOR_HIGHLIGHT, ""),
        ]
        for text, color, style in legends:
            self.set_font(self.font_name, style, 9)
            self.set_text_color(*color)
            self.cell(0, 6, text, ln=True)
        self.set_text_color(*COLOR_DARK)
        self.ln(4)

    def issues_section(self, issues: list[dict]):
        """问题详情列表。"""
        self._write_section_title("三、问题详情")
        if not issues:
            self.set_font(self.font_name, "", 10)
            self.set_text_color(*COLOR_GRAY)
            self.cell(0, 8, "未发现问题，文档质量良好。", ln=True)
            return

        for idx, issue in enumerate(issues, 1):
            self._render_issue(issue, idx)
            # 分页检查
            if self.get_y() > self.h - 40:
                self.add_page()

    def _render_issue(self, issue: dict, idx: int):
        """渲染单个问题条目。"""
        sev = issue.get("severity", "low")
        itype = issue.get("type", "suggestion")
        color = self._severity_color(sev)
        type_color = self._type_color(itype)

        # 问题背景条
        self.set_fill_color(*color)
        y0 = self.get_y()
        self.rect(self.l_margin, y0, 3, 6, "F")

        # 编号 + 类型标签 + 严重程度标签
        self.set_xy(self.l_margin + 5, y0)
        self.set_font(self.font_name, "B", 9)
        self.set_text_color(*color)
        issue_id = issue.get("id", f"ISS-{idx:03d}")
        self.cell(0, 6, f"{issue_id}  ", ln=0)

        # 类型标签
        type_label = TYPE_LABELS.get(itype, itype)
        self._write_tag(type_label, type_color)

        # 严重程度标签
        sev_label = SEVERITY_LABELS.get(sev, sev)
        sev_bg = color
        self.set_x(self.get_x() + 2)
        self._write_tag(sev_label, sev_bg)
        self.ln(8)

        # 标题（加粗 + 彩色）
        title = issue.get("title", "（无标题）")
        self.set_font(self.font_name, "B", 11)
        self.set_text_color(*color)
        self.set_x(self.l_margin + 5)
        self.multi_cell(self.w - self.l_margin - self.r_margin - 5, 6.5, title)
        self.ln(1)

        # 描述
        desc = issue.get("description", "")
        if desc:
            self._labeled_field("问题描述", desc, self.font_name, "", 9)

        # 位置
        location = issue.get("location", "")
        if location:
            self._labeled_field("所在位置", location, self.font_name, "", 9, COLOR_GRAY)

        # 影响
        impact = issue.get("impact", "")
        if impact:
            self._labeled_field("影响分析", impact, self.font_name, "", 9, COLOR_HIGH)

        # 建议
        suggestion = issue.get("suggestion", "")
        if suggestion:
            self._labeled_field("改进建议", suggestion, self.font_name, "I", 9, COLOR_LOW)

        # 分隔线
        self.ln(3)
        self.set_draw_color(220, 220, 225)
        y_sep = self.get_y()
        self.line(self.l_margin + 5, y_sep, self.w - self.r_margin, y_sep)
        self.ln(4)

    def _labeled_field(self, label: str, text: str, font_name: str,
                        style: str = "", size: int = 9,
                        color: tuple | None = None):
        """带标签的文本字段。"""
        color = color or COLOR_DARK
        self.set_font(font_name, "B", size)
        self.set_text_color(*COLOR_GRAY)
        self.set_x(self.l_margin + 5)
        self.cell(0, 5.5, f"▸ {label}：", ln=True)
        self.set_font(font_name, style, size)
        self.set_text_color(*color)
        self.set_x(self.l_margin + 12)
        self.multi_cell(self.w - self.l_margin - self.r_margin - 12, 5.5, text)
        self.ln(1.5)

    def footer(self):
        """页脚。"""
        self.set_y(-15)
        self.set_font(self.font_name, "", 7)
        self.set_text_color(*COLOR_GRAY)
        self.cell(0, 10, f"CaseMind · {self.project} · 需求分析报告 · 第{self.page_no()}页", align="C")


def generate_pdf_report(project: str, analysis_data: dict) -> bytes:
    """生成需求分析 PDF 报告，返回 bytes。

    analysis_data 格式：
    {
        "summary": "总体评价",
        "statistics": {"high": N, "medium": N, "low": N, "total": N},
        "issues": [{id, type, severity, title, description, location, impact, suggestion}, ...]
    }
    """
    pdf = ReqAnalysisPDF(project)
    pdf.set_margin(18)

    # 封面
    pdf.cover_page()

    # 标注说明
    pdf.color_legend()

    # 总体评价
    summary = analysis_data.get("summary", "（暂无总体评价）")
    pdf.summary_section(summary)

    # 统计
    stats = analysis_data.get("statistics", {})
    pdf.statistics_section(stats)

    # 问题详情
    issues = analysis_data.get("issues", [])
    pdf.issues_section(issues)

    # 输出
    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()
