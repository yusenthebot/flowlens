# FlowLens Troubleshooting Guide

Solutions for common issues, frequently asked questions, performance tuning, and debugging.

---

## Common Errors & Solutions

### SDK & Instrumentation

#### "No module named 'flowlens'"

**Problem:** FlowLens is not installed or not in your Python path.

**Solution:**
```bash
# Check if installed
python -c "import flowlens; print(flowlens.__version__)"

# If not installed, install it
pip install flowlens

# Or install from source with dev mode
git clone https://github.com/yusenthebot/flowlens.git
cd flowlens
pip install -e .
```

#### "FlowLens instance is None - decorators will be no-ops"

**Problem:** You're using decorators without initializing FlowLens.

**Solution:**
```python
from flowlens import FlowLens

# Initialize at module startup
lens = FlowLens(service_name="my_service")

# Now decorators will work
@lens.trace_agent(name="my_agent")
def my_function():
    pass
```

#### Decorators not capturing spans

**Problem:** Spans are created but not exported or appearing in server.

**Solutions:**

1. **Check exporter configuration:**
```python
from flowlens import FlowLens
from flowlens.sdk.exporters import HTTPExporter

lens = FlowLens(service_name="my_app")

# Set exporter to send to server
exporter = HTTPExporter(server_url="http://localhost:8585")
lens.set_exporter(exporter)
```

2. **Verify async decorator usage:**
```python
# For async functions, use async/await properly
@trace_agent(name="agent")
async def my_async_agent():
    result = await some_async_call()
    return result

# Call it correctly
await my_async_agent()  # Not: my_async_agent() without await
```

3. **Check that FlowLens is initialized before imports:**
```python
# app.py - at the TOP, before imports of decorated modules
from flowlens import FlowLens
lens = FlowLens(service_name="myapp")

# Then import modules that use decorators
from my_agents import agent_function
```

#### "Task was destroyed but it is pending"

**Problem:** Async function finished before span was processed.

**Solution:**

Ensure proper async/await usage and don't use synchronous operations in async spans:

```python
# Good - proper async
@trace_agent(name="agent")
async def my_agent():
    result = await async_operation()
    return result

# Bad - blocking in async
@trace_agent(name="agent")
async def my_agent():
    result = blocking_operation()  # Don't do this in async code
    return result
```

#### Token usage is zero or incorrect

**Problem:** LLM token counts are not being captured.

**Solutions:**

1. **Check response format:**
```python
# The @trace_llm decorator extracts tokens from response
# Supported formats:
# - Anthropic: response.usage.input_tokens / output_tokens
# - OpenAI: response.usage.prompt_tokens / completion_tokens
# - Google: response.usage_metadata.input_token_count
# - Custom: response['usage']['input_tokens']

@trace_llm(name="claude_call")
def call_claude():
    # Make sure to return the full response object, not just text
    response = client.messages.create(...)
    return response  # Not: return response.content[0].text
```

2. **Use token extraction utilities:**
```python
from flowlens.sdk.utils import extract_token_usage

response = {...}  # Any LLM response
usage = extract_token_usage(response, model="gpt-4o")
if usage:
    print(f"Input: {usage.input_tokens}, Output: {usage.output_tokens}")
```

#### Auto-instrumentation not working

**Problem:** OpenAI/Anthropic SDK calls aren't being traced automatically.

**Solution:**

```python
from flowlens import FlowLens
from flowlens.sdk.auto_instrument import auto_instrument

# Initialize FlowLens first
lens = FlowLens(service_name="my_app")

# Then auto-instrument (must be called BEFORE importing client libs)
auto_instrument("openai")  # or "anthropic", "langchain"

# Now import and use clients normally
from openai import OpenAI
client = OpenAI()

# This call will be traced automatically
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello"}]
)
```

---

### Server & Deployment

#### "Connection refused" when connecting to server

**Problem:** FlowLens server isn't running or not accessible.

**Solution:**

1. **Check if server is running:**
```bash
# If using Docker
docker ps | grep flowlens

# If manual install
curl http://localhost:8585/health

# If running, should return: {"status": "ok"}
```

2. **Start the server:**
```bash
# Using Docker
docker compose up -d

# Using manual installation
python -m uvicorn flowlens.server.app:create_app \
  --factory --host 0.0.0.0 --port 8585
```

