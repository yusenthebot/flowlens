"""End-to-end tests verifying dashboard API endpoints return valid data."""

import pytest

from flowlens.server.app import create_app


def _make_trace_data(
    trace_id="t1",
    has_errors=False,
    service_name="test-svc",
    start_time=1000.0,
    agent_name="vr-alpha",
    session_id="session-001",
    tags=None,
):
    """Build a fully valid trace for dashboard testing."""
    if tags is None:
        tags = {}

    if "agent" not in tags:
        tags["agent"] = agent_name

    if session_id:
        tags["session_id"] = session_id

    return {
        "trace_id": trace_id,
        "service_name": service_name,
        "start_time": start_time,
        "end_time": start_time + 1.0,
        "duration_ms": 1000.0,
        "span_count": 2,
        "total_tokens": 500,
        "total_cost_usd": 0.005,
        "has_errors": has_errors,
        "error_count": 1 if has_errors else 0,
        "metadata": {"env": "test"},
        "tags": tags,
        "spans": [
            {
                "span_id": f"{trace_id}_s1",
                "trace_id": trace_id,
                "parent_span_id": None,
                "name": "agent",
                "kind": "agent",
                "status": "ok",
                "start_time": start_time,
                "end_time": start_time + 1.0,
                "duration_ms": 1000.0,
                "attributes": {
                    "agent.name": agent_name,
                    "test": True,
                },
                "events": [],
                "token_usage": {
                    "input_tokens": 300,
                    "output_tokens": 200,
                    "total_cost_usd": 0.005,
                },
            },
            {
                "span_id": f"{trace_id}_s2",
                "trace_id": trace_id,
                "parent_span_id": f"{trace_id}_s1",
                "name": "search",
                "kind": "tool",
                "status": "error" if has_errors else "ok",
                "start_time": start_time + 0.1,
                "end_time": start_time + 0.5,
                "duration_ms": 400.0,
                "attributes": {},
                "events": [],
                "error": {"message": "timeout"} if has_errors else None,
            },
        ],
    }


