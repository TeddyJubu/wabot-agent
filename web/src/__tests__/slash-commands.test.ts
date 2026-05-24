import { describe, it, expect } from "vitest";
import { SLASH_COMMANDS, matchSlash } from "@/hooks/useSlashCommands";

describe("SLASH_COMMANDS table", () => {
  it("/qr expands to the __open_pair__ sentinel (routes to /pair, not a slide-over)", () => {
    const qr = SLASH_COMMANDS.find((c) => c.name === "/qr");
    expect(qr).toBeDefined();
    expect(qr!.expand()).toBe("__open_pair__");
  });
});

describe("matchSlash()", () => {
  it("matchSlash('/qr') returns exactly the /qr command", () => {
    const matches = matchSlash("/qr");
    expect(matches).toHaveLength(1);
    expect(matches[0]?.name).toBe("/qr");
    expect(matches[0]?.expand()).toBe("__open_pair__");
  });

  it("matchSlash('/') returns every registered command", () => {
    const matches = matchSlash("/");
    expect(matches).toEqual(SLASH_COMMANDS);
  });
});
