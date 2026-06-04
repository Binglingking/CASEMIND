#!/usr/bin/env python3
"""Convert NPD handbook markdown to PDF with compact layout."""

import re
from fpdf import FPDF

FONT_PATH = "C:/Windows/Fonts/simhei.ttf"
FONT_PATH_SONG = "C:/Windows/Fonts/simsun.ttc"
OUTPUT_PATH = "D:/CaseMind/docs/NPD型领导职场生存法则手册.pdf"

# Read markdown
with open("D:/CaseMind/docs/NPD型领导职场生存法则手册.md", "r", encoding="utf-8") as f:
    lines = f.readlines()


class PDF(FPDF):
    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.add_font("hei", "", FONT_PATH)
        self.add_font("hei", "B", FONT_PATH)
        self.add_font("song", "", FONT_PATH_SONG)
        self.set_auto_page_break(auto=True, margin=15)
        self.set_margins(15, 12, 15)

    def header(self):
        if self.page_no() > 1:
            self.set_font("hei", "", 7)
            self.set_text_color(150, 150, 150)
            self.cell(0, 5, "NPD型领导职场生存法则手册", align="C")
            self.ln(6)
            self.set_draw_color(200, 200, 200)
            self.line(15, self.get_y(), 195, self.get_y())
            self.ln(2)
            self.set_text_color(0, 0, 0)

    def footer(self):
        self.set_y(-12)
        self.set_font("hei", "", 7)
        self.set_text_color(150, 150, 150)
        self.cell(0, 5, f"- {self.page_no()} -", align="C")


pdf = PDF()
pdf.add_page()

# State tracking
in_code_block = False
code_buffer = []
in_table = False
table_rows = []
table_aligns = []

# Patterns
h1_re = re.compile(r"^# (.+)")
h2_re = re.compile(r"^## (.+)")
h3_re = re.compile(r"^### (.+)")
h4_re = re.compile(r"^#### (.+)")
table_re = re.compile(r"^\|(.+)\|$")
hr_re = re.compile(r"^---+\s*$")
blockquote_re = re.compile(r"^>\s*(.*)")
bullet_re = re.compile(r"^[-*]\s+(.+)")
code_fence_re = re.compile(r"^```")


def clean(text):
    """Remove markdown formatting symbols, keep text."""
    text = text.strip()
    # Remove bold/italic markers
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    # Remove inline code backticks
    text = re.sub(r"`(.+?)`", r"\1", text)
    # Remove links
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)
    # Replace emoji with text equivalents
    text = text.replace("📌", "[提示]")
    text = text.replace("⭐⭐⭐⭐⭐", "[5星]")
    text = text.replace("⭐⭐⭐⭐", "[4星]")
    text = text.replace("⭐⭐⭐", "[3星]")
    text = text.replace("⭐⭐", "[2星]")
    text = text.replace("⭐", "[1星]")
    text = text.replace("🔴🔴🔴", "[致命]")
    text = text.replace("🔴🔴", "[高危]")
    text = text.replace("🔴", "[警戒]")
    text = text.replace("🟡", "[消耗]")
    text = text.replace("🟢", "[轻微]")
    text = text.replace("❌", "[禁止]")
    text = text.replace("□", "[ ]")
    text = text.replace("🔷", "[要点]")
    text = text.replace("📊", "")
    # Remove any remaining emoji (supplementary plane chars)
    text = re.sub(r"[\U0001F000-\U0001FFFF]", "", text)
    text = re.sub(r"[☀-➿]", "", text)
    text = re.sub(r"[⭐⭕]", "", text)
    return text


