<p align="right">
  <a href="README_EN.md">English</a> | <a href="README.md">中文</a>
</p>

<div align="center">
  <img src="examples/logo.svg" width="80" alt="FlowLens">
  <h1>FlowLens</h1>
  <p><strong>看清你的 AI Agent 到底在做什么。</strong></p>
  <p>为 LLM Agent 团队打造的可观测性平台。像 Chrome DevTools，但面向 AI。</p>
</div>

<p align="center">
  <a href="https://pypi.org/project/flowlens/"><img src="https://img.shields.io/pypi/v/flowlens.svg" alt="PyPI version"></a>
  <a href="https://github.com/yusenthebot/flowlens/actions"><img src="https://img.shields.io/github/actions/workflow/status/yusenthebot/flowlens/ci.yml?branch=main&label=tests" alt="Tests"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10%2B-blue.svg" alt="Python 3.10+"></a>
  <a href="https://github.com/yusenthebot/flowlens/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
  <a href="https://opentelemetry.io/"><img src="https://img.shields.io/badge/OpenTelemetry-compatible-blueviolet.svg" alt="OTEL Compatible"></a>
</p>

<div align="center">
  <img src="examples/screenshot_terminal.png" width="700" alt="实时监控你的 Agent">
  <br>
  <em>实时观察 Alpha、Beta、Gamma 并行工作 — 每次工具调用、每次文件读取、每个决策。</em>
</div>

---

你有没有遇到过 Agent 在你不知道的重试循环中烧掉 $50 的 token？或者花了一小时调试多 Agent 工作流，最后发现根因在三个服务之外？

我们创建 FlowLens 是因为受够了盲飞。运行 AI Agent 团队时，故障模式超出传统日志的捕获能力 — Agent 悄悄重试 47 次、context window 溢出、一个慢工具调用引发全链路阻塞。

**FlowLens 实时捕获这一切。** 追踪每次 LLM 调用、工具执行和决策点 — 然后构建因果错误图，瞬间定位根因。

