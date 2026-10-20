export const SHORTCUTS: [string, string][] = [
  ['Space', 'Pause or resume the lines (and the replay)'],
  ['← / →', 'Replay: previous / next event'],
  ['N / Shift+N', 'Replay: next / previous highlight'],
  ['G', 'Go to the meeting that needs you'],
  ['J / K', 'Next / previous meeting that needs you'],
  ['M', 'Voice on / off'],
  ['T', 'Tree view and call'],
  ['B', 'Board of all meetings and call'],
  ['F', 'Focus layout (a bigger shared screen) and grid'],
  ['R', 'Recap'],
  ['L', 'Live transcript beside the call, on or off'],
  ['?', 'This help'],
  ['Esc', 'Close'],
];

export function ShortcutsHelp({ onClose }: { onClose: () => void }) {
  return (
    <div role="dialog" aria-modal="true" aria-label="Keyboard shortcuts" data-testid="shortcuts" className="fixed inset-0 z-[120] flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-md rounded-xl bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-[#E2E0D9] px-4 py-2.5">
          <h2 className="text-[14px] font-semibold">Keyboard shortcuts</h2>
          <button type="button" onClick={onClose} autoFocus className="rounded-md border border-[#E2E0D9] px-2.5 py-1 text-[12px]">Close</button>
        </div>
        <table className="w-full text-[12.5px]">
          <tbody>
            {SHORTCUTS.map(([key, what]) => <tr key={key} className="border-b border-[#F0EFE8]"><td className="w-32 px-4 py-1.5 font-mono font-semibold">{key}</td><td className="px-2 py-1.5 text-[#5B5B5B]">{what}</td></tr>)}
          </tbody>
        </table>
        <p className="px-4 py-3 text-[11.5px] text-[#8E8E8E]">Shortcuts are off while you type in a box.</p>
      </div>
    </div>
  );
}