3. **Check network configuration:**
```bash
# Verify port is open
lsof -i :8585

# Check firewall
ufw status
```

#### "database is locked"

**Problem:** SQLite database is being accessed by multiple processes.

**Solutions:**

1. **Wait for current operation to complete:**
SQLite WAL mode should handle concurrent access. Usually self-resolves.

2. **Force WAL mode:**
```bash
sqlite3 /path/to/flowlens.db
PRAGMA journal_mode = WAL;
.quit
```

3. **Check for stale connections:**
```bash
# If using Docker
docker compose restart flowlens-server
```

4. **Recover database (last resort):**
```bash
# Stop the server
docker compose down

# Check and repair
sqlite3 /data/flowlens.db
PRAGMA integrity_check;

# Rebuild index
REINDEX;

# Exit and restart
.quit
docker compose up -d
```

#### Port already in use

**Problem:** Something else is using port 8585.

**Solution:**

1. **Find what's using the port:**
```bash
# Linux/Mac
lsof -i :8585

# Windows
netstat -ano | findstr :8585
```

2. **Kill the process:**
```bash
# Get the PID from above, then:
kill -9 <PID>

# Or use Docker
docker rm -f $(docker ps -a | grep 8585)
```

3. **Use a different port:**
```bash
docker run -p 9000:8585 flowlens:latest

# Then access at http://localhost:9000
```

#### Dashboard not loading

**Problem:** Can't access dashboard at `http://localhost:8585/dashboard`.

**Solutions:**

1. **Verify server is running and healthy:**
```bash
curl http://localhost:8585/health
```

2. **Check browser console for errors:**
- Open DevTools (F12)
- Check Console tab for JavaScript errors
- Check Network tab for failed requests

3. **Verify CORS settings:**
```bash
# If accessing from different domain, set CORS origins
export FLOWLENS_CORS_ORIGINS="http://localhost:3000,http://localhost:8585"

# Restart server
docker compose down
docker compose up -d
```

#### WebSocket connection fails

**Problem:** Real-time trace updates not working.

**Solutions:**

1. **Check if WebSocket is enabled:**
```python
# In flowlens.server.app, WebSocket should be enabled automatically
# Verify with: GET /ws endpoint should upgrade to WebSocket
```

2. **Check proxy configuration:**
If behind Nginx/Apache, ensure WebSocket upgrade headers are configured:
```nginx
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection "upgrade";
```

3. **Firewall blocking:**
WebSocket may be blocked by firewall. Ensure port 8585 (or your port) is open for upgrades.

---

### API Issues

#### "401 Unauthorized" on API requests

**Problem:** API authentication failed.

**Note:** FlowLens v0.4.0 has no authentication by default. If you see this:
- Check if you're behind a reverse proxy that adds authentication
- Verify CORS headers if making cross-origin requests

#### "413 Payload Too Large"

**Problem:** Trace payload exceeds server limits.

**Solution:**

This usually means traces are very large. Check:

```python
# Limit trace size
@trace_agent(name="agent")
def agent_function():
    # Each span adds overhead. Very large traces (10k+ spans) may exceed limits.
    # Consider breaking into smaller traces
    pass
```

#### "429 Too Many Requests"

**Problem:** Rate limit exceeded.

**Solution:**

1. **Increase rate limit:**
```bash
export FLOWLENS_RATE_LIMIT=500  # Requests per minute per IP
docker compose down
docker compose up -d
```

2. **Batch requests:**
```python
# Instead of:
for i in range(1000):
    agent()

# Do:
import time
for i in range(1000):
    agent()
    if i % 100 == 0:
        time.sleep(1)  # Rate limiting
```

---

## Frequently Asked Questions

### General Questions

**Q: What Python versions does FlowLens support?**

A: Python 3.10+ (uses `match` statements and modern type hints). Test on 3.10, 3.11, 3.12.

**Q: Can I use FlowLens with synchronous code?**

A: Yes. All decorators work with both async and sync functions.

```python
from flowlens import FlowLens

lens = FlowLens(service_name="myapp")

# Both work fine
@lens.trace_agent(name="sync_agent")
def sync_function():
    return "result"

@lens.trace_agent(name="async_agent")
async def async_function():
    return "result"
```

**Q: What LLM providers are supported?**

