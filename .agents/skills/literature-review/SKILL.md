---
name: literature-review
description: Use when the user wants to draft a literature review, survey a research area, summarize a field, organize workspace papers, identify gaps, or export review references.
---
# 文献综述写作

基于工作区中的论文，撰写结构化的文献综述。

## 前提

用户必须指定一个 **workspace**（`--ws NAME`）。如果用户未指定：
1. 运行 `scholaraio ws list` 列出已有工作区
2. 让用户选择或创建一个

综述输出写入 `workspace/<name>/` 目录。

## 模式选择

本 skill 支持两种工作模式：
- **手动模式**（默认）：逐步确认大纲和章节，适合精密打磨的综述写作
- **快速模式**：用户明确要求快速生成时，跳过人工确认，自动完成文献扫描、分组、分析和初稿生成

### 输出格式选择（必须在开始时明确确认）

在了解写作需求时，**必须主动询问用户**期望的输出格式：

1. **Markdown 速览稿**：轻量、便于在线阅读、快速迭代
2. **LaTeX 正式学术综述**：遵循 `docs/writing-guide/academic-survey-writing-guide.md` 的规范，适用于长文深度分析，最终输出 PDF

**如果用户未明确选择，默认追问一次。** 若用户选择 LaTeX 正式学术综述，执行以下准备步骤：
- **必读文档**：
  - `docs/writing-guide/academic-survey-writing-guide.md`（项目内置精简版流程）
  - 若宿主环境提供项目记忆中的学术写作指南文件（如 `academic_writing_guidelines.md`、`academic_writing_rich_elements.md`、`chinese_latex_typesetting.md`），可一并参考；若不可用，则以仓库内文档为准
- **硬性要求**：
  - 使用 `\documentclass[12pt,a4paper]{article}` + `ctex` 编译；中文综述用 `xelatex`，英文综述用 `lualatex`
  - 作者字段必须包含 `Claude (AI Assistant)`
  - 所有非原创论述必须标注数字上标引用 `[n]`，使用 BibTeX 管理；**最终编译前必须执行引用闭合检查**：确保所有 `\cite{}` 都有对应 bibitem，所有 bibitem 都被引用或经 `\nocite{}` 声明，无孤儿文献
  - 禁止生成 AI 风格的密集 bullet point 罗列；优先使用连贯段落、批判性分析、因果推演
  - 每章至少包含 2–3 种丰富元素（源论文插图 + 数据表格/伪代码算法/TikZ 概念图）
  - 图注描述必须与图片实际内容严格对应；**插入任何图片前必须先打开查看**
  - **学术综述必须包含独立的“批判性讨论”章节**：对资料不对称、方法论局限、厂商宣称与独立验证的鸿沟、封闭生态权衡等进行分析
  - 若涉及硬件/微架构演进，必须区分同代内的不同变体（如训练版 vs 推理版），并在结论中逐一总结每一代/变体的核心贡献；如资料充足，建议补充专利布局分析
  - 正文完成后执行“补充插入源论文插图”步骤，最后编译 PDF 并做视觉检查

## 快速模式（Fast Mode）

触发条件（满足任一即可）：
- 用户明确说"快速生成"、"直接写"、"跳过确认"、"先给我一版"
- 用户在请求中体现出明显的时间紧迫或对完整度的要求高于精雕细琢

快速模式执行流程：

**重要原则：快速模式 ≠ 低质量模式。** 快速模式跳过的是与用户的人工确认环节，而不是深度分析环节。以下流程强制执行三道质量控制：Critic 骨架重组、Subagent 批判性精读模板、每章最低丰富元素。

1. **自动摸底文献**：运行 `ws show <name>` 和 `ws search <name> "<主题>"`，快速扫描工作区所有论文的 L1-L2
2. **自动构建骨架**：
   - 如已存在主题模型，参考 `scholaraio topics` 的分组结构（注意：`topics` 反映的是**全局主库**分布，若工作区与主库差异较大，应优先基于工作区论文摘要直接推断分组）
   - 否则直接基于摘要由 LLM 推断最优分组（主题式/方法论式/时间线式/争议式），**不中断用户确认**
