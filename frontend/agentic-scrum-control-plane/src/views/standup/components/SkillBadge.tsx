import { cap } from '../models/lookup';

/** A skill or a temporary role a person took for THIS meeting. It is a label on the person, never a kind of person: the same developer may take another skill in the next meeting. */
export function SkillBadge({ skill, role }: { skill?: string | null; role?: string | null }) {
  if (!skill && !role) return null;
  return (
    <span className="flex flex-wrap items-center gap-1">
      {skill && (
        <span data-testid="skill-badge" title="Skill taken for this meeting" className="rounded-[3px] border border-[#1F5FA8]/30 bg-[#1F5FA8]/10 px-1.5 py-0.5 text-[10px] font-semibold text-[#14447D]">
          {cap(skill)}
        </span>
      )}
      {role && (
        <span data-testid="role-badge" title="Temporary role in this meeting" className="rounded-[3px] border border-[#7B3FA0]/30 bg-[#7B3FA0]/10 px-1.5 py-0.5 text-[10px] font-medium italic text-[#58297A]">
          {role}
        </span>
      )}
    </span>
  );
}