A: Auto-instrumentation supports:
- OpenAI (GPT-4o, GPT-4o-mini, o1, o1-mini)
- Anthropic (Claude 3.5 Sonnet, Claude 3 Haiku, etc.)
- Google (Gemini 1.5 Pro, Gemini 1.5 Flash)
- DeepSeek (DeepSeek R1, DeepSeek V3)
- And any LLM with manual `@trace_llm` decorator

**Q: Is there a GUI for trace analysis?**

A: Yes! FlowLens includes:
- Web dashboard at `http://localhost:8585/dashboard`
- Interactive DAG visualization
- Trace filtering and search
- Cost breakdown and metrics

**Q: Does FlowLens persist data?**

A: Yes. FlowLens stores traces in SQLite by default at:
- Docker: `/data/flowlens.db` (persistent volume)
- Manual: `./flowlens.db` or configured path

**Q: Can I export traces to external systems?**

A: Currently:
- Export to console (development)
- Export to JSON/JSONL files
- Export via HTTP to FlowLens server
- OTLP export coming in v0.5.0

**Q: What's the overhead of tracing?**

A: Minimal:
- Span creation: <1ms per span
- Context propagation: <0.1ms per span
- Export: Async, non-blocking

**Q: Can I filter or sample traces?**

A: Yes, via exporters:

```python
from flowlens import FlowLens

lens = FlowLens(
    service_name="myapp",
    sample_rate=0.1  # Sample 10% of traces
)

# Or custom sampling:
@trace_agent(name="agent")
def my_agent():
    pass

# Only export if certain condition
exporter = CustomExporter(should_export=lambda trace: trace.error_rate > 0.5)
lens.set_exporter(exporter)
```

### Deployment Questions

**Q: What's the recommended deployment setup?**

A: For production:
1. Docker container with persistent volume
2. Nginx reverse proxy with SSL/TLS
3. Daily backups
4. Rate limiting configured

See `docs/deployment.md` for complete setup.

**Q: How much disk space does FlowLens need?**

A: SQLite is efficient. Rules of thumb:
- Small team (100 traces/day): ~1GB per month
- Medium team (1000 traces/day): ~10GB per month
- Use trace cleanup to limit retention (e.g., keep 30 days)

**Q: Can I use FlowLens with Kubernetes?**

A: Yes. See `docs/deployment.md` for Kubernetes YAML examples.

**Q: How do I backup traces?**

A: Regular SQLite backups:

```bash
# Daily backup
cp /data/flowlens.db /backups/flowlens-$(date +%Y%m%d).db

# Or with Docker
docker compose exec -T flowlens-server \
  sqlite3 /data/flowlens.db ".backup /tmp/backup.db"
```

### Performance Questions

**Q: Why are API responses slow?**

A: Check:
1. Database size (run `VACUUM; ANALYZE;`)
2. Number of spans in trace (large traces = slower analysis)
3. Rate limiting not exceeded
4. Server resources (CPU, RAM)

**Q: How many traces can FlowLens handle?**

A: Depends on:
- Hardware (SQLite is single-threaded)
- Average spans per trace (more spans = slower queries)
- Retention period (older data = larger db)

For reference:
- Typical: 10k-100k traces per week
- Scale up by adding filtering/cleanup or Kubernetes replicas

**Q: How do I optimize dashboard loading?**

A: The dashboard loads traces on-demand. If slow:
1. Reduce number of traces shown (use filters/search)
2. Use date range filters
3. Check database with `ANALYZE; VACUUM;`

---

## Debug Mode Instructions

### Enable Debug Logging

```python
import logging
from flowlens import FlowLens

# Enable debug logging for FlowLens
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("flowlens")
logger.setLevel(logging.DEBUG)

# Initialize with debug
lens = FlowLens(service_name="myapp")
```

### Enable Server Debug Mode

```bash
# Set log level to DEBUG
export FLOWLENS_LOG_LEVEL=DEBUG

# Start server
docker compose down
docker compose up -d

# View logs
docker compose logs -f flowlens-server
```

### Capture All Network Requests

```bash
# Using curl with verbose output
curl -v http://localhost:8585/v1/traces

# Using httpie (more readable)
pip install httpie
http --verbose http://localhost:8585/v1/traces
```

### Database Inspection

