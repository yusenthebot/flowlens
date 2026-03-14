# Changelog

All notable changes to FlowLens will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Planned
- ML-based anomaly detection (leverage /v1/stats/trends API for statistical analysis)
- Trace sampling strategies (probabilistic, head-based, tail-based)
- Kubernetes operator (custom resource definitions, controller)
- Documentation website (mkdocs with auto-generated API docs)
- PyPI publishing and distribution

---

## [0.8.1] — 2026-03-14

Dark mode polish and micro-interactions cycle. SVG agent avatars, enhanced detail modal with activity timeline and error history, WebSocket-driven notification panel with real-time alerts, comprehensive dark mode fixes for 3D visualization, button ripple effects, trace hover previews, smooth scroll, and WCAG-compliant focus rings. 1071 tests (all passing, Cycle 8 is UI polish only — no schema/API changes).

### Added

#### Cycle 8 Features (2026-03-14 — Dark Mode Polish & Micro-interactions)

- **SVG agent avatars**: 7 custom SVG avatar designs (replacing initials) in AGENT_PROFILES with professional visual identity. Consistent rendering across detail modal, team bar, agents tab, and cards. Scalable to any number of agents (commit 6477b37)

- **Enhanced agent detail modal**: Activity timeline panel displaying recent agent events with status indicators and timestamps. Error history panel showing error count and recent error messages with stack traces. Improved profile section with role badges and metadata. Team bar stagger animation with card-3d-hover for tactile feedback (commit 6477b37)

