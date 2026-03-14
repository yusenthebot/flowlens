# Agent Team Pattern — Self-Improving Open Source

## Overview
A pattern for using multiple AI agents organized as a "company" to autonomously improve open source projects through iterative cycles. This pattern enables rapid, coordinated development across multiple specializations using different AI models optimized for their specific roles.

## Roles

### Project Manager / Coordinator (Haiku)
- **Cost**: Lowest (fastest, smallest context window)
- **Speed**: Fastest
- **Responsibilities**: Planning, progress tracking, documentation, coordination, retrospectives
- **Key outputs**: Status docs, cycle plans, retrospectives, team communication
- **Why Haiku**: Excels at structured planning and documentation. Cost-effective for text-heavy tasks. Can maintain context across conversation compaction.

### Frontend Engineer (Opus)
- **Cost**: Highest (largest context window, most capable)
- **Speed**: Moderate
- **Responsibilities**: UI/UX design, dashboard development, visual user experience, design decisions
- **Why Opus**: Creative design decisions benefit from highest capability. Large context window helps understand visual systems holistically.

### Backend Engineer (Sonnet)
- **Cost**: Medium (balanced capability and cost)
- **Speed**: Fast
- **Responsibilities**: API development, database schema, server infrastructure, performance optimization
- **Why Sonnet**: Implementation-focused work benefits from good balance of speed and quality. Systematic backend tasks.

### SDK Engineer (Sonnet)
- **Cost**: Medium
- **Speed**: Fast
- **Responsibilities**: Client libraries, auto-instrumentation, integrations with external services, API wrapping
- **Why Sonnet**: Systematic implementation work. Adapter/wrapper patterns are well-suited to Sonnet's capabilities.

### DevOps / Quality Engineer (Sonnet)
- **Cost**: Medium
- **Speed**: Fast
- **Responsibilities**: CI/CD pipelines, containerization, configuration management, testing infrastructure, quality tooling
- **Why Sonnet**: Template-heavy, configuration-focused work. Systematic implementation of standard practices.

## Workflow

### Phase 1: Analysis
1. Launch Explore agent to deeply analyze the project
2. Understand current state, identify gaps and opportunities
3. Review existing code, architecture, tests, and documentation
4. PM creates comprehensive cycle plan based on findings

### Phase 2: Parallel Execution
1. Launch all specialist agents in parallel
2. Each agent works in isolated git worktree (prevents conflicts)
3. Each agent focuses on their specialization
4. PM tracks progress and removes blockers
5. Each agent runs tests before pushing changes

### Phase 3: Integration
1. Merge worktrees sequentially (least conflicting first)
2. Run full test suite after each merge
3. Fix any integration issues that arise
4. Commit consolidated changes to main
5. Verify CI/CD pipeline passes

### Phase 4: Retrospective & Planning
1. PM reviews what was accomplished vs. planned
2. Document any unexpected findings or challenges
3. Identify gaps and issues for next cycle
4. Update roadmap and metrics
5. Plan next cycle based on outcomes
6. Repeat

## Key Principles

### Isolation
- Each agent works in separate git worktree to avoid conflicts
- Changes are reviewed and merged one at a time
- Clear responsibility boundaries prevent duplicate work

### Testing
- Always run tests before submitting changes
- Full test suite runs after each merge
- Test failures are fixed before proceeding
- New features include test coverage

### Communication
- PM coordinates between agents
- Status updates document progress
- Blockers are identified and resolved quickly
- Decisions are documented in planning docs

### Iteration
- Cycles are time-boxed (typically 1-2 hours)
- Goals are achievable within cycle duration
- Next cycle learns from previous one
- Quality improves each iteration

## Anti-patterns to Avoid

### Technical
- Don't let agents work on overlapping files (causes merge conflicts)
- Don't skip testing after merges (breaks reliability)
- Don't merge without running test suite
- Don't let agents work on unrelated tasks (wastes context)
- Don't ignore integration issues (compounds problems)

### Organizational
- Don't run too many Opus agents (expensive, unclear specialization)
- Don't forget to track what changed (makes retrospectives useless)
- Don't skip the retrospective phase (continuous improvement breaks)
- Don't assign tasks outside agent specialization (quality suffers)
- Don't update code without updating docs (knowledge lost)

### Process
- Don't run cycles without clear goals
- Don't create blockers between phases
- Don't merge fast without review
- Don't let technical debt accumulate between cycles
- Don't forget to celebrate progress

## Scaling

### Adding Specializations
Can create additional agents for:
- Security Engineer (Sonnet)
- Performance Engineer (Opus)
- Accessibility Engineer (Sonnet)
- Documentation Engineer (Haiku)
- Testing / QA Engineer (Sonnet)

### Increasing Throughput
- Run multiple cycles overnight
- Increase cycle length for larger features
- Use separate worktree per agent vs. shared
- Implement feature flags for parallel work

### Maintaining Quality
- Keep test coverage high (>90%)
- Regular security audits
- Performance benchmarking
- Accessibility testing
- User feedback loops

## Cost Optimization

### Token Budgeting
| Model | Typical Usage | Context Window | Best For |
|-------|---------------|-----------------|----------|
| Opus | 1-2 agents, high-complexity tasks | 200k | UI/UX, architecture, design decisions |
| Sonnet | 2-4 agents, implementation | 200k | Features, APIs, infrastructure |
| Haiku | 1 agent, coordination | 200k | Planning, docs, coordination |

### Budget per Cycle
- Analysis phase: ~50k tokens (Haiku + Explore agent)
- Execution: ~400k tokens (all specialists working 1-2 hours)
- Integration: ~50k tokens (testing, merging)
- Retrospective: ~20k tokens (PM documenting)
- **Total typical**: 500-700k tokens per cycle

## Success Metrics

### Project Level
- Feature completion on schedule
- Test coverage maintained or improved
- Zero failed merges
- Reduced technical debt

### Agent Performance
- Time to task completion
- Code quality (passing tests, clean style)
- Effective specialization (staying in lane)
- Low conflict rates

### Team Health
- Clear documentation of work
- Effective knowledge transfer
- Team members feel productive
- Regular retrospectives driving improvement

## Example Application

This pattern has been successfully applied to:
- **FlowLens** - Agent Observability Platform (this project)
- Rapid prototyping of new features
- Breaking down large refactoring projects
- Parallel development of interconnected systems
- Documentation improvement campaigns

## Replicating This Pattern

To use this pattern in another project:

1. **Assess suitability**: Projects need clear role separation, good testing coverage, and defined scope
2. **Establish structure**: Create docs/, cycle plans, and PR templates
3. **Define roles**: Assign specializations based on project needs
4. **Create cycle plans**: Use CYCLE_PLAN.md format
5. **Set up isolation**: Git worktrees or branching strategy
6. **Run first cycle**: Start with small goals, build from there
7. **Iterate**: Use retrospectives to improve the process itself

The pattern is language-agnostic and works for any open-source project with clear architectural layers.
