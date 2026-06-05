---
name: document
description: Use when the user wants to create or inspect DOCX, PPTX, or XLSX files, generate Office deliverables, or verify layout and content with scholaraio document inspect.
---

# Office 文档生成与检查

直接用 Python API 生成 Word / PowerPoint / Excel 文档，并通过 `scholaraio document inspect` 检查文档结构和布局。

## 核心思路

**生成**：不要用 `scholaraio export docx`（那个只是简单的 Markdown 转换器）。本 skill 直接编写 Python 脚本调用 Office 库 API，类似 draw skill 直接调用 Inkscape API 画图。

**检查**：生成后必须用 `scholaraio document inspect <file>` 检查文档，确认布局、内容、图片尺寸无误，再交付给用户。

输出目录：`workspace/` 下；用户报告可放 `workspace/reports/`，系统生成图表默认放 `workspace/_system/figures/`。

## 文档检查（inspect）

```bash
# 检查 PPTX：逐页输出 shape 位置/尺寸/文字/图片信息 + 溢出警告
scholaraio document inspect presentation.pptx

# 检查 DOCX：段落/标题/表格/图片结构 + 样式摘要
scholaraio document inspect report.docx

# 检查 XLSX：Sheet 概览 + 数据预览 + 图表列表
scholaraio document inspect data.xlsx
```

**输出内容**：

| 格式 | 检查项 |
|------|--------|
| PPTX | 每页 shape 类型、位置(英寸)、尺寸、文字预览、图片大小、表格维度、**溢出检测** |
| DOCX | 标题层级、段落内容、表格结构、嵌入图片、样式统计 |
| XLSX | Sheet 列表、数据范围、冻结窗格、合并单元格、表头预览、数据预览、图表类型和标题 |

## 与其他 skill 的组合

| 组合 | 流程 |
|------|------|
| draw + document | draw 生成 PNG/SVG → `doc.add_picture()` 嵌入 DOCX/PPTX |
| search + document | 搜索结果 → 表格写入 DOCX/XLSX |
| literature-review + document | 生成综述内容 → 带 TOC 的正式 Word 文档 |
| paper-writing + document | 论文章节 → 排版完整的 Word 文件 |
| topics + document | 主题分析 → 可视化报告（PPTX 幻灯片） |

---

## 工具 1：python-docx（Word 文档）

### 依赖

```python
from docx import Document
from docx.shared import Inches, Cm, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
```

### 文档结构

```python
from pathlib import Path
from docx import Document
from docx.shared import Inches, Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH

OUT = Path("workspace/reports/report.docx")
OUT.parent.mkdir(parents=True, exist_ok=True)

doc = Document()

# ── 文档属性 ──
doc.core_properties.title = "研究简报"
doc.core_properties.author = "ScholarAIO"

# ── 页面设置（A4，适当边距）──
section = doc.sections[0]
section.page_width = Cm(21)
section.page_height = Cm(29.7)
section.top_margin = Cm(2.5)
section.bottom_margin = Cm(2.5)
section.left_margin = Cm(3)
section.right_margin = Cm(3)

# ── 页眉 ──
header = section.header
header.is_linked_to_previous = False
hp = header.paragraphs[0]
hp.text = "ScholarAIO Research Brief"
hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT

# ── 页脚（页码）──
footer = section.footer
footer.is_linked_to_previous = False
fp = footer.paragraphs[0]
fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
# 插入自动页码字段
from docx.oxml.ns import qn
run = fp.add_run()
fld = run._element.makeelement(qn('w:fldSimple'), {qn('w:instr'): ' PAGE '})
run._element.append(fld)

# ── 标题 ──
doc.add_heading("研究简报标题", level=0)

# ── 正文段落 ──
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
run = p.add_run("这是正文内容。")
run.font.name = "Times New Roman"
run.font.size = Pt(12)

# 混合格式
p2 = doc.add_paragraph()
p2.add_run("关键发现：").bold = True
p2.add_run("湍流调制效应在高 Stokes 数条件下显著增强。")

# ── 分页 ──
doc.add_page_break()

# ── 嵌入图片（来自 draw skill 输出）──
img = Path("workspace/_system/figures/pipeline.png")
if img.exists():
    doc.add_picture(str(img), width=Inches(5))
    # 图片标题
    cap = doc.add_paragraph("图 1：ScholarAIO 数据流水线")
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cap.runs[0].italic = True

# ── 表格 ──
table = doc.add_table(rows=1, cols=4, style="Light Grid Accent 1")
hdr = table.rows[0].cells
hdr[0].text = "论文"
hdr[1].text = "作者"
hdr[2].text = "年份"
hdr[3].text = "引用量"
# 添加数据行
row = table.add_row().cells
row[0].text = "Particle response and turbulence modification"
row[1].text = "Kulick et al."
row[2].text = "1994"
row[3].text = "608"

# ── 多级列表 ──
doc.add_heading("主要结论", level=1)
for item in ["结论一：颗粒抑制湍流", "结论二：Stokes 数是关键参数"]:
    doc.add_paragraph(item, style="List Bullet")

# 有序列表
for i, item in enumerate(["第一步", "第二步", "第三步"], 1):
    doc.add_paragraph(item, style="List Number")

doc.save(str(OUT))
print(f"已生成: {OUT}")
```

