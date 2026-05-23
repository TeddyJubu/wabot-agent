export interface SlashCommand {
  name: string;
  description: string;
  /** Expand into either a chat message or a sentinel ("__open_slide_over__:<id>"). */
  expand: () => string;
}

export const SLASH_COMMANDS: SlashCommand[] = [
  {
    name: "/qr",
    description: "Open WhatsApp pairing QR",
    expand: () => "__open_slide_over__:qr",
  },
  {
    name: "/runs",
    description: "Open recent runs",
    expand: () => "__open_slide_over__:runs",
  },
  {
    name: "/groups",
    description: "Open WhatsApp groups",
    expand: () => "__open_slide_over__:groups",
  },
  {
    name: "/settings",
    description: "Open settings",
    expand: () => "__open_slide_over__:settings",
  },
  {
    name: "/policy",
    description: "Open settings (send policy)",
    expand: () => "__open_slide_over__:settings",
  },
  {
    name: "/knowledge",
    description: "Open knowledge editor",
    expand: () => "__open_knowledge__",
  },
];

export function matchSlash(input: string): SlashCommand[] {
  if (!input.startsWith("/")) return [];
  const q = input.slice(1).toLowerCase();
  if (q.length === 0) return SLASH_COMMANDS;
  return SLASH_COMMANDS.filter((c) => c.name.slice(1).toLowerCase().startsWith(q));
}
