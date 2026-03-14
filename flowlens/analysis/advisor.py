"""
自动建议引擎 — 根据检测到的 patterns 和 DAG 生成可操作的建议

TraceAdvisor 分析 trace、DAG 和 patterns，为每种错误提供：
- 严重等级评分
- 具体的可操作建议
- 成本和时间节省估计
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..sdk.models import Trace
from .models import CausalDAG, DetectedPattern, PatternType


@dataclass
class TraceAdvisor:
    """
    自动建议引擎

    Input:
        - trace: 完整的 agent 执行 trace
        - dag: 构建的因果 DAG
        - patterns: 检测到的 patterns

    Output:
        - 结构化报告，包含严重等级、建议和节省估计
    """
    trace: Trace
    dag: CausalDAG
    patterns: list[DetectedPattern]

    @property
    def severity_score(self) -> int:
        """
        计算 trace 的严重等级评分 (0-100)
        基于：
        - patterns 数量和严重性
        - error 数量和级联深度
        """
        score = 0

        # Pattern 贡献
        for p in self.patterns:
            if p.severity == "critical":
                score += 30
            elif p.severity == "warning":
                score += 15
            elif p.severity == "info":
                score += 5

        # Error 数量贡献
        error_count = self.trace.error_count
        if error_count > 0:
            score += min(20, error_count * 5)

        # 级联深度贡献
        cascade_depth = self.dag.cascade_depth
        if cascade_depth > 0:
            score += min(15, cascade_depth * 5)

        return min(100, score)

    @property
    def estimated_savings(self) -> dict[str, Any]:
        """
        根据检测到的 patterns 估计可能的节省

        Returns:
            {
                "token_savings": int,
                "cost_savings_usd": float,
                "time_savings_ms": float,
            }
        """
        token_savings = 0
        cost_savings = 0.0
        time_savings = 0.0

        for pattern in self.patterns:
            if pattern.pattern_type == PatternType.REDUNDANT_CALLS:
                # 冗余调用可以消除
                call_count = pattern.details.get("call_count", 2)
                # 假设可以消除 (call_count - 1) 次调用
                savings_count = call_count - 1
                # 估计每次 tool 调用的成本（保守估计）
                token_savings += savings_count * 500  # 每次 tool 平均 500 tokens
                cost_savings += savings_count * 0.01
                time_savings += savings_count * 100  # 每次 100ms

            elif pattern.pattern_type == PatternType.SLOW_TOOL:
                # 慢速工具可以优化
                slowness = pattern.details.get("slowness_factor", 3.0)
                duration = pattern.details.get("duration_ms", 0)
                # 假设可以优化到平均水平
                avg_duration = duration / slowness
                time_savings += duration - avg_duration

            elif pattern.pattern_type == PatternType.COST_SPIKE:
                # 成本尖峰可以通过分批处理或缩短上下文来优化
                cost_usd = pattern.details.get("cost_usd", 0)
                # 假设可以节省 30%
                cost_savings += cost_usd * 0.3
                tokens = pattern.details.get("token_count", 0)
                token_savings += int(tokens * 0.3)

            elif pattern.pattern_type == PatternType.CONTEXT_OVERFLOW:
                # 上下文溢出可以通过清理来优化
                usage_ratio = pattern.details.get("usage_ratio", 0.95)
                if usage_ratio >= 0.95:
                    # 假设可以清理 20% 的 tokens
                    tokens = pattern.details.get("total_tokens", 0)
                    token_savings += int(tokens * 0.2)
                    cost_savings += 0.05  # 粗略估计

        return {
            "token_savings": token_savings,
            "cost_savings_usd": round(cost_savings, 4),
            "time_savings_ms": round(time_savings, 1),
        }

    def generate_report(self) -> dict[str, Any]:
        """
        生成完整的分析报告

        Returns:
            {
                "severity_score": int (0-100),
                "severity_level": "low" | "medium" | "high" | "critical",
                "error_summary": str,
                "pattern_summary": list[str],
                "recommendations": list[str],
                "estimated_savings": dict,
                "patterns_detail": list[dict],
            }
        """
        score = self.severity_score
        if score >= 80:
            severity_level = "critical"
        elif score >= 60:
            severity_level = "high"
        elif score >= 40:
            severity_level = "medium"
        else:
            severity_level = "low"

        # 生成错误总结
        error_summary = self._generate_error_summary()

        # 生成 pattern 总结
        pattern_summary = self._generate_pattern_summary()

        # 生成建议
        recommendations = self._generate_recommendations()

        # 获取节省估计
        savings = self.estimated_savings

        return {
            "severity_score": score,
            "severity_level": severity_level,
            "error_summary": error_summary,
            "pattern_summary": pattern_summary,
            "recommendations": recommendations,
            "estimated_savings": savings,
            "patterns_detail": [p.to_dict() for p in self.patterns],
        }

    def _generate_error_summary(self) -> str:
        """生成错误总结"""
        error_count = self.trace.error_count
        total_spans = len(self.trace.spans)
        error_rate = self.trace.error_rate
        cascade_depth = self.dag.cascade_depth
        root_causes = len(self.dag.root_causes)

        parts = []
        if error_count == 0:
            return "Trace 执行成功，无错误"

        parts.append(f"检测到 {error_count}/{total_spans} 个 spans 出错（错误率 {error_rate:.0%}）")

        if root_causes > 0:
            parts.append(f"{root_causes} 个根因")

        if cascade_depth > 0:
            parts.append(f"最大级联深度 {cascade_depth}")

        return "；".join(parts)

    def _generate_pattern_summary(self) -> list[str]:
        """生成 pattern 总结"""
        if not self.patterns:
            return ["未检测到已知 patterns"]

        summary = []
        by_type: dict[PatternType, int] = {}
        for p in self.patterns:
            by_type[p.pattern_type] = by_type.get(p.pattern_type, 0) + 1

        for ptype, count in by_type.items():
            summary.append(f"检测到 {count} 个 {ptype.value} patterns")

        return summary

    def _generate_recommendations(self) -> list[str]:
        """根据 patterns 生成可操作的建议"""
        recommendations = []
        seen = set()

        for pattern in self.patterns:
            ptype = pattern.pattern_type

            if ptype == PatternType.RETRY_STORM:
                tool_name = pattern.details.get("tool_name", "unknown")
                if f"retry_{tool_name}" not in seen:
                    recommendations.append(
                        f"为 {tool_name} 工具添加指数退避重试策略，"
                        f"最大重试次数 3-5 次"
                    )
                    seen.add(f"retry_{tool_name}")

            elif ptype == PatternType.INFINITE_LOOP:
                cycle = pattern.details.get("cycle", [])
                if "loop_break" not in seen:
                    recommendations.append(
                        f"为 {' → '.join(cycle)} 循环添加中断条件，"
                        f"例如最大迭代次数或状态检查"
                    )
                    seen.add("loop_break")

            elif ptype == PatternType.CONTEXT_OVERFLOW:
                model = pattern.details.get("model", "unknown")
                if f"context_{model}" not in seen:
                    recommendations.append(
                        f"清理 {model} 的上下文窗口：使用总结、分页或分层检索"
                    )
                    seen.add(f"context_{model}")

            elif ptype == PatternType.TIMEOUT_CASCADE:
                timeout_span = pattern.details.get("timeout_span", "unknown")
                if f"timeout_{timeout_span}" not in seen:
                    recommendations.append(
                        f"为 {timeout_span} 增加超时时间或添加 fallback 处理"
                    )
                    seen.add(f"timeout_{timeout_span}")

            elif ptype == PatternType.EMPTY_RESPONSE:
                if "empty_response" not in seen:
                    recommendations.append(
                        "检查 LLM 的输入提示词，确保包含足够上下文和明确指示"
                    )
                    seen.add("empty_response")

            elif ptype == PatternType.HALLUCINATION_CASCADE:
                tool_name = pattern.details.get("tool_span", "unknown")
                if f"hallucination_{tool_name}" not in seen:
                    recommendations.append(
                        f"为 {tool_name} 添加输入验证，过滤不合理的 LLM 输出"
                    )
                    seen.add(f"hallucination_{tool_name}")

            elif ptype == PatternType.COST_SPIKE:
                llm_name = pattern.details.get("llm_name", "unknown")
                if f"cost_{llm_name}" not in seen:
                    recommendations.append(
                        f"优化 {llm_name} 的输入大小：缩短提示词、压缩上下文或使用更小模型"
                    )
                    seen.add(f"cost_{llm_name}")

            elif ptype == PatternType.SLOW_TOOL:
                tool_name = pattern.details.get("tool_name", "unknown")
                slowness = pattern.details.get("slowness_factor", 1.0)
                if f"slow_{tool_name}" not in seen:
                    recommendations.append(
                        f"优化 {tool_name} 性能（当前 {slowness:.1f}x 慢于平均）："
                        f"添加缓存、并行化、或使用更快的 API"
                    )
                    seen.add(f"slow_{tool_name}")

            elif ptype == PatternType.REDUNDANT_CALLS:
                tool_name = pattern.details.get("tool_name", "unknown")
                call_count = pattern.details.get("call_count", 2)
                if f"redundant_{tool_name}" not in seen:
                    recommendations.append(
                        f"为 {tool_name} 添加结果缓存，避免重复调用（当前 {call_count} 次）"
                    )
                    seen.add(f"redundant_{tool_name}")

        return recommendations if recommendations else [
            "当前 trace 无明显优化建议"
        ]
