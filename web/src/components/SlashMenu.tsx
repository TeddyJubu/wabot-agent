import type { SlashCommand } from "@/hooks/useSlashCommands";

interface Props {
  commands: SlashCommand[];
  activeIdx: number;
  onPick: (c: SlashCommand) => void;
}

export default function SlashMenu({ commands, activeIdx, onPick }: Props) {
  if (commands.length === 0) return null;
  return (
    <ul className="absolute bottom-full left-0 right-0 mb-2 overflow-hidden rounded-card border border-border bg-bg-card shadow-sm">
      {commands.map((c, i) => (
        <li key={c.name}>
          <button
            type="button"
            onClick={() => onPick(c)}
            className={`flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm transition ${
              i === activeIdx ? "bg-bg-app" : ""
            }`}
          >
            <span className="font-mono text-accent">{c.name}</span>
            <span className="text-xs text-fg-muted">{c.description}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}
