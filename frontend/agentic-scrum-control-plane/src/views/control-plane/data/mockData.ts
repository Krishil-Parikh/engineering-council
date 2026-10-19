import { Agent, Artifact, Meet, SkillCategory, Sprint, DelegationEdge, Message } from '../types';

// Repository seed data for the demo workspace. Consumed solely by
// src/adapters/control-plane/toWorkspaceSnapshot.ts — no view file imports
// this module (enforced by test gate).

export const INITIAL_AGENTS: Agent[] = [
  {
    id: 'agent-sm',
    name: 'ScrumMaster',
    role: 'scrum_master',
    roleTitle: 'Sprint Arbiter & Protocol Lead',
    status: 'orchestrating',
    isLive: false,
    avatarNumber: 'SM',
    activeTask: 'Moderating schema consensus & convergence gate',
    sparkline: [22, 38, 55, 60, 48, 65, 78, 85, 92, 70],
    contextTokens: 114200,
    tokensVelocity: 1420,
    model: 'gemini-2.5-pro (deterministic)',
    skills: ['Orchestration', 'Consensus Protocol', 'Sprint Metrics', 'Risk Gates'],
    subAgentsCount: 5,
    allocatedMemory: '3.4 GB',
    confidenceScore: 98.4,
    recentTools: ['eval_consensus_matrix()', 'check_gate_conditions()', 'synthesize_artifact()']
  },
  {
    id: 'agent-03',
    name: 'Agent-03',
    role: 'backend',
    roleTitle: 'Backend · Lead Architect',
    status: 'speaking',
    isLive: true,
    avatarNumber: '03',
    activeTask: 'Defending distributed log partitioning vs two-phase commit',
    sparkline: [12, 28, 45, 82, 98, 88, 95, 74, 92, 99],
    contextTokens: 184500,
    tokensVelocity: 2180,
    model: 'gemini-2.5-pro',
    skills: ['Go/Rust Engine', 'Idempotent RPC', 'Event Sourcing', 'FINMA Compliance'],
    subAgentsCount: 2,
    allocatedMemory: '5.1 GB',
    confidenceScore: 96.1,
    recentTools: ['benchmark_raft_quorum()', 'generate_grpc_proto()', 'verify_lock_tables()']
  },
  {
    id: 'agent-04',
    name: 'Agent-04',
    role: 'backend',
    roleTitle: 'Backend · Stream Infrastructure',
    status: 'debating',
    isLive: false,
    avatarNumber: '04',
    activeTask: 'Pushing back on Postgres replication lag in high volume trades',
    sparkline: [40, 52, 60, 75, 80, 85, 65, 70, 78, 82],
    contextTokens: 142000,
    tokensVelocity: 1650,
    model: 'gemini-2.5-flash',
    skills: ['Kafka Streams', 'CDC Pipelines', 'RocksDB StateStore', 'High Throughput'],
    allocatedMemory: '4.2 GB',
    confidenceScore: 94.7,
    recentTools: ['simulate_backpressure()', 'calc_p99_latency()']
  },
  {
    id: 'agent-05',
    name: 'Agent-05',
    role: 'database',
    roleTitle: 'Database · Storage Engine Lead',
    status: 'evaluating',
    isLive: false,
    avatarNumber: '05',
    activeTask: 'Benchmarking composite hash index on order_settlement_ledger',
    sparkline: [15, 25, 30, 48, 62, 70, 58, 64, 80, 84],
    contextTokens: 98400,
    tokensVelocity: 1200,
    model: 'gemini-2.5-flash',
    skills: ['PostgreSQL 16', 'TimescaleDB', 'Partition Pruning', 'ACID Isolation'],
    allocatedMemory: '3.8 GB',
    confidenceScore: 97.2,
    recentTools: ['explain_analyze_plan()', 'partition_table_ddl()']
  },
  {
    id: 'agent-01',
    name: 'Agent-01',
    role: 'frontend',
    roleTitle: 'Frontend · Terminal Principal',
    status: 'idle',
    isLive: false,
    avatarNumber: '01',
    activeTask: 'Subscribing to WebSocket settlement feed for order book tape',
    sparkline: [30, 32, 28, 35, 40, 38, 42, 39, 45, 40],
    contextTokens: 82100,
    tokensVelocity: 850,
    model: 'gemini-2.5-flash',
    skills: ['React 19', 'Canvas Renderer', 'Virtual Scrolling', 'SSE Buffer'],
    allocatedMemory: '2.6 GB',
    confidenceScore: 95.0,
    recentTools: ['bundle_analyzer()', 'profile_render_fps()']
  },
  {
    id: 'agent-02',
    name: 'Agent-02',
    role: 'frontend',
    roleTitle: 'Frontend · Real-time Telemetry',
    status: 'idle',
    isLive: false,
    avatarNumber: '02',
    activeTask: 'Designing sub-millisecond execution tick visualization',
    sparkline: [18, 20, 22, 25, 20, 28, 30, 25, 28, 32],
    contextTokens: 64000,
    tokensVelocity: 620,
    model: 'gemini-2.5-flash',
    skills: ['Micro-frontends', 'State Sync', 'Accessible Tables', 'WASM Math'],
    allocatedMemory: '2.1 GB',
    confidenceScore: 93.8,
    recentTools: ['compile_wasm_worker()', 'test_memory_leak()']
  },
  {
    id: 'agent-06',
    name: 'Agent-06',
    role: 'qa',
    roleTitle: 'QA · Chaos & Invariants',
    status: 'idle',
    isLive: false,
    avatarNumber: '06',
    activeTask: 'Generating network split scenarios for ledger split-brain verification',
    sparkline: [10, 15, 20, 30, 45, 55, 60, 50, 45, 48],
    contextTokens: 76000,
    tokensVelocity: 740,
    model: 'gemini-2.5-pro',
    skills: ['Chaos Mesh', 'Jepsen Tests', 'Invariant Assertions', 'Stress Profile'],
    allocatedMemory: '2.8 GB',
    confidenceScore: 98.9,
    recentTools: ['inject_packet_drop()', 'verify_double_spend()']
  }
];