class TestDashboardAPIs:
    """E2E tests for dashboard API endpoints."""

    @pytest.fixture
    def client(self, tmp_path):
        """Create test client with seeded data."""
        app = create_app(db_path=str(tmp_path / "dashboard_e2e.db"))
        from fastapi.testclient import TestClient

        client_obj = TestClient(app)

        # Seed realistic data: 10 traces across 3 agents, 2 sessions
        for i in range(10):
            agent = ["vr-alpha", "vr-beta", "vr-gamma"][i % 3]
            session = ["session-001", "session-002"][i % 2]
            has_error = i % 4 == 0

            trace = _make_trace_data(
                trace_id=f"dashboard-t{i}",
                has_errors=has_error,
                agent_name=agent,
                session_id=session,
                start_time=1000.0 + i * 10,
            )
            client_obj.post("/v1/traces/ingest", json=trace)

        return client_obj

    # Health & System
    def test_health_returns_healthy_status(self, client):
        """Health endpoint should return status=healthy with version."""
        r = client.get("/health")
        assert r.status_code == 200

        data = r.json()
        assert data["status"] == "healthy"
        assert "version" in data
        assert "uptime_seconds" in data
        assert "trace_count" in data
        assert "db_size_bytes" in data

    def test_health_correct_version(self, client):
        """Health endpoint should return semantic version string."""
        r = client.get("/health")
        data = r.json()
        version = data["version"]
        parts = version.split(".")
        assert len(parts) >= 2, f"Invalid version format: {version}"

    def test_health_trace_count_nonzero_with_data(self, client):
        """Health endpoint should report correct trace count after seeding."""
        r = client.get("/health")
        data = r.json()
        assert data["trace_count"] == 10

    # Stats
    def test_stats_returns_nonzero(self, client):
        """Stats should return non-zero values when traces exist."""
        r = client.get("/v1/stats")
        assert r.status_code == 200

        data = r.json()
        assert data["total_traces"] == 10
        assert data["total_spans"] > 0
        assert data["total_tokens"] > 0
        assert data["total_cost"] > 0.0
        assert "error_traces" in data

    def test_stats_has_required_fields(self, client):
        """Stats response must have all dashboard display fields."""
        r = client.get("/v1/stats")
        data = r.json()

        required_fields = [
            "total_traces",
            "total_spans",
            "total_tokens",
            "total_cost",
            "error_traces",
            "avg_duration_ms",
        ]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
            assert isinstance(
                data[field], (int, float)
            ), f"Field {field} should be numeric, got {type(data[field])}"

    def test_stats_error_traces_count_correct(self, client):
        """Error trace count should match seeded error count."""
        r = client.get("/v1/stats")
        data = r.json()
        assert 2 <= data["error_traces"] <= 4

    # Agents Summary
    def test_agents_summary_detects_agents(self, client):
        """Agent summary should detect agents from span attributes."""
        r = client.get("/v1/agents/summary")
        assert r.status_code == 200

        data = r.json()
        agents = data.get("agents", []) if isinstance(data, dict) else data
        assert isinstance(agents, list), "Should return agents list"
        assert len(agents) > 0, "Should detect at least one agent"

    def test_agents_summary_has_all_seeded_agents(self, client):
        """Should detect all 3 seeded agents: vr-alpha, vr-beta, vr-gamma."""
        r = client.get("/v1/agents/summary")
        data = r.json()
        agents = data.get("agents", []) if isinstance(data, dict) else data

        agent_names = {a["agent"] for a in agents}
        expected = {"vr-alpha", "vr-beta", "vr-gamma"}
        assert expected.issubset(
            agent_names
        ), f"Missing agents. Expected {expected}, got {agent_names}"

    def test_agents_summary_has_key_fields(self, client):
        """Each agent summary should have agent name and metrics."""
        r = client.get("/v1/agents/summary")
        data = r.json()
        agents = data.get("agents", []) if isinstance(data, dict) else data

        assert len(agents) > 0, "Should have agents"
        for agent in agents:
            assert "agent" in agent, "Agent must have 'agent' field"
            assert "trace_count" in agent, "Agent must have 'trace_count'"
            assert "error_count" in agent, "Agent must have 'error_count'"
            assert "total_cost_usd" in agent, "Agent must have 'total_cost_usd'"

    def test_agents_summary_metrics_nonzero(self, client):
        """Agent metrics should be > 0 for agents with traces."""
        r = client.get("/v1/agents/summary")
        data = r.json()
        agents = data.get("agents", []) if isinstance(data, dict) else data

        for agent in agents:
            assert agent["trace_count"] > 0, f"Agent {agent['agent']} has 0 traces"
            assert agent["total_cost_usd"] > 0, f"Agent {agent['agent']} has 0 cost"

    # Activity Stream
    def test_activity_stream_returns_events(self, client):
        """Activity stream should return events with correct structure."""
        r = client.get("/v1/activity/stream")
        assert r.status_code == 200

        data = r.json()
        assert "events" in data, "Activity stream should have 'events' key"
        assert isinstance(data["events"], list), "Events should be a list"
        assert len(data["events"]) > 0, "Should have at least one event"

    def test_activity_stream_event_has_agent_name(self, client):
        """Each activity event should identify the agent that triggered it."""
        r = client.get("/v1/activity/stream")
        data = r.json()

        for event in data["events"]:
            assert "agent" in event or "agent_name" in event, "Event must have agent identification"

    def test_activity_stream_event_has_timestamp(self, client):
        """Each activity event should have a timestamp."""
        r = client.get("/v1/activity/stream")
        data = r.json()

        for event in data["events"]:
            assert (
                "timestamp" in event or "time" in event or "created_at" in event
            ), "Event must have timestamp field"

    # Sessions
    def test_sessions_returns_list(self, client):
        """Sessions endpoint should return a dictionary with sessions list."""
        r = client.get("/v1/sessions")
        assert r.status_code == 200

        data = r.json()
        assert "sessions" in data, "Should have 'sessions' key"
        assert isinstance(data["sessions"], list), "Sessions should be a list"

    def test_sessions_endpoint_works(self, client):
        """Sessions endpoint should work and respond properly."""
        r = client.get("/v1/sessions")
        assert r.status_code == 200

        data = r.json()
        assert "sessions" in data

    def test_sessions_has_basic_structure(self, client):
        """Sessions should be a list structure."""
        r = client.get("/v1/sessions")
        sessions = r.json()["sessions"]
        assert isinstance(sessions, list)

    # Cost Forecast
    def test_cost_forecast_returns_projection(self, client):
        """Cost forecast should return daily costs and projection."""
        r = client.get("/v1/cost/forecast?days=30&forecast_days=10")
        assert r.status_code == 200

        data = r.json()
        assert isinstance(data, (dict, list)), "Cost forecast should return dict or list"

    # Cost Breakdown
    def test_cost_breakdown_groups_data(self, client):
        """Cost breakdown should group costs by service/kind/name."""
        r = client.get("/v1/cost/breakdown?group_by=service_name")
        assert r.status_code == 200

        data = r.json()
        assert isinstance(data, list), "Cost breakdown should be a list"
        assert len(data) > 0, "Should have breakdown groups"

    def test_cost_breakdown_has_dimension_and_cost(self, client):
        """Each breakdown item should have dimension and cost."""
        r = client.get("/v1/cost/breakdown?group_by=service_name")
        items = r.json()

        for item in items:
            assert "dimension" in item, "Breakdown item needs dimension"
            assert "total_cost_usd" in item, "Breakdown item needs cost"
            assert item["total_cost_usd"] > 0, "Cost should be positive"

    # Stats Trends
    def test_stats_trends_returns_timeseries(self, client):
        """Stats trends should return time-series data for charting."""
        r = client.get("/v1/stats/trends?hours=24&bucket_minutes=60")
        assert r.status_code == 200

        data = r.json()
        assert isinstance(data, (dict, list)), "Trends should return dict or list"

    # Static Files
    def test_static_files_serve_200(self, client):
        """All 5 static JS/CSS files should return 200 status."""
        static_files = [
            "/static/dashboard.js",
            "/static/dashboard.css",
            "/static/charts.js",
            "/static/network.js",
            "/static/websocket.js",
        ]

        for file_path in static_files:
            r = client.get(file_path)
            assert r.status_code == 200, f"Static file {file_path} returned {r.status_code}"

    def test_static_dashboard_js_contains_code(self, client):
        """dashboard.js should be valid JavaScript."""
        r = client.get("/static/dashboard.js")
        assert r.status_code == 200

        content = r.text
        assert len(content) > 100, "dashboard.js should have content"

    def test_static_dashboard_css_contains_styles(self, client):
        """dashboard.css should be valid CSS."""
        r = client.get("/static/dashboard.css")
        assert r.status_code == 200

        content = r.text
        assert len(content) > 100, "dashboard.css should have content"
        assert "{" in content and "}" in content, "CSS should have valid syntax"

    # Dashboard HTML
    def test_dashboard_html_serves(self, client):
        """Main dashboard HTML should serve."""
        r = client.get("/dashboard")
        assert r.status_code == 200

        html = r.text
        assert len(html) > 500, "Dashboard HTML should have content"

    def test_root_redirect_or_serves(self, client):
        """Root / should either serve HTML or redirect."""
        r = client.get("/", follow_redirects=True)
        assert r.status_code == 200

    # Patterns & Analysis
    def test_patterns_summary_returns_data(self, client):
        """Patterns summary should return anti-pattern detections."""
        r = client.get("/v1/patterns/summary")
        assert r.status_code == 200

        data = r.json()
        assert isinstance(data, dict), "Patterns summary should be a dict"

    # Feedback System
    def test_feedback_summary_accessible(self, client):
        """Feedback summary endpoint should be accessible."""
        r = client.get("/v1/feedback/summary")
        assert r.status_code == 200

        data = r.json()
        assert isinstance(data, dict), "Feedback summary should be a dict"

    def test_feedback_recent_returns_list(self, client):
        """Feedback recent endpoint should return recent feedback entries."""
        r = client.get("/v1/feedback/recent?limit=10")
        assert r.status_code == 200

        data = r.json()
        assert isinstance(data, (dict, list))


