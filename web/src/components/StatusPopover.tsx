import { useStore, type ReadinessVariant } from "@/store";
import StatusDot from "./StatusDot";

interface Props {
  onClose: () => void;
}

export default function StatusPopover({ onClose }: Props) {
  const readiness = useStore((s) => s.readiness);

  return (
    <div
      role="dialog"
      aria-label="Readiness summary"
      onMouseLeave={onClose}
      className="absolute left-0 top-full z-40 mt-2 w-72 rounded-card border border-border bg-bg-card p-3 shadow-sm"
    >
      <ul className="divide-y divide-border">
        <Row label="Model" value={readiness.model.label} variant={readiness.model.variant} />
        <Row label="wabot" value={readiness.wabot.label} variant={readiness.wabot.variant} />
        <Row label="Send policy" value={readiness.policy.label} variant={readiness.policy.variant} />
        <Row label="Memory" value={readiness.memory.label} variant={readiness.memory.variant} />
      </ul>
    </div>
  );
}

function Row({
  label,
  value,
  variant,
}: {
  label: string;
  value: string;
  variant: ReadinessVariant;
}) {
  return (
    <li className="flex items-center justify-between py-2 text-xs">
      <span className="text-fg-muted">{label}</span>
      <span className="inline-flex items-center gap-2">
        <StatusDot variant={variant} animated={false} />
        <span>{value}</span>
      </span>
    </li>
  );
}
