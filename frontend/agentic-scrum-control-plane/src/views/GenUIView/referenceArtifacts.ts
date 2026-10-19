import type { ArtifactFile } from '../../types';

/**
 * Static reference documents for the GenUI narrative (release manifest and
 * drawer reference viewer). This is UI-only presentational content owned by
 * the GenUI view — not shared domain state. Live artifact acceptance lives
 * in the canonical workspace snapshot (`domain/types.ts`).
 */
export const ARTIFACTS_LIST: ArtifactFile[] = [
  {
    name: 'PRD.md',
    size: '14.2 KB',
    type: 'Markdown Specification',
    lastModified: '2 mins ago',
    content: `# Product Requirements Document (PRD)
## Project: Agentic SDLC Orchestration Control Plane
**Author:** Scrum Master Agent & Bench (Agent-01 through 06)
**Supervision:** Business SME

### 1. Objective
Establish a single-viewport, generative SDLC control plane that coordinates autonomous AI developer agents through structured agile phases (Kickoff -> Brainstorm -> PRD -> Build -> Review -> Ship).

### 2. Guiding Invariants
1. **Single Narrative Spine**: Never divide attention across five competing top tabs.
2. **Generative Autonomy**: UI advances automatically when milestones complete.
3. **Template Equivalence**: All generic developer agents instantiate from one base template and claim skills dynamically upon meet entry.
4. **SME Authority**: Decisive architecture checkpoints require explicit Business SME review.

### 3. Acceptance Criteria
- [x] Sub-200ms phase state cross-fade transitions
- [x] Full-bleed React Flow delegation graph with active edge transmission
- [x] Rolling 24-hour PR velocity sparkline with Recharts area gradient
- [x] Collapsible 40px reveal drawer with zero content reflow`,
  },
  {
    name: 'architecture-spec.json',
    size: '8.4 KB',
    type: 'JSON Architecture Definition',
    lastModified: '6 mins ago',
    content: JSON.stringify({
      system: "Agentic Scrum Orchestrator",
      version: "3.0.0",
      topology: "hub-and-spoke",
      orchestrator: {
        agent: "Scrum Master",
        heartbeatMs: 500,
        consensusThreshold: 1.0
      },
      agentBench: {
        capacity: 12,
        defaultActive: 6,
        model: "generic-developer-v3"
      },
      phasePipeline: ["kickoff", "brainstorm", "prd", "build", "review", "ship"],
      dataStores: {
        eventLog: "redis-pubsub-stream",
        auditTrail: "postgres-timescale",
        stateCache: "in-memory-lru"
      }
    }, null, 2),
  },
  {
    name: 'api-schema.graphql',
    size: '5.1 KB',
    type: 'GraphQL Schema',
    lastModified: '14 mins ago',
    content: `type Agent {
  id: ID!
  name: String!
  role: String!
  claimedSkill: String
  status: AgentStatus!
  activeBranch: String
  contextUsagePercent: Int!
}

type PhaseState {
  currentPhase: PhaseId!
  completedPhases: [PhaseId!]!
  activeCountdownSeconds: Int
  isLive: Boolean!
}

type Mutation {
  advancePhase(phase: PhaseId!): PhaseState!
  submitSmeDecision(decision: String!): Boolean!
  claimSkill(agentId: ID!, skillId: ID!): Agent!
}`,
  },
  {
    name: 'migrations.sql',
    size: '3.6 KB',
    type: 'SQL Migration Scripts',
    lastModified: '22 mins ago',
    content: `CREATE TABLE IF NOT EXISTS sprints (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  sprint_number INT NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_allocations (
  agent_id VARCHAR(64) NOT NULL,
  sprint_id UUID REFERENCES sprints(id),
  skill_id VARCHAR(64),
  assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (agent_id, sprint_id)
);`,
  },
];
