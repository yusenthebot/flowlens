# Cycle 13 Report — Actionable Intelligence

## Summary

Actionable Intelligence cycle focuses on transforming FlowLens from a passive observability dashboard into a proactive decision-making tool. Alpha implements Session Timeline view to organize traces by session_id with new Sessions tab and vertical timeline visualization, enabling multi-trace workflows and session analysis. Beta adds trace feedback/annotations with star rating UI, comments, and filtering to capture user insights about trace quality and span behavior. Gamma delivers cost forecasting with monthly projection, budget progress visualization, cost-by-model breakdown, and optimization quick-wins to enable cost-aware resource planning.

## Goals

- **Alpha**: Session Timeline view — new Sessions tab, group traces by session_id, vertical timeline visualization, new API endpoints for session queries
- **Beta**: Trace feedback/annotations — star rating UI (1-5 stars), comment collection, feedback display in detail panel, filter traces by rating
- **Gamma**: Cost forecasting + budget alerts — monthly cost projection based on 24h trend, budget progress bar with projected overage, cost-by-model breakdown, optimization quick-wins (batch size, retry count, model selection)

## Work Areas

### Alpha — Session Timeline View

**Focus**: Enable users to view and analyze related traces as cohesive sessions.

**Tasks**:
- [ ] **Sessions API endpoint** — /v1/sessions — groups traces by session_id tag, returns session metadata (ID, agent count, trace count, duration, error count, cost)
- [ ] **Sessions tab UI** — New dashboard tab showing session cards: session ID, agent involvement, span/error counts, cost breakdown, time range
- [ ] **Session detail view** — Click session to view timeline of traces within that session, vertical waterfall showing execution order and inter-trace timing
- [ ] **Session filtering** — Filter by agent, status (all-pass / has-error), cost range, date range
- [ ] **Session export** — Export session details (JSON/CSV) with all related traces for offline analysis

**Files**: `flowlens/server/app.py`, `flowlens/server/dashboard.html`, `flowlens/server/static/sessions.js`, `flowlens/server/static/sessions.css`

**Expected Outcome**: Sessions become first-class observability concept; users can track multi-trace workflows and identify session-level patterns.

---

### Beta — Trace Feedback & Annotations

**Focus**: Collect and surface user insights about trace quality and span performance.

**Tasks**:
- [ ] **Star rating system** — 1-5 star rating per trace (default: no rating), persistent in SQLite (traces table)
- [ ] **Comment field** — Free-text comment per trace (max 500 chars) for notes about trace quality, expected behavior, debugging observations
- [ ] **Feedback UI in trace detail panel** — Star rating widget + comment editor below trace metadata, quick-edit inline
- [ ] **Feedback aggregation API** — /v1/traces/:id/feedback — GET/POST feedback, includes rating, comment, modified_at timestamp
- [ ] **Feedback filter** — Filter Traces tab by star rating (1-5 stars, or "unrated"), enables rapid access to problematic/exemplary traces
- [ ] **Feedback statistics** — Trace card shows average rating badge (★★★★☆ 4.2) for quick visual scanning

**Files**: `flowlens/server/app.py`, `flowlens/server/dashboard.html`, `flowlens/server/static/traces.js`, `flowlens/storage/schema.py`

**Expected Outcome**: Teams document trace quality trends, identify high-value instrumentation points, and surface regressions quickly via community feedback.

---

### Gamma — Cost Forecasting + Budget Alerts

**Focus**: Enable cost-aware planning and early warnings before budget overage.

**Tasks**:
- [ ] **Cost forecast model** — Analyze 24h cost trend, extrapolate to monthly projection (assume steady state), confidence interval based on variance
- [ ] **Budget progress bar** — Visual indicator of budget spent vs limit, color-coded (green: <70%, yellow: 70-90%, red: >90%), projected end-of-month status
- [ ] **Cost-by-model breakdown** — Pie/donut chart showing cost contribution by model (GPT-4, GPT-3.5, Claude, etc.), top-3 drivers highlighted
- [ ] **Optimization quick-wins** — Query cost data to identify low-hanging fruit: high-cost retries (>2 retries per trace), N+1 patterns (>5 spans from same agent in <100ms window), high token count spans (>2000 tokens), suggest batch size increase
- [ ] **Monthly projection card** — Show projected month-end cost with warning if >110% of budget, updated hourly
- [ ] **Cost anomaly detection** — Spike alert if hourly cost >2σ above daily average

**Files**: `flowlens/server/app.py`, `flowlens/server/dashboard.html`, `flowlens/server/static/cost.js`, `flowlens/server/static/cost.css`

**Expected Outcome**: Cost becomes proactive control point; teams get early warnings and actionable optimization suggestions, reducing runaway spending.

---

## Blocked

None

## Technical Decisions

### 1. Session Grouping: Tag-Based vs Explicit Session Span

