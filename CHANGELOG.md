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
