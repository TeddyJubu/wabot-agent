/** Mirrors backend truncate_for_prompt for UI hints. */
export function truncateForPrompt(text: string, maxChars: number): string {
  const stripped = text.trim();
  if (!stripped) return "";
  if (stripped.length <= maxChars) return stripped;
  const suffix = "… [truncated]";
  const keep = Math.max(0, maxChars - suffix.length);
  return stripped.slice(0, keep).trimEnd() + suffix;
}
