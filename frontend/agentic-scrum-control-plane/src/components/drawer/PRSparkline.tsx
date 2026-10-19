import React, { useState, useEffect } from 'react';
import { AreaChart, Area, XAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { PRHourlyData } from '../../types';
import { Odometer } from '../common/Odometer';

interface PRSparklineProps {
  data: PRHourlyData[];
  totalPRs: number;
}

// Custom Tooltip (§5.1: small glass-bg chip, mono numeral + hour label, no generic white-box styling)
const SparklineTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    return (
      <div className="px-2.5 py-1.5 rounded-lg border border-[#E7E6DF] bg-[#FCFCFB]/95 backdrop-blur-md shadow-md text-xs font-mono select-none">
        <div className="text-[10px] text-[#8E8E8E]">{label}</div>
        <div className="font-semibold text-[#161616]">
          {payload[0].value} {payload[0].value === 1 ? 'PR merged' : 'PRs merged'}
        </div>
      </div>
    );
  }
  return null;
};

export const PRSparkline: React.FC<PRSparklineProps> = ({ data, totalPRs }) => {
  return (
    <div className="w-full h-full flex flex-col justify-between py-1">
      {/* Sprint Swimlane */}
      <div className="flex items-center justify-between pb-3 border-b border-[#E7E6DF] text-xs">
        <div className="flex items-center gap-6 font-mono text-[#5B5B5B]">
          <div className="flex items-center gap-2">
            <span className="font-medium text-[#161616]">Sprint 01</span>
            <span className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-700" />
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-700" />
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-700" />
            </span>
          </div>

          <span className="text-[#D5D3CA]">──</span>

          <div className="flex items-center gap-2">
            <span className="font-medium text-[#161616]">Sprint 02</span>
            <span className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-700" />
              <span className="text-[10px] text-[#E60000]">◆</span>
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-700" />
            </span>
          </div>

          <span className="text-[#D5D3CA]">──</span>

          <div className="flex items-center gap-2">
            <span className="font-medium text-[#161616]">Sprint 03 (Current)</span>
            <span className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-700" />
              <span className="w-1.5 h-1.5 rounded-full bg-[#E60000] animate-pulse" />
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-[11px] text-[#8E8E8E]">Velocity Trend</span>
          <span className="w-2 h-2 rounded-full bg-[#E60000]" />
        </div>
      </div>

      {/* Sparkline & Total Header */}
      <div className="my-2">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-xs text-[#5B5B5B]">
            Pull requests merged · last 24h
          </span>
          <div className="flex items-center gap-1.5 text-xs font-semibold text-[#161616]">
            <Odometer value={totalPRs} />
            <span className="text-[11px] text-[#5B5B5B] font-normal">total</span>
          </div>
        </div>

        {/* Recharts AreaChart Sparkline (§5.1) */}
        <div className="w-full h-16 relative">
          <ResponsiveContainer width="100%" height={64}>
            <AreaChart data={data} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id="prGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#E60000" stopOpacity={0.28} />
                  <stop offset="100%" stopColor="#E60000" stopOpacity={0} />
                </linearGradient>
              </defs>
              <Area
                type="monotone"
                dataKey="prs"
                stroke="#161616"
                strokeWidth={1.5}
                fill="url(#prGradient)"
                dot={false}
                activeDot={{
                  r: 3.5,
                  fill: '#E60000',
                  stroke: '#FCFCFB',
                  strokeWidth: 2,
                }}
                isAnimationActive={true}
                animationDuration={600}
                animationEasing="ease-out"
              />
              <XAxis
                dataKey="time"
                tick={{ fontSize: 10, fill: '#8E8E8E', fontFamily: 'JetBrains Mono' }}
                axisLine={false}
                tickLine={false}
                ticks={['00:00', '06:00', '12:00', '18:00', 'now']}
              />
              <Tooltip
                content={<SparklineTooltip />}
                cursor={{ stroke: '#D5D3CA', strokeWidth: 1 }}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Yesterday / Today / Blockers Tri-column (§5) */}
      <div className="grid grid-cols-3 gap-6 pt-3 border-t border-[#E7E6DF] text-xs">
        <div>
          <div className="text-[10.5px] uppercase font-mono text-[#8E8E8E] mb-1">
            Yesterday
          </div>
          <p className="text-[#161616] truncate">· Schema finalized & ratified</p>
        </div>
        <div>
          <div className="text-[10.5px] uppercase font-mono text-[#8E8E8E] mb-1">
            Today
          </div>
          <p className="text-[#161616] truncate">· Redis session channel shipped</p>
        </div>
        <div>
          <div className="text-[10.5px] uppercase font-mono text-[#8E8E8E] mb-1">
            Blockers
          </div>
          <p className="text-[#5B5B5B] truncate">· None (all unblocked)</p>
        </div>
      </div>
    </div>
  );
};
