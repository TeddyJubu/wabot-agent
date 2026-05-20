import { useCallback, useEffect, useState } from "react";
import {
  createGroup,
  fetchGroup,
  fetchGroupInvite,
  fetchGroups,
  joinGroup,
  leaveGroup,
  removeGroupPicture,
  setGroupPicture,
  updateGroup,
  updateGroupParticipants,
  type GroupDetail,
  type GroupSummary,
} from "@/api/groups";

function parsePhones(raw: string): string[] {
  return raw
    .split(/[\n,;]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

export default function GroupsPanel() {
  const [groups, setGroups] = useState<GroupSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<GroupDetail | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [inviteLink, setInviteLink] = useState<string | null>(null);

  const [createName, setCreateName] = useState("");
  const [createMembers, setCreateMembers] = useState("");
  const [joinLink, setJoinLink] = useState("");
  const [editName, setEditName] = useState("");
  const [editTopic, setEditTopic] = useState("");
  const [memberPhones, setMemberPhones] = useState("");

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

  async function loadDetail(jid: string) {
    setSelected(jid);
    setInviteLink(null);
    setError(null);
    try {
      const g = await fetchGroup(jid);
      setDetail(g);
      setEditName(g.name ?? "");
      setEditTopic(g.topic ?? "");
    } catch (err) {
      setDetail(null);
      setError(err instanceof Error ? err.message : "Could not load group");
    }
  }

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await reload();
      if (selected) await loadDetail(selected);
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

      <section className="space-y-2 rounded-card border border-border p-3">
        <p className="text-xs font-medium uppercase tracking-wider text-fg-muted">
          Create group
        </p>
        <input
          className="w-full rounded-card border border-border bg-bg-app px-3 py-2 text-sm"
          placeholder="Group name"
          value={createName}
          onChange={(e) => setCreateName(e.target.value)}
          disabled={busy}
        />
        <textarea
          className="w-full rounded-card border border-border bg-bg-app px-3 py-2 text-sm"
          placeholder="Members (+65…, one per line)"
          rows={2}
          value={createMembers}
          onChange={(e) => setCreateMembers(e.target.value)}
          disabled={busy}
        />
        <button
          type="button"
          disabled={busy || !createName.trim()}
          className="rounded-pill bg-accent px-4 py-1.5 text-xs font-medium text-bg-app disabled:opacity-50"
          onClick={() =>
            void run(async () => {
              await createGroup(createName.trim(), parsePhones(createMembers));
              setCreateName("");
              setCreateMembers("");
            })
          }
        >
          Create
        </button>
      </section>

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
          onClick={() =>
            void run(async () => {
              await joinGroup(joinLink.trim());
              setJoinLink("");
            })
          }
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

      <ul className="max-h-40 space-y-1 overflow-y-auto">
        {groups.map((g) => (
          <li key={g.jid}>
            <button
              type="button"
              disabled={busy}
              onClick={() => void loadDetail(g.jid)}
              className={`w-full rounded-card border px-3 py-2 text-left text-xs transition ${
                selected === g.jid
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

      {detail && selected && (
        <section className="space-y-2 rounded-card border border-border p-3">
          <p className="text-xs font-medium uppercase tracking-wider text-fg-muted">
            Manage {detail.name || selected}
          </p>
          <p className="break-all font-mono text-[10px] text-fg-muted">{selected}</p>
          <input
            className="w-full rounded-card border border-border bg-bg-app px-3 py-2 text-sm"
            placeholder="Group name"
            value={editName}
            onChange={(e) => setEditName(e.target.value)}
            disabled={busy}
          />
          <input
            className="w-full rounded-card border border-border bg-bg-app px-3 py-2 text-sm"
            placeholder="Description / topic"
            value={editTopic}
            onChange={(e) => setEditTopic(e.target.value)}
            disabled={busy}
          />
          <button
            type="button"
            disabled={busy}
            className="w-full rounded-pill border border-border px-3 py-1.5 text-xs"
            onClick={() =>
              void run(async () => {
                await updateGroup(selected, {
                  name: editName.trim() || undefined,
                  topic: editTopic.trim() || undefined,
                });
              })
            }
          >
            Save name & topic
          </button>
          <textarea
            className="w-full rounded-card border border-border bg-bg-app px-3 py-2 text-sm"
            placeholder="Phone numbers to add/remove"
            rows={2}
            value={memberPhones}
            onChange={(e) => setMemberPhones(e.target.value)}
            disabled={busy}
          />
          <div className="flex flex-wrap gap-2">
            {(["add", "remove", "promote", "demote"] as const).map((action) => (
              <button
                key={action}
                type="button"
                disabled={busy || !memberPhones.trim()}
                className="rounded-pill border border-border px-3 py-1 text-xs capitalize disabled:opacity-50"
                onClick={() =>
                  void run(async () => {
                    await updateGroupParticipants(
                      selected,
                      parsePhones(memberPhones),
                      action,
                    );
                    setMemberPhones("");
                  })
                }
              >
                {action}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label className="rounded-pill border border-border px-3 py-1 text-xs cursor-pointer">
              Set group photo
              <input
                type="file"
                accept="image/jpeg,image/png,image/webp"
                className="hidden"
                disabled={busy}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.target.value = "";
                  if (!file) return;
                  void run(async () => {
                    await setGroupPicture(selected, file);
                  });
                }}
              />
            </label>
            <button
              type="button"
              disabled={busy}
              className="rounded-pill border border-border px-3 py-1 text-xs"
              onClick={() =>
                void run(async () => {
                  if (!confirm("Remove this group's profile photo?")) return;
                  await removeGroupPicture(selected);
                })
              }
            >
              Remove photo
            </button>
            <button
              type="button"
              disabled={busy}
              className="rounded-pill border border-border px-3 py-1 text-xs"
              onClick={() =>
                void run(async () => {
                  const res = await fetchGroupInvite(selected, false);
                  setInviteLink(res.invite_link ?? null);
                })
              }
            >
              Invite link
            </button>
            <button
              type="button"
              disabled={busy}
              className="rounded-pill border border-border px-3 py-1 text-xs"
              onClick={() =>
                void run(async () => {
                  if (!confirm("Leave this group on the linked device?")) return;
                  await leaveGroup(selected);
                  setSelected(null);
                  setDetail(null);
                })
              }
            >
              Leave group
            </button>
          </div>
          {inviteLink && (
            <p className="break-all rounded-card bg-bg-card p-2 text-xs text-fg-muted">
              {inviteLink}
            </p>
          )}
        </section>
      )}
    </div>
  );
}
