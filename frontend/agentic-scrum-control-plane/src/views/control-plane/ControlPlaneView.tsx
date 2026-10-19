import React from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { ScrumProvider, useScrum } from './context/ScrumContext';
import { TopBar } from './components/TopBar';
import { TabRail } from './components/TabRail';
import { LeftRail } from './components/LeftRail';
import { RightInspector } from './components/RightInspector';
import { BottomStrip } from './components/BottomStrip';
import { OverviewTab } from './components/tabs/OverviewTab';
import { CanvasTab } from './components/tabs/CanvasTab';
import { MeetTab } from './components/tabs/MeetTab';
import { ArtifactsTab } from './components/tabs/ArtifactsTab';
import { TimelineTab } from './components/tabs/TimelineTab';
import { SmeInterventionModal } from './components/modals/SmeInterventionModal';
import type { WorkspaceSnapshot } from '../../domain/types';
import type { CommandResult, WorkspaceCommand } from '../../domain/commands';

const MainLayout: React.FC = () => {
  const { activeTab } = useScrum();

  return (
    <div className="flex flex-col h-screen w-screen bg-[#FCFCFB] text-[#161616] overflow-hidden select-none">
      {/* 1. Persistent Top Bar (72px) */}
      <TopBar />

      {/* 2. Middle Surface: [ TabRail (64px) | LeftRail (232px) | Center Stage | RightInspector (320px) ] */}
      <div className="flex flex-1 overflow-hidden relative">
        {/* Tab Rail (64px) */}
        <TabRail />

        {/* Left Agent Roster Rail (232px) */}
        <LeftRail />

        {/* Center Stage: Swappable Tab Views with Morph & Ease */}
        <main className="flex-1 flex flex-col overflow-hidden relative bg-[#FCFCFB]">
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={activeTab}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
              className="flex-1 flex flex-col overflow-hidden"
            >
              {activeTab === 'overview' && <OverviewTab />}
              {activeTab === 'canvas' && <CanvasTab />}
              {activeTab === 'meet' && <MeetTab />}
              {activeTab === 'artifacts' && <ArtifactsTab />}
              {activeTab === 'timeline' && <TimelineTab />}
            </motion.div>
          </AnimatePresence>
        </main>

        {/* Right Inspector Panel (320px) */}
        <RightInspector />
      </div>

      {/* 3. Persistent Bottom Strip (40px) */}
      <BottomStrip />

      {/* Business SME Directive Dialog */}
      <SmeInterventionModal />
    </div>
  );
};

export default function ControlPlaneView({ workspaceSnapshot, executeCommand }: { workspaceSnapshot?: WorkspaceSnapshot; executeCommand?: (command: WorkspaceCommand) => Promise<CommandResult> }) {
  return (
    <ScrumProvider sharedWorkspace={workspaceSnapshot} sharedExecuteCommand={executeCommand}>
      <MainLayout />
    </ScrumProvider>
  );
}
