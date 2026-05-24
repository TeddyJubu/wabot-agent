import { useState } from "react";
import { createGroup } from "@/api/groups";

function parsePhones(raw: string): string[] {
  return raw
    .split(/[\n,;]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

interface Props {
  busy?: boolean;
  onCreated: () => void | Promise<void>;
  onError: (message: string) => void;
  setBusy: (busy: boolean) => void;
}

export function GroupCreateForm({ busy, onCreated, onError, setBusy }: Props) {
  const [name, setName] = useState("");
  const [members, setMembers] = useState("");

  async function submit() {
    setBusy(true);
    try {
      await createGroup(name.trim(), parsePhones(members));
      setName("");
      setMembers("");
      await onCreated();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="space-y-2 rounded-card border border-border p-3">
      <p className="text-xs font-medium uppercase tracking-wider text-fg-muted">
        Create group
      </p>
      <input
        className="w-full rounded-card border border-border bg-bg-app px-3 py-2 text-sm"
        placeholder="Group name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        disabled={busy}
      />
      <textarea
        className="w-full rounded-card border border-border bg-bg-app px-3 py-2 text-sm"
        placeholder="Members (+65…, one per line)"
        rows={2}
        value={members}
        onChange={(e) => setMembers(e.target.value)}
        disabled={busy}
      />
      <button
        type="button"
        disabled={busy || !name.trim()}
        className="rounded-pill bg-accent px-4 py-1.5 text-xs font-medium text-bg-app disabled:opacity-50"
        onClick={() => void submit()}
      >
        Create
      </button>
    </section>
  );
}
