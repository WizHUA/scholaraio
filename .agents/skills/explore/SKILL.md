---
name: explore
description: Use when the user wants to survey a journal or field, fetch papers from OpenAlex, cluster topics, build exploration embeddings, or search named explore libraries under data/libraries/explore.
---
# 多维文献探索

从 OpenAlex 拉取文献（支持多维过滤），本地嵌入 + BERTopic 聚类 + 多模式搜索，用于文献调研。数据与主库完全隔离。

## 执行逻辑

### 拉取论文

支持多种过滤维度，可任意组合：

```bash
# 按期刊 ISSN
scholaraio explore fetch --issn <ISSN> --name <名称> [--year-range <起-止>]

# 按研究概念
scholaraio explore fetch --concept <OpenAlex-concept-ID> --name <名称>

# 按作者
scholaraio explore fetch --author <OpenAlex-author-ID> --name <名称>

# 按机构
scholaraio explore fetch --institution <OpenAlex-institution-ID> --name <名称>

# 按关键词
scholaraio explore fetch --keyword "acoustic metamaterial" --name <名称>

# 多维组合 + 高引过滤
scholaraio explore fetch --institution I123 --year-range 2020-2025 --min-citations 50 --name <名称>

# 增量更新（追加新论文，DOI 去重）
scholaraio explore fetch --issn 0022-1120 --name jfm --incremental
```

全部过滤参数：
- `--issn` — 期刊 ISSN
- `--concept` — OpenAlex concept ID
- `--topic-id` — OpenAlex topic ID
- `--author` — OpenAlex author ID
- `--institution` — OpenAlex institution ID
- `--keyword` — 标题/摘要关键词搜索
- `--source-type` — 来源类型（journal/conference/repository）
- `--oa-type` — 论文类型（article/review 等）
- `--min-citations` — 最小引用量
- `--year-range` — 年份过滤（如 2020-2025）
- `--name` — 探索库名称（默认从 filter 推导）
- `--incremental` — 增量更新模式

常用期刊 ISSN：
- JFM (Journal of Fluid Mechanics): 0022-1120
- PoF (Physics of Fluids): 1070-6631
- JCP (Journal of Computational Physics): 0021-9991
- IJMF (Int J Multiphase Flow): 0301-9322

### 生成嵌入

```bash
scholaraio explore embed --name <名称> [--rebuild]
```

### 主题聚类

```bash
scholaraio explore topics --name <名称> --build
scholaraio explore topics --name <名称> --rebuild --nr-topics <N>
scholaraio explore topics --name <名称>
scholaraio explore topics --name <名称> --topic <ID> [--limit N]
```

### 搜索（三种模式）

```bash
# 语义搜索（默认）
scholaraio explore search --name <名称> "<查询词>" [--limit N]

# 关键词搜索（FTS5）
scholaraio explore search --name <名称> "<查询词>" --mode keyword

# 融合搜索（语义 + 关键词 RRF 排序）
scholaraio explore search --name <名称> "<查询词>" --mode unified
```

### 生成可视化

```bash
scholaraio explore viz --name <名称>
```

### 列出所有探索库

```bash
scholaraio explore list
```

### 查看探索库信息

```bash
scholaraio explore info
scholaraio explore info --name <名称>
```

对于全新探索库，完整流程是：fetch → embed → topics --build → viz

## 示例

用户说："帮我拉取 JFM 的全部论文"
→ 执行 `explore fetch --issn 0022-1120 --name jfm`

用户说："帮我看看 acoustic metamaterial 领域有哪些研究"
→ 执行 `explore fetch --keyword "acoustic metamaterial" --name acoustic-metamaterial`

用户说："拉取某机构近 5 年高引论文"
→ 执行 `explore fetch --institution I123 --year-range 2020-2025 --min-citations 50 --name inst-highcite`

用户说："在 JFM 里搜 drag reduction"
→ 执行 `explore search --name jfm "drag reduction"`

用户说："用关键词搜索 JFM 中的 turbulence"
→ 执行 `explore search --name jfm "turbulence" --mode keyword`

用户说："更新 JFM 探索库"
→ 执行 `explore fetch --issn 0022-1120 --name jfm --incremental`

用户说："我有哪些探索库"
→ 执行 `explore list`（或 `explore info`）
