# 学术长文综述编写流程（精简版）

**目标**：撰写20-50页深入学术综述
**核心原则**：段落驱动论述、批判性分析、技术细节深入、完整引用标注

---

## 一、文献调研阶段

### 0.1 输出格式确认（必须先问）

在开始任何写作前，**必须主动询问用户**期望的输出格式：

- **Markdown 速览稿**：轻量、便于在线阅读、快速迭代
- **LaTeX 正式学术综述**：20–50页深度综述，最终输出 PDF

若用户选择 LaTeX，后续步骤必须严格执行本指南中标记为 **(LaTeX)** 的规范。

### 1.1 检索策略（三轮检索）
- **本地知识库**：`usearch`融合检索 + `search-author`关键作者
- **互联网补充**：`websearch`最新进展 + 第三方深度分析
- **arXiv预印本**：`arxiv`未正式发表的奠基性工作

### 1.2 核心文献识别
- [ ] 奠基性论文（领域开创，高引用）
- [ ] 顶会论文（ISCA/MICRO/HPCA/ASPLOS）
- [ ] 工业界技术报告（官方博客/白皮书）
- [ ] 关键人物工作（追踪核心作者序列）

### 1.3 文献入库流程
```bash
# 下载PDF → configured paper inbox
curl -o data/spool/inbox/xxx.pdf <URL>

# 批量入库
scholaraio pipeline ingest

# 验证入库
ls data/libraries/papers/ | grep <作者>

# 创建综述工作区
scholaraio ws init <survey-name>
scholaraio ws add <survey-name> <paper-id>...
```

### 1.4 深度阅读（L1→L4）
```bash
scholaraio show <id> --layer 1  # 元数据确认
scholaraio show <id> --layer 2  # 摘要理解
scholaraio show <id> --layer 4  # 全文精读
```

**阅读要点**：
- 架构设计动机和背景
- 核心技术实现细节
- 性能数据（吞吐/延迟/能效）
- 与相关工作的对比
- 局限性和未来方向

---

## 二、内容规划阶段

### 2.1 标准结构（7-10章）
1. **引言**（3-4页）：背景、问题、范围、贡献
2. **主体章节**（20-24页）：按时间线或技术主题展开
3. **软件生态**（4-5页）：编程模型、编译器、运行时
4. **横向对比**（4-5页）：与竞品技术的批判性对比
5. **未来趋势**（3-4页）：技术方向、开放问题
6. **结论**（1-2页）：核心发现总结

### 2.2 写作规范（红线）
| ✅ 必须做 | ❌ 禁止做 |
|-----------|-----------|
| 连贯段落论述 | 简单罗列bullet point |
| 批判性分析（优势/局限/权衡） | 仅描述不分析 |
| 深入技术细节（微架构/算法） | 浅尝辄止的概念介绍 |
| 每个技术事实标注引用 `[n]` | 无来源的陈述 |
| 图注与图片内容严格匹配 | 未查看图片就写图注 |
| 使用完整表格展示对比数据 | 碎片化的数据散落文中 |

---

## 三、写作执行阶段

### 3.1 LaTeX模板核心配置 (LaTeX)

```latex
\documentclass[12pt,a4paper]{article}
\usepackage[fontset=none]{ctex}
\setCJKmainfont{Noto Serif CJK SC}[
    BoldFont={Noto Serif CJK SC Bold},
    ItalicFont={Noto Serif CJK SC}
]
\setCJKmonofont{Noto Sans CJK SC}
\usepackage{microtype} \sloppy
\usepackage{amsmath,booktabs,graphicx,multirow,array}
\usepackage{tikz,pgfplots}
\usepackage{algorithm,algpseudocode}
\usepackage{siunitx}
\usepackage[numbers]{natbib}
\bibliographystyle{unsrt}
\usepackage{hyperref}
\author{技术调研报告 \quad Claude (AI Assistant)}
```

