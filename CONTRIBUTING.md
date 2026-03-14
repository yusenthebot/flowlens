# Contributing to FlowLens

Thank you for your interest in contributing to FlowLens! This guide will help you get started.

## Getting Started

### Prerequisites

- Python 3.10 or higher
- git

### Development Setup

1. **Clone the repository:**

```bash
git clone https://github.com/niceyusen/flowlens.git
cd flowlens
```

2. **Create a virtual environment:**

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install in development mode with all dependencies:**

```bash
pip install -e ".[dev]"
```

This installs:
- Core dependencies (FastAPI, Pydantic, aiosqlite)
- Development tools (pytest, pytest-asyncio, black, ruff)
- Optional OTLP export support

4. **Verify installation:**

```bash
pytest tests/ -v
python -m examples.demo_agent
```

All tests should pass and the demo should run successfully.

---

## Code Style Guide

FlowLens follows standard Python conventions. We use automated tools to enforce consistency.

### Formatting & Linting

```bash
# Format code with black (line length 100)
black flowlens/ tests/ examples/

# Check code style with ruff
ruff check flowlens/ tests/

# Type checking (optional but recommended)
mypy flowlens/ --ignore-missing-imports
```

### Code Style Rules

**1. File Organization**

```python
# Standard library imports
import asyncio
import json
from pathlib import Path
from typing import Any, Optional

# Third-party imports
import numpy as np
from fastapi import FastAPI

# Local imports
from .models import Span, Trace
from ..sdk.decorators import trace_agent
```

**2. Naming Conventions**

- Classes: `PascalCase` (e.g., `FlowLens`, `TraceStore`)
- Functions/methods: `snake_case` (e.g., `build_causal_dag`, `start_span`)
- Constants: `UPPER_SNAKE_CASE` (e.g., `DEFAULT_LIMIT`, `MAX_RETRIES`)
- Private: prefix with `_` (e.g., `_estimate_cost`, `_current_span`)

**3. Docstrings**

Use Google-style docstrings for public APIs:

```python
def build_causal_dag(trace: Trace) -> CausalDAG:
    """Build a directed acyclic graph showing error propagation.

    Analyzes trace spans to identify root causes and cascade patterns.
    Classifies each error as ROOT_CAUSE, CASCADED, or INDEPENDENT.

    Args:
        trace: Completed trace with spans

    Returns:
        CausalDAG: Graph with nodes, edges, and root cause classifications

    Raises:
        ValueError: If trace is None
    """
```

**4. Type Hints**

Always use type hints for function signatures:

```python
def get_trace(self, trace_id: str) -> Optional[Trace]:
    """Get a trace by ID."""
    ...

async def export(self, trace: Trace, timeout: float = 30.0) -> None:
    """Export a trace."""
    ...
```

**5. Comments**

- Use comments sparingly; code should be self-documenting
- Explain "why", not "what"
- Use `# TODO`, `# FIXME`, `# NOTE` markers

```python
# Good: Explains why
# Use contextvars for async-safe context propagation across tasks
_current_trace = contextvars.ContextVar('current_trace', default=None)

# Bad: Explains what (code already shows what)
# Set the current trace
_current_trace.set(trace)
```

**6. Line Length**

- Maximum 100 characters (enforced by black)
- Break long lines logically:

```python
# Good
result = long_function_name(
    argument1=value1,
    argument2=value2,
    argument3=value3,
)

# Bad
result = long_function_name(argument1=value1, argument2=value2, argument3=value3)
```

---

## Writing Tests

FlowLens uses pytest with 100% async support.

### Test Organization

```
tests/
├── test_models.py        # Data model unit tests
├── test_decorators.py    # Decorator behavior tests
├── test_dag.py           # DAG builder and pattern detection
└── test_server.py        # API and storage tests
```

### Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run specific file
pytest tests/test_models.py -v

# Run specific test
pytest tests/test_models.py::TestSpan::test_create_default -v

# Run with coverage
pytest tests/ --cov=flowlens --cov-report=html
```

### Writing Test Cases

**1. Use fixtures for setup:**

```python
@pytest.fixture
def captured_traces():
    """Setup FlowLens and capture traces for testing."""
    traces: list[Trace] = []

    def capture(trace: Trace):
        traces.append(trace)

    lens = FlowLens(service_name="test")
    lens.set_exporter(CallbackExporter(capture))
    yield traces
    lens.shutdown()
```

**2. Test async functions with `@pytest.mark.asyncio`:**

```python
@pytest.mark.asyncio
async def test_trace_agent_async(captured_traces):
    @trace_agent(name="bot")
    async def my_agent():
        return "done"

    result = await my_agent()
    assert result == "done"
    assert len(captured_traces) == 1
```

**3. Test edge cases:**

```python
def test_trace_with_zero_spans(self):
    """Edge case: trace with no spans."""
    trace = Trace(service_name="empty")
    trace.finish()
    assert trace.error_rate == 0.0  # No division by zero
    assert trace.to_dict()["span_count"] == 0