3. **Critic 骨架重组（强制）**：
   在写初稿前，必须由 critic subagent 审查自动生成的骨架。审查标准：
   - 分组是否按"方法论演进"或"核心争议"组织，而非机械的年份/机构罗列
   - 各章节标题是否暗示了明确的论点，而非模糊的"XX 年研究"
   - 章节间是否有清晰的逻辑递进（问题 → 方法 → 对比 → 局限）
   若骨架被判定为"清单式"而非"论证式"，必须重写骨架后再进入下一步。
4. **自动深度阅读（强制提示词模板）**：
   对每章节的核心论文，启动 subagent 并行提取 L3/L4 关键发现。**Subagent 必须使用 `_templates/critic-reading.md` 中的批判性精读模板，不得简化。**
   - 将值得保留的发现自动追加到各论文的 `notes.md`。优先使用 CLI：`scholaraio show "<paper-id>" --append-notes "## YYYY-MM-DD | <workspace> | literature-review-fast\n- Finding 1\n- Finding 2"`；若需要批量自动化，再由主 agent 直接读写文件实现
   - 利用 `images/` 和公式进行多模态分析（如适用）
5. **自动生成初稿（丰富元素强制）**：
   - 若用户选择 **Markdown**：按骨架一次性撰写完整综述（含开头、各章节、结尾），保存为 `literature-review.md`。每章必须包含至少 1 个数据对比表或自动生成的概念图（`scholaraio diagram --from-text ...`），禁止纯文字大段罗列
   - 若用户选择 **LaTeX**：按骨架一次性撰写 `literature-review.tex`，每章至少包含 2 种丰富元素（源论文插图 / 数据表格 / 伪代码算法 / TikZ 概念图），编译输出 `literature-review.pdf`
6. **保存产物**：
   - Markdown 模式：
     - 综述正文：`workspace/<name>/literature-review.md`
     - 章节大纲：`workspace/<name>/literature-review-outline.md`
     - 参考文献：`workspace/<name>/references.bib`
   - LaTeX 模式：
     - LaTeX 源文件：`workspace/<name>/literature-review.tex`
     - 编译后的 PDF：`workspace/<name>/literature-review.pdf`
     - 章节大纲：`workspace/<name>/literature-review-outline.md`
     - 参考文献：`workspace/<name>/references.bib`
7. **向用户汇报**：仅输出文件路径、总字数/页数、章节概览，不 dump 全文

快速模式不改变学术态度要求：仍须指出矛盾、区分事实与推测、如实引用来源。

## 执行逻辑（手动模式）

### 1. 了解写作需求（含格式确认）

向用户确认：
- **综述主题**：围绕什么研究问题？
- **目标读者**：期刊论文的 Related Work？学位论文的文献综述章节？独立 review article？
- **语言**：中文 / English
- **篇幅**：大致字数或页数
- **输出格式**：Markdown 速览稿 / LaTeX 正式学术综述（默认必须追问）
- **风格参考**（可选）：用户可提供一篇范文或已有文本，你来分析其结构、叙述风格、引用密度、段落组织方式，然后仿照

若用户选择 **LaTeX 正式学术综述**，立即读取上述必读文档，并将其规范贯彻到后续全部步骤中。

### 2. 摸底文献范围

```bash
scholaraio ws show <name>                    # 查看工作区论文列表
scholaraio ws search <name> "<主题>"          # 范围内搜索
scholaraio topics                             # 主题聚类概览（如已建模）
```

对工作区内论文做 L1-L2 快速扫描（标题 + 摘要），建立全局认知：
```bash
scholaraio show <paper-id> --layer 2          # 逐篇扫描摘要
```

### 3. 构建综述骨架

根据文献内容，提出分组方案（按方法/时间线/研究问题/理论流派），形成章节大纲。向用户展示大纲并确认。

