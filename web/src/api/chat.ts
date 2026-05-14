import type { UiEnvelope } from "@/types/ui-envelope";

export type StreamEvent =
  | { type: "delta"; text: string }
  | { type: "tool_call"; name: string; args_redacted?: unknown; call_id?: string }
  | {
      type: "tool_result";
      ok: boolean;
      name?: string;
      call_id?: string;
      ui?: UiEnvelope;
      result?: unknown;
    }
  | {
      type: "final";
      run_id: string;
      session_id: string;
      output: string;
      live_model: boolean;
    }
  | { type: "error"; message: string };

export interface ChatStreamHandler {
  onEvent: (e: StreamEvent) => void;
  signal?: AbortSignal;
}

/**
 * POST /api/chat/stream and dispatch each NDJSON event to onEvent.
 * Resolves when the stream ends; rejects on network error.
 */
export async function postChatStream(
  message: string,
  { onEvent, signal }: ChatStreamHandler,
): Promise<void> {
  const res = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ message }),
    signal,
  });
  if (!res.ok || !res.body) {
    throw new Error(`chat stream failed: ${res.status}`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let nl: number;
    while ((nl = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, nl).trim();
      buffer = buffer.slice(nl + 1);
      if (!line) continue;
      try {
        onEvent(JSON.parse(line) as StreamEvent);
      } catch {
        /* malformed line — skip */
      }
    }
  }
  // Flush any buffered UTF-8 bytes the decoder held back on chunk
  // boundaries; without this the trailing event can be truncated when
  // the final JSON line straddles two read() chunks or the connection
  // ends mid-codepoint.
  buffer += decoder.decode();
  const tail = buffer.trim();
  if (tail) {
    try {
      onEvent(JSON.parse(tail) as StreamEvent);
    } catch {
      /* skip */
    }
  }
}