> **立即体验：** [**在线交互式 Dashboard**](https://yusenthebot.github.io/flowlens/demo_dashboard.html) | [**产品导览**](https://yusenthebot.github.io/flowlens/demo_autoplay.html) — 无需安装

---

## 快速开始 — 交给你的 Agent

把这段话粘贴给 Claude Code、Cursor 或任何 AI 编程助手：

> Set up FlowLens agent observability for this project.
> Install flowlens, add the hook, and start the dashboard.
> Repo: https://github.com/yusenthebot/flowlens

或者自己 30 秒搞定：

```bash
pip install flowlens
flowlens demo --dashboard
# 打开 http://localhost:8585 🎉
```

就这样。你会看到一个包含示例 trace、实时 Agent 监控和成本追踪的 dashboard。

---

## 核心功能

### 实时 Agent 终端
*像 htop，但面向 AI Agent*

<p align="center">
  <img src="examples/screenshot_terminal.png" alt="实时终端" width="820">
</p>

点击任意 Agent 打开 tmux 风格终端面板。实时观看文件读取、bash 命令、grep 模式和 LLM 调用。监控多个 Agent 时自动排列为网格。可拖拽、可缩放，通过 WebSocket 零延迟更新。

**为什么重要：** 几秒内发现卡住的 Agent，而不是等到账单到来。

### Trace 瀑布图
*精确看到时间和金钱花在哪里*

<p align="center">
  <img src="examples/screenshot_traces.png" alt="Trace 列表" width="820">
</p>

每条 trace 都有智能摘要 — "3 Read, 2 Bash, 1 LLM" — 而不是无意义的 UUID。按 Agent、状态、时长或时间窗口筛选。点击任意 trace 查看按 Agent 着色的瀑布时间线，内联显示文件路径、命令和成本分解。

**为什么重要：** 请求耗时 45 秒时，你能精确知道是哪个 3 秒的工具调用导致了 42 秒的级联。

### 智能模式检测
*自动捕获 12 种反模式*

<p align="center">
  <img src="examples/screenshot_patterns.png" alt="模式检测" width="820">
</p>

FlowLens 监控重试风暴、无限循环、context 溢出、超时级联、token 浪费等。每个检测器都可通过环境变量配置阈值。无需编写规则 — 开箱即用。

**为什么重要：** 最烧钱的模式恰恰是你不知道的那些。

### 成本智能
*在账单到来前掌握花费*

<p align="center">
  <img src="examples/screenshot_cost.png" alt="成本分析" width="820">
</p>

按模型、工具或服务分解 token 和成本，支持 16+ 模型。月度预测带置信区间。预算告警支持复合 AND 条件。

**为什么重要：** "昨天花了 $200" 不如 "Agent-3 在用 GPT-4 做 Claude Haiku 就能搞定的任务" 有用。

### 会话时间线
*逐步回放任何对话*

<p align="center">
  <img src="examples/screenshot_sessions.png" alt="会话时间线" width="820">
</p>

按会话分组 trace。查看完整的时间线 — 哪些 Agent 参与了、每步耗时多久、什么失败了、为什么。

### Agent 网络拓扑
*查看 Agent 如何协作*

<p align="center">
  <img src="examples/screenshot_agents.png" alt="Agent 网络" width="820">
</p>

每个 Agent 都有独特的头像、颜色和仪表盘卡片。一眼看到 trace 数量、错误率、成本、延迟和活动曲线。交互式 SVG 网络展示调用层级关系和动态粒子。

---

## 5 行代码接入

```python
from flowlens import FlowLens, trace_agent, trace_llm, trace_tool

lens = FlowLens(service_name="my-agent", export_to="http")

@trace_agent(name="researcher")
async def research(topic):
    plan = await plan_research(topic)     # 自动追踪
    docs = await search_knowledge(plan)   # 成本追踪
    return await synthesize(docs)         # 错误捕获
```

或者用自动插桩跳过装饰器：

```python
from flowlens import FlowLens
from flowlens.sdk.auto_instrument import auto_instrument

lens = FlowLens(service_name="my-agent", export_to="http")
auto_instrument(lens)  # 自动 patch Anthropic、OpenAI、LangChain
```

---

## 竞品对比

|  | Langfuse | LangSmith | Opik | **FlowLens** |
|---|:---:|:---:|:---:|:---:|
| 开源 | ✅ | ❌ | ✅ | **✅** |
| 因果 DAG 分析 | — | — | — | **✅** |
| 反模式检测 | — | — | — | **15+ 可配置** |
| Agent 团队监控 | — | 部分 | — | **实时 + 终端** |
| 会话时间线 | — | — | — | **✅** |
| 成本预测 | — | — | — | **月度 + 置信区间** |
| 自动插桩 | 部分 | ✅ | — | **✅** |
| WebSocket 实时推送 | — | — | — | **✅** |
| 自托管 | Docker | ❌ | Docker | **pip + Docker** |

---

## 架构

```
+------------------------------------------------------------------+
|                         你的 Agent 代码                           |
|   @trace_agent  .  @trace_llm  .  @trace_tool                   |
+---------------+--------------------------------------------------+
                |
        +-------v--------+            +-----------------------------+
        |   SDK 层        |            |      分析层                  |
        |                 |            |                             |
        | . TraceContext   |            | . Causal DAG Builder        |
        | . Exporters x7   |            | . 15+ Pattern Detectors     |
        | . Auto-Instrument|            | . Cost Engine (16+ models)  |
        | . Plugins        |            | . Budget Alert Engine       |
        +-------+---------+            +-----------^-----------------+
                |                                  |
                +------------------>  +------------+------------------+
                      export          |       服务层                    |
                                      |                                |
                                      | . FastAPI REST API (25+ 路由)  |
                                      | . WebSocket 实时推送            |
                                      | . SQLite + FTS5 全文搜索        |
                                      | . SVG Dashboard（单页应用）     |
                                      +--------------------------------+
```

---

## CLI 参考

```bash
flowlens serve    [--host HOST] [--port PORT] [--db PATH]    # 启动仪表盘
flowlens analyze  <trace-file.jsonl>                          # 分析 trace
flowlens export   [--format json|csv|jsonl] [--output FILE]   # 导出数据
flowlens import   <json-file> [--db PATH]                     # 导入 trace
flowlens stats    [--db PATH]                                 # 统计信息
flowlens health   [--db PATH]                                 # 健康检查
flowlens demo     [--all] [--dashboard] [--quick]             # 运行演示
flowlens version                                              # 查看版本
```

---

## 示例

无需 API 密钥：

```bash
python3 examples/quickstart.py           # 基础追踪
python3 examples/rag_pipeline.py         # RAG 全流程
python3 examples/multi_agent.py          # 4 Agent 协作
python3 examples/cost_optimizer.py       # 模型成本对比
python3 examples/live_dashboard.py       # 启动仪表盘
```

| 示例 | 说明 |
|---|---|
| [`quickstart.py`](examples/quickstart.py) | 装饰器基础追踪 |
| [`rag_pipeline.py`](examples/rag_pipeline.py) | RAG：嵌入、搜索、重排、生成 |
| [`multi_agent.py`](examples/multi_agent.py) | 多 Agent + 重试逻辑 |
| [`cost_optimizer.py`](examples/cost_optimizer.py) | 模型策略成本对比 |
| [`demo_dashboard.html`](https://yusenthebot.github.io/flowlens/demo_dashboard.html) | 交互式 dashboard（无需安装） |
| [`demo_autoplay.html`](https://yusenthebot.github.io/flowlens/demo_autoplay.html) | 产品导览（无需安装） |

---

## 文档

| 文档 | 说明 |
|---|---|
| [快速入门指南](docs/quickstart.md) | 逐步上手教程 |
| [API 参考](docs/api-reference.md) | 完整 REST API 文档 |
| [架构说明](docs/architecture.md) | 内部设计与架构 |
| [部署指南](docs/deployment.md) | Docker 与生产环境部署 |
| [常见问题](docs/troubleshooting.md) | 故障排查 |

---

## 参与贡献

欢迎贡献！请参阅 [CONTRIBUTING.md](CONTRIBUTING.md)。

```bash
git clone https://github.com/yusenthebot/flowlens.git
cd flowlens
pip install -e ".[dev]"
python3 -m pytest tests/ -q   # 1156 个测试
```

---

## 准备好看看你的 Agent 在干什么了吗？

```bash
pip install flowlens && flowlens demo --dashboard
```

如果 FlowLens 帮你避免了一次 $50 的重试循环，**给个 Star** 吧。⭐

---

[MIT](LICENSE) — Copyright (c) 2024-2026 FlowLens Contributors
