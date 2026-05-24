import { clsx } from "clsx";
import { Brain, Database, ShieldCheck, Smartphone } from "lucide-react";
import type { ComponentType, SVGProps } from "react";
import type { PairingState } from "@/api/pairing";
import {
  useStore,
  type ReadinessRow,
  type ReadinessVariant,
} from "@/store";

// Mirror StatusDot's palette so the colour story stays consistent. We use
// background + border + text rather than only the dot's fill, so the chip itself
// communicates state — but the value text remains the primary signal (WCAG
// 1.4.1: colour is never the only carrier of meaning).
const VARIANT_CLASSES: Record<ReadinessVariant, string> = {
  ok: "border-ok/40 bg-ok/10",
  warn: "border-warn/40 bg-warn/10",
  bad: "border-bad/40 bg-bad/10",
  pending: "border-border bg-bg-card",
};

const DOT_CLASSES: Record<ReadinessVariant, string> = {
  ok: "bg-ok",
  warn: "bg-warn",
  bad: "bg-bad",
  pending: "bg-fg-muted",
};

type IconComponent = ComponentType<SVGProps<SVGSVGElement>>;

interface ChipDescriptor {
  key: "wabot" | "model" | "policy" | "memory";
  label: string;
  icon: IconComponent;
  row: ReadinessRow;
  onClick: () => void;
}

function pairingRow(pairing: PairingState | null): ReadinessRow {
  if (!pairing) return { label: "checking", variant: "pending" };
  if (pairing.logged_in && pairing.connected) {
    return { label: "connected", variant: "ok" };
  }
  if (pairing.logged_in && !pairing.connected) {
    return { label: "offline", variant: "warn" };
  }
  if (!pairing.reachable) return { label: "unreachable", variant: "bad" };
  if (pairing.qr_available) return { label: "scan to pair", variant: "warn" };
  return { label: "not linked", variant: "warn" };
}

function openPairTab() {
  window.open("/pair", "_blank", "noopener");
}

export default function StatusBar() {
  const readiness = useStore((s) => s.readiness);
  const pairing = useStore((s) => s.pairing);
  const openSlideOver = useStore((s) => s.openSlideOver);

  const openSettings = () => openSlideOver("settings");

  const chips: ChipDescriptor[] = [
    {
      key: "wabot",
      label: "WhatsApp",
      icon: Smartphone,
      row: pairingRow(pairing),
      onClick: openPairTab,
    },
    {
      key: "model",
      label: "Model",
      icon: Brain,
      row: readiness.model,
      onClick: openSettings,
    },
    {
      key: "policy",
      label: "Send policy",
      icon: ShieldCheck,
      row: readiness.policy,
      onClick: openSettings,
    },
    {
      key: "memory",
      label: "Memory",
      icon: Database,
      row: readiness.memory,
      onClick: openSettings,
    },
  ];

  return (
    <nav
      aria-label="Workspace status"
      className="flex flex-wrap items-center justify-center gap-2 mb-4"
    >
      {chips.map(({ key, label, icon: Icon, row, onClick }) => (
        <button
          key={key}
          type="button"
          aria-label={`${label}: ${row.label}`}
          onClick={onClick}
          className={clsx(
            "inline-flex items-center gap-2 rounded-pill border px-3 py-2 text-xs",
            "transition hover:bg-bg-card focus-visible:outline-none",
            "focus-visible:ring-2 focus-visible:ring-accent",
            VARIANT_CLASSES[row.variant],
          )}
        >
          <Icon aria-hidden="true" className="size-4 text-fg-muted" />
          <span className="font-medium text-fg">{label}</span>
          <span
            aria-hidden="true"
            className={clsx("inline-block size-2 rounded-full", DOT_CLASSES[row.variant])}
          />
          <span className="text-fg-muted">{row.label}</span>
        </button>
      ))}
    </nav>
  );
}
