import React, { useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

interface ToastCaptionProps {
  message: string | null;
  onDismiss: () => void;
}

export const ToastCaption: React.FC<ToastCaptionProps> = ({ message, onDismiss }) => {
  useEffect(() => {
    if (!message) return;
    const timer = setTimeout(() => {
      onDismiss();
    }, 3500);
    return () => clearTimeout(timer);
  }, [message, onDismiss]);

  return (
    <div className="fixed top-18 left-1/2 -translate-x-1/2 z-50 pointer-events-none flex justify-center">
      <AnimatePresence>
        {message && (
          <motion.div
            initial={{ opacity: 0, y: -8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.98 }}
            transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
            className="pointer-events-auto px-4 py-2 rounded-full border border-[#161616]/10 bg-[#FCFCFB]/95 backdrop-blur-md shadow-lg flex items-center gap-2.5 text-[12.5px] font-medium text-[#161616]"
          >
            <span className="w-2 h-2 rounded-full bg-[#E60000] animate-pulse" />
            <span>{message}</span>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};
