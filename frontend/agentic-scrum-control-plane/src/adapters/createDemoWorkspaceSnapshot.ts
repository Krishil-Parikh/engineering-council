import { INITIAL_AGENTS, INITIAL_SKILLS, INITIAL_TRANSCRIPT, PR_HOURLY_HISTORY } from '../data/mockData';
import { createInitialWorkspaceSnapshot as createControlPlaneSnapshot } from './control-plane/toWorkspaceSnapshot';
import type { WorkspaceSnapshot } from '../domain/types';

export function createDemoWorkspaceSnapshot(workspaceId: string): WorkspaceSnapshot {
  const controlPlane = createControlPlaneSnapshot(workspaceId);
  return {
    ...controlPlane,
    agents: controlPlane.agents.map((agent) => {
      const genui = INITIAL_AGENTS.find((candidate) => candidate.id === agent.id);
      // Overlay only operational/presentational GenUI fields. Identity, role
      // narrative, live status, and tasks stay with the richer Control Plane
      // model so both views share one coherent agent population.
      return genui ? {
        ...agent,
        claimedSkill: genui.claimedSkill,
        activeBranch: genui.activeBranch,
        contextUsagePercent: genui.contextUsagePercent,
        avatarColor: genui.avatarColor,
      } : agent;
    }),
    skills: INITIAL_SKILLS.map((skill) => ({
      id: skill.id,
      name: skill.name,
      instructions: skill.instructions,
      claimedCount: skill.claimedCount,
    })),
    messages: [
      ...INITIAL_TRANSCRIPT.map((message) => ({
        id: message.id,
        meetId: 'meet-01',
        senderId: message.speakerId,
        senderName: message.speakerName,
        text: message.content,
        timestamp: message.timestamp,
      })),
      ...controlPlane.messages,
    ],
    metrics: {
      ...controlPlane.metrics,
      totalMessagesToday: INITIAL_TRANSCRIPT.length + controlPlane.messages.length,
      prHistory: PR_HOURLY_HISTORY,
    },
  };
}