export const INITIAL_SKILLS: SkillCategory[] = [
  { id: 'sk-1', name: 'Backend', activeCount: 3, totalCount: 3, isSolid: true },
  { id: 'sk-2', name: 'Frontend', activeCount: 2, totalCount: 2, isSolid: true },
  { id: 'sk-3', name: 'Database', activeCount: 1, totalCount: 1, isSolid: true },
  { id: 'sk-4', name: 'DevOps & SRE', activeCount: 0, totalCount: 2, isSolid: false },
  { id: 'sk-5', name: 'Security & FINMA', activeCount: 1, totalCount: 2, isSolid: true }
];

export const INITIAL_MEETS: Meet[] = [
  {
    id: 'meet-04',
    number: '04',
    sprintId: 'sprint-03',
    title: 'Meet 04 · live — Backend schema debate',
    topic: 'Postgres partitioned ledger vs distributed log stream under 20ms SLA',
    status: 'live',
    elapsedTime: '14:32',
    remainingTime: '04:12',
    elapsedSec: 872,
    remainingSec: 252,
    participants: ['ScrumMaster', 'Agent-03', 'Agent-04', 'Agent-05', 'SME-01'],
    consensusRate: 83.3,
    debateIntensity: 78,
    heatSegments: [
      { minute: 1, intensity: 10, isDebate: false },
      { minute: 3, intensity: 25, isDebate: false },
      { minute: 6, intensity: 45, isDebate: false },
      { minute: 8, intensity: 90, isDebate: true },
      { minute: 9, intensity: 95, isDebate: true },
      { minute: 11, intensity: 85, isDebate: true },
      { minute: 13, intensity: 70, isDebate: true },
      { minute: 14, intensity: 60, isDebate: false }
    ],
    summary: 'Active dispute on whether PostgreSQL table partitioning introduces lock contention during market open bursts (120k tx/sec). Agent-03 proposes hybrid Raft journal with async Postgres cold-storage sinking.'
  },
  {
    id: 'meet-03',
    number: '03',
    sprintId: 'sprint-03',
    title: 'Meet 03 — gRPC vs WebSocket Contract Alignment',
    topic: 'Client protocol specification and backpressure flow control',
    status: 'completed',
    elapsedTime: '15:00',
    remainingTime: '00:00',
    elapsedSec: 900,
    remainingSec: 0,
    participants: ['ScrumMaster', 'Agent-01', 'Agent-02', 'Agent-03'],
    consensusRate: 100,
    debateIntensity: 35,
    heatSegments: [
      { minute: 2, intensity: 20, isDebate: false },
      { minute: 5, intensity: 50, isDebate: true },
      { minute: 10, intensity: 30, isDebate: false },
      { minute: 15, intensity: 15, isDebate: false }
    ],
    summary: 'Consensus achieved: Browser UI consumes compacted WebSocket delta frames; backend microservices communicate purely over gRPC with Protobuf schema v3.'
  },
  {
    id: 'meet-02',
    number: '02',
    sprintId: 'sprint-03',
    title: 'Meet 02 — FINMA Regulatory Traceability Bounds',
    topic: 'Mandatory audit trails and cryptographic proof chain requirements',
    status: 'completed',
    elapsedTime: '15:00',
    remainingTime: '00:00',
    elapsedSec: 900,
    remainingSec: 0,
    participants: ['ScrumMaster', 'Agent-03', 'Agent-05', 'SME-01'],
    consensusRate: 100,
    debateIntensity: 42,
    heatSegments: [
      { minute: 4, intensity: 60, isDebate: true },
      { minute: 7, intensity: 65, isDebate: true },
      { minute: 12, intensity: 25, isDebate: false }
    ],
    summary: 'SME-01 confirmed: every trade allocation must persist an immutable SHA-256 parent hash back into the daily ledger before broker ack.'
  },
  {
    id: 'meet-01',
    number: '01',
    sprintId: 'sprint-03',
    title: 'Meet 01 — Sprint 03 Kickoff & Architecture Scope',
    topic: 'Targeting 20ms p99 settlement time for Zurich Equities Desk',
    status: 'completed',
    elapsedTime: '15:00',
    remainingTime: '00:00',
    elapsedSec: 900,
    remainingSec: 0,
    participants: ['ScrumMaster', 'Agent-01', 'Agent-02', 'Agent-03', 'Agent-04', 'Agent-05', 'Agent-06'],
    consensusRate: 100,
    debateIntensity: 15,
    heatSegments: [
      { minute: 2, intensity: 15, isDebate: false },
      { minute: 8, intensity: 20, isDebate: false }
    ],
    summary: 'All 6 developer agents accepted sprint objectives. PRD baseline drafted and assigned.'
  }
];

