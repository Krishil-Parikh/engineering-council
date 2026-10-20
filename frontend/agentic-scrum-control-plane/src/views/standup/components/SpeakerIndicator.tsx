/** Three bars that move while someone speaks. The words "speaking" are read out for people who cannot see them. */
export function SpeakerIndicator({ active }: { active: boolean }) {
  if (!active) return null;
  return (
    <span data-testid="speaker-indicator" className="inline-flex items-end gap-[2px]" role="img" aria-label="speaking">
      {[0, 1, 2].map((i) => (
        <span key={i} className="w-[3px] rounded-full bg-[#E60000] motion-safe:animate-pulse" style={{ height: 6 + i * 3, animationDelay: `${i * 120}ms` }} />
      ))}
    </span>
  );
}
