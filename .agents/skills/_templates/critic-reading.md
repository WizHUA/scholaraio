---
name: critic-reading
description: 批判性精读模板。用于 subagent 对单篇论文进行 L3/L4 深度分析，强制输出四部分结构化结论，禁止翻译式复述和 bullet point 罗列。
used_by: [literature-review, paper-writing, paper-guided-reading]
version: 1.0.0
---

# 批判性精读模板 (Critic Reading)

你的任务是批判性分析指定论文的 L3（结论）或 L4（全文）内容。

返回必须包含以下四部分：
1. 核心方法及其独特之处（与 workspace 内同类方法相比）
2. 关键实验发现，以及作者的推断是否被证据充分支持
3. 至少 1 个明显局限、方法缺陷或过度宣称
4. 该论文与本 workspace 中其他论文的关联（支持/反驳/扩展了谁）

禁止行为：逐段翻译式复述、只列 bullet point、做没有来源的推测。

输出格式：连贯段落，使用学术语言，引用具体数据或公式时标注页码/章节。