export const INITIAL_MESSAGES: Message[] = [
  {
    id: 'msg-01',
    meetId: 'meet-04',
    senderId: 'agent-sm',
    senderName: 'ScrumMaster',
    senderRole: 'Scrum Master',
    timestamp: '14:26:10',
    timeOffsetSec: 50,
    text: 'Agenda item 2: Schema definition for the `order_settlement_ledger`. Agent-05 has proposed daily partition tables in PostgreSQL. Agent-03 and Agent-04, please state feasibility for sub-20ms SLA.',
    type: 'speech'
  },
  {
    id: 'msg-02',
    meetId: 'meet-04',
    senderId: 'agent-05',
    senderName: 'Agent-05',
    senderRole: 'Database',
    timestamp: '14:27:04',
    timeOffsetSec: 104,
    text: 'Our partition strategy isolates table locks per trading day: `order_settlement_YYYY_MM_DD`. Benchmarks show write latency p99 at 4.2ms when bulk-inserting in microbatches of 250 records with unlogged staging tables.',
    type: 'speech',
    codeSnippet: 'CREATE TABLE settlement_2026_09 (\n  order_id UUID NOT NULL,\n  account_num VARCHAR(32) NOT NULL,\n  settled_amount NUMERIC(18,4) NOT NULL,\n  finma_hash BYTEA NOT NULL,\n  PRIMARY KEY (order_id, account_num)\n) PARTITION BY RANGE (settled_at);'
  },
  {
    id: 'msg-03',
    meetId: 'meet-04',
    senderId: 'agent-03',
    senderName: 'Agent-03',
    senderRole: 'Backend Lead',
    timestamp: '14:28:15',
    timeOffsetSec: 175,
    text: 'I must push back on pure PostgreSQL for the active ingestion path. During 09:00:00 Market Open surges, the Zurich desk pumps 140,000 transactions/sec. Even with partitioned tables, vacuum contention and disk write amplification will spike p99 beyond 85ms.',
    type: 'debate_challenge',
    isContradiction: true,
    inResponseTo: 'msg-02'
  },
  {
    id: 'msg-04',
    meetId: 'meet-04',
    senderId: 'agent-04',
    senderName: 'Agent-04',
    senderRole: 'Stream Infra',
    timestamp: '14:29:40',
    timeOffsetSec: 260,
    text: 'Agent-03 is correct regarding lock amplification. If we instead route execution ingress through an in-memory Raft WAL (RocksDB backed), we acknowledge the trade in 1.8ms, then stream CDC change events into Agent-05\'s Postgres ledger asynchronously.',
    type: 'speech'
  },
  {
    id: 'msg-05',
    meetId: 'meet-04',
    senderId: 'agent-05',
    senderName: 'Agent-05',
    senderRole: 'Database',
    timestamp: '14:30:52',
    timeOffsetSec: 332,
    text: 'If we do async sinking, what guarantees zero data loss on node failure before the CDC commits to Postgres? SME-01 requires zero lost clearing entries per Swiss FINMA Article 14.',
    type: 'debate_challenge',
    isContradiction: true,
    inResponseTo: 'msg-04'
  },
  {
    id: 'msg-06',
    meetId: 'meet-04',
    senderId: 'agent-03',
    senderName: 'Agent-03',
    senderRole: 'Backend Lead',
    timestamp: '14:32:07',
    timeOffsetSec: 407,
    text: 'We enforce an f+1 quorum fsync on the Raft WAL before returning the gRPC ACK to the trading terminal. Three independent availability zones in Zurich & Geneva. Zero lost records even during catastrophic power loss.',
    type: 'speech'
  },
  {
    id: 'msg-07',
    meetId: 'meet-04',
    senderId: 'sme-01',
    senderName: 'SME-01',
    senderRole: 'Business SME (Regulatory Lead)',
    timestamp: '14:32:45',
    timeOffsetSec: 445,
    text: 'Business SME Intervention: Quorum fsync across Zurich/Geneva meets FINMA Article 14 if and only if the cryptographic parent hash is calculated synchronously at the Raft leader. Does the Raft proposal include cryptographic chain generation?',
    type: 'sme_input'
  },
  {
    id: 'msg-08',
    meetId: 'meet-04',
    senderId: 'agent-03',
    senderName: 'Agent-03',
    senderRole: 'Backend Lead',
    timestamp: '14:33:30',
    timeOffsetSec: 490,
    text: 'Yes. The Go engine utilizes AVX-512 hardware accelerated SHA-256 hashing. Calculation takes 420 nanoseconds per payload. It is embedded directly in the Raft state machine header before broadcast.',
    type: 'speech'
  },
  {
    id: 'msg-09',
    meetId: 'meet-04',
    senderId: 'agent-sm',
    senderName: 'ScrumMaster',
    senderRole: 'Scrum Master',
    timestamp: '14:34:10',
    timeOffsetSec: 530,
    text: 'We have convergence. Agent-05, will you update Architecture.md section 4.2 to specify the Raft in-memory WAL with Postgres cold-storage mirror?',
    type: 'consensus'
  },
  {
    id: 'msg-10',
    meetId: 'meet-04',
    senderId: 'agent-05',
    senderName: 'Agent-05',
    senderRole: 'Database',
    timestamp: '14:34:55',
    timeOffsetSec: 575,
    text: 'Accepted. Updating Architecture.md and preparing schema migration scripts. PRD acceptance status: 6/6 signoffs ready.',
    type: 'artifact_update'
  }
];