常见组织方式：
- **主题式**：按研究子问题分组（最常用）
- **时间线式**：按发展阶段梳理
- **方法论式**：按技术路线对比
- **争议式**：按观点分歧组织正反论证

**骨架可视化**：若采用方法论式或时间线式，可生成结构图辅助用户理解章节组织：
```bash
# 例如：方法演进时间线
scholaraio diagram --from-text "2000: Method A; 2010: Method B; 2020: Method C" --type tech_route --format drawio

# 例如：主题分类树
scholaraio diagram --from-text "Theme 1 contains X and Y; Theme 2 contains Z" --type model_arch --format svg
```
将图文件路径附在大纲之后供用户参考。

### 4. 深度阅读关键论文

对每个章节的核心论文，先检查 configured papers library 中是否有历史分析笔记（`<paper-dir>/notes.md`），有则复用已有发现，避免重复劳动。

然后加载 L3（结论）或 L4（全文）：
```bash
scholaraio show <paper-id> --layer 3          # 结论
scholaraio show <paper-id> --layer 4          # 全文（仅关键论文）
```

分析完成后，将值得跨会话保留的关键发现追加到论文的 `notes.md`。优先使用 CLI：
```bash
scholaraio show "<paper-id>" --append-notes "## YYYY-MM-DD | <workspace> | literature-review
- 方法特点
- 核心贡献
- 与其他论文的关键对比"
```
也可由主 agent 直接读写文件实现。格式：`## YYYY-MM-DD | <workspace> | literature-review`，内容包括方法特点、核心贡献、与其他论文的关键对比。

**多模态分析**（MinerU 解析的论文保留了图表和公式）：
- 读取论文中的关键图表（configured papers library 下的 `<dir>/images/`），辅助理解实验结果和方法流程
- 分析论文中的数学公式（LaTeX），对比不同论文的建模方法差异
- 必要时编写 Python 代码做定量对比（如提取多篇论文报告的数值结果，绘制对比表格）

引用图谱辅助发现关联：
```bash
scholaraio shared-refs "<id1>" "<id2>"        # 共同引用分析
scholaraio refs "<id>"                        # 参考文献
scholaraio citing "<id>"                      # 被引论文
```

### 5. 撰写综述

按确认的大纲逐节撰写。写作原则：

- **综合而非罗列**：每段围绕一个论点组织多篇文献，不是逐篇摘要
- **批判性视角**：指出方法局限、结论矛盾、实验条件差异
- **明确过渡**：章节间有清晰的逻辑衔接
- **引用格式**：正文中用数字上标 `[n]` 标注来源，与 BibTeX key 对应
- **丰富元素**（LaTeX 模式下强制执行）：
  - 源论文插图：架构图、性能图、数据流图
  - 数据表格：系统对比、规格演进
  - 伪代码算法：核心流程精确描述
  - TikZ/PGFPlots：概念示意图或趋势图
  - **自动生成综述结构图**：对方法论式/争议式综述，优先调用 `diagram --from-text ...` 生成分类框架或演进时间线，插入 LaTeX/Markdown 中。若基于具体论文生成，可附加 `--critic` 启用闭环审查：
    ```bash
    # 基于文字描述直接生成
    scholaraio diagram --from-text "分类：A类包含方法1/2；B类包含方法3/4；本文属于C类" --type model_arch --format svg

    # 基于论文生成（可附加 --critic）
    scholaraio diagram <paper-id> --type model_arch --format svg --critic
    ```
- **如有风格参考**：严格仿照用户提供的范文的叙述节奏、引用密度、段落长度、术语习惯

每写完一节，暂停让用户审阅，再继续下一节。

### 6. 收尾与输出

- 撰写综述开头（研究背景 + 综述范围 + 组织方式）和结尾（现状总结 + 研究空白 + 未来方向）
- **研究空白深度分析（可选但强烈推荐）**：若用户需要系统性的研究空白识别，在写结论前运行 `/research-gap --ws <name>`，将其结构化输出整合到"研究空白与未来方向"段落中，提升综述的学术价值
- 导出参考文献：
```bash
scholaraio ws export <name> -o workspace/<name>/references.bib
```

