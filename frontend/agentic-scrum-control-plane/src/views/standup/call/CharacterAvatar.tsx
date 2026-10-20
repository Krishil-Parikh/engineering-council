import { useId } from 'react';
import type { ReactElement } from 'react';
import { lookFor, hash } from './script';
import type { Look } from './script';

/** A person drawn as a small scene: a room behind, a desk in front, the person at it. What they do (speak, review, wait, get stuck, need you, finish) comes from the tile's `data-state` and
 *  `data-speaking`, styled in call.css. The characters are drawn for this project; the idea of a character in a room at a desk, with a mouth that moves when they talk, is Agent Standup's (MIT). */

const SCENES: ((id: string) => ReactElement)[] = [
  (id) => (
    <>
      <defs><linearGradient id={`${id}s`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#FFC2A8" /><stop offset=".55" stopColor="#FF93B4" /><stop offset="1" stopColor="#9A7BFF" /></linearGradient></defs>
      <rect width="100" height="75" fill={`url(#${id}s)`} />
      <circle cx="74" cy="31" r="19" fill="#FFF3D0" opacity=".22" /><circle cx="74" cy="31" r="11" fill="#FFF3D0" />
      <path d="M0 50Q24 34 48 48T100 44V75H0z" fill="#7B5FD6" /><path d="M0 57Q30 45 62 56T100 53V75H0z" fill="#5B46B8" />
    </>
  ),
  (id) => (
    <>
      <defs><linearGradient id={`${id}s`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#0D1230" /><stop offset="1" stopColor="#2A2E68" /></linearGradient></defs>
      <rect width="100" height="75" fill={`url(#${id}s)`} />
      {[[12, 10], [30, 18], [58, 8], [88, 22], [72, 14], [44, 24], [8, 30], [94, 8]].map(([x, y], i) => <circle key={i} className="su-tw" style={{ animationDelay: `-${i * 0.4}s` }} cx={x} cy={y} r=".7" fill="#fff" />)}
      <circle cx="80" cy="18" r="7" fill="#FFF4CF" /><circle cx="83" cy="16" r="6.2" fill="#1D2150" />
      <g fill="#161A45">{[[0, 40, 12], [12, 34, 9], [21, 44, 11], [32, 30, 8], [40, 41, 12], [52, 36, 9], [61, 45, 11], [72, 33, 10], [82, 42, 9], [91, 37, 10]].map(([x, y, w], i) => <rect key={i} x={x} y={y} width={w} height={75 - y} />)}</g>
    </>
  ),
  (id) => (
    <>
      <defs><linearGradient id={`${id}s`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#FFEADB" /><stop offset="1" stopColor="#FFD2B5" /></linearGradient><linearGradient id={`${id}w`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#BFE9FF" /><stop offset="1" stopColor="#EAF8FF" /></linearGradient></defs>
      <rect width="100" height="75" fill={`url(#${id}s)`} />
      <rect x="9" y="9" width="30" height="30" rx="3" fill="#fff" /><rect x="11" y="11" width="26" height="26" rx="2" fill={`url(#${id}w)`} /><path d="M24 11v26M11 24h26" stroke="#fff" strokeWidth="1.6" />
      <rect x="62" y="22" width="32" height="2.4" rx="1" fill="#B98A64" />
      {[['#FF7A6B', 64, 12], ['#4CC3FF', 68, 14], ['#FFD84A', 72, 10], ['#7C8CFF', 76, 13], ['#4FD1A5', 80, 11]].map(([c, x, h], i) => <rect key={i} x={x as number} y={22 - (h as number)} width="3.6" height={h as number} rx=".8" fill={c as string} />)}
    </>
  ),
  (id) => (
    <>
      <defs><linearGradient id={`${id}s`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#BDF1FF" /><stop offset="1" stopColor="#EFFFF6" /></linearGradient></defs>
      <rect width="100" height="75" fill={`url(#${id}s)`} />
      <g fill="#fff" className="su-drift"><ellipse cx="22" cy="16" rx="9" ry="3.6" /><ellipse cx="28" cy="13.5" rx="6" ry="3.6" /><ellipse cx="74" cy="24" rx="8" ry="3" /></g>
      <path d="M0 48Q25 36 52 47T100 42V75H0z" fill="#7DDC9A" /><path d="M0 56Q30 46 64 56T100 52V75H0z" fill="#4FC482" />
      <rect x="80" y="30" width="2.6" height="14" fill="#8A5A3A" /><circle cx="81.3" cy="27" r="8" fill="#3FAE6C" />
    </>
  ),
];

function shade(hex: string, amount: number): string {
  const n = parseInt(hex.slice(1), 16);
  const f = (v: number) => Math.max(0, Math.min(255, Math.round(v + (amount > 0 ? (255 - v) * amount : v * amount))));
  return `#${[(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => f(v).toString(16).padStart(2, '0')).join('')}`;
}

function Hair({ look }: { look: Look }) {
  const c = look.hair;
  switch (look.hairStyle) {
    case 0: return <path d="M35 36Q35 18 50 18Q65 18 65 36Q60 27 50 27Q40 27 35 36z" fill={c} />;
    case 1: return <path d="M33 40Q31 17 50 16Q69 17 67 40Q64 28 50 27Q36 28 33 40zM33 40q-3 12 1 18q3-6 2-16z" fill={c} />;
    case 2: return <g fill={c}><circle cx="39" cy="26" r="8" /><circle cx="50" cy="22" r="9" /><circle cx="61" cy="26" r="8" /></g>;
    case 3: return <path d="M34 38Q33 18 50 17Q66 18 66 38Q66 30 58 26Q44 30 34 38z" fill={c} />;
    default: return <g fill={c}><path d="M36 33Q38 20 50 20Q62 20 64 33Q56 26 50 26Q44 26 36 33z" /><circle cx="35" cy="33" r="3" /><circle cx="65" cy="33" r="3" /></g>;
  }
}

export interface AvatarProps {
  id: string;
  type: string;
  speaking?: boolean;
  className?: string;
}

export function CharacterAvatar({ id, type, className }: AvatarProps) {
  const uid = useId().replace(/[:]/g, '');
  const look = lookFor(id, type);
  const delay = -((hash(id) % 45) / 10);
  const dark = shade(look.shirt, -0.22);
  const ink = '#2A2233';
  const eyeRx = [3.1, 3.7, 2.5][look.eyes];
  const eyeRy = [4.3, 3.7, 5][look.eyes];
  const ex = [43, 57];
  const fy = 38;
  return (
    <svg viewBox="0 0 100 75" preserveAspectRatio="xMidYMid slice" className={className} aria-hidden focusable="false">
      {SCENES[look.scene](`${uid}`)}
      <g className="su-fig" style={{ ['--d' as string]: `${delay}s` }}>
        {/* body */}
        <rect x="29" y="52" width="42" height="36" rx="14" fill={look.shirt} />
        <rect x="29" y="52" width="42" height="14" rx="7" fill={shade(look.shirt, 0.18)} opacity=".55" />
        {look.accessory === 'tie' && <path d="M50 55l-3 5 3 14 3-14z" fill="#8F0000" />}
        {look.accessory === 'scarf' && <path d="M38 54q12 7 24 0v5q-12 7-24 0z" fill="#FFC857" />}
        {/* arms */}
        <ellipse cx="29" cy="64" rx="5" ry="10" fill={dark} transform="rotate(10 29 64)" />
        <ellipse cx="71" cy="64" rx="5" ry="10" fill={dark} transform="rotate(-10 71 64)" />
        <g className="su-hand-up"><ellipse cx="74" cy="50" rx="4.4" ry="9" fill={dark} transform="rotate(-8 74 50)" /><circle cx="75" cy="41" r="4" fill={look.skin} /></g>
        {/* head */}
        <g className="su-head">
          <rect x="45" y="48" width="10" height="8" rx="3" fill={shade(look.skin, -0.08)} />
          <circle cx="50" cy="38" r="16" fill={look.skin} />
          <ellipse cx="36.5" cy="42" rx="3.3" ry="2" fill="#FF6F91" opacity=".28" /><ellipse cx="63.5" cy="42" rx="3.3" ry="2" fill="#FF6F91" opacity=".28" />
          <g className="su-eyes-open">
            {ex.map((x) => <g key={x} className="su-eye" style={{ ['--d' as string]: `${delay}s` }}><ellipse cx={x} cy={fy} rx={eyeRx} ry={eyeRy} fill={ink} /><circle cx={x + 1} cy={fy - 1.4} r="1.1" fill="#fff" /></g>)}
          </g>
          <g className="su-eyes-happy">
            {ex.map((x) => <path key={x} d={`M${x - 3.6} ${fy + 1.4}Q${x} ${fy - 4.2} ${x + 3.6} ${fy + 1.4}`} fill="none" stroke={ink} strokeWidth="1.7" strokeLinecap="round" />)}
          </g>
          <path className="su-brow l" d={`M${ex[0] - 3.6} ${fy - eyeRy - 3}q3.6-2 7.2 0`} fill="none" stroke={ink} strokeWidth="1.4" strokeLinecap="round" />
          <path className="su-brow r" d={`M${ex[1] - 3.6} ${fy - eyeRy - 3}q3.6-2 7.2 0`} fill="none" stroke={ink} strokeWidth="1.4" strokeLinecap="round" />
          <path className="su-mouth-idle" d="M45.5 47q4.5 3.8 9 0" fill="none" stroke={ink} strokeWidth="1.6" strokeLinecap="round" />
          <ellipse className="su-mouth-talk" cx="50" cy="48" rx="4.2" ry="3.6" fill="#4B1C2C" />
          {look.glasses && <g fill="rgba(255,255,255,.18)" stroke="#2C2F40" strokeWidth="1.1"><circle cx={ex[0]} cy={fy} r="6.2" /><circle cx={ex[1]} cy={fy} r="6.2" /><path d={`M${ex[0] + 6.2} ${fy}h${ex[1] - ex[0] - 12.4}`} fill="none" /></g>}
          <Hair look={look} />
          {look.accessory === 'cap' && <g><path d="M33 33Q33 17 50 17Q67 17 67 33z" fill="#2C2F40" /><path d="M48 32q22-2 28 4q-12 3-28 0z" fill="#1F2230" /></g>}
          {look.accessory === 'headset' && <g><path d="M33 40Q31 17 50 16Q69 17 67 40" fill="none" stroke="#2C2F40" strokeWidth="3" strokeLinecap="round" /><rect x="29" y="35" width="7" height="12" rx="3.5" fill="#E60000" stroke="#2C2F40" strokeWidth="1.4" /><rect x="64" y="35" width="7" height="12" rx="3.5" fill="#E60000" stroke="#2C2F40" strokeWidth="1.4" /><path d="M32 47q2 8 14 9" fill="none" stroke="#2C2F40" strokeWidth="1.2" strokeLinecap="round" /></g>}
        </g>
      </g>
      {/* desk */}
      <defs><linearGradient id={`${uid}d`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={look.desk[0]} /><stop offset="1" stopColor={look.desk[1]} /></linearGradient></defs>
      <rect y="62" width="100" height="13" fill={`url(#${uid}d)`} /><rect y="62" width="100" height="1.3" fill="#fff" opacity=".38" /><rect y="63.3" width="100" height="2.6" fill="#000" opacity=".1" />
      <g className="su-laptop"><rect x="33" y="46" width="34" height="18" rx="2.8" fill="#D3D8E6" /><circle cx="50" cy="55" r="2.3" fill={shade(look.shirt, 0.3)} /><rect x="29.5" y="63.4" width="41" height="3" rx="1.5" fill="#AAB1C2" /></g>
      <g className="su-hands"><circle className="su-hand l" cx="38" cy="65.6" r="3.1" fill={look.skin} /><circle className="su-hand r" cx="62" cy="65.6" r="3.1" fill={look.skin} /></g>
      <g className="su-hourglass"><path d="M13 44h10l-5 7 5 7H13l5-7z" fill="none" stroke="#fff" strokeWidth="1.4" strokeLinejoin="round" /><path d="M15 56h6l-3-3z" fill="#FFD24A" /></g>
      <g className="su-bang"><circle cx="82" cy="30" r="8" fill="#E60000" /><rect x="81" y="24" width="2" height="7" rx="1" fill="#fff" /><circle cx="82" cy="34" r="1.2" fill="#fff" /></g>
      <g className="su-sparks" fill="#FFE58A"><path d="M22 28l1 -3 1 3 3 1 -3 1 -1 3 -1 -3 -3 -1z" /><path d="M78 22l.8-2.4.8 2.4 2.4.8-2.4.8-.8 2.4-.8-2.4-2.4-.8z" fill="#FF9BB8" /></g>
    </svg>
  );
}
