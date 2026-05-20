export interface SlashCommand {
  name: string;
  description: string;
  /** Expand into either a chat message or a sentinel ("__open_slide_over__:<id>"). */
  expand: () => string;
}

export const SLASH_COMMANDS: SlashCommand[] = [
  {
    name: "/qr",
    description: "Show the WhatsApp pairing QR",
    expand: () => "show me the WhatsApp pairing QR",
  },
  {
    name: "/skills",
    description: "List local skills",
    expand: () => "list local skills",
  },
  {
    name: "/runs",
    description: "Open recent runs",
    expand: () => "__open_slide_over__:runs",
  },
  {
    name: "/settings",
    description: "Open settings",
    expand: () => "__open_slide_over__:settings",
  },
  {
    name: "/knowledge",
    description: "Open knowledge editor",
    expand: () => "__open_knowledge__",
  },
  {
    name: "/policy",
    description: "Show current send policy",
    expand: () => "what is the current send policy and allowed recipients?",
  },
  {
    name: "/health",
    description: "Check wabot daemon health",
    expand: () => "is wabot healthy? run wabot_health.",
  },
];

export function matchSlash(input: string): SlashCommand[] {
  if (!input.startsWith("/")) return [];
  const q = input.slice(1).toLowerCase();
  if (q.length === 0) return SLASH_COMMANDS;
  return SLASH_COMMANDS.filter((c) => c.name.slice(1).toLowerCase().startsWith(q));
}