**模板说明**：
- 使用 `article` 而非 `ctexart`，兼容性更好，便于加载 `algorithm` 等包。
- `\setCJKmonofont` 是解决 `listings` 代码环境中 CJK 字符显示异常的关键。
- 若环境已安装 `biblatex`，可改用 `biblatex`；否则 `natbib + \bibliographystyle{unsrt}` 为可靠兜底方案。
- `siunitx` 用于规范输出科学单位（如 `\SI{7}{nm}`、`\num{4096}`）。

### 3.2 丰富元素使用要求 (LaTeX)

**每章至少包含2-3种元素**（含源论文插图）：

0. **源论文插图**（正文章节完成后补充插入）
   ```latex
   \begin{figure}[htbp]
   \centering
   \includegraphics[width=0.8\textwidth]{../../data/libraries/papers/作者-年份-标题/images/图名.jpg}
   \caption{原论文架构图。数据来源：作者, 会议, 年份}
   \label{fig:original}
   \end{figure}
   ```

1. **数据表格**（系统化对比）
   ```latex
   \begin{table}[htbp]
   \centering
   \caption{表标题}
   \footnotesize
   \begin{tabular}{@{}lccc@{}}
   \toprule
   \textbf{特性} & \textbf{Gen 1} & \textbf{Gen 2} \\
   \midrule
   峰值性能 & 92 TOPS & 275 TFLOPS \\
   \bottomrule
   \end{tabular}
   \end{table}
   ```
   若表格过宽，使用 `\resizebox{\textwidth}{!}{...}` 包裹 `tabular`。

2. **TikZ架构图**（可视化抽象概念）
   ```latex
   \begin{figure}[htbp]
   \centering
   \begin{tikzpicture}[
       block/.style={draw, minimum width=2cm, minimum height=1cm}
   ]
   \node[block] (a) {模块A};
   \node[block, right=of a] (b) {模块B};
   \draw[->] (a) -- (b);
   \end{tikzpicture}
   \caption{架构示意图}
   \end{figure}
   ```

3. **伪代码算法**（精确描述流程）
   ```latex
   \begin{algorithm}[htbp]
   \caption{算法名称}
   \begin{algorithmic}[1]
   \Require 输入条件
   \Ensure 输出结果
   \State 执行步骤
   \end{algorithmic}
   \end{algorithm}
   ```

4. **引用标注**（学术严谨性）
   ```latex
   TPU采用了脉动阵列架构[1]。
   根据Jouppi等人的研究[2]，能效比GPU高出30-80倍。
   ```

### 3.3 正文写作检查点

**每段必含**：
- [ ] 主题句（明确论点）
- [ ] 支撑细节（数据/引文/分析）
- [ ] 过渡句（与上下文衔接）

**关键章节必含**：
- [ ] 引言：研究问题明确、综述贡献清晰
- [ ] 主体：技术实现细节、设计权衡分析
- [ ] 对比：批判性视角、数据支撑
- [ ] 结论：核心发现、未来方向

---

## 四、质量控制阶段

### 4.1 技术准确性检查
- [ ] 所有技术参数都有文献来源
- [ ] 架构描述与原始论文一致
- [ ] 性能数据引用权威基准测试
- [ ] 未标注来源的信息已标记 `\textcolor{red}{*}`

### 4.2 LaTeX编译检查 (LaTeX)
```bash
lualatex -interaction=nonstopmode main.tex
bibtex main.aux           # 若使用 natbib
lualatex -interaction=nonstopmode main.tex
lualatex -interaction=nonstopmode main.tex
```

**常见无害警告**：
- `microtype` 可能出现 "slots in the configuration are unknown" 警告（与 `luatexja` 共存时的已知现象），不影响输出。
- CJK 等宽字体的斜体变体缺失时，编译器会自动以正体替代。

### 4.3 补充插入源论文插图（关键步骤）

**时机**：正文内容完成后、最终编译前

**目的**：补充原始论文中的关键架构图、性能图表、数据流图等，增强综述说服力

**操作流程**：

