type Policy = "dry_run" | "allowlist" | "allow_all" | "owner";

interface PolicySectionProps {
  policy: Policy;
  setPolicy: (p: Policy) => void;
  owners: string;
  setOwners: (v: string) => void;
  recipients: string;
  setRecipients: (v: string) => void;
}

const POLICY_CHOICES: readonly Policy[] = ["dry_run", "allowlist", "owner", "allow_all"];

/**
 * Send-policy chooser + owner numbers + extra allowlist. The "allow_all"
 * radio prompts for confirmation in the browser before flipping —
 * the server-side guard (``SettingsPatch.confirm_allow_all``) is the
 * real enforcement; this confirm() is just UX defense-in-depth.
 */
export function PolicySection({
  policy,
  setPolicy,
  owners,
  setOwners,
  recipients,
  setRecipients,
}: PolicySectionProps) {
  return (
    <fieldset className="space-y-2">
      <legend className="text-xs font-medium uppercase tracking-wider text-fg-muted">
        Send policy
      </legend>
      <div className="flex flex-wrap gap-2">
        {POLICY_CHOICES.map((p) => (
          <label
            key={p}
            className={`cursor-pointer rounded-pill border px-2.5 py-1 text-xs transition ${
              policy === p ? "border-accent bg-accent/10 text-accent" : "border-border"
            }`}
          >
            <input
              type="radio"
              name="policy"
              className="sr-only"
              checked={policy === p}
              onChange={() => {
                if (
                  p === "allow_all" &&
                  !window.confirm("Allow-all removes the recipient guard. Continue?")
                ) {
                  return;
                }
                setPolicy(p);
              }}
            />
            {p}
          </label>
        ))}
      </div>
      <label className="block">
        <span className="text-xs text-fg-muted">Owner numbers (owner policy)</span>
        <textarea
          rows={2}
          value={owners}
          onChange={(e) => setOwners(e.target.value)}
          placeholder="+6580286424"
          className="mt-1 w-full rounded-card border border-border bg-bg-card px-3 py-2 text-sm font-mono"
        />
      </label>
      <p className="text-xs text-fg-muted">
        With <span className="font-mono">owner</span> policy, the dashboard and these numbers may
        message anyone; other inbound chats can only reply in-thread.
      </p>
      <label className="block">
        <span className="text-xs text-fg-muted">Allowed recipients (optional extras)</span>
        <textarea
          rows={3}
          value={recipients}
          onChange={(e) => setRecipients(e.target.value)}
          placeholder="+15550001111, +15550002222"
          className="mt-1 w-full rounded-card border border-border bg-bg-card px-3 py-2 text-sm font-mono"
        />
      </label>
    </fieldset>
  );
}
