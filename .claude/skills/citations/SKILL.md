---
name: citations
description: Use when the user asks about highly cited papers, citation rankings, or updating citation counts from external APIs.
---
# 引用量查询

查看高引论文排行，或补查论文引用量数据。

## 执行逻辑

### 查看高引论文排行

```bash
scholaraio top-cited [--limit N] [--year RANGE] [--journal NAME] [--type TYPE]
```

### 补查引用量

```bash
# 补查所有缺失引用量的论文
scholaraio refetch --all

# 强制重查所有
scholaraio refetch --all --force

# 加速并发（默认 5）
scholaraio refetch --all -j 10

# 补查单篇
scholaraio refetch "<paper-id>"
```

## 示例

用户说："哪些论文引用最多"
→ 执行 `top-cited --limit 20`

用户说："看看流体力学期刊的高引论文"
→ 执行 `top-cited --journal "Fluid Mech"`

用户说："帮我补查引用量"
→ 执行 `refetch --all`

用户说："2020 年以后的综述文章排行"
→ 执行 `top-cited --year 2020- --type review`
