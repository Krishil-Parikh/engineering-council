import { INITIAL_AGENTS, INITIAL_MESSAGES, INITIAL_ARTIFACTS, INITIAL_MEETS, INITIAL_SPRINTS, INITIAL_EDGES } from '../../views/control-plane/data/mockData';
import type { WorkspaceSnapshot } from '../../domain/types';

export function createInitialWorkspaceSnapshot(workspaceId: string): WorkspaceSnapshot {
  return {
    workspaceId,
    version: 1,
    phaseId: 'kickoff',
    agents: INITIAL_AGENTS.map((agent) => ({
      id: agent.id,
      name: agent.name,
      role: agent.roleTitle,
      status: agent.isLive ? 'speaking' : agent.status === 'idle' ? 'idle' : 'active',
      activeTask: agent.activeTask,
      confidenceScore: agent.confidenceScore,
    })),
    messages: INITIAL_MESSAGES.map((message) => ({
      id: message.id,
      meetId: message.meetId,
      senderId: message.senderId,
      senderName: message.senderName,
      text: message.text,
      timestamp: message.timestamp,
    })),
    skills: [],
    artifacts: INITIAL_ARTIFACTS.map((artifact) => ({
      id: artifact.id,
      title: artifact.title,
      filename: artifact.filename,
      status: artifact.status,
      currentVersion: artifact.currentVersion,
      acceptedCount: artifact.acceptedCount,
      totalRequired: artifact.totalRequired,
      versions: artifact.versions.map((version) => ({
        version: version.version,
        timestamp: version.timestamp,
        author: version.author,
        summary: version.summary,
        diffAdditions: [...version.diffAdditions],
        diffDeletions: [...version.diffDeletions],
        acceptedBy: [...version.acceptedBy],
      })),
      markdownContent: artifact.markdownContent,
      acceptedBy: [...artifact.acceptedBy],
    })),
    meets: INITIAL_MEETS.map((meet) => ({
      id: meet.id,
      title: meet.title,
      status: meet.status,
      consensusRate: meet.consensusRate,
      debateIntensity: meet.debateIntensity,
    })),
    sprints: INITIAL_SPRINTS.map((sprint) => ({
      id: sprint.id,
      number: sprint.number,
      title: sprint.title,
      phase: sprint.phase,
      progress: sprint.progress,
      status: sprint.status,
    })),
    edges: INITIAL_EDGES.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      label: edge.label,
      isActive: edge.isActive,
      latencyMs: edge.latencyMs,
    })),
    metrics: { totalMessagesToday: INITIAL_MESSAGES.length, totalPRs: 38, prHistory: [] },
    processedEventIds: [],
  };
}
