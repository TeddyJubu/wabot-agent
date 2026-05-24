import { useEffect, useState } from "react";
import { LineChart, Line, ResponsiveContainer } from "recharts";
import { AlertTriangle } from "lucide-react";
import {
  getOverview,
  getRunsSeries,
  type OverviewResponse,
  type RunsSeriesResponse,
} from "@/api/metrics";
import { useStore } from "@/store";

/**
 * Repeat-use home view. Three regions, in order:
 *
 * 1. A KPI row of four tiles sourced from `/api/metrics/overview`.
 * 2. A tiny 24h sparkline of runs/hour, or a placeholder when the series is
 *    empty.
 * 3. A "Next action" card that surfaces the single most important warning
 *    the user should act on right now.
 *
 * The digest deliberately stays small — for richer charts the user opens
 * the Insights route, which mounts `<OverviewPanel />`.
 */
export default function DailyDigest() {
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [runsSeries, setRunsSeries] = useState<RunsSeriesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      getOverview(),
      getRunsSeries({ window: "24h", bucket: "hour" }),
    ])
      .then(([ov, rs]) => {
        if (cancelled) return;
        setOverview(ov);
        setRunsSeries(rs);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const msg = err instanceof Error ? err.message : "Could not load digest";
        setError(msg);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section aria-label="Daily digest" className="space-y-6">
      {/* KPI row */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <DigestCard
          label="Messages today"
          value={overview ? formatCount(overview.messages_today) : "—"}
        />
        <DigestCard
          label="Runs today"
          value={overview ? formatCount(overview.runs_today) : "—"}
        />
        <DigestCard
          label="Cost 24h"
          value={overview ? formatCost(overview.cost_usd_24h) : "—"}
        />
        <DigestCard
          label="Queue depth"
          value={overview ? formatCount(overview.queue_depth) : "—"}
        />
      </div>

      {/* Sparkline */}
      <div>
        <p className="mb-2 text-xs font-medium text-fg-muted">
          Runs · last 24 hours
        </p>
        <Sparkline series={runsSeries} />
      </div>

      {/* Next action */}
      <NextActionCard />

      {error && (
        <p className="rounded-card border border-bad/40 bg-bad/10 px-3 py-2 text-xs text-bad">
          {error}
        </p>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Local subcomponents — kept inline so the digest is self-contained and we
// don't reach into slide-overs/overview/* (that's overview-panel territory).
// ---------------------------------------------------------------------------

interface DigestCardProps {
  label: string;
  value: string;
}

function DigestCard({ label, value }: DigestCardProps) {
  return (
    <div className="min-w-0 rounded-card border border-border bg-bg-card p-3">
      <p className="truncate text-xs text-fg-muted">{label}</p>
      <p className="mt-1 truncate text-xl font-semibold tabular-nums text-fg">
        {value}
      </p>
    </div>
  );
}

interface SparklineProps {
  series: RunsSeriesResponse | null;
}

function Sparkline({ series }: SparklineProps) {
  if (!series || series.series.length === 0) {
    return (
      <div className="flex h-20 items-center justify-center rounded-card border border-border bg-bg-card text-xs text-fg-muted">
        No activity in the last 24 hours
      </div>
    );
  }

  const data = series.series.map((s) => ({
    ts: s.timestamp,
    runs: s.count,
  }));

  return (
    <div className="h-20 rounded-card border border-border bg-bg-card p-2">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
          <Line
            type="monotone"
            dataKey="runs"
            stroke="hsl(var(--accent))"
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function NextActionCard() {
  const readiness = useStore((s) => s.readiness);
  const pairing = useStore((s) => s.pairing);
  const openSlideOver = useStore((s) => s.openSlideOver);

  // Priority order: send-policy first (security), then wabot endpoint, then
  // pairing. Mirrors the precedence we apply in the status bar.
  let kind: "policy" | "wabot" | "pairing" | "ok" = "ok";
  if (readiness.policy.label === "allow_all") {
    kind = "policy";
  } else if (readiness.wabot.variant !== "ok") {
    kind = "wabot";
  } else if (pairing && pairing.logged_in === false) {
    kind = "pairing";
  }

  if (kind === "ok") {
    return (
      <div className="rounded-card border border-border bg-bg-card p-4">
        <p className="text-sm text-fg">
          All systems normal — nothing to action right now.
        </p>
      </div>
    );
  }

  const message =
    kind === "policy"
      ? "Send policy is allow_all. Review who can be messaged."
      : kind === "wabot"
        ? "wabot endpoint isn't configured."
        : "WhatsApp isn't paired.";

  const actionLabel = kind === "pairing" ? "Open /pair" : "Open settings";
  const onAction =
    kind === "pairing"
      ? () => window.open("/pair", "_blank", "noopener")
      : () => openSlideOver("settings");

  return (
    <div className="flex items-start gap-3 rounded-card border border-warn/40 bg-warn/10 p-4">
      <AlertTriangle
        aria-hidden="true"
        className="mt-0.5 size-5 shrink-0 text-warn"
      />
      <div className="flex-1">
        <p className="text-sm font-medium text-fg">Next action</p>
        <p className="mt-0.5 text-sm text-fg-muted">{message}</p>
      </div>
      <button
        type="button"
        onClick={onAction}
        className="shrink-0 min-h-[44px] rounded-pill border border-border bg-bg-app px-4 py-2 text-xs font-medium text-fg transition hover:bg-bg-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        {actionLabel}
      </button>
    </div>
  );
}

function formatCount(n: number): string {
  return new Intl.NumberFormat().format(n);
}

function formatCost(n: number): string {
  return `$${n.toFixed(2)}`;
}
