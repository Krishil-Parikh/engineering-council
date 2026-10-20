import type { StandupParticipant } from '../models/standup';
import { PARTICIPANT_LABEL } from '../models/meeting-status';
import { CharacterAvatar } from './CharacterAvatar';
import { tileOrder } from './CallView';

function Node({ person }: { person: StandupParticipant }) {
  return (
    <div data-testid="tree-node" data-status={person.status} className="flex items-center gap-2 rounded-lg border border-white/10 bg-[#1B1D27] p-1.5 text-[#E9EAF0]">
      <span className="h-8 w-11 shrink-0 overflow-hidden rounded-md"><CharacterAvatar id={person.participant_id} type={person.participant_type} className="h-full w-full" /></span>
      <span className="min-w-0">
        <span className="block truncate text-[12.5px] font-semibold">{person.display_name}</span>
        <span className="block truncate text-[10.5px] text-[#9AA0B6]">
          {PARTICIPANT_LABEL[person.participant_type] ?? person.participant_type}{person.skill ? ` · ${person.skill}` : ''}{person.role ? ` · ${person.role}` : ''}
        </span>
      </span>
      {person.badge && <span className="ml-auto shrink-0 rounded-full bg-white/10 px-2 py-0.5 text-[10.5px]">{person.badge}</span>}
    </div>
  );
}

/** Who reports to whom in the meeting: the Business SME, the Scrum Master, and the developers (grouped by the skill they took for this meeting). Press T to switch to it. */
export function TreeView({ participants }: { participants: StandupParticipant[] }) {
  const people = tileOrder(participants.filter((p) => p.status !== 'left'));
  const sme = people.filter((p) => p.participant_type === 'business_sme');
  const scrum = people.filter((p) => p.participant_type === 'scrum_master');
  const rest = people.filter((p) => !['business_sme', 'scrum_master'].includes(p.participant_type));
  const groups = new Map<string, StandupParticipant[]>();
  for (const p of rest) groups.set(p.skill ?? 'No skill taken yet', [...(groups.get(p.skill ?? 'No skill taken yet') ?? []), p]);
  return (
    <section aria-label="Who is in the meeting" data-testid="tree-view" className="rounded-xl bg-[#12131A] p-4 text-[#E9EAF0]">
      {people.length === 0 && <p className="text-[13px] text-[#9AA0B6]">Nobody has joined this meeting yet.</p>}
      <ul className="space-y-2" role="tree" aria-label="Meeting hierarchy">
        {sme.map((p) => (
          <li key={p.participant_id} role="treeitem" aria-expanded="true">
            <Node person={p} />
            <ul className="ml-6 mt-2 space-y-2 border-l border-white/15 pl-4" role="group">
              {scrum.map((s) => (
                <li key={s.participant_id} role="treeitem" aria-expanded="true">
                  <Node person={s} />
                  <ul className="ml-6 mt-2 space-y-3 border-l border-white/15 pl-4" role="group">
                    {[...groups.entries()].map(([skill, members]) => (
                      <li key={skill} role="treeitem" aria-expanded="true">
                        <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-[0.1em] text-[#9AA0B6]">{skill}</div>
                        <ul className="grid gap-1.5 sm:grid-cols-2" role="group">{members.map((m) => <li key={m.participant_id} role="treeitem"><Node person={m} /></li>)}</ul>
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          </li>
        ))}
        {sme.length === 0 && scrum.map((s) => <li key={s.participant_id} role="treeitem"><Node person={s} /></li>)}
        {sme.length === 0 && scrum.length === 0 && rest.map((m) => <li key={m.participant_id} role="treeitem"><Node person={m} /></li>)}
      </ul>
    </section>
  );
}
