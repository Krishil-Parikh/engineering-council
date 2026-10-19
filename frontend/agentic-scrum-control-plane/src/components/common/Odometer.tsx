import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

interface OdometerProps {
  value: number;
  className?: string;
  suffix?: string;
  prefix?: string;
}

export const Odometer: React.FC<OdometerProps> = ({
  value,
  className = '',
  suffix = '',
  prefix = '',
}) => {
  const [displayValue, setDisplayValue] = useState(value);

  useEffect(() => {
    setDisplayValue(value);
  }, [value]);

  const digits = displayValue.toString().split('');

  return (
    <span className={`inline-flex items-center font-mono tabular-nums ${className}`}>
      {prefix && <span>{prefix}</span>}
      <span className="inline-flex overflow-hidden">
        <AnimatePresence mode="popLayout" initial={false}>
          {digits.map((digit, idx) => (
            <motion.span
              key={`${idx}-${digit}`}
              initial={{ y: -16, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              exit={{ y: 16, opacity: 0 }}
              transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
              className="inline-block"
            >
              {digit}
            </motion.span>
          ))}
        </AnimatePresence>
      </span>
      {suffix && <span>{suffix}</span>}
    </span>
  );
};