### 常用 API 速查

| 操作 | API |
|------|-----|
| 标题 | `doc.add_heading(text, level=0-9)` |
| 段落 | `doc.add_paragraph(text, style=None)` |
| 行内格式 | `p.add_run(text)` → `.bold` `.italic` `.underline` `.font.name` `.font.size` `.font.color.rgb` |
| 图片 | `doc.add_picture(path, width=Inches(X))` |
| 表格 | `doc.add_table(rows, cols, style="Table Grid")` |
| 合并单元格 | `cell_a.merge(cell_b)` |
| 分页 | `doc.add_page_break()` |
| 分节 | `doc.add_section()` → 独立页眉页脚/页面方向 |
| 页眉页脚 | `section.header.paragraphs[0]` / `section.footer` |
| 段落对齐 | `p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY` |
| 段落间距 | `p.paragraph_format.space_before = Pt(6)` |
| 首行缩进 | `p.paragraph_format.first_line_indent = Cm(0.75)` |
| 行距 | `p.paragraph_format.line_spacing = 1.5` |
| 文档属性 | `doc.core_properties.title / .author / .subject` |
| 横向页面 | `section.orientation = WD_ORIENT.LANDSCAPE` + 交换宽高 |

### 插入目录（TOC）

python-docx 不直接支持 TOC，但可以通过 XML 插入 TOC 字段，在 Word 中打开后按 F9 更新：

```python
from docx.oxml.ns import qn

p = doc.add_paragraph()
run = p.add_run()
fld_begin = run._element.makeelement(qn('w:fldChar'), {qn('w:fldCharType'): 'begin'})
run._element.append(fld_begin)

run2 = p.add_run()
instr = run2._element.makeelement(qn('w:instrText'), {})
instr.text = ' TOC \\o "1-3" \\h \\z \\u '
run2._element.append(instr)

run3 = p.add_run()
fld_end = run3._element.makeelement(qn('w:fldChar'), {qn('w:fldCharType'): 'end'})
run3._element.append(fld_end)

# 在 TOC 后加分页
doc.add_page_break()
```

### 常用表格样式

`"Table Grid"` `"Light Grid Accent 1"` `"Light Shading Accent 1"` `"Medium Shading 1 Accent 1"` `"Colorful Grid Accent 1"`

---

## 工具 2：python-pptx（PowerPoint 演示）

### 依赖

```python
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
```

### 演示文稿结构