1. **识别关键图表**
   - 从已入库的源论文中筛选重要插图
   - 优先选择：架构示意图、性能对比图、技术演进图、数据流图

2. **提取图片**
   ```bash
   # 查看源论文目录
   ls data/libraries/papers/<作者>-<年份>-<标题>/images/

   # 复制到综述images目录（或直接用相对路径引用）
   mkdir -p workspace/<综述目录>/images/
   cp data/libraries/papers/<作者>-<年份>-<标题>/images/figX.jpg \
      workspace/<综述目录>/images/
   ```

3. **LaTeX插入图片**
   ```latex
   \begin{figure}[htbp]
   \centering
   \includegraphics[width=0.8\textwidth]{images/figX.jpg}
   \caption{原论文图注（翻译/精简）。\\数据来源：Jouppi et al., ISCA 2017}
   \label{fig:original}
   \end{figure}
   ```

4. **图注编写检查**
   - [ ] 打开原图确认内容
   - [ ] 图注准确描述图片展示内容
   - [ ] 标注数据来源（作者/会议/年份）
   - [ ] 正文中引用该图（如"如图~\ref{fig:original}所示"）

**注意事项**：
- 优先使用矢量图（PDF/SVG），如无则使用高分辨率PNG
- 图片宽度建议`0.8\textwidth`或`\columnwidth`
- 涉及多张原论文图片时，保持风格一致性

### 4.4 PDF视觉检查清单（最终核查）
- [ ] 中文显示正常，无乱码
- [ ] **源论文插图已插入并清晰可读**
- [ ] **图注与图片内容严格匹配**
- [ ] 公式、表格编号连续
- [ ] 页码、目录正确
- [ ] 参考文献格式统一

---

## 五、可选归档阶段

### 5.1 归档结构
若团队后续采用独立归档目录，可参考以下结构：

```
<archive-root>/YYYY-MM-DD-<标题>/
├── main.tex              # LaTeX源文件
├── main.pdf              # 编译后的PDF
├── images/               # 插图目录
│   ├── fig1-arch.jpg
│   └── ...
└── metadata.json         # 元数据
```

### 5.2 metadata.json模板
若归档流程需要结构化元数据，可配套维护 `metadata.json`：

```json
{
  "title": "完整标题",
  "date": "2026-04-02",
  "keywords": ["关键词1", "关键词2"],
  "subject": "领域",
  "pdf_filename": "main.pdf",
  "tex_files": ["main.tex"],
  "images_dir": "images",
  "authors": ["Claude (AI Assistant)"],
  "note": "基于xxx文献的综述，涵盖xxx主题"
}
```

---

## 六、快速参考

### 常用命令
```bash
# 文献检索
scholaraio usearch "<关键词>" --top 20
scholaraio websearch "<关键词>" --count 15
scholaraio arxiv "<标题>"

# 文献管理
scholaraio pipeline ingest
scholaraio ws init <name>
scholaraio show <id> --layer 4

# LaTeX编译
lualatex -interaction=nonstopmode main.tex
bibtex main.aux
lualatex -interaction=nonstopmode main.tex
lualatex -interaction=nonstopmode main.tex
```

### 常见陷阱
| 陷阱 | 规避方法 |
|------|----------|
| 未确认输出格式就开写 | 第一步必须问 Markdown 还是 LaTeX |
| 未入库就写作 | 必须先将核心论文入库 |
| 忘记插入源论文插图 | 正文完成后专门补充插图步骤 |
| 图注与图片不符 | 插入前必查看图片内容 |
| 简单罗列摘要 | 批判性整合，分析优缺点 |
| 缺少引用标注 | 每段关键内容标注 `[n]` |
| 浅尝辄止 | 深入到微架构实现细节 |
| 表格过宽溢出 | 使用 `\resizebox` 或 `\footnotesize` |
| 代码环境中文乱码 | 配置 `\setCJKmonofont` |

---

**核心原则回顾**：段落驱动论述、批判性分析、技术细节深入、完整引用标注
