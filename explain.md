# ScholarAIO 配置与使用指南

这份指南按你的使用习惯定制：

- 主模式：Claude Code / agent 对话式使用
- 次模式：CLI 与 MCP 之后补上
- Python 环境：独立 Conda 环境
- 硬件：NVIDIA GPU
- PDF 方案：本地 MinerU 优先，云 API 兜底
- LLM API：你通过 cc switch 管理 Claude Code API，同时项目内另配 ScholarAIO 所需 LLM 接口
- 密钥管理：优先使用 config.local.yaml，必要时用环境变量覆盖

---

## 1. 先建立正确认知

ScholarAIO 有三层：

1. 核心能力层：Python 模块，真正做入库、检索、向量、主题建模、导出。
2. 接口层：CLI 与 MCP server，把这些能力暴露出去。
3. Agent 编排层：skills 和 instructions，告诉 Claude Code 什么时候用哪些能力。

所以最稳妥的配置顺序，不是先折腾 skill 或 MCP，而是：

1. 配 Python 环境
2. 安装项目与依赖
3. 配置 config.yaml / config.local.yaml
4. 配好 LLM 与 PDF 解析链路
5. 跑 setup check
6. 用最小样本跑 ingest / search / show
7. 最后再理解 MCP 接入

---

## 2. 推荐配置顺序

### 第一步：创建独立 Conda 环境

推荐新建一个干净环境，不要混到你已有科研环境里。

```bash
conda create -n scholaraio python=3.11 -y
conda activate scholaraio
python --version
```

为什么推荐 Python 3.11：

1. 满足项目要求（>=3.10）
2. 与目前常见 scientific stack 兼容较好
3. 比 3.10 更顺，但又没有 3.12 某些三方包的兼容波动

如果你未来准备把 MinerU、本地 embedding、BERTopic 都放一起跑，这个独立环境会省很多排障时间。

### 第二步：在源码仓库内开发安装

你当前是本地源码模式，所以直接在仓库根目录安装：

```bash
pip install -U pip setuptools wheel
pip install -e ".[full]"
```

这会装：

1. 核心依赖
2. 语义检索依赖 embed
3. 主题建模依赖 topics
4. 导入依赖 import
5. PDF 相关依赖

如果你只想先跑最小链路，也可以先：

```bash
pip install -e .
```

之后缺什么再补：

```bash
pip install "scholaraio[embed]"
pip install "scholaraio[topics]"
pip install "scholaraio[full]"
```

### 第三步：初始化配置文件

项目里主配置是 [config.yaml](config.yaml)，敏感信息建议放 [config.local.example.yaml](config.local.example.yaml) 的拷贝文件里。

执行：

```bash
cp config.local.example.yaml config.local.yaml
```

然后你会维护两份配置：

1. `config.yaml`：公共配置、模型名、路径、后端类型
2. `config.local.yaml`：API keys、邮箱、Zotero 等敏感信息

### 第四步：先跑一次环境诊断

```bash
scholaraio setup check --lang zh
```

这一步会检查：

1. Python 版本
2. 核心依赖 / embed / topics / import 是否安装
3. config.yaml 是否存在
4. LLM key 是否配置
5. MinerU 是否可用
6. 数据目录是否存在

这一步应该成为你以后每次排障的第一个命令。

---

## 3. LLM API 应该怎么配

### 你的实际场景

你说你通过 cc switch 管理 Claude Code 本身的 API，这没有问题。但要注意：

1. `cc switch` 解决的是 Claude Code 主 agent 用哪个模型/接口
2. ScholarAIO 自己的元数据提取、TOC/L3 富化、部分 academic workflow，仍然看它自己的配置读取

也就是说，这里是两套“API 使用面”：

1. Claude Code 自己的模型切换
2. ScholarAIO 内部调用的 LLM backend

### 推荐做法

对于 ScholarAIO，自身优先放在 `config.local.yaml`：

```yaml
llm:
  api_key: "你的方舟兼容 API Key"
ingest:
  mineru_api_key: "你的 MinerU 云 API Key（可空）"
  contact_email: "你的邮箱"
```

如果你的方舟 API 是 OpenAI-compatible，就在 [config.yaml](config.yaml) 中把 llm 段设为类似：

