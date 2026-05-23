import { useEffect, useState } from "react";
import { listSkills, type SkillRow } from "@/api/skills";
import { listMcpServers, type McpServerRow } from "@/api/mcp";
import { SkillsSection } from "./integrations/SkillsSection";
import { McpServersSection } from "./integrations/McpServersSection";

export default function IntegrationsPanel() {
  const [skills, setSkills] = useState<SkillRow[]>([]);
  const [servers, setServers] = useState<McpServerRow[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void load();
  }, []);

  async function load() {
    setState("loading");
    setError(null);
    try {
      const [s, m] = await Promise.all([listSkills(), listMcpServers()]);
      setSkills(s);
      setServers(m);
      setState("ready");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load integrations");
      setState("error");
    }
  }

  async function refreshSkills() {
    try {
      const s = await listSkills();
      setSkills(s);
    } catch {
      // silently ignore — skills section surfaces its own errors
    }
  }

  async function refreshServers() {
    try {
      const m = await listMcpServers();
      setServers(m);
    } catch {
      // silently ignore
    }
  }

  return (
    <div className="space-y-6">
      {state === "loading" && (
        <p className="text-xs text-fg-muted">Loading integrations…</p>
      )}

      {state === "error" && error && (
        <p className="rounded-card border border-bad/40 bg-bad/10 px-3 py-2 text-xs text-bad">
          {error}
        </p>
      )}

      {state === "ready" && (
        <>
          <SkillsSection skills={skills} onRefresh={() => void refreshSkills()} />
          <McpServersSection servers={servers} onRefresh={() => void refreshServers()} />
        </>
      )}
    </div>
  );
}