export const INITIAL_ARTIFACTS: Artifact[] = [
  {
    id: 'art-01',
    title: 'Product Requirement Document',
    filename: 'PRD.md',
    type: 'prd',
    currentVersion: 'v2.3',
    status: 'approved',
    acceptedCount: 6,
    totalRequired: 6,
    acceptedBy: ['Agent-01', 'Agent-02', 'Agent-03', 'Agent-04', 'Agent-05', 'Agent-06'],
    versions: [
      {
        version: 'v2.3',
        timestamp: 'Today, 14:35',
        author: 'ScrumMaster',
        summary: 'Incorporated Swiss FINMA Article 14 cryptographic chaining and 20ms p99 latency threshold',
        diffAdditions: [
          '+ § 3.4.1 All clearing transactions must maintain SHA-256 parent cryptographic lineage.',
          '+ § 3.4.2 Zurich and Geneva multi-zone Raft quorum required before order ACK.'
        ],
        diffDeletions: [
          '- § 3.4 Single database master with read replica architecture.'
        ],
        acceptedBy: ['Agent-01', 'Agent-02', 'Agent-03', 'Agent-04', 'Agent-05', 'Agent-06']
      },
      {
        version: 'v2.2',
        timestamp: 'Yesterday, 16:20',
        author: 'Agent-03',
        summary: 'Specified gRPC Protobuf v3 payloads for inter-service communication',
        diffAdditions: [
          '+ § 4.1 Strict typing via Proto3 with backward compatible field tags.'
        ],
        diffDeletions: [
          '- § 4.1 REST JSON API for internal settlement services.'
        ],
        acceptedBy: ['Agent-01', 'Agent-03', 'Agent-04']
      },
      {
        version: 'v2.0',
        timestamp: 'Sep 20, 09:00',
        author: 'ScrumMaster',
        summary: 'Initial Sprint 03 baseline PRD creation',
        diffAdditions: [
          '+ Initial problem definition, user personas, throughput targets.'
        ],
        diffDeletions: [],
        acceptedBy: ['ScrumMaster', 'Agent-01', 'Agent-03']
      }
    ],
    markdownContent: `# PRD: Real-time Clearing & Settlement Engine (Zurich Hub)
**Status:** APPROVED (6/6 Agents · SME Signed)  
**Classification:** UBS Internal High-Assurance  
**Sprint:** 03  

## 1. Executive Summary
The NextGen Settlement Engine processes high-volume equity and fixed-income clearing orders originating from the Zurich trading floor. The core requirement is deterministic sub-20ms p99 acknowledgment under peak market open conditions (120,000 tx/sec) while strictly complying with Swiss FINMA Article 14 immutable transaction auditability.

## 2. Key Performance Indicators (KPIs)
- **Ingestion Latency:** p99 < 18ms from terminal dispatch to persistent ACK.
- **Sustained Throughput:** 120,000 transactions/second across 3 availability zones.
- **Availability:** 99.999% fault tolerance with zero human intervention failover.
- **Data Loss Tolerance:** Exactly 0 records (RPO = 0, RTO < 2 seconds).

## 3. Regulatory & Compliance (FINMA Article 14)
- **§ 3.4.1 Lineage Assurance:** Every trade allocation must include the SHA-256 hash of the immediately preceding ledger block, forming an unbroken cryptographic chain.
- **§ 3.4.2 Multi-datacenter Durability:** Trades require acknowledgment from at least two geographically isolated Swiss sovereign datacenters (Zurich West and Geneva Tier-IV) before client acknowledgment.
- **§ 3.4.3 Tamper-Evident Storage:** Historical partitions must be write-once-read-many (WORM) compliant for 10 years.

## 4. Architectural Boundaries
- Frontend: Single-page WebAssembly terminal consuming compressed delta binary streams.
- Ingestion Gateway: Stateless Go cluster fronted by Layer 4 BGP load balancers.
- Storage Consensus: Distributed in-memory Raft WAL journal sinking asynchronously to partitioned PostgreSQL instances.`
  },
  {
    id: 'art-02',
    title: 'Architecture Specification',
    filename: 'architecture.md',
    type: 'architecture',
    currentVersion: 'v1.4',
    status: 'in_review',
    acceptedCount: 5,
    totalRequired: 6,
    acceptedBy: ['Agent-01', 'Agent-02', 'Agent-03', 'Agent-04', 'Agent-05'],
    versions: [
      {
        version: 'v1.4',
        timestamp: 'Today, 14:36',
        author: 'Agent-05',
        summary: 'Updated storage layer with RocksDB Raft WAL and async PostgreSQL cold store',
        diffAdditions: [
          '+ § 4.2 Ingestion path uses local RocksDB SSD journal with 3-node Raft consensus.',
          '+ § 4.3 Change Data Capture (CDC) pipeline feeds daily partitioned Postgres tables.'
        ],
        diffDeletions: [
          '- § 4.2 Direct PostgreSQL write transactions during peak hours.'
        ],
        acceptedBy: ['Agent-01', 'Agent-02', 'Agent-03', 'Agent-04', 'Agent-05']
      },
      {
        version: 'v1.2',
        timestamp: 'Sep 21, 11:15',
        author: 'Agent-03',
        summary: 'Defined gRPC streaming contract and backpressure buffer limits',
        diffAdditions: [
          '+ § 2.1 Max queue depth: 250,000 entries before shedding non-critical telemetry.'
        ],
        diffDeletions: [],
        acceptedBy: ['Agent-01', 'Agent-03']
      }
    ],
    markdownContent: `# Architecture Specification: High-Frequency Settlement Core
**Document Version:** v1.4  
**Authors:** Agent-03 (Backend Lead), Agent-05 (DBA)  
**Review Status:** 5/6 Accepted (Pending Agent-06 Chaos Verification)

## 1. Top-Level Topology
\`\`\`
[ Trading Terminals ]
         │ (WebSocket Compact Binary)
         ▼
[ Edge Ingress Layer (Envoy / L4 BGP) ]
         │ (gRPC Stream)
         ▼
[ Ingestion Engine (Go + AVX-512 SHA-256) ]
         │ (Raft Quorum Replication)
   ┌─────┴────────────────┐
   ▼                      ▼
[ Zurich Node A ]    [ Geneva Node B ]
   │                      │
   └──────► [ Kafka CDC Stream ]
                  │
                  ▼
         [ Partitioned PostgreSQL 16 ]
\`\`\`

## 2. Ingestion & Consensus SLA
1. **Hardware Acceleration:** SHA-256 cryptographic lineage computed in CPU registers (AVX-512) before network dispatch.
2. **Consensus Engine:** etcd/raft implementation in Go, pinned to isolated NUMA cores.
3. **Partition Isolation:** Database writes occur out-of-band via Debezium CDC connectors, isolating user-facing latency from B-tree index balancing.`
  },
  {
    id: 'art-03',
    title: 'UI & Execution Terminal Spec',
    filename: 'design.md',
    type: 'design',
    currentVersion: 'v1.1',
    status: 'approved',
    acceptedCount: 6,
    totalRequired: 6,
    acceptedBy: ['Agent-01', 'Agent-02', 'Agent-03', 'Agent-04', 'Agent-05', 'Agent-06'],
    versions: [
      {
        version: 'v1.1',
        timestamp: 'Sep 21, 17:00',
        author: 'Agent-01',
        summary: 'Added 60 FPS order book virtual scroll and UBS Swiss styling guidelines',
        diffAdditions: [
          '+ § 2.2 Tabular numerals required on all currency and timing display elements.',
          '+ § 2.3 Single-accent red glow reserved exclusively for live execution events.'
        ],
        diffDeletions: [],
        acceptedBy: ['Agent-01', 'Agent-02', 'Agent-03', 'Agent-04', 'Agent-05', 'Agent-06']
      }
    ],
    markdownContent: `# Design & Terminal Specification: The Deck
**Document Version:** v1.1  
**Authors:** Agent-01 (Frontend Principal)  
**Target:** 1440×900 Desktop Workstation  

## 1. Visual Hierarchy & Philosophy
The interface operates as a high-density, low-fatigue command station.
- **Base Surface:** \`#FCFCFB\` (UBS Paper).
- **Ink Primary:** \`#161616\`.
- **Accent:** \`#E60000\` (UBS Red), strictly reserved for live running states.
- **Glass Tier:** 20px blur with 86% paper opacity for elevated command layers.`
  }
];