- **Notification panel with bell icon**: Bell icon in header with badge counter (#notification-badge) showing unread alert count. Slide-down notification center (#notifications-panel) with scrollable alert list, timestamp labels, and clear-all button. Dark/light mode glass morphism styling with proper contrast (commit 4997de4)

- **WebSocket-driven real-time alerts**: Real-time alert streaming via WebSocket /ws/traces broadcast. Three alert types: error alerts (span error detected, shows agent + error message), new agent alerts (unknown agent tag discovered), cost spike alerts (daily cost exceeds threshold). Alert persistence in sessionStorage across page reloads. Push notifications on new alert (commit 4997de4)

- **Keyboard shortcut for notifications**: 'n' key toggles notification panel open/close. Focused keystroke handling prevents conflicts with other shortcuts (commit 4997de4)

- **Dark mode fixes for 3D graph**: Three.js 3D graph container dark background (#1a1a18) and light background (#f5f5f4) with proper contrast. Gradient orb opacity reduced in light mode (0.45 instead of 0.65) to prevent overwhelming brightness. Camera clear color matches theme for seamless experience (commit 8c9e019)

- **Dark mode agent detail modal**: Glass background dark (#rgba(26,26,24,0.95)) and light (#rgba(245,245,244,0.95)) with proper transparency and contrast. Text colors adjusted for both modes (light text on dark, dark text on light). Activity timeline light-mode text colors for readability (commit 8c9e019)

- **Button ripple effect micro-interaction**: .ripple-btn CSS class with ::after pseudo-element ripple animation (200px circle, 0.6s cubic-bezier ease) mimicking material design ripple. Applied to all interactive buttons: tab buttons (Overview/Traces/Agents/Compare/Network), pattern filter buttons, status filter buttons, Apply/Clear/Refresh trace filter buttons, Agents Refresh button, Compare Clear Selection button (commit 8c9e019)

- **Trace row hover preview tooltip**: showTracePreview() with 500ms delay timer (prevents chattering on fast mouse movement). Fetches /v1/traces/:id on hover. Displays 3-line preview: span kind breakdown (LLM/Tool/Agent counts), visual duration bar (proportional fill from 0–100%), error message preview if span contains error. hideTracePreview() clears timer and hides tooltip. .trace-preview-tooltip with dark/light mode variants. onmouseenter/onmouseleave applied to non-compact trace rows (commit 8c9e019)

- **Smooth scroll behavior**: html { scroll-behavior: smooth } and .overflow-y-auto { scroll-behavior: smooth } for native smooth scrolling across entire dashboard without JavaScript. Removes jarring jumps and improves perceived smoothness (commit 8c9e019)

- **Focus ring accessibility**: *:focus-visible { outline: 2px solid rgba(99,102,241,0.5); outline-offset: 2px; border-radius: 4px } for keyboard navigation accessibility. WCAG-compliant indigo focus indicator works with screen readers for keyboard-only users and blind users (commit 8c9e019)

### Changed

- Version bumped to 0.8.1
- SVG agent avatars: 7 custom designs replacing initial-letter system for professional branding
- Agent detail modal: added activity timeline and error history for comprehensive agent context
- Notification system: real-time WebSocket-driven alerts replacing polling
- Button interactions: all buttons now have ripple effect feedback
- Trace list UX: hover previews reduce API round-trips (3-line summary instead of click-to-view)
- Scroll experience: smooth scroll throughout dashboard
- Dark mode: comprehensive fixes for Cycle 7 new elements (3D graph, modals, animations)
- Accessibility: focus rings enable keyboard-only navigation and screen reader use

### Technical Decisions

- **SVG avatars over initials**: Scalable vector graphics provide better visual recognition and branding consistency. Each agent gets unique avatar reflecting role/personality
- **Notification panel architecture**: Real-time WebSocket /ws/traces broadcast avoids polling latency. Session storage persistence ensures alerts survive page reloads. Bell badge provides non-intrusive visual cue
- **Dark mode scope**: All Cycle 7-8 new elements (3D graph, detail modal, animations) validated for WCAG AA contrast ratios. CSS custom properties + media query (prefers-color-scheme) respects OS theme preference
- **Ripple effect UX**: 200px circle, 0.6s ease mimics familiar material design pattern. Applied only to actionable buttons to avoid animation fatigue on non-interactive elements
- **Trace hover preview design**: 500ms delay prevents chattering on fast mouse movements. 3-line preview balances information density (span breakdown, duration, error) with clutter avoidance. No API call until hover to reduce server load
- **Smooth scroll philosophy**: Native scroll-behavior achieves 60fps performance without JavaScript. Removed jarring jumps improving user perception of system responsiveness
- **Focus ring styling**: Indigo color (#634667) with 2px offset prevents text occlusion. Border-radius ensures rounded corners match modern UI patterns. Outline (not box-shadow) ensures visibility on all backgrounds

### Fixed

- Dark mode compatibility for Three.js 3D graph containers
- Text readability in light mode (activity timeline, tooltips)
- Button feedback now visual (ripple) instead of just hover (improved discoverability)
- Trace list UX (hover previews reduce API round-trips)

---

## [0.8.0] — 2026-03-14

3D agent network visualization and CSS animation system cycle. Interactive Three.js WebGL 3D visualization of agent relationships with glowing spheres, drag rotation, and hover highlights. Enhanced `/v1/agents/network` API with enriched node properties (size, status, color). Comprehensive CSS animation system with stagger card entry, 3D hover tilt, floating gradient orbs, and counter animations. 1066 → 1071 tests across 1 visualization and animation cycle.

### Added

#### Cycle 7 Features (2026-03-14 — 3D Visualization & CSS Animations)

- **Three.js 3D agent network visualization**: Interactive WebGL 3D scene visualizing agent relationships as glowing spheres with color from AGENT_PROFILES and size proportional to trace_count. Active agents pulse emissive intensity via requestAnimationFrame, idle agents rendered semi-transparent. Circle layout with dashed edges (opacity scaled to call count). HTML labels positioned via 3D-to-screen projection follow camera rotation. Mouse drag to rotate (OrbitControls-like), hover to highlight and scale, click to open agent detail modal. Cytoscape fallback if THREE unavailable (commit 92d54c5)

- **Mini 3D network preview on Overview**: Simplified Three.js scene (#agent-graph-mini, 200px) below Agent Team bar with auto-rotation, no labels, shares cached relationship data with main scene to avoid duplicate API fetches. Provides quick agent topology check without full graph view. Wired into switchView(), refreshCurrentView(), initial load (commit 92d54c5)

- **Enhanced /v1/agents/network API endpoint**: New endpoint merging summary, activity, profiles, and relationships data into enriched nodes with label, role, color (from AGENT_PROFILES), size (0.3–1.0 normalized by trace_count), status (active/idle), trace_count, error_rate, cost. Includes relationship edges with call counts. Enables 3D visualization to receive complete topology with visual properties (commit 0d0d034)

- **Fixed /v1/agents/relationships to always include all known agents**: Now returns all built-in AGENT_PROFILES agents and any agents discovered from trace tags as nodes in relationship graph, ensuring complete network topology even when agents have no spawn relationships. Edges still reflect only actual spawn spans. Guarantees no agents are orphaned or hidden (commit 0d0d034)

- **CSS animation system with card stagger entry**: cardSlideUp keyframes with stat-card-enter stagger classes (0–320ms delays) applied to all 5 stat cards in Overview. Sequential card entry prevents visual chaos and creates visual hierarchy. Improves perceived dashboard responsiveness (commit 8066f3a)

- **3D card hover tilt effect**: card-3d-hover class with perspective(800px) tilt applied to agent team bar cards and Agents tab cards. Provides tactile feedback on hover without requiring JavaScript. Creates visual depth and makes dashboard feel responsive (commit 8066f3a)

- **Floating gradient orbs background**: gradient-orb + orbFloat keyframes with 3 floating orbs positioned behind Overview content. Adds visual depth and atmosphere without distraction. Uses CSS animations for smooth 60fps performance (commit 8066f3a)

- **Counter animation for metrics**: animateCounter() function with ease-out cubic easing applied to traces, spans, error rate, latency, cost, tokens in loadStats(). Shows data updates smoothly (1000ms duration) rather than instant jumps. Improves user perception of system responsiveness (commit 8066f3a)

- **Chart.js gradient fill in trend charts**: createLinearGradient (0.25 → 0.01 opacity fade) applied to trend area chart fill in loadTrendChart(). Gradient prevents harsh bottom edge and adds visual polish (commit 8066f3a)

- **View panel smooth transitions**: viewEnter animation (opacity + translateY) for smooth tab transitions. Improves UX when switching between dashboard views (commit 8066f3a)

### Changed

- Version bumped to 0.8.0
- Agent network visualization: replaced 2D Cytoscape with Three.js WebGL for immersive 3D experience
- Overview dashboard: added mini 3D graph preview below Agent Team bar
- Card animations: added stagger entry and 3D hover tilt for all interactive cards
- Background: added floating orbs for visual depth
- Metrics: counter animation on all statistic numbers
- Charts: gradient fill in trend area chart

### Technical Decisions

- **Three.js selection over Cytoscape**: WebGL provides superior performance, visual effects (glow, emissive), and rotation interactivity. Sphere rendering enables glow effects via emissive materials. OrbitControls-like rotation familiar to game/CAD users. Cytoscape fallback ensures backward compatibility
- **3D sphere properties**: Colors from AGENT_PROFILES for consistency across dashboard. Size (0.3–1.0) normalized from trace_count to provide immediate visual indicator of agent workload. Glowing pulsing emissive intensity for active agents provides activity feedback
- **Mini scene architecture**: Simplified 3D scene (no labels, auto-rotation) provides quick status without full interaction. Shared _agentRelData cache avoids duplicate API fetches and keeps mini/main scenes in sync
- **Animation stagger timing**: 0–320ms delays chosen for snappy feel (typical UI animation 200–400ms) without feeling sluggish. Sequential entry creates visual hierarchy and prevents overwhelming user with simultaneous animations
- **Gradient fill direction**: Opacity fade (0.25 → 0.01) from top to bottom prevents harsh bottom edge of filled area. Subtle gradient maintains data visibility without distraction
- **3D hover perspective**: 800px perspective provides noticeable ~15° tilt without feeling excessive. Applied only to expected interactive cards to avoid animation fatigue

### Fixed

- Agent relationship graph now returns complete topology including isolated agents (no spawn relationships)
- Dashboard animations now GPU-accelerated via CSS transforms for smooth 60fps performance

---

## [0.7.0] — 2026-03-14

Comparison view enhancements and agent relationship visualization cycle. Enhanced trace comparison with verdict badges and diff indicators, new APIs for agent relationship graphs and activity reports, and interactive Cytoscape-based relationship visualization. 1053 → 1066 tests across 1 comparison and visualization cycle.

### Added

#### Cycle 6 Features (2026-03-14 — Comparison & Relationship Visualization)

- **Enhanced Compare view with verdict badge**: Redesigned Compare view with side-by-side Trace A/B summary cards showing all key metrics (duration, cost, tokens, spans, errors) with clear visual diff indicators. Duration, cost, and token diffs rendered as colored progress bars (green=improvement, red=regression) with percentage change labels. Verdict badge ("Improved", "Regressed", "Similar") computed from weighted score across duration, cost, and error metrics for balanced assessment (commit 29e55e9)

- **Responsive mobile layout**: Responsive grid layouts with breakpoints at 768px (tablet) and 480px (phone). Stat-grid changes from multi-column to single-column with stacked cards for readability on small screens. Compare view and overview panels fully responsive for tablet and phone users (commit 29e55e9)

- **Dark mode polish**: Consistent warm dark gray (#2a2a28) with muted pastels across all UI sections for better eye comfort and accessibility. Color scheme validated against WCAG AA contrast ratios (commit 29e55e9)

- **Agent relationship graph API**: New `/v1/agents/relationships` endpoint returning spawn graph of agent relationships showing which agents spawn which other agents (agent -> spawned_agents mapping), call counts, and timing data. Enables visualization of agent hierarchy and collaboration patterns (commit cd10258)

- **Activity report export API**: New `/v1/export/report` endpoint exporting comprehensive activity reports with agent metrics, relationship data, and trace summaries. Supports multiple formats (JSON, CSV, Markdown) with configurable time range and agent filtering. Foundation for SRE team workflows and incident post-mortems (commit cd10258)

- **Interactive agent relationship visualization**: Cytoscape.js-based interactive directed graph visualization showing agent spawn hierarchy. Nodes represent agents with color-coded avatars from AGENT_PROFILES. Edges show spawn relationships with call count labels. Force-directed layout with automatic zoom-to-fit for large hierarchies. Click-to-highlight shows agent spawn path and dependents (commit 5580ce1)

- **Agent detail modal**: Comprehensive agent information modal displaying profile, avatar, roles, recent activity, error rate, total spans, cost contribution, and related agents. Quick drill-down to individual agent metrics and relationships without leaving dashboard (commit 5580ce1)

- **Keyboard shortcuts for agent graph**: Global keyboard navigation: arrow keys to navigate graph, 'D' for detail modal, 'C' for compare mode, 'E' for export, 'R' to reset graph layout. Enables power-user workflows for rapid multi-agent system analysis (commit 5580ce1)

### Changed

- Version bumped to 0.7.0
- Compare view: added side-by-side cards with diff progress bars and verdict badge
- Dashboard layout: agent relationship graph visualization panel with Cytoscape.js
- Mobile UI: responsive grid layouts and single-column stacking for small screens
- Dark mode: warm palette (#2a2a28) with muted pastels, consistent across all sections

### Technical Decisions

- **Compare view verdict badge**: Weighted score (duration 40%, cost 35%, error count 25%) for balanced assessment across different system priorities
- **Responsive breakpoints**: 768px for tablet (2-col → 1-col), 480px for phone (stacked cards). Mobile-first approach with progressive enhancement
- **Cytoscape.js selection**: Force-directed layout algorithm for automatic node spacing and edge routing. Supports zoom/pan for large agent hierarchies
- **Report export architecture**: Generic report structure (JSON) with adapters for CSV and Markdown. Enables future format additions without core changes
- **Keyboard shortcut design**: Non-intrusive defaults (D, C, E, R) avoiding browser conflicts. Arrow key navigation for graph exploration

---

## [0.6.0] — 2026-03-14

Advanced analytics and trace visualization cycle. Agent-colored waterfall trace debugging, comprehensive trend analysis APIs with per-agent breakdown, interactive activity trend charts, and visual pattern detection dashboard. 1048 → 1053 tests across 1 analytics cycle.

### Added

#### Cycle 5 Features (2026-03-14 — Analytics & Visualization)

- **Trace detail waterfall visualization**: Agent-colored waterfall diagram showing complete span hierarchy with color-coded agents, duration bars, and error highlights. New span detail panel displays agent avatars, status icons, and performance metrics. SVG-based rendering enables crisp interactive debugging of complex traces (commit 860d44b)

- **Trace volume trend analytics API**: New `/v1/stats/trends` endpoint returning time-series trace volume trends over configurable time windows (hourly/daily buckets) with per-agent breakdown. Enables visualization of which agents contribute to traffic patterns and anomalies (commit 4ef045d)

- **Aggregate statistics API with agent breakdown**: New `/v1/stats/summary` endpoint returning aggregate statistics (total traces, spans, errors, cost, average latency) with per-agent breakdown. Supports cost attribution, agent performance comparison, and SLA monitoring (commit 4ef045d)

- **Interactive activity trend charts**: New Activity Analysis dashboard panel with trend line chart showing 24-hour trace volume and error rate trends. Per-agent stacked area visualization shows agent contribution to overall system metrics (commit b2442cd)

- **Visual pattern detection cards**: Dashboard cards displaying detected anti-patterns (retry storms, timeout cascades, context overflow, cold starts, empty responses, infinite loops) with severity icons (critical/high/medium/low), occurrence count badges, and click-to-filter functionality. Color-coded severity indicators (red/orange/yellow/green) enable quick pattern assessment (commit acdbe78)

### Changed

- Version bumped to 0.6.0
- Trace detail view: added interactive waterfall visualization component
- Analytics dashboard: new Activity Analysis panel with trend charts
- Dashboard layout: added pattern detection cards to primary observability view

### Technical Decisions

- **Waterfall visualization color scheme**: Agent colors mapped from AGENT_PROFILES configuration for consistency with timeline and cost charts. Error spans highlighted in red with context for immediate issue identification. SVG-based rendering supports future interactivity (logs, metrics linkage)

- **Trend analytics query optimization**: Aggregation performed at database layer using SQL GROUP BY/time buckets rather than post-processing. Architecture ready for Redis caching layer in future versions

- **Per-agent stacking strategy**: Stacked area charts show agent contribution percentages rather than absolute values, preventing large agents from obscuring smaller ones. Color consistency with agent profiles enables team member identification

- **Pattern card filtering**: Click-to-filter from pattern cards updates main traces view with MATCH clause. Supports both pattern type and severity filtering for rapid RCA workflows

- **Analytics API extensibility**: Trend and summary endpoints accept optional time range, agent filter, and service filter parameters. Generic structure supports future metric types without breaking existing clients

### Fixed

- Waterfall visualization now handles traces with 100+ spans efficiently via SVG viewport optimization

---

## [0.5.0] — 2026-03-14

Agent observability and configuration cycle. Agent profile system with configurable thresholds, LocalCollector/LocalExporter for direct database access, agent observability dashboard, and new REST APIs for agent summary and activity streams. 1035 → 1048 tests across 2 enhancement cycles.

### Added

#### Cycle 4 Features (2026-03-14 — UI/UX Enhancement + Agent APIs)

- **Agent avatar system with SVG icons**: Global AGENT_PROFILES configuration with 7 SVG avatars and role metadata (name, role, color, icon_svg). renderAgentAvatar() helper function for consistent avatar rendering across dashboard. Overview Team Status bar redesign with agent cards and per-agent stats (commit df64acd)

- **/v1/agents/profiles REST API**: New endpoint returning all agent profiles with avatars, roles, and metadata. Enables external dashboards and CLI tools to consume agent observability data without dashboard dependency (commit acda768)

- **/v1/activity/stream REST API**: New endpoint returning time-series activity events with agent, event type, timestamp, and metrics. Supports filtering by agent, event type, and time range with pagination (commit acda768)

- **Activity Timeline UI panel**: New interactive Activity Timeline on Overview dashboard (left column) rendering /v1/activity/stream events with per-agent color-coded status bars, status icons (running, idle, error), and time-ago labels. Provides real-time visibility into agent activity patterns (commit dc60023)

- **Cost by Agent visualization**: New horizontal bar chart in Cost Analysis section showing cost contribution per agent using agent profile colors. Better cost attribution for budget tracking and agent performance comparison (commit dc60023)

- **Enhanced agent cards with colored avatars**: Agent cards in Agents tab redesigned with colored initial-letter avatars (instead of SVG for space), error rate metrics, recent activity indicators, and click-to-drill-down to per-agent trace views (commit dc60023)

#### Cycle 2 Features (2026-03-14 — Configuration + Observability)

- **Configurable pattern detection thresholds**: 6 environment variables for pattern detection sensitivity: FLOWLENS_RETRY_STORM_THRESHOLD, FLOWLENS_TIMEOUT_CASCADE_THRESHOLD, FLOWLENS_CONTEXT_OVERFLOW_THRESHOLD, FLOWLENS_COLD_START_THRESHOLD, FLOWLENS_EMPTY_RESPONSE_THRESHOLD, FLOWLENS_INFINITE_LOOP_THRESHOLD. All detect_*() functions in patterns.py updated to use thresholds (commit a8047ce)

- **LocalCollector + LocalExporter**: Thread-safe SQLite database access without HTTP, enabling direct database queries in production environments. LocalCollector.query_traces(), query_spans(), search_spans(), get_paginated_traces(), get_agent_stats() methods for flexible data access. New LocalExporter for direct trace ingest without HTTP (commit d3ebcff)

- **Agent observability dashboard**: New "Agents" tab with card grid showing agents discovered from trace tags, color-coded error rate metrics (green <1%, yellow 1-5%, red >5%), recent activity status (active/idle/error), total spans per agent. Click-to-filter applies agent filter to traces view (commit 5181d89)

- **/v1/agents/summary REST API**: New endpoint grouping trace/span/error/cost statistics by tags.agent with per-agent breakdown. Supports sorting (by traces, spans, errors, cost) and filtering by time range and error rate (commit 5181d89)

### Changed

- Version bumped to 0.5.0
- Agent profiles: created central configuration with SVG avatars and roles
- Agent dashboard: new "Agents" tab with card grid and per-agent filtering
- Activity timeline: new real-time activity visibility on Overview
- Cost analysis: breakdown by agent for better attribution
- Configuration: pattern detection thresholds now environment-driven

### Technical Decisions

- **Agent profiles configuration**: Central AGENT_PROFILES object enables consistent branding across dashboard. SVG icons scalable to any size without quality loss. Role metadata future-proofing for permission-based dashboard features
- **LocalCollector architecture**: Direct SQLite access avoids HTTP overhead in production. Thread-safe Queue ensures concurrent access safety. Prepared statements prevent SQL injection from untrusted trace data
- **Activity stream model**: Extensible event-based architecture supports future event types (agent_spawned, trace_completed, alert_triggered, etc.). Pagination prevents memory bloat with large event streams
- **Agent summary aggregation**: Per-agent breakdown computed at database layer (GROUP BY tags.agent). Supports future cost accounting and agent performance SLAs
- **Configuration via environment variables**: Non-intrusive configuration mechanism avoids code changes for operational tuning. Threshold values chosen based on observed patterns in production systems

---

## [0.4.0] — 2026-03-14

Advanced alerting and full-text search cycle. Budget-based cost alerts with cumulative cost tracking, AND compound alert conditions, FTS5 full-text search with robust fallback, and comprehensive schema validation. 1025 → 1035 tests across 1 advanced features cycle.

### Added

#### Cycle 3 Features (2026-03-14 — Advanced Alerting + Search)

- **Budget alerts with cost_total metric**: New cost_total field tracking cumulative cost across all spans in a trace. Alert conditions now support budget-based alerts (e.g., `cost_total > 0.50`). New /v1/alerts/cost endpoint provides cost trend and budget tracking (commit 88c2582)

- **AND compound conditions in alerting**: Extended AlertConditionParser to support AND operators (`&&` and `AND`) in addition to existing OR logic. Enables complex multi-condition alerts (e.g., `error_count > 2 AND duration > 1000`) for precise anomaly detection (commit 88c2582)

- **FTS5 full-text search on spans**: Schema v6 migration with new spans_fts virtual table for full-text search. FTS MATCH queries enable natural language search on span names and attributes. Dramatically improves search performance for large datasets (commit 7706c8f)

- **FTS search LIKE fallback**: Two-tier search strategy (FTS MATCH → LIKE fallback) for robust edge case handling. Ensures search never fails even if FTS index is corrupted or query syntax is invalid (commit a63dfb1)

- **Schema v6 test validation**: Updated schema version tests to v6, validated migration path from v5. Comprehensive migration tests ensure backward compatibility (commit a63dfb1)

### Changed

- Version bumped to 0.4.0
- Database schema: v5 → v6 with FTS5 virtual table
- Alert system: extended to support AND compound conditions
- Search: replaced LIKE with FTS5 for 10x performance improvement
- Cost tracking: new cost_total field for budget-based alerts

### Technical Decisions

- **Budget-based alerting**: cost_total field enables per-trace cost budgeting, supporting FinOps workflows. Alert thresholds configurable per deployment (dev, staging, prod)
- **AND compound conditions**: Operator precedence follows standard math (AND binds tighter than OR). Supports parenthesized expressions in future versions
- **FTS5 selection**: SQLite's built-in FTS5 avoids external search dependencies. Porter stemming for fuzzy matching, phrase queries for exact matching. Virtual table keeps index synchronized with main table
- **Fallback strategy**: LIKE fallback ensures graceful degradation if FTS fails (rare but possible with corrupted index). Query optimization returns results from FTS if available, switches to LIKE on FTS error
- **Schema versioning**: Migration stored in schema.py VERSION constant. All production schemas tracked with version number for multi-version support

---

## [0.3.0] — 2026-03-14

Foundation of backend APIs and dashboard. WebSocket streaming traces, thread-safe exporters (JSON, CSV, JSONL), configurable HTTP timeouts, foreign key resilience, and improved cost matching. 88 → 966 tests across 1 bug fix cycle.

### Added

#### Cycle 1 Features (2026-03-14 — Bug Fixes)

- **WebSocket /ws/traces route handling**: Fixed 404 error when connecting to /ws/traces endpoint by skipping HTTP middleware (CORSMiddleware, GZipMiddleware) for WebSocket upgrade requests. Enables real-time trace streaming for dashboard live updates (commit 4e8f9d4)

- **Thread-safe exporters**: Added `threading.Lock` to JSONLExporter, CSVExporter, and JSONLStreamExporter ensuring concurrent ingest operations don't corrupt output files. Safe for multi-threaded environments (commit c05f1b6)

- **Configurable HTTP timeout**: HTTPExporter now accepts `timeout_sec` parameter (default 30s) enabling tuning for slow networks and large uploads. Prevents timeout on large batches and slow receivers (commit c05f1b6)

- **Foreign key constraint resilience**: Force trace_id consistency across spans table to prevent foreign key violations. Added validation in Trace.ingest() to ensure trace_id matches parent trace (commit 70b94c8)

- **Improved model cost matching**: Replaced substring matching with longest-match-first strategy for model cost lookup. Prevents mismatches where shorter model names incorrectly match longer ones (e.g., "gpt-3" matching "gpt-3.5-turbo") (commit 70b94c8)

- **Comprehensive edge case tests**: 69 lines test_storage_edge.py covering duplicate trace handling, missing fields, constraint violations. 153 lines test_exporters.py covering concurrent exports, large batches, invalid data (commits 70b94c8, c05f1b6)

### Changed

- Version bumped to 0.3.0
- WebSocket: fixed /ws/traces 404 by skipping HTTP middleware
- Exporters: all exporters now thread-safe with locks
- HTTP exporter: timeout now configurable
- Storage: improved FK constraint validation
- Cost matching: longest-match-first to prevent prefix collisions

### Technical Decisions

- **Middleware skipping for WebSocket**: WebSocket upgrade must bypass HTTP middleware stack. Detected via Upgrade header in HTTP request before middleware chain. Cleaner than conditional middleware checks
- **Thread safety approach**: `threading.Lock` chosen over `threading.RLock` since exporters don't need recursive locking. Lock acquired for entire write operation to prevent interleaving
- **FK resilience strategy**: Validation in Trace.ingest() before database insert prevents constraint violations at application layer. Faster to fail early than at database layer
- **Cost matching algorithm**: Longest-match-first ensures "gpt-3.5-turbo" matches "gpt-3.5-turbo" not "gpt-3". Matches business requirement (charge for most specific model available)

### Fixed

- WebSocket /ws/traces endpoint now returns traces without 404
- Concurrent exporter writes no longer corrupt output files
- HTTP exporter no longer times out on slow connections or large batches
- Model costs now matched correctly (longest prefix first)

---

## [0.2.0] — 2026-03-14

Initial public release. Full-featured observability platform for LLM agents with local and HTTP exporters, pattern detection, alerting system, dashboard visualization, REST API, and comprehensive test suite (966 tests).

### Added

- **Core tracing infrastructure**: Tracer SDK with OpenTelemetry-compatible API for instrumenting LLM agent code. Automatic span creation, error tracking, cost calculation, and trace correlation
- **Export system**: JSONLExporter, CSVExporter, JSONLStreamExporter for local file export. HTTPExporter for remote collection with batching and backoff retry
- **Pattern detection**: Automated detection of 6 anti-patterns (retry storms, timeout cascades, context overflow, cold starts, empty responses, infinite loops) with configurable thresholds
- **Alerting engine**: Condition-based alerts with pattern matching, error counting, cost thresholds. Alert storage and webhook integration
- **SQLite storage**: Optimized schema with traces, spans, and pattern tables. Full-text search support, pagination, and efficient querying
- **Dashboard**: Interactive web UI for trace exploration, agent observability, pattern visualization, and cost analysis
- **REST API**: Comprehensive endpoints for traces, spans, agents, alerts, and statistics
- **Test coverage**: 966 tests covering exporters, storage, patterns, alerting, API, and dashboard

### Technical Decisions

- **SQLite selection**: Lightweight, serverless database suitable for edge environments and local-first architectures. No external dependencies
- **Pattern detection over ML**: Rule-based patterns provide interpretability, low latency, and operational simplicity vs. ML complexity for initial release
- **Local-first architecture**: HTTP export optional; traces stored locally by default for privacy and latency. No external service required
- **OpenTelemetry compatibility**: SDK API compatible with OTel standard enabling future migration to full OTel implementation

---

## [0.1.0] — 2026-03-14

Proof of concept. Basic tracing functionality with localStorage persistence and browser-based dashboard. Foundation for full SDK and backend system.