**Decision**: Use session_id tag in trace metadata (tags: {session_id: "..."}), no explicit session span type.

**Rationale**:
- Session is organizational concept, not a span type (keeps schema clean)
- Retroactively supports existing instrumentation (add session_id tag to any trace)
- Flexible: sessions can contain traces from multiple agents or tools
- No schema changes (uses existing tags table)

### 2. Feedback Storage: Traces Table vs Separate Table

**Decision**: Add `star_rating` (int, 1-5, nullable) and `feedback_comment` (text, nullable) columns to traces table.

**Rationale**:
- 1:1 relationship (one feedback per trace)
- Minimal schema expansion (2 columns)
- Fast feedback queries (no join required)
- Feedback tied to trace lifetime (cascade on trace delete)

### 3. Cost Forecast: Simple Extrapolation vs ML Model

**Decision**: Linear extrapolation from 24h trend with variance-based confidence interval.

**Rationale**:
- Simple, interpretable model (no black box)
- Works for steady-state loads (common case for production services)
- Reduces false alarms vs complex ML models
- Easy to explain to stakeholders ("if this pace continues...")

### 4. Budget Alert Timing: Immediate vs Daily Digest

**Decision**: Real-time spike alerts (>2σ anomaly) + daily budget review card on Overview.

**Rationale**:
- Spike alerts catch sudden regressions immediately
- Daily card prevents "alert fatigue"
- Users can opt into hourly/daily email digest (future)
- Keeps Overview focused (one card vs multiple notifications)

## Next Cycle Goals

- [ ] Complete all Session, Feedback, and Cost Forecast implementations
- [ ] Run full E2E tests on session timeline and feedback workflows
- [ ] Performance test cost forecast on 10k+ traces with hourly spike detection
- [ ] User acceptance testing with ops team on cost alerts and quick-wins
- [ ] Plan Cycle 14: ML-based pattern detection or integration with external cost monitoring

## Metrics

| Metric | Target | Notes |
|--------|--------|-------|
| Tests | 1071 + 30 (new session/feedback/forecast tests) | Schema changes: 2 trace columns + new session view |
| Commits | 12-18 (3 agents × 4-6 commits each) | — |
| Session API latency | <100ms (1000+ traces) | Indexed query on session_id tag |
| Feedback UI latency | <50ms (star + comment edit) | Client-side, local persistence |
| Cost forecast accuracy | 90%+ for steady-state loads | Compared against actual month-end cost |
| Budget alert false positive rate | <5% | Based on anomaly threshold tuning |
| Sessions discovered | 10-20 (demo data) | Auto-grouping by session_id tag presence |
| Feedback collection rate | 5%+ of traces | Historical baseline from user feedback data |
| Code organization | 0 file conflicts | Alpha=sessions API, Beta=feedback, Gamma=cost |

## Files Affected

**Alpha** (Session Timeline view):
- `flowlens/server/app.py` — new /v1/sessions, /v1/sessions/:id, /v1/sessions/:id/traces endpoints
- `flowlens/server/dashboard.html` — new Sessions tab section
- `flowlens/server/static/sessions.js` — session timeline rendering, filter logic
- `flowlens/server/static/sessions.css` — session cards, timeline styles

**Beta** (Trace Feedback & Annotations):
- `flowlens/server/app.py` — new /v1/traces/:id/feedback GET/POST endpoints
- `flowlens/server/dashboard.html` — trace detail panel feedback section
- `flowlens/server/static/traces.js` — star rating widget, comment editor, filter logic
- `flowlens/storage/schema.py` — add star_rating, feedback_comment to traces table (v7 migration)
- `flowlens/storage/storage.py` — update trace read/write to include feedback fields

**Gamma** (Cost Forecasting):
- `flowlens/server/app.py` — new /v1/cost/forecast, /v1/cost/by-model, /v1/cost/quick-wins endpoints
- `flowlens/server/dashboard.html` — cost forecast card, budget progress bar, model breakdown chart
- `flowlens/server/static/cost.js` — forecast calculation, anomaly detection logic
- `flowlens/server/static/cost.css` — cost forecast visualizations

## Potential File Conflicts

- **All agents modify app.py**: Coordinate via pull request reviews, each agent owns distinct endpoint sections (Alpha=sessions, Beta=trace feedback, Gamma=cost forecast)
- **Alpha & Beta modify traces.js**: Coordinate on session filter vs feedback filter UI positioning

## Success Criteria

- Session timeline correctly groups traces by session_id; performance <100ms for 1000+ traces
- Feedback star ratings and comments persist and display accurately in trace detail view
- Cost forecast projection matches actual spend within 10% for steady-state loads
- Optimization quick-wins are accurate (identify real N+1, retry, batch opportunities)
- All components accessible in light/dark mode (WCAG AA contrast maintained)
- Zero file conflicts during development via coordinated PR reviews
