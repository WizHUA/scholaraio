---
name: super-fetch
description: Use when standard fetch or search tools are blocked by WAFs, anti-bot checks, rate limits, or dynamic rendering needs, and the user needs source-annotated web content converted to Markdown.
---
# 强力文献/网页抓取 (Super-Fetch)

绕过严格的 Web 应用防火墙（WAF，如知乎 `zse-ck`）和主流搜索引擎的反爬虫/访问频率限制（IP Block/Timeout），稳定从互联网获取参考资料并转为高标准 Markdown 文档，且带有严格的溯源标记。

## 场景识别
当用户提出以下需求时触发此工作流：
- "到网上搜一些关于XXX的文章爬下来"
- "越过反爬去抓取XXX页面的内容"
- 传统的基于 `requests` 或内置 web search 的工具全部报错（Timeout / 403 Forbidden）。

## 核心组件与依赖策略
此 Skill 提倡将前文开发并成功验证的 DrissionPage 架构复用到其他同类高防网站：
1. **搜索引擎防屏蔽跳板**: 放弃容易触发限流终端的 Bing / DuckDuckGo / Baidu API，使用相对宽松的 `so.com` (360搜索) 配合正则表达式，直接从检索返回的原始 HTML 体中提取精准的目标 URL（避免复杂的 CSS 解析）。
2. **免签防护层穿透**: 废弃常规 `requests` 或弱自动化方案，依赖 `DrissionPage` (`ChromiumPage`) 控制底层浏览器，原生处理复杂的 JS 质询验证（JS Challenge），等待所需 DOM 完全挂载。
3. **Markdown 转化与溯源**: 将抓取的 HTML 正文体使用 `html2text` 转换为整洁的 Markdown，并固化**强制来源注入**流程。

## 执行逻辑 (SOP Workflow)

### 1. 制定检索策略与获取 URL
- **关键词聚合**: 确定需要检索的信息词与限定域（如 `量子计算 核心优势 site:zhihu.com/p/`）。
- **编写/运行跳板脚本**:
  - 在当前工作区动态生成一个类似 `search_360.py` 的轻量搜索请求包装器。
  - 使用简单的 header 并用正则 `re.findall` 从搜索结果的 a 标签中粗暴提取目标 URL IDs。

### 2. 动态渲染提取 (DOM Extraction)
- **部署爬虫拦截点**: 
  - 根据抓取网站特征，定位准确的正文容器（如知乎专栏的 `.Post-RichTextContainer`，微信公众号的 `#js_content`）。
  - 利用 `DrissionPage` 打开网页：`page.get(url)`，确保使用 `page.wait.load_start()` 等隐式等待确保内容刷新。

### 3. 数据清洗与元信息注入 (Data Injection)
- 严禁抓取出来直接交接，必须组装标准化的前言：
  ```python
  md_content = html2text.html2text(content_html)
  header = f"""> **来源信息标注 (Source Annotation)**\n> - **链接**: {url}\n> - **主题**: {topic}\n\n"""
  final_content = header + md_content
  ```
- **持久化**: 分配合理的存放目录结构（默认存放于 `workspace/<当前对应子项目>/vault-local/scraped/`），按标题安全规范（剔除特殊字符）命名为 `.md`。

### 4. 交付检验与汇报
- 从抓取完成的内容里抽取部分大纲确认无跑题（搜索引发的副作用）。
- 向用户汇报：
  1. 成功抓取数量。
  2. 可能偏题的废弃内容声明。
  3. 附带文件路径，以便用户检查和后续调用。