export const INITIAL_SPRINTS: Sprint[] = [
  {
    id: 'sprint-03',
    number: '03',
    title: 'Sprint 03 — Architecture, Ledger & Ingestion Core',
    goal: 'Lock architecture, achieve 6/6 agent consensus, and validate sub-20ms p99 SLA under FINMA compliance',
    phase: 'Architecture & Schema Consensus',
    progress: 72,
    status: 'active',
    startDate: 'Sep 18, 2026',
    targetDate: 'Oct 02, 2026',
    meets: [
      { id: 'meet-01', label: 'Meet 01', title: 'Sprint Kickoff & Scope', outcome: 'consensus', duration: '15:00' },
      { id: 'meet-02', label: 'Meet 02', title: 'FINMA Traceability Bounds', outcome: 'consensus', duration: '15:00' },
      { id: 'meet-03', label: 'Meet 03', title: 'gRPC vs WebSocket Contract', outcome: 'consensus', duration: '15:00' },
      { id: 'meet-04', label: 'Meet 04', title: 'Backend Schema Debate', outcome: 'pivot', duration: '14:32 (live)' }
    ],
    smeReviewPoints: [
      { label: 'Mid-Sprint Regulatory Gate', date: 'Sep 21', approved: true, note: 'SME-01 approved SHA-256 chain strategy.' },
      { label: 'Architecture Signoff Gate', date: 'Sep 23', approved: false, note: 'Awaiting Meet 04 closure & chaos verification.' }
    ],
    standup: {
      yesterday: [
        'Agent-03 completed Go raft prototype benchmark in Zurich testbed (118k tx/sec).',
        'Agent-05 partitioned Postgres tables by date with hash bucketing across 16 shards.',
        'Agent-01 implemented WebAssembly WebSocket binary decoder with 0.4ms unpack time.'
      ],
      today: [
        'Agent-03 & Agent-05 resolving lock contention debate in Meet 04.',
        'Agent-04 tuning Kafka CDC connectors for sub-5ms commit delay.',
        'Agent-06 initializing Jepsen network split simulations on 3-node cluster.'
      ],
      blockers: [
        'None active. Pending final signoff from Agent-06 on partition split brain prevention.'
      ]
    },
    retro: {
      wentWell: [
        'Cross-agent architectural debate converged within 14 minutes without deadlocks.',
        'SME intervention directly prevented an architectural rework before code was written.'
      ],
      toImprove: [
        'Database indexing discussions started without concrete write-amplification numbers.'
      ],
      actionItems: [
        'Mandate benchmark scripts before introducing competing database proposals.'
      ]
    }
  },
  {
    id: 'sprint-02',
    number: '02',
    title: 'Sprint 02 — Data Ingress & High-Volume Kafka Sinks',
    goal: 'Benchmark stream ingress throughput and verify network latency variance',
    phase: 'Completed',
    progress: 100,
    status: 'completed',
    startDate: 'Sep 04, 2026',
    targetDate: 'Sep 18, 2026',
    meets: [
      { id: 's2-m1', label: 'Meet 01', title: 'Ingress Throughput Target', outcome: 'consensus', duration: '14:20' },
      { id: 's2-m2', label: 'Meet 02', title: 'Broker Partitioning Model', outcome: 'consensus', duration: '15:00' },
      { id: 's2-m3', label: 'Meet 03', title: 'Final Benchmark Review', outcome: 'consensus', duration: '12:45' }
    ],
    smeReviewPoints: [
      { label: 'Data Governance Check', date: 'Sep 11', approved: true, note: 'Approved encryption at rest.' }
    ],
    standup: {
      yesterday: ['Sprint completed.'],
      today: ['Retrospective finalized.'],
      blockers: []
    },
    retro: {
      wentWell: ['Kafka pipeline reached 150k msg/sec stable.'],
      toImprove: ['Earlier participation from QA agent on partition drop.'],
      actionItems: ['Include Agent-06 in kickoff meetings.']
    }
  },
  {
    id: 'sprint-01',
    number: '01',
    title: 'Sprint 01 — Project Foundation & Compliance Scaffolding',
    goal: 'Establish repository structure, zero-trust secrets, and baseline CI/CD',
    phase: 'Completed',
    progress: 100,
    status: 'completed',
    startDate: 'Aug 21, 2026',
    targetDate: 'Sep 04, 2026',
    meets: [
      { id: 's1-m1', label: 'Meet 01', title: 'Security Architecture', outcome: 'consensus', duration: '15:00' },
      { id: 's1-m2', label: 'Meet 02', title: 'CI Pipeline & Linting Gates', outcome: 'consensus', duration: '11:10' }
    ],
    smeReviewPoints: [
      { label: 'Security Baseline Review', date: 'Aug 28', approved: true, note: 'All SOC2 & ISO 27001 controls verified.' }
    ],
    standup: {
      yesterday: ['Sprint completed.'],
      today: ['Scaffolding tagged.'],
      blockers: []
    },
    retro: {
      wentWell: ['Clean setup of reproducible hermetic builds.'],
      toImprove: ['Initial Docker builds were too heavy.'],
      actionItems: ['Shift to minimal distroless base images.']
    }
  }
];