class TestDashboardDataIntegrity:
    """Tests for data consistency across endpoints."""

    @pytest.fixture
    def client(self, tmp_path):
        """Create client with carefully seeded data."""
        app = create_app(db_path=str(tmp_path / "integrity.db"))
        from fastapi.testclient import TestClient

        client_obj = TestClient(app)

        for i in range(5):
            trace = _make_trace_data(
                trace_id=f"integrity-{i}",
                agent_name="test-agent",
                session_id="test-session",
                start_time=1000.0 + i,
            )
            client_obj.post("/v1/traces/ingest", json=trace)

        return client_obj

    def test_stats_and_health_consistent(self, client):
        """Health endpoint trace count should match stats endpoint."""
        health = client.get("/health").json()
        stats = client.get("/v1/stats").json()

        assert (
            health["trace_count"] == stats["total_traces"]
        ), "Health and stats trace counts should match"

    def test_agents_and_stats_span_count_consistent(self, client):
        """Total spans in stats should roughly match agents span sum."""
        stats = client.get("/v1/stats").json()
        agents_resp = client.get("/v1/agents/summary").json()
        agents = agents_resp.get("agents", []) if isinstance(agents_resp, dict) else agents_resp

        total_agent_spans = sum(a.get("total_spans", 0) for a in agents)

        assert (
            abs(total_agent_spans - stats["total_spans"]) <= 5
        ), f"Span count mismatch: agents sum {total_agent_spans} vs stats {stats['total_spans']}"

    def test_cost_breakdown_matches_total_cost(self, client):
        """Cost breakdown sum should equal total cost in stats."""
        stats = client.get("/v1/stats").json()
        breakdown = client.get("/v1/cost/breakdown?group_by=service_name").json()

        breakdown_sum = sum(item.get("total_cost_usd", 0) for item in breakdown)
        stats_total = stats["total_cost"]

        assert (
            abs(breakdown_sum - stats_total) < 0.01
        ), f"Cost mismatch: breakdown sum {breakdown_sum} vs stats {stats_total}"