```python
from pathlib import Path
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN

OUT = Path("workspace/reports/presentation.pptx")
OUT.parent.mkdir(parents=True, exist_ok=True)

prs = Presentation()

# ── 标题页 ──
slide = prs.slides.add_slide(prs.slide_layouts[0])  # Title Slide
slide.shapes.title.text = "研究进展报告"
slide.placeholders[1].text = "ScholarAIO 自动生成\n2026-03-15"

# ── 内容页（标题 + 正文）──
slide = prs.slides.add_slide(prs.slide_layouts[1])  # Title and Content
slide.shapes.title.text = "主要发现"
body = slide.placeholders[1]
tf = body.text_frame
tf.text = "发现一：颗粒显著调制湍流结构"
p = tf.add_paragraph()
p.text = "发现二：Stokes 数是关键控制参数"
p.level = 0
p = tf.add_paragraph()
p.text = "在高 Re 条件下效应更加显著"
p.level = 1  # 缩进子条目

# ── 空白页 + 自定义内容 ──
slide = prs.slides.add_slide(prs.slide_layouts[6])  # Blank

# 文本框
txBox = slide.shapes.add_textbox(Inches(1), Inches(0.5), Inches(8), Inches(1))
tf = txBox.text_frame
p = tf.paragraphs[0]
p.text = "数据概览"
p.font.size = Pt(28)
p.font.bold = True
p.font.color.rgb = RGBColor(0x1a, 0x1a, 0x2e)
p.alignment = PP_ALIGN.CENTER

# 表格
table = slide.shapes.add_table(3, 4, Inches(0.5), Inches(2), Inches(9), Inches(3)).table
for i, h in enumerate(["论文", "年份", "期刊", "引用量"]):
    table.cell(0, i).text = h

# 图片（来自 draw skill）
img = Path("workspace/_system/figures/pipeline.png")
if img.exists():
    slide.shapes.add_picture(str(img), Inches(1), Inches(4), width=Inches(8))

prs.save(str(OUT))
print(f"已生成: {OUT}")
```

### 常用 API 速查

| 操作 | API |
|------|-----|
| 标题页 | `prs.slide_layouts[0]` |
| 内容页 | `prs.slide_layouts[1]` |
| 空白页 | `prs.slide_layouts[6]` |
| 文本框 | `slide.shapes.add_textbox(left, top, width, height)` |
| 表格 | `slide.shapes.add_table(rows, cols, left, top, width, height)` |
| 图片 | `slide.shapes.add_picture(path, left, top, width, height)` |
| 文字格式 | `p.font.size` `.bold` `.italic` `.color.rgb` |
| 段落对齐 | `p.alignment = PP_ALIGN.CENTER` |
| 多级列表 | `p.level = 0/1/2` |
| 幻灯片尺寸 | `prs.slide_width` / `prs.slide_height` |

### Slide Layout 索引

`0` Title Slide | `1` Title and Content | `2` Section Header | `3` Two Content | `4` Comparison | `5` Title Only | `6` Blank

---

## 工具 3：openpyxl（Excel 表格）

### 依赖

```python
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.chart import BarChart, Reference
```

### 工作簿结构

```python
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

OUT = Path("workspace/reports/data.xlsx")
OUT.parent.mkdir(parents=True, exist_ok=True)

wb = Workbook()
ws = wb.active
ws.title = "论文统计"

# ── 表头样式 ──
header_font = Font(bold=True, color="FFFFFF", size=11)
header_fill = PatternFill(start_color="4A90D9", end_color="4A90D9", fill_type="solid")
thin_border = Border(
    left=Side(style="thin"), right=Side(style="thin"),
    top=Side(style="thin"), bottom=Side(style="thin"),
)

headers = ["标题", "作者", "年份", "期刊", "引用量"]
for col, h in enumerate(headers, 1):
    cell = ws.cell(row=1, column=col, value=h)
    cell.font = header_font
    cell.fill = header_fill
    cell.alignment = Alignment(horizontal="center")
    cell.border = thin_border

# ── 数据行 ──
data = [
    ["Convex Optimization", "Boyd et al.", 2013, "Springer", 31085],
    ["EMD & Hilbert Spectrum", "Huang et al.", 1998, "Proc. Royal Soc.", 22921],
]
for r, row_data in enumerate(data, 2):
    for c, val in enumerate(row_data, 1):
        cell = ws.cell(row=r, column=c, value=val)
        cell.border = thin_border

# ── 列宽 ──
ws.column_dimensions['A'].width = 40
ws.column_dimensions['B'].width = 20
ws.column_dimensions['D'].width = 25

# ── 冻结表头 ──
ws.freeze_panes = "A2"

# ── 自动筛选 ──
ws.auto_filter.ref = ws.dimensions

wb.save(str(OUT))
print(f"已生成: {OUT}")
```

