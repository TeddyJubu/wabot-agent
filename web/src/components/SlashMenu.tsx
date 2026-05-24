import type { SlashCommand } from "@/hooks/useSlashCommands";

interface Props {
  commands: SlashCommand[];
  activeIdx: number;
  onPick: (c: SlashCommand) => void;
}

/**
 * @deprecated Phase B replaced this with the Cmd-K CommandPalette
 * (`@/components/CommandPalette`). SlashMenu is still rendered in the
 * `?ui=v2`-OFF branch of `App.tsx` for the one-release flag-deprecation
 * window. Remove this file once the v2 flag is flipped on by default and
 * the bottom slash input is gone from `App.tsx`.
 *
 * Tracking: UX-IMPLEMENTATION-PLAN.md -> Phase D - L6.
 */
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
