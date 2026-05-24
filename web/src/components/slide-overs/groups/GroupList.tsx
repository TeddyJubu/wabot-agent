import type { GroupSummary } from "@/api/groups";

interface Props {
  groups: GroupSummary[];
  selectedJid: string | null;
  busy?: boolean;
  onSelect: (jid: string) => void;
}

export function GroupList({ groups, selectedJid, busy, onSelect }: Props) {
  return (
    <ul className="max-h-40 space-y-1 overflow-y-auto">
      {groups.map((g) => (
        <li key={g.jid}>
          <button
            type="button"
            disabled={busy}
            onClick={() => onSelect(g.jid)}
            className={`w-full rounded-card border px-3 py-2 text-left text-xs transition ${
              selectedJid === g.jid
                ? "border-accent bg-bg-card"
                : "border-border hover:bg-bg-card"
            }`}
          >
            <span className="block font-medium">{g.name || g.jid}</span>
            <span className="text-fg-muted">
              {g.participant_count ?? "?"} members
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}