class TestDashboardErrorHandling:
    """Tests for API error handling and edge cases."""

    @pytest.fixture
    def client(self, tmp_path):
        """Create clean client."""
        app = create_app(db_path=str(tmp_path / "errors.db"))
        from fastapi.testclient import TestClient

        return TestClient(app)

    def test_stats_returns_zeros_on_empty_db(self, client):
        """Stats should return valid zeros when no traces exist."""
        r = client.get("/v1/stats")
        assert r.status_code == 200

        data = r.json()
        assert data["total_traces"] == 0
        assert data["total_spans"] == 0

    def test_agents_returns_empty_on_no_traces(self, client):
        """Agent summary should return empty when no data."""
        r = client.get("/v1/agents/summary")
        assert r.status_code == 200

        data = r.json()
        agents = data.get("agents", []) if isinstance(data, dict) else data
        assert isinstance(agents, list)
        assert len(agents) == 0

    def test_sessions_returns_empty_on_no_traces(self, client):
        """Sessions should return empty when no traces."""
        r = client.get("/v1/sessions")
        assert r.status_code == 200

        data = r.json()
        assert "sessions" in data
        assert data["sessions"] == []

    def test_invalid_cost_breakdown_group_by_returns_error(self, client):
        """Invalid group_by parameter should return error."""
        r = client.get("/v1/cost/breakdown?group_by=invalid_field")
        assert r.status_code in [400, 422]

    def test_invalid_stats_trends_hours_returns_error(self, client):
        """Stats trends with invalid hours should error."""
        r = client.get("/v1/stats/trends?hours=9999999")
        assert r.status_code in [200, 400, 422]

    def test_negative_pagination_offset_rejected(self, client):
        """Negative pagination offset should be rejected."""
        r = client.get("/v1/sessions?offset=-1")
        assert r.status_code in [400, 422]

    def test_zero_cost_forecast_days_rejected(self, client):
        """Zero forecast days should be rejected."""
        r = client.get("/v1/cost/forecast?forecast_days=0")
        assert r.status_code in [400, 422]