```yaml
llm:
  backend: openai-compat
  model: 你的模型名
  base_url: 你的方舟兼容接口根地址
  api_key: null
```

真正的 key 放 `config.local.yaml`。

### 如果你想和 cc switch 配合

推荐两种方式：

#### 方式 A：项目稳定优先

Claude Code 用 cc switch 管理。
ScholarAIO 固定写 `config.local.yaml`。

优点：

1. 最稳
2. 不依赖外部 shell 注入
3. 复现容易

适合你现在这个阶段。

#### 方式 B：环境变量联动

在 Conda 环境激活脚本里注入：

```bash
export SCHOLARAIO_LLM_API_KEY="..."
export OPENAI_API_KEY="..."
```

这样 ScholarAIO 会按优先级读取环境变量。

适合你后期希望多个项目共用同一套 API 注入逻辑。

### 我的建议

你当前先走：

1. `cc switch` 管 Claude Code 主模型
2. `config.local.yaml` 管 ScholarAIO 内部 API

先把两层解耦，避免排障时混在一起。

---

## 4. PDF 转 Markdown 应该怎么配

你想要“本地优先 + 云端兜底”，这是最合理的。

### 路线设计

1. 本地 MinerU：平时主用
2. 云端 MinerU API：本地服务不可用时兜底

项目本身就是这样设计的：会先尝试本地 endpoint，不通再走 cloud key。

### 本地 MinerU 建议

你说 Docker 和 Python 本地服务都可以，我建议：

1. 如果你追求稳定和少污染，优先 Docker
2. 如果你想更容易调试 Python 依赖，再考虑裸 Python 部署

对于入门期，优先 Docker，更省时间。

### 项目侧需要的配置

在 [config.yaml](config.yaml) 中保留：

```yaml
ingest:
  mineru_endpoint: http://localhost:8000
  mineru_cloud_url: https://mineru.net/api/v4
  mineru_api_key: null
```

然后在 `config.local.yaml` 放 cloud key，作为兜底。

### 为什么要两者都配

因为这样你会得到最顺的体验：

1. 本地服务起着时，PDF 直接本地转
2. 本地服务没起或挂了，项目还能 fallback 到云
3. 不会因为某一天没开本地服务，整个 ingest 流程就卡死

### 如果你暂时不想折腾本地 MinerU

可以先只配云 API，或者甚至只放 `.md` 到 inbox。

这不影响你先学会 ScholarAIO 的主流程。

---

## 5. GPU 与 embedding 的配置顺序

你有 NVIDIA GPU，所以建议启用本地 embedding。

### 默认策略

项目默认 embedding 模型是 Qwen3-Embedding-0.6B，首次使用会下载，大约 1.2GB。

配置里建议保持：

```yaml
embed:
  model: Qwen/Qwen3-Embedding-0.6B
  device: auto
  source: modelscope
```

### 为什么先不手改太多

因为项目里已经做了：

1. 自动设备选择
2. GPU 自适应 batch profiling
3. OOM fallback

所以你初期只要保证：

1. PyTorch 能看到 GPU
2. 首次模型下载成功

就够了。

### 建议的验证顺序

先不要直接跑 topics，先跑：

```bash
scholaraio embed
```

确认 embedding 能跑通后，再去碰 BERTopic。

---

## 6. 最推荐的首次完整配置流程

下面是我建议你第一次完整配置时的顺序：

### 阶段 A：环境与项目安装

```bash
conda create -n scholaraio python=3.11 -y
conda activate scholaraio
pip install -U pip setuptools wheel
pip install -e ".[full]"
cp config.local.example.yaml config.local.yaml
scholaraio setup check --lang zh
```

### 阶段 B：填配置

你至少要确认：

1. [config.yaml](config.yaml) 中的 LLM backend / base_url / model 是否与你的方舟接口匹配
2. `config.local.yaml` 中是否填了 `llm.api_key`
3. `config.local.yaml` 中是否填了 `ingest.mineru_api_key` 作为云兜底
4. `contact_email` 是否填写，用于 Crossref polite pool

### 阶段 C：验证基础功能

```bash
scholaraio setup check --lang zh
scholaraio --help
```

