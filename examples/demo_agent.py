#!/usr/bin/env python3
"""
FlowLens Demo — 一个会出错的 Agent，演示完整采集和分析链路

运行方式：
    python -m examples.demo_agent

演示内容：
1. Agent 执行一个多步任务
2. 中途某个 tool 超时 → 导致级联失败
3. Agent 重试 → 最终成功
4. FlowLens 采集全部 trace → 导出 JSONL
5. 分析因果 DAG → 检测 pattern → 输出报告
"""

import asyncio
import random
import sys
import os
import time

# 确保可以从项目根目录运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flowlens import FlowLens, trace_agent, trace_tool, trace_llm
from flowlens.sdk.models import Trace
from flowlens.analysis.dag_builder import build_causal_dag
from flowlens.analysis.patterns import detect_patterns


# ===== 模拟 LLM 响应 =====

class FakeLLMResponse:
    """模拟 Anthropic SDK 返回格式"""
    def __init__(self, text: str, input_tokens: int, output_tokens: int):
        self.content = [type("Block", (), {"type": "text", "text": text})()]
        self.usage = type("Usage", (), {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        })()
        self.stop_reason = "end_turn"


# ===== 被装饰的函数 =====

@trace_llm(model="claude-sonnet-4-20250514", name="planner")
async def call_llm(prompt: str) -> FakeLLMResponse:
    """模拟 LLM 调用"""
    await asyncio.sleep(0.05)
    return FakeLLMResponse(
        text=f"Plan: search → fetch → summarize for '{prompt}'",
        input_tokens=random.randint(800, 1500),
        output_tokens=random.randint(200, 600),
    )


call_count = {"search": 0, "fetch": 0}


@trace_tool(name="web_search")
async def web_search(query: str) -> dict:
    """模拟搜索 — 偶尔失败"""
    call_count["search"] += 1
    await asyncio.sleep(0.03)

    if call_count["search"] == 1:
        # 第一次搜索超时
        raise TimeoutError(f"Search timed out for '{query}' after 30s")

    return {"results": [f"Result 1 for {query}", f"Result 2 for {query}"], "count": 2}


@trace_tool(name="fetch_page")
async def fetch_page(url: str) -> dict:
    """模拟页面抓取 — 第一次因为上游 search 失败而收到无效输入"""
    call_count["fetch"] += 1
    await asyncio.sleep(0.02)

    if call_count["fetch"] == 1:
        # 级联失败：收到空 URL（因为 search 失败了）
        raise ValueError(f"Invalid URL: '{url}' — likely from failed upstream search")

    return {"title": "Example Page", "content": f"Content from {url}"}


@trace_tool(name="summarize")
async def summarize(text: str) -> dict:
    """模拟摘要"""
    await asyncio.sleep(0.02)
    return {"summary": f"Summary of: {text[:50]}..."}


@trace_agent(name="research_bot")
async def run_research_agent(task: str) -> dict:
    """
    Research Agent — 模拟一个有故障恢复的 Agent

    流程：
    1. LLM 规划
    2. 搜索（第 1 次超时）
    3. 抓取（第 1 次级联失败）
    4. 重试搜索（成功）
    5. 重试抓取（成功）
    6. LLM 摘要
    """
    results = {}

    # Step 1: LLM 规划
    plan = await call_llm(task)

    # Step 2: 搜索（会超时）
    try:
        search_result = await web_search(task)
    except TimeoutError:
        # Step 3: 抓取（级联失败 — 用空 URL）
        try:
            await fetch_page("")
        except ValueError:
            pass  # 预期的级联失败

        # Step 4: 重试搜索
        search_result = await web_search(task)

    # Step 5: 抓取（成功）
    page = await fetch_page(search_result["results"][0])

    # Step 6: 摘要
    summary = await summarize(page["content"])

    # Step 7: 最终 LLM 整理
    final = await call_llm(f"Organize: {summary['summary']}")

    return {
        "task": task,
        "status": "completed",
        "summary": summary["summary"],
    }


# ===== 分析和报告 =====

def print_analysis(trace: Trace) -> None:
    """打印因果分析报告"""
    dag = build_causal_dag(trace)
    patterns = detect_patterns(trace, dag)

    print("\n" + "=" * 60)
    print("  FlowLens Causal Analysis Report")
    print("=" * 60)

    print(f"\n📊 Trace: {trace.trace_id[:16]}...")
    print(f"   Spans: {len(trace.spans)}")
    print(f"   Duration: {trace.duration_ms:.0f}ms")
    print(f"   Tokens: {trace.total_tokens}")
    print(f"   Cost: ${trace.total_cost_usd:.4f}")
    print(f"   Errors: {trace.error_count}")

    if dag.root_causes:
        print(f"\n🔴 Root Causes ({len(dag.root_causes)}):")
        node_map = {n.span_id: n for n in dag.nodes}
        for rc_id in dag.root_causes:
            node = node_map[rc_id]
            print(f"   → {node.name}: {node.error_message}")

    cascaded = [n for n in dag.nodes if n.error_role.value == "cascaded"]
    if cascaded:
        print(f"\n🟡 Cascaded Errors ({len(cascaded)}):")
        for node in cascaded:
            print(f"   ↳ {node.name}: {node.error_message}")

    if dag.edges:
        print(f"\n🔗 Error Propagation ({len(dag.edges)} edges):")
        node_map = {n.span_id: n for n in dag.nodes}
        for edge in dag.edges:
            src = node_map.get(edge.source_id)
            tgt = node_map.get(edge.target_id)
            if src and tgt:
                print(f"   {src.name} → {tgt.name} ({edge.relation})")

    if patterns:
        print(f"\n⚠️  Detected Patterns ({len(patterns)}):")
        for p in patterns:
            icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(p.severity, "•")
            print(f"   {icon} [{p.pattern_type.value}] {p.description}")

    print(f"\n   Cascade depth: {dag.cascade_depth}")
    print("=" * 60)


# ===== Main =====

collected_traces: list[Trace] = []


def capture_trace(trace: Trace) -> None:
    """回调函数 — 捕获 trace 用于分析"""
    collected_traces.append(trace)


async def main() -> None:
    from flowlens.sdk.exporters import CallbackExporter, ConsoleExporter

    print("🔬 FlowLens Demo — Agent Observability in Action\n")

    # 初始化 FlowLens
    lens = FlowLens(
        service_name="demo-research-bot",
        export_to="console",
        verbose=True,
    )
    # 添加一个 callback exporter 来捕获 trace 对象
    lens.set_exporter(
        type("MultiExporter", (), {
            "export": lambda self, t: (
                ConsoleExporter(verbose=True).export(t),
                capture_trace(t),
            ),
            "shutdown": lambda self: None,
        })()
    )

    # 运行 Agent
    print("▶ Running research agent...\n")
    result = await run_research_agent("Latest advances in agentic AI 2026")
    print(f"\n✅ Agent result: {result['status']}")

    # 分析
    if collected_traces:
        print_analysis(collected_traces[0])

    lens.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