**Markdown 模式产物**：
- 综述正文：`workspace/<name>/literature-review.md`（或用户指定的文件名）
- 章节大纲：`workspace/<name>/literature-review-outline.md`

**LaTeX 模式产物**：
- 综述源文件：`workspace/<name>/literature-review.tex`
- 编译后的 PDF：`workspace/<name>/literature-review.pdf`
- 章节大纲：`workspace/<name>/literature-review-outline.md`
- 插图目录：`workspace/<name>/images/`（复制自源论文的图片）

### 7. LaTeX 模式下特有的“插图补充、审校与编译”步骤

**时机**：正文全部完成后、向用户交付前

**操作**：
1. **遍历各章节，识别需要补充的源论文关键插图**（架构图、性能图、数据流图、规格对比表）
2. **严格来源审查**：若某技术节点缺乏同行评审来源的架构图/实物照片，**禁止**使用来源不明的互联网图片强行填充；应在正文中如实说明"该代际尚无公开的微架构披露"
3. 将图片从 configured papers library 下的 `<dir>/images/` 复制到 `workspace/<name>/images/`
4. **打开每一张图片确认内容**，然后写准确的 LaTeX `figure` 环境 + `caption`
5. 在正文中以 `"如图~\\ref{fig:xxx}所示"` 的形式引用插图
6. **插图审计脚本（必须执行）**：
   - 检查所有 `\includegraphics{}` 路径是否都存在
   - 检查所有 `\label{}` 是否至少被 `\ref{}` 引用一次
   - 检查所有 `\ref{}` 是否都有对应的 `\label{}`
   - **不要删除**工作目录中的图片文件，仅记录哪些图片未被引用；后续若用户确认进入 `/publish` 归档/发布流程，再按交付需要过滤
7. **引用闭合检查**：
   - 对比 `\cite{}` 与 `\bibitem{}`，确保无孤儿文献、无缺失引用
   - 对于在致谢/背景中提及的核心文献，若未直接 `\cite{}`，使用 `\nocite{}` 保留其 bibitem
8. 运行编译（至少2–3遍修正交叉引用），确认无 "undefined reference" 错误：中文综述用 `xelatex -interaction=nonstopmode literature-review.tex`，英文综述用 `lualatex -interaction=nonstopmode literature-review.tex`
9. 清理编译中间文件（`.aux` `.log` `.out` `.toc` 等），仅保留 `.tex` 和 `.pdf`
10. 打开 PDF 进行最终视觉检查：
    - 中文无乱码
    - 插图清晰、图注与内容严格匹配
    - 页码/目录/引用编号正确
    - 参考文献格式统一
    - 摘要与结论覆盖了全部章节，无遗漏
11. **若该综述后续进入 `published/` 归档目录，同步更新 `metadata.json`**：修正页数、关键词和 note，使其与实际 PDF 一致

## 学术态度

- 论文结论是作者的宣称，不是真理。综述应体现辩证思考。
- 当多篇论文对同一问题有不同结论时，主动指出分歧并分析可能原因。
- 高引用量 ≠ 正确。结合方法学质量、实验条件、可复现性综合评价。
- 明确区分「实验证据支持的结论」和「作者的推测/解读」。

## 示例

用户说："帮我写一篇关于湍流减阻的文献综述，基于 drag-review 工作区"
→ 查看 `ws show drag-review`，扫描论文，提出大纲，逐节撰写

用户说："我有一段范文，帮我按这个风格写"
→ 分析范文的结构和叙述特征，然后仿照该风格组织语言

用户说："用 LaTeX 正式格式写一篇 Groq TPU/GPU 对比综述"
→ 确认格式后，先阅读 `docs/writing-guide/academic-survey-writing-guide.md` 和记忆文件，进入 LaTeX 正式写作流程