### 阶段 D：先走最小数据流

先放一个 Markdown 到 `data/inbox/`，而不是一上来处理 PDF。

然后：

```bash
scholaraio pipeline ingest
scholaraio search "你的关键词"
scholaraio show 论文ID --layer 2
```

### 阶段 E：再测 PDF 链路

1. 启动本地 MinerU 或准备云 API
2. 放一个 PDF 到 `data/inbox/`
3. 再跑：

```bash
scholaraio pipeline ingest
```

### 阶段 F：再测向量与主题

```bash
scholaraio embed
scholaraio vsearch "你的自然语言问题"
scholaraio topics --build
```

---

## 7. 从使用者视角，应该怎么理解日常流程

你以后日常大概率会落到下面四条流程。

### 流程 1：知识库建设

1. 把 PDF / md 放入 inbox
2. 跑 pipeline ingest
3. 跑 audit
4. 跑 rename 或 enrich

### 流程 2：阅读与检索

1. search
2. vsearch
3. usearch
4. show L1-L4

### 流程 3：项目组织

1. 创建 workspace
2. 添加论文到 workspace
3. 在 workspace 内搜索
4. 导出 BibTeX

### 流程 4：写作与研究协作

1. literature-review
2. paper-writing
3. citation-check
4. research-gap

这里最重要的是：

你不需要一开始把所有能力都学会。先把“入库 -> 检索 -> 阅读”三件事跑通，就已经进入正循环。

---

## 8. MCP 到底是什么，为什么先不急着接

对你目前阶段，MCP 可以这样理解：

1. ScholarAIO 的 Python 能力已经存在
2. MCP server 只是把它们包装成一组标准工具
3. 外部客户端通过 MCP 协议调用这些工具

所以你现在先不接 MCP 客户端是对的，因为：

1. 如果本地核心能力都没跑通，接了 MCP 也只是换个入口报错
2. 先用 CLI 把行为跑顺，后面接 MCP 非常自然

你当前最合适的顺序是：

1. 先本地跑通 CLI
2. 再理解 `scholaraio-mcp` 如何启动
3. 最后再把它接给 Claude Desktop / Cursor / 其他 IDE

---

## 9. 插件模式简单理解

虽然你现在是本地开发安装，但插件模式你只需要记住：

1. 插件装上后，会在会话开始时触发 hook
2. hook 会运行 [scripts/check-deps.sh](scripts/check-deps.sh)
3. 脚本会尝试安装 `scholaraio`、复制全局配置到 `~/.scholaraio/config.yaml`
4. 之后数据与配置都落在 `~/.scholaraio/`

这意味着：

1. 本地源码模式适合开发与调试
2. 插件模式适合“在任意项目里调用 ScholarAIO 能力”

你现在先不需要切过去。

---

## 10. 我给你的最终建议

### 第一阶段：最小闭环

目标：先会用，不求全。

1. Conda 新环境
2. `pip install -e ".[full]"`
3. 配 `config.local.yaml`
4. 跑 `scholaraio setup check --lang zh`
5. 用一个 Markdown 跑 `pipeline ingest`
6. 跑 `search` 和 `show`

### 第二阶段：补 PDF 与 GPU 链路

1. 启本地 MinerU
2. 补 MinerU cloud key 作为 fallback
3. 跑一个 PDF 测 ingest
4. 跑 `embed`
5. 跑 `vsearch`

### 第三阶段：进入研究工作流

1. 建 workspace
2. 试 topics
3. 试 export
4. 再用 agent + skills 去做综述和写作

---

## 11. 你下一步最该做什么

如果你要最快进入可用状态，我建议你现在按下面顺序执行：

```bash
conda create -n scholaraio python=3.11 -y
conda activate scholaraio
pip install -U pip setuptools wheel
pip install -e ".[full]"
cp config.local.example.yaml config.local.yaml
scholaraio setup check --lang zh
```

然后你把以下信息补齐：

1. 方舟兼容 API 的 `base_url`
2. 方舟模型名
3. 你的 LLM key
4. 你的 MinerU cloud key（如果有）

补完之后，再跑一次：

```bash
scholaraio setup check --lang zh
```

如果输出全都合理，再开始 ingest 第一篇文档。
