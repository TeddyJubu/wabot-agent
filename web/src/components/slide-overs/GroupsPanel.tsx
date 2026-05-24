import { useCallback, useEffect, useState } from "react";
import {
  fetchGroup,
  fetchGroups,
  joinGroup,
  type GroupDetail,
  type GroupSummary,
} from "@/api/groups";
import { GroupCreateForm } from "./groups/GroupCreateForm";
import { GroupEditor } from "./groups/GroupEditor";
import { GroupList } from "./groups/GroupList";

export default function GroupsPanel() {
  const [groups, setGroups] = useState<GroupSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<GroupDetail | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [joinLink, setJoinLink] = useState("");

  const reload = useCallback(async () => {
    setState("loading");
    setError(null);
    try {
      setGroups(await fetchGroups());
      setState("ready");
    } catch (err) {
      setState("error");
      setError(err instanceof Error ? err.message : "Could not load groups");
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const loadDetail = useCallback(async (jid: string) => {
    setSelected(jid);
    setError(null);
    try {
      const g = await fetchGroup(jid);
      setDetail(g);
    } catch (err) {
      setDetail(null);
      setError(err instanceof Error ? err.message : "Could not load group");
    }
  }, []);

  const refreshAll = useCallback(async () => {
    await reload();
    if (selected) await loadDetail(selected);
  }, [reload, loadDetail, selected]);

  async function joinViaInvite() {
    setBusy(true);
    setError(null);
    try {
      await joinGroup(joinLink.trim());
      setJoinLink("");
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4 text-sm">
      {state === "loading" && <p className="text-xs text-fg-muted">Loading groups…</p>}
      {state === "error" && !groups.length && (
        <p className="text-xs text-bad">{error ?? "Could not load groups."}</p>
      )}
      {error && state === "ready" && (
        <p className="rounded-card border border-bad/40 bg-bad/10 px-3 py-2 text-xs text-bad">
          {error}
        </p>
      )}

      <GroupCreateForm
        busy={busy}
        setBusy={setBusy}
        onCreated={refreshAll}
        onError={setError}
      />

      <section className="space-y-2 rounded-card border border-border p-3">
        <p className="text-xs font-medium uppercase tracking-wider text-fg-muted">
          Join via invite
        </p>
        <input
          className="w-full rounded-card border border-border bg-bg-app px-3 py-2 text-sm"
          placeholder="https://chat.whatsapp.com/…"
          value={joinLink}
          onChange={(e) => setJoinLink(e.target.value)}
          disabled={busy}
        />
        <button
          type="button"
          disabled={busy || !joinLink.trim()}
          className="rounded-pill border border-border px-4 py-1.5 text-xs disabled:opacity-50"
          onClick={() => void joinViaInvite()}
        >
          Join
        </button>
      </section>

      <div className="flex items-center justify-between">
        <p className="text-xs font-medium uppercase tracking-wider text-fg-muted">
          Your groups ({groups.length})
        </p>
        <button
          type="button"
          className="text-xs text-accent"
          disabled={busy}
          onClick={() => void reload()}
        >
          Refresh
        </button>
      </div>

      <GroupList
        groups={groups}
        selectedJid={selected}
        busy={busy}
        onSelect={(jid) => void loadDetail(jid)}
      />

      {detail && selected && (
        <GroupEditor
          group={detail}
          jid={selected}
          busy={busy}
          setBusy={setBusy}
          onMutate={refreshAll}
          onError={setError}
          onLeft={() => {
            setSelected(null);
            setDetail(null);
          }}
        />
      )}
    </div>
  );
}
