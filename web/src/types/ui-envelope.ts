export type ToolKind =
  | "wabot_status"
  | "pairing_qr"
  | "send_confirm"
  | "memory"
  | "inbox_message";

export interface ToolAction {
  id: string;
  label: string;
  tool: string | null;
  args: Record<string, unknown>;
}

export interface UiEnvelope {
  kind: ToolKind;
  data: Record<string, unknown>;
  actions: ToolAction[];
}

export interface WabotStatusData {
  status: "ok" | "warn" | "bad";
  version?: string;
  uptime_s?: number;
  last_seen_s?: number;
  error?: string;
}

export interface PairingQrData {
  available: boolean;
  linked_device?: string | null;
}

export interface SendConfirmData {
  policy: "dry_run" | "allowlist" | "allow_all";
  recipient_masked: string;
  body_preview: string;
  needs_approval: boolean;
  delivered: boolean;
  image_path?: string;
  caption_preview?: string;
}

export interface MemoryFact {
  id: string;
  text: string;
}

export interface MemoryData {
  contact_masked: string;
  facts: MemoryFact[];
}

export interface InboxPreviewMessage {
  sender: string;
  text: string;
}

export interface InboxMessageData {
  count: number;
  found: boolean;
  messages: InboxPreviewMessage[];
  source?: string;
}
