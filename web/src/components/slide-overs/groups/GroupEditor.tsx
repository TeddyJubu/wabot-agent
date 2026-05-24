import { useEffect, useState } from "react";
import {
  fetchGroupInvite,
  leaveGroup,
  removeGroupPicture,
  setGroupPicture,
  updateGroup,
  updateGroupParticipants,
} from "@/api/groups";
import type { GroupDetail } from "@/api/groups";
import { ConfirmDialog } from "@/components/ConfirmDialog";

function parsePhones(raw: string): string[] {
  return raw
    .split(/[\n,;]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

interface Props {
  group: GroupDetail;
  jid: string;
  busy?: boolean;
  setBusy: (busy: boolean) => void;
  onMutate: () => void | Promise<void>;
  onError: (message: string) => void;
  onLeft: () => void;
}

export function GroupEditor({
  group,
  jid,
  busy,
  setBusy,
  onMutate,
  onError,
  onLeft,
}: Props) {
  const [editName, setEditName] = useState(group.name ?? "");
  const [editTopic, setEditTopic] = useState(group.topic ?? "");
  const [memberPhones, setMemberPhones] = useState("");
  const [inviteLink, setInviteLink] = useState<string | null>(null);
  const [confirmRemovePhotoOpen, setConfirmRemovePhotoOpen] = useState(false);
  const [confirmLeaveOpen, setConfirmLeaveOpen] = useState(false);

  // Keep local edits in sync if the parent reloads a different detail.
  useEffect(() => {
    setEditName(group.name ?? "");
    setEditTopic(group.topic ?? "");
    setInviteLink(null);
  }, [group]);

  /**
   * Run a side-effectful action and let the parent refetch by default.
   * Pass `{ mutate: false }` for read-only operations (e.g. fetching the
   * invite link) — without that guard, `onMutate()` would re-fetch the
   * detail and `useEffect` above would reset `inviteLink` to null, making
   * the link flicker / disappear after click.
   */
  async function run(
    action: () => Promise<void>,
    opts?: { mutate?: boolean },
  ) {
    setBusy(true);
    try {
      await action();
      if (opts?.mutate !== false) {
        await onMutate();
      }
    } catch (err) {
      onError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="space-y-2 rounded-card border border-border p-3">
      <p className="text-xs font-medium uppercase tracking-wider text-fg-muted">
        Manage {group.name || jid}
      </p>
      <p className="break-all font-mono text-[10px] text-fg-muted">{jid}</p>
      <input
        aria-label="Group name"
        className="w-full rounded-card border border-border bg-bg-app px-3 py-2 text-sm"
        placeholder="Group name"
        value={editName}
        onChange={(e) => setEditName(e.target.value)}
        disabled={busy}
      />
      <input
        aria-label="Description / topic"
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
            await updateGroup(jid, {
              name: editName.trim() || undefined,
              topic: editTopic.trim() || undefined,
            });
          })
        }
      >
        Save name & topic
      </button>
      <textarea
        aria-label="Phone numbers to add, remove, promote, or demote"
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
                  jid,
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
                await setGroupPicture(jid, file);
              });
            }}
          />
        </label>
        <button
          type="button"
          disabled={busy}
          className="rounded-pill border border-border px-3 py-1 text-xs"
          onClick={() => setConfirmRemovePhotoOpen(true)}
        >
          Remove photo
        </button>
        <button
          type="button"
          disabled={busy}
          className="rounded-pill border border-border px-3 py-1 text-xs"
          onClick={() =>
            void run(
              async () => {
                const res = await fetchGroupInvite(jid, false);
                setInviteLink(res.invite_link ?? null);
              },
              { mutate: false },
            )
          }
        >
          Invite link
        </button>
        <button
          type="button"
          disabled={busy}
          className="rounded-pill border border-border px-3 py-1 text-xs"
          onClick={() => setConfirmLeaveOpen(true)}
        >
          Leave group
        </button>
      </div>
      {inviteLink && (
        <p className="break-all rounded-card bg-bg-card p-2 text-xs text-fg-muted">
          {inviteLink}
        </p>
      )}

      <ConfirmDialog
        open={confirmRemovePhotoOpen}
        title="Remove profile photo?"
        description="The group will revert to the default avatar on the linked device."
        confirmLabel="Remove photo"
        variant="danger"
        onConfirm={() => {
          setConfirmRemovePhotoOpen(false);
          void run(async () => {
            await removeGroupPicture(jid);
          });
        }}
        onCancel={() => setConfirmRemovePhotoOpen(false)}
      />

      <ConfirmDialog
        open={confirmLeaveOpen}
        title="Leave this group?"
        description="You'll be removed from the group on the linked device."
        confirmLabel="Leave group"
        variant="danger"
        onConfirm={() => {
          setConfirmLeaveOpen(false);
          void run(async () => {
            await leaveGroup(jid);
            onLeft();
          });
        }}
        onCancel={() => setConfirmLeaveOpen(false)}
      />
    </section>
  );
}