### 图表

```python
from openpyxl.chart import BarChart, Reference

# 假设 B 列是年份，E 列是引用量，数据从第 2 行到第 N 行
chart = BarChart()
chart.title = "引用量分布"
chart.y_axis.title = "Citations"
data_ref = Reference(ws, min_col=5, min_row=1, max_row=ws.max_row)
cats_ref = Reference(ws, min_col=1, min_row=2, max_row=ws.max_row)
chart.add_data(data_ref, titles_from_data=True)
chart.set_categories(cats_ref)
ws.add_chart(chart, "G2")
```

### 常用 API 速查

| 操作 | API |
|------|-----|
| 单元格读写 | `ws.cell(row, column, value)` 或 `ws['A1'] = val` |
| 追加行 | `ws.append([v1, v2, ...])` |
| 合并 | `ws.merge_cells('A1:C1')` |
| 列宽/行高 | `ws.column_dimensions['A'].width` / `ws.row_dimensions[1].height` |
| 冻结 | `ws.freeze_panes = "A2"` |
| 筛选 | `ws.auto_filter.ref = ws.dimensions` |
| 字体 | `Font(name, size, bold, italic, color)` |
| 填充 | `PatternFill(start_color, fill_type="solid")` |
| 边框 | `Border(left=Side(style="thin"), ...)` |
| 对齐 | `Alignment(horizontal, vertical, wrap_text)` |
| 数字格式 | `cell.number_format = "0.00%"` |
| 新工作表 | `wb.create_sheet("Sheet2")` |
| 图表 | `BarChart` / `LineChart` / `PieChart` + `ws.add_chart()` |

---

## 执行逻辑

1. **判断输出格式**：
   - 报告/综述/简报/论文 → **DOCX**
   - 汇报/演示/答辩 → **PPTX**
   - 数据表/统计/列表 → **XLSX**
   - 用户未指定 → 根据内容性质选择，默认 DOCX

2. **收集内容**：调用其他 skill/CLI 获取数据
   - `scholaraio search/usearch` — 搜索论文
   - `scholaraio show --layer 2/3` — 获取摘要/结论
   - `scholaraio top-cited` — 高引论文
   - `scholaraio topics --topic N` — 主题论文
   - `scholaraio ws show <name>` — 工作区论文列表

3. **生成图表**（如需要）：用 draw skill 生成 PNG/SVG 到 `workspace/_system/figures/`

4. **编写 Python 脚本**：用上述 API 直接构建文档，在一个脚本中完成全部操作

5. **输出到 `workspace/`**：
   ```
   workspace/
   └── reports/
       ├── research_brief.docx
       ├── presentation.pptx
       └── paper_stats.xlsx
   ```

6. **检查文档**：运行 `scholaraio document inspect <file>` 检查生成结果
   - PPTX：确认图片未溢出、文字未超出容器、布局合理
   - DOCX：确认标题层级正确、表格完整、图片已嵌入
   - XLSX：确认数据完整、图表标题正确、冻结窗格生效
   - 如发现问题 → 修改脚本 → 重新生成 → 再次 inspect

7. **告知用户**输出路径

## 快捷方式

对于简单的 Markdown → DOCX 转换（不需要高级排版），仍可使用：
```bash
scholaraio export docx --input file.md --output file.docx
```

## 示例

用户说："帮我总结一下文献库，写个简报到 Word 文件"
→ 调用 `top-cited`、`topics`、`insights` 收集数据 → 写 python-docx 脚本生成带标题、目录、表格、图片的 DOCX

用户说："把 phd-thesis 工作区的论文做成 PPT 给导师汇报"
→ 调用 `ws show phd-thesis` 获取论文列表 → 按主题分组 → 写 python-pptx 脚本生成幻灯片

用户说："导出所有论文的统计数据到 Excel"
→ 遍历 configured papers library 下的 `*/meta.json` 提取字段 → 写 openpyxl 脚本生成带筛选和图表的 XLSX

用户说："画一个流程图然后嵌入到报告里"
→ 先用 draw skill 生成 PNG → 再用 python-docx 的 `add_picture()` 嵌入 DOCX
