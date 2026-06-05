---
name: onboard
description: Quick session onboarding — introduce ScholarAIO capabilities, check environment, survey the knowledge base, list workspaces, and navigate to the target project. Use at the start of a new session when the user wants to get oriented, pick a workspace, or understand the current state of the library.
version: 1.0.0
author: WizHUA/scholaraio
license: MIT
tags: ["onboarding", "session", "workspace", "overview"]
---
# Session Onboard / 会话入场

新会话开始时执行此流程，帮用户快速了解项目全貌、文库现状，并定位到目标工作区。

## 执行逻辑

按以下 4 步顺序执行，每步只输出关键结论，不堆长文。

### Step 1 — 环境速检

```bash
scholaraio setup check --lang zh
```

- 只关注是否有 ❌ 项。全部 ✅ 则一句话带过（"环境就绪"）。
- 有缺失项时简要说明影响，询问用户是否要修复（可转交 `/setup` skill）。

### Step 2 — 文库概况

运行以下命令获取文库快照：

```bash
scholaraio search "" --top 1
```

从输出中读取论文总数（输出首行通常包含 `共 N 篇` 或 `N results`）。

再运行：

```bash
scholaraio ws list
```

汇总后向用户报告：

> **文库概况**
> - 论文总数：N 篇
> - ScholarAIO 工作区：列出名称
> - Workspace 项目：读 `workspace/README.md` 的「已有示例」部分，列出编号项目

如果论文数 > 30，不要展开列表，一句话概括即可。

### Step 3 — 定位工作区

询问用户本次会话要在哪个项目上工作（给出编号列表供选择）。

用户选定后：
1. 读取该项目的 `workspace/<项目>/README.md`，了解项目定位、目录约定和当前状态。
2. 如果项目关联了 ScholarAIO 工作区（如 `circuitcutting-thesis`），运行 `scholaraio ws show <名称>` 查看论文子集。
3. 向用户简要汇报项目当前状态和待办事项（从 README 中提取）。

### Step 4 — 能力速查

根据用户选定的项目类型，推荐最可能用到的 skills：

**文献驱动型项目**（毕设、综述、调研）：
- `/search` — 文献搜索（融合检索）
- `/show` — 查看论文（L1-L4）
- `/workspace` — 工作区管理
- `/literature-review` — 文献综述写作
- `/export` — 导出 BibTeX / DOCX
- `/graph` — 引用图谱
- `/research-gap` — 研究空白识别

**写作型项目**（论文撰写、审稿回复）：
- `/paper-writing` — 章节写作
- `/citation-check` — 引用验证
- `/writing-polish` — 写作润色
- `/review-response` — 审稿回复
- `/document` — 生成 DOCX / PPTX

**演示/分享型项目**（PPT 制作、报告）：
- `/search` — 检索支撑材料
- `/show` — 查看论文细节
- `/draw` — 绘制图表
- `/document` — 生成 PPTX / DOCX
- `/export` — 导出参考文献

**探索型项目**（领域调研、前沿追踪）：
- `/explore` — OpenAlex 多维文献探索
- `/topics` — BERTopic 主题聚类
- `/citations` — 高引排行
- `/insights` — 研究行为分析

只列出与当前项目相关的 3-5 个 skill，附一句话说明，不要全部列出。

## 输出格式

整个 onboard 过程控制在一屏以内，结构如下：

```
🔧 环境状态：<一句话>

📚 文库概况：N 篇论文 | M 个工作区 | K 个项目
   工作区：ws-a, ws-b, ...
   项目：01-XXX, 02-YYY, ...

📂 当前项目：<用户选定的项目>
   状态：<从 README 提取>
   待办：<从 README 提取>

🛠 推荐技能：
   /search — 文献搜索
   /show — 查看论文
   ...
```

## 注意事项

- 这是编排型 skill，不需要新增 Python 代码或 CLI 命令。
- 如果用户直接说了要去哪个项目（如"继续 03-CircuitCutting"），跳过 Step 3 的询问，直接定位。
- 如果用户只想了解项目概况而不想定位到具体工作区，执行 Step 1-2 后停止。
- 所有 CLI 输出超过 30 行时，用 subagent 处理并只返回摘要。
- 首次使用时，如果环境未配置完成，优先引导用户完成 `/setup`。