```

**4. Test error conditions:**

```python
def test_invalid_input_raises(self):
    """Test that invalid input raises appropriate exception."""
    with pytest.raises(ValueError, match="span_id cannot be empty"):
        Span(name="test", span_id="")
```

### Test Coverage Requirements

- Aim for ≥90% line coverage
- Test both happy path and error paths
- Test edge cases (empty input, boundary conditions, etc.)

---

## Pull Request Process

### Before Submitting

1. **Create a feature branch:**

```bash
git checkout -b feature/your-feature-name
```

2. **Make your changes:**
   - Keep commits atomic and logical
   - Write clear commit messages

3. **Run tests and linting:**

```bash
# Format code
black flowlens/ tests/ examples/

# Run linting
ruff check flowlens/ tests/

# Run tests
pytest tests/ -v

# Check coverage
pytest tests/ --cov=flowlens
```

4. **Update documentation:**
   - Update docstrings if changing public APIs
   - Update `docs/api-reference.md` for new endpoints
   - Update `docs/architecture.md` if changing core algorithms

5. **Commit and push:**

```bash
git add .
git commit -m "feat: add support for distributed tracing"
git push origin feature/your-feature-name
```

### Creating a Pull Request

1. **Push your branch to GitHub**
2. **Create a PR** with:
   - Clear title (e.g., "Add support for OpenTelemetry export")
   - Description of changes and motivation
   - Reference any related issues (e.g., "Closes #42")
   - Check list of testing and documentation updates

3. **PR Template:**

```markdown
## Description

Brief description of the changes.

## Motivation

Why is this change needed?

## Changes

- List the specific changes
- One item per bullet point

## Testing

- [ ] Tests added/updated
- [ ] All tests pass
- [ ] Edge cases tested

## Documentation

- [ ] Docstrings updated
- [ ] API reference updated (if applicable)
- [ ] Architecture docs updated (if applicable)

## Checklist

- [ ] Code follows style guide
- [ ] Tests pass locally
- [ ] No breaking changes (or clearly documented)
```

### Review Process

- At least one maintainer review required
- Address review feedback promptly
- Request re-review once changes are made
- Merge only when approved and CI passes

---

## Reporting Issues

### Bug Reports

Include:
- Python version and OS
- Minimal reproducible example
- Expected vs actual behavior
- Relevant error messages or logs

**Template:**

```markdown
## Describe the Bug

Clear description of the issue.

## To Reproduce

```python
# Minimal code that reproduces the issue
from flowlens import FlowLens

lens = FlowLens()
# ...
```

## Expected Behavior

What should happen.

## Actual Behavior

What actually happens.

## Environment

- Python: 3.10
- OS: Ubuntu 22.04
- FlowLens version: 0.1.0
```

### Feature Requests

Include:
- Clear use case and motivation
- Proposed API design (if applicable)
- Examples of how it would be used

---

## Development Guidelines

### Architecture Principles

1. **Zero-Intrusion**: Decorators should never modify function behavior
2. **Async-First**: Support async by default, sync as fallback
3. **Type Safety**: Use type hints throughout
4. **Modularity**: Keep concerns separated (SDK, Analysis, Server layers)

### Adding New Features

**If adding a new decorator:**

1. Add to `flowlens/sdk/decorators.py`
2. Support both async and sync functions
3. Handle the case where FlowLens instance is None
4. Add 5+ test cases
5. Document in `docs/api-reference.md`

**If adding a new pattern detector:**

1. Add to `flowlens/analysis/patterns.py`
2. Return `DetectedPattern` objects
3. Add 3+ test cases to `tests/test_dag.py`
4. Update `docs/architecture.md`

**If adding a new API endpoint:**

1. Add to `flowlens/server/app.py`
2. Create Pydantic models for request/response
3. Add 2+ test cases to `tests/test_server.py`
4. Document in `docs/api-reference.md`

### Performance Considerations

- Avoid blocking operations in async code
- Span creation overhead should be <1ms
- DAG analysis should be <100ms for 1000 spans
- Use indexes for database queries >1000 traces

### Dependencies

Before adding a new dependency:

1. Check if it's already included in `pyproject.toml`
2. Prefer standard library when possible
3. For optional dependencies, use extras groups (e.g., `[otlp]`)
4. Keep dependency count low (currently 3 core dependencies)

---

## Release Process

(For maintainers)

```bash
# Update version in pyproject.toml
# Update CHANGELOG.md
# Create release tag
git tag v0.2.0
git push origin v0.2.0

# Build and publish
python -m build
twine upload dist/*
```

---

## Getting Help

- **Documentation**: See `docs/` directory
- **Issues**: Open a GitHub issue
- **Discussions**: GitHub Discussions (TBD)
- **Email**: maintainers in repository

---

## Code of Conduct

Please be respectful and constructive in all interactions. We're building this together!

---

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
