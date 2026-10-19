import React from 'react';
import { motion, AnimatePresence } from 'motion/react';

interface OdometerProps {
  value: string | number;
  className?: string;
  prefix?: string;
  suffix?: string;
}

export const Odometer: React.FC<OdometerProps> = ({ value, className = '', prefix, suffix }) => {
  const stringValue = String(value);
  const characters = stringValue.split('');

  return (
    <span className={`inline-flex items-center tabular-nums overflow-hidden ${className}`}>
      {prefix && <span className="mr-0.5">{prefix}</span>}
      {characters.map((char, index) => {
        // If not a digit, just render as static character (e.g. ':', '/', '.', '%')
        if (!/\d/.test(char)) {
          return (
            <span key={`sym-${index}`} className="inline-block px-[1px]">
              {char}
            </span>
          );
        }

        return (
          <span
            key={`col-${index}`}
            className="inline-block relative h-[1.15em] w-[0.62em] overflow-hidden text-center align-middle"
          >
            <AnimatePresence mode="popLayout" initial={false}>
              <motion.span
                key={char}
                initial={{ y: '100%', opacity: 0.3 }}
                animate={{ y: '0%', opacity: 1 }}
                exit={{ y: '-100%', opacity: 0 }}
                transition={{ duration: 0.26, ease: [0.16, 1, 0.3, 1] }}
                className="absolute inset-0 flex items-center justify-center font-semibold"
              >
                {char}
              </motion.span>
            </AnimatePresence>
          </span>
        );
      })}
      {suffix && <span className="ml-0.5">{suffix}</span>}
    </span>
  );
};
