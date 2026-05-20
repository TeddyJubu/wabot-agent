export interface GroupSummary {
  jid: string;
  name?: string;
  participant_count?: number;
  announce?: boolean;
  locked?: boolean;
  created_at?: string;
}

export interface GroupParticipant {
  jid: string;
  is_admin?: boolean;
  is_super?: boolean;
}

export interface GroupDetail {
  jid: string;
  name?: string;
  topic?: string;
  participant_count?: number;
  announce?: boolean;
  locked?: boolean;
  created_at?: string;
  participants?: GroupParticipant[];
}

async function parseJson<T>(res: Response): Promise<T> {
  const body = (await res.json().catch(() => ({}))) as T & { detail?: string };
  if (!res.ok) {
    throw new Error(
      typeof body.detail === "string" ? body.detail : `Request failed (${res.status})`,
    );
  }
  return body;
}

export async function fetchGroups(): Promise<GroupSummary[]> {
  const res = await fetch("/api/whatsapp/groups", { credentials: "include" });
  const data = await parseJson<{ groups?: GroupSummary[] }>(res);
  return data.groups ?? [];
}

export async function fetchGroup(jid: string): Promise<GroupDetail> {
  const res = await fetch(`/api/whatsapp/groups/${encodeURIComponent(jid)}`, {
    credentials: "include",
  });
  const data = await parseJson<{ group?: GroupDetail; ok?: boolean }>(res);
  return data.group ?? (data as unknown as GroupDetail);
}

export async function createGroup(
  name: string,
  participants: string[],
): Promise<Record<string, unknown>> {
  const res = await fetch("/api/whatsapp/groups", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, participants }),
  });
  return parseJson(res);
}

export async function updateGroup(
  jid: string,
  patch: { name?: string; topic?: string; announce?: boolean; locked?: boolean },
): Promise<Record<string, unknown>> {
  const res = await fetch(`/api/whatsapp/groups/${encodeURIComponent(jid)}`, {
    method: "PATCH",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  return parseJson(res);
}

export async function updateGroupParticipants(
  jid: string,
  participants: string[],
  action: "add" | "remove" | "promote" | "demote",
): Promise<Record<string, unknown>> {
  const res = await fetch(
    `/api/whatsapp/groups/${encodeURIComponent(jid)}/participants`,
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ participants, action }),
    },
  );
  return parseJson(res);
}

export async function fetchGroupInvite(
  jid: string,
  reset = false,
): Promise<{ invite_link?: string }> {
  const res = await fetch(`/api/whatsapp/groups/${encodeURIComponent(jid)}/invite`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reset }),
  });
  return parseJson(res);
}

export async function joinGroup(inviteLink: string): Promise<Record<string, unknown>> {
  const res = await fetch("/api/whatsapp/groups/join", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ invite_link: inviteLink }),
  });
  return parseJson(res);
}

export async function leaveGroup(jid: string): Promise<Record<string, unknown>> {
  const res = await fetch(`/api/whatsapp/groups/${encodeURIComponent(jid)}/leave`, {
    method: "POST",
    credentials: "include",
  });
  return parseJson(res);
}

export async function setGroupPicture(
  jid: string,
  file: File,
): Promise<Record<string, unknown>> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`/api/whatsapp/groups/${encodeURIComponent(jid)}/picture`, {
    method: "POST",
    credentials: "include",
    body: form,
  });
  return parseJson(res);
}

export async function removeGroupPicture(jid: string): Promise<Record<string, unknown>> {
  const res = await fetch(`/api/whatsapp/groups/${encodeURIComponent(jid)}/picture`, {
    method: "DELETE",
    credentials: "include",
  });
  return parseJson(res);
}