def render_table(pdf, rows):
    """Render a markdown table."""
    if not rows:
        return
    # Parse cells
    parsed = []
    for row in rows:
        cells = [c.strip() for c in row.split("|")]
        # Remove empty first/last from leading/trailing |
        if cells and cells[0] == "":
            cells = cells[1:]
        if cells and cells[-1] == "":
            cells = cells[:-1]
        parsed.append(cells)

    # Filter out separator rows (---)
    data_rows = []
    for row in parsed:
        if all(re.match(r"^[-:]+$", c.strip()) for c in row):
            continue
        data_rows.append(row)

    if not data_rows:
        return

    num_cols = max(len(r) for r in data_rows)
    # Calculate column widths
    page_w = 180  # usable width
    col_widths = []
    max_lens = []
    for ci in range(num_cols):
        max_len = 0
        for row in data_rows:
            if ci < len(row):
                # Approximate: Chinese chars count as 2
                cell_len = sum(2 if ord(c) > 127 else 1 for c in row[ci])
                max_len = max(max_len, cell_len)
        max_lens.append(max_len)
    total_len = sum(max_lens) or 1
    for ml in max_lens:
        col_widths.append(max(page_w * ml / total_len, 15))

    # Adjust to fit page
    total_w = sum(col_widths)
    if total_w > page_w:
        ratio = page_w / total_w
        col_widths = [w * ratio for w in col_widths]

    row_h = 6
    for ri, row in enumerate(data_rows):
        is_header = ri == 0
        # Check page break
        if pdf.get_y() + row_h > 280:
            pdf.add_page()

        x_start = pdf.get_x()
        y_start = pdf.get_y()

        if is_header:
            pdf.set_fill_color(230, 240, 250)
            pdf.set_font("hei", "B", 7.5)
        else:
            pdf.set_fill_color(255, 255, 255)
            pdf.set_font("hei", "", 7.5)

        max_h = row_h
        cell_lines = []
        for ci in range(num_cols):
            cell_text = row[ci] if ci < len(row) else ""
            cell_text = clean(cell_text)
            # Calculate wrapped lines
            cw = col_widths[ci] - 2
            chars_per_line = max(int(cw / 2.5), 1)  # approx
            lines_wrap = []
            while len(cell_text) > chars_per_line:
                lines_wrap.append(cell_text[:chars_per_line])
                cell_text = cell_text[chars_per_line:]
            lines_wrap.append(cell_text)
            cell_lines.append(lines_wrap)
            max_h = max(max_h, len(lines_wrap) * 4.5 + 2)

        # Draw cells
        x = x_start
        for ci in range(num_cols):
            pdf.set_xy(x, y_start)
            pdf.cell(col_widths[ci], max_h, "", border=1, fill=True)
            # Write text inside cell
            text_y = y_start + 1
            for line in cell_lines[ci]:
                pdf.set_xy(x + 1, text_y)
                pdf.cell(col_widths[ci] - 2, 4, line, align="L")
                text_y += 4.5
            x += col_widths[ci]

        pdf.set_xy(x_start, y_start + max_h)

    pdf.ln(2)


def render_code_block(pdf, code_lines):
    """Render a code block with gray background."""
    if not code_lines:
        return
    pdf.set_font("song", "", 7)
    line_h = 3.8
    block_h = len(code_lines) * line_h + 4

    if pdf.get_y() + block_h > 280:
        pdf.add_page()

    y_start = pdf.get_y()
    pdf.set_fill_color(245, 245, 245)
    pdf.rect(15, y_start, 180, block_h, "F")
    pdf.set_xy(18, y_start + 2)
    pdf.set_text_color(50, 50, 50)
    for line in code_lines:
        # Replace emoji in code blocks too
        line = line.replace("🟢", "[G]").replace("🟡", "[Y]").replace("🔴", "[R]")
        line = line.replace("⭐", "*").replace("❌", "[X]").replace("□", "[ ]")
        pdf.cell(0, line_h, line.rstrip())
        pdf.ln(line_h)
        pdf.set_x(18)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(3)