export const INITIAL_EDGES: DelegationEdge[] = [
  { id: 'e-sm-03', source: 'agent-sm', target: 'agent-03', label: 'Task Delegation', isActive: true, latencyMs: 14, dataPacket: 'Schema Consensus Protocol v2' },
  { id: 'e-sm-01', source: 'agent-sm', target: 'agent-01', label: 'UI Directive', isActive: false, latencyMs: 8 },
  { id: 'e-03-04', source: 'agent-03', target: 'agent-04', label: 'CDC Invariants', isActive: true, latencyMs: 6, dataPacket: 'Raft WAL sync ACK' },
  { id: 'e-03-05', source: 'agent-03', target: 'agent-05', label: 'Partition Table DDL', isActive: true, latencyMs: 18, dataPacket: 'Hash key schema' },
  { id: 'e-01-02', source: 'agent-01', target: 'agent-02', label: 'Buffer Sync', isActive: false, latencyMs: 4 },
  { id: 'e-03-06', source: 'agent-03', target: 'agent-06', label: 'Chaos Trigger', isActive: false, latencyMs: 12 },
  { id: 'e-sm-sme', source: 'sme-01', target: 'agent-sm', label: 'Regulatory Directive', isActive: true, latencyMs: 2, dataPacket: 'FINMA Art. 14 Rule' }
];
