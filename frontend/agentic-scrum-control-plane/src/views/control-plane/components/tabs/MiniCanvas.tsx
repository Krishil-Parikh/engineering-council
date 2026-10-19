import React from 'react';
import { DelegationCanvas } from '../canvas/DelegationCanvas';

interface MiniCanvasProps {
  onExpand: () => void;
}

export const MiniCanvas: React.FC<MiniCanvasProps> = ({ onExpand }) => {
  return <DelegationCanvas isMini={true} onExpand={onExpand} />;
};
