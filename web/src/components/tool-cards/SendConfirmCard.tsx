import { Send, Image as ImageIcon, ShieldAlert } from "lucide-react";
import type { ToolAction, SendConfirmData } from "@/types/ui-envelope";

interface Props {
  data: SendConfirmData;
  actions: ToolAction[];
  onAction: (id: string) => void;
}

const POLICY_LABEL: Record<SendConfirmData["policy"], string> = {
  dry_run: "Dry run",
  allowlist: "Allowlisted",
  allow_all: "Allow all",
};

export default function SendConfirmCard({ data, actions, onAction }: Props) {
  const isImage = Boolean(data.image_path);
  const Icon = isImage ? ImageIcon : Send;
  const policyTone =
    data.policy === "allow_all"
      ? "text-warn"
      : data.policy === "dry_run"
        ? "text-fg-muted"
        : "text-accent";

  return (
    <div className="rounded-card border border-border bg-bg-card p-4 shadow-sm">
      <div className="flex items-start gap-3">
        <Icon className="mt-0.5 size-5 text-accent" aria-hidden />
        <div className="flex-1">
          <div className="flex items-baseline justify-between gap-3">
            <h3 className="text-sm font-medium">
              {data.delivered
                ? "Sent"
                : data.needs_approval
                  ? "Awaiting your approval"
                  : "Send drafted"}
            </h3>
            <span className={`text-xs ${policyTone}`}>{POLICY_LABEL[data.policy]}</span>
          </div>
          <p className="mt-1 font-mono text-xs text-fg-muted">to {data.recipient_masked}</p>
          <p className="mt-2 whitespace-pre-wrap rounded-card bg-bg-app p-2.5 text-sm">
            {isImage ? <em className="text-fg-muted">[image] </em> : null}
            {data.body_preview || data.caption_preview || (
              <span className="text-fg-muted">(no body)</span>
            )}
          </p>
          {data.policy === "allow_all" && data.needs_approval && (
            <p className="mt-2 inline-flex items-center gap-1.5 text-xs text-warn">
              <ShieldAlert className="size-3.5" aria-hidden /> Allow-all bypasses the recipient guard.
            </p>
          )}
          {actions.length > 0 && (
            <div className="mt-3 flex gap-2">
              {actions.map((a) => (
                <button
                  key={a.id}
                  onClick={() => onAction(a.id)}
                  className={
                    a.id === "approve"
                      ? "rounded-pill bg-accent px-3 py-1.5 text-xs font-medium text-accent-fg hover:opacity-90"
                      : "rounded-pill border border-border px-3 py-1.5 text-xs hover:bg-bg-app"
                  }
                >
                  {a.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