```bash
# Connect to database
sqlite3 /path/to/flowlens.db

# List tables
.tables

# Check schema
.schema traces
.schema spans

# Query traces
SELECT id, service_name, error_rate, span_count FROM traces LIMIT 5;

# Find slow traces
SELECT id, duration_ms, span_count
FROM traces
WHERE duration_ms > 5000
ORDER BY duration_ms DESC
LIMIT 10;

# Exit
.quit
```

### Profiling & Benchmarking

```python
import time
from flowlens import FlowLens

lens = FlowLens(service_name="profiling")

# Time decorator overhead
@lens.trace_agent(name="agent")
def my_function():
    time.sleep(0.1)  # Simulate work

# Measure
start = time.time()
for _ in range(100):
    my_function()
elapsed = time.time() - start

print(f"100 traces in {elapsed:.2f}s")
print(f"Average overhead: {(elapsed/100)*1000:.2f}ms per trace")
```

### Common Debug Patterns

```python
# 1. Trace span creation
from flowlens.sdk.core import FlowLens

lens = FlowLens(service_name="debug_app")

@lens.trace_agent(name="debug_agent")
def debug_function():
    print("Agent started")
    yield from range(3)
    print("Agent finished")

# 2. Manual span creation for debugging
with lens.start_span("manual_span", "TOOL") as span:
    span.status = "OK"
    span.output = {"debug": "info"}

# 3. Check active traces
print(f"Active traces: {len(lens._active_traces)}")

# 4. Manual export
from flowlens.sdk.exporters import ConsoleExporter
console_exporter = ConsoleExporter()
for trace in lens._active_traces.values():
    console_exporter.export(trace)
```

---

## Performance Tuning Tips

### SDK-Level Optimization

```python
from flowlens import FlowLens

lens = FlowLens(
    service_name="optimized_app",
    sample_rate=0.5,  # Trace 50% of calls
    max_span_count=5000,  # Limit spans per trace
)

# Use faster exporters for high throughput
from flowlens.sdk.exporters import JSONLExporter

exporter = JSONLExporter(
    file_path="/tmp/traces.jsonl",
    batch_size=100,  # Buffer exports
)
lens.set_exporter(exporter)
```

### Database Optimization

```bash
# Periodic maintenance
sqlite3 /data/flowlens.db << EOF
-- Optimize query planner
PRAGMA optimize;

-- Clean up free pages
VACUUM;

-- Rebuild indexes
REINDEX;

-- Analyze table distribution
ANALYZE;
EOF
```

### Server Optimization

```bash
# Use production ASGI server instead of development uvicorn
pip install gunicorn

gunicorn \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8585 \
  --max-requests 10000 \
  --timeout 120 \
  flowlens.server.app:create_app
```

### Query Optimization

```python
# Instead of fetching all traces:
# Bad: /v1/traces?limit=10000
# Good: /v1/traces?limit=100&offset=0

# Use filters to reduce data:
# /v1/traces?service=myservice&error_only=true&after=2026-03-01
```

---

## Getting Help

If you can't find the answer here:

1. **Check documentation:**
   - `docs/quickstart.md` — Getting started guide
   - `docs/architecture.md` — System design
   - `docs/api-reference.md` — API documentation
   - `CONTRIBUTING.md` — Development guide

2. **Search existing issues:**
   - GitHub Issues: https://github.com/yusenthebot/flowlens/issues

3. **Report a bug:**
   - Include Python version: `python --version`
   - Include FlowLens version: `pip show flowlens`
   - Include minimal reproduction case
   - Include error message and traceback

4. **Ask for help:**
   - Open a GitHub Discussion
   - Include relevant code and error logs
   - Describe what you expected vs what happened

---

## Reporting Issues

Use the bug report template (available in `.github/ISSUE_TEMPLATE/bug_report.md`):

```markdown
## Describe the Bug
[Clear description of the issue]

## To Reproduce
```python
# Minimal code that reproduces the issue
```

## Expected Behavior
[What should happen]

## Actual Behavior
[What actually happens]

## Environment
- Python: 3.11
- FlowLens: 0.4.0
- OS: Ubuntu 22.04
- Docker: Yes/No

## Additional Context
[Any other relevant information]
```

---

## Resources

- **Homepage:** https://github.com/yusenthebot/flowlens
- **Documentation:** `/docs` directory
- **API Reference:** `docs/api-reference.md`
- **Architecture:** `docs/architecture.md`
- **Contributing:** `CONTRIBUTING.md`