# Process line by line
i = 0
while i < len(lines):
    line = lines[i].rstrip("\n")

    # Code block start/end
    if code_fence_re.match(line):
        if in_code_block:
            # End code block
            render_code_block(pdf, code_buffer)
            code_buffer = []
            in_code_block = False
        else:
            # Flush table if pending
            if in_table:
                render_table(pdf, table_rows)
                table_rows = []
                in_table = False
            in_code_block = True
        i += 1
        continue

    if in_code_block:
        code_buffer.append(line)
        i += 1
        continue

    # Table row
    if table_re.match(line):
        if not in_table:
            in_table = True
            table_rows = []
        table_rows.append(line)
        i += 1
        continue
    else:
        if in_table:
            render_table(pdf, table_rows)
            table_rows = []
            in_table = False

    # Horizontal rule
    if hr_re.match(line):
        pdf.ln(2)
        y = pdf.get_y()
        pdf.set_draw_color(180, 180, 180)
        pdf.line(15, y, 195, y)
        pdf.ln(4)
        i += 1
        continue

    # Empty line
    if not line.strip():
        pdf.ln(2)
        i += 1
        continue

    # Heading 1
    m = h1_re.match(line)
    if m:
        if pdf.page_no() > 1:
            pdf.ln(4)
        pdf.set_font("hei", "B", 16)
        pdf.set_text_color(30, 80, 160)
        text = clean(m.group(1))
        pdf.multi_cell(0, 8, text, align="C")
        pdf.ln(2)
        pdf.set_text_color(0, 0, 0)
        i += 1
        continue

    # Heading 2
    m = h2_re.match(line)
    if m:
        pdf.ln(3)
        if pdf.get_y() > 260:
            pdf.add_page()
        pdf.set_font("hei", "B", 13)
        pdf.set_text_color(40, 100, 180)
        text = clean(m.group(1))
        pdf.multi_cell(0, 7, text)
        pdf.ln(1)
        pdf.set_text_color(0, 0, 0)
        i += 1
        continue

    # Heading 3
    m = h3_re.match(line)
    if m:
        pdf.ln(2)
        if pdf.get_y() > 265:
            pdf.add_page()
        pdf.set_font("hei", "B", 10.5)
        pdf.set_text_color(60, 60, 60)
        text = clean(m.group(1))
        pdf.multi_cell(0, 6, text)
        pdf.ln(1)
        pdf.set_text_color(0, 0, 0)
        i += 1
        continue

    # Heading 4
    m = h4_re.match(line)
    if m:
        pdf.ln(1)
        pdf.set_font("hei", "B", 9.5)
        pdf.set_text_color(80, 80, 80)
        text = clean(m.group(1))
        pdf.multi_cell(0, 5.5, text)
        pdf.ln(1)
        pdf.set_text_color(0, 0, 0)
        i += 1
        continue

    # Blockquote
    m = blockquote_re.match(line)
    if m:
        text = clean(m.group(1))
        if text:
            y = pdf.get_y()
            pdf.set_draw_color(100, 150, 220)
            pdf.line(17, y, 17, y + 5)
            pdf.set_xy(20, y)
            pdf.set_font("hei", "", 8)
            pdf.set_text_color(80, 80, 80)
            pdf.multi_cell(160, 4.5, text)
            pdf.set_text_color(0, 0, 0)
        i += 1
        continue

    # Bullet point
    m = bullet_re.match(line)
    if m:
        text = clean(m.group(1))
        pdf.set_font("hei", "", 8.5)
        pdf.cell(5, 5, "•")
        pdf.multi_cell(170, 5, text)
        pdf.ln(0.5)
        i += 1
        continue

    # Checkbox
    if line.strip().startswith("□"):
        text = clean(line.strip())
        pdf.set_font("hei", "", 8.5)
        pdf.cell(5, 5, "")
        pdf.multi_cell(170, 5, text)
        pdf.ln(0.5)
        i += 1
        continue

    # Regular text
    text = clean(line)
    if text:
        pdf.set_font("hei", "", 8.5)
        pdf.multi_cell(0, 5, text)
        pdf.ln(0.5)

    i += 1

# Flush remaining
if in_table and table_rows:
    render_table(pdf, table_rows)
if in_code_block and code_buffer:
    render_code_block(pdf, code_buffer)

pdf.output(OUTPUT_PATH)
print(f"PDF generated: {OUTPUT_PATH}")
