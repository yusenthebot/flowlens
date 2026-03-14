"""FlowLens Analysis — causal DAG engine, root cause analysis, pattern detection."""

from .advisor import TraceAdvisor
from .comparator import TraceDiff, compare_traces
from .dag_builder import (
    build_causal_dag,
    calculate_critical_path,
    get_error_propagation_chain,
)
from .models import (
    CausalDAG,
    CausalEdge,
    CausalNode,
    DetectedPattern,
    ErrorRole,
    PatternType,
)
from .patterns import detect_patterns

__all__ = [
    # DAG building
    "build_causal_dag",
    "calculate_critical_path",
    "get_error_propagation_chain",
    # Models
    "CausalDAG",
    "CausalNode",
    "CausalEdge",
    "ErrorRole",
    "PatternType",
    "DetectedPattern",
    # Pattern detection
    "detect_patterns",
    # Advice engine
    "TraceAdvisor",
    # Comparator
    "compare_traces",
    "TraceDiff",
]
