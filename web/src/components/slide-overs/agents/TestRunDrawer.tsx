import { useState } from "react";
import { testAgent, type AgentTestResponse } from "@/api/agents";

interface Props {
  slug: string;
  onClose: () => void;
}

export function TestRunDrawer({ slug, onClose }: Props) {
  const [prompt, setPrompt] = useState("");
  const [result, setResult] = useState<AgentTestResponse | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    if (!prompt.trim()) return;
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const res = await testAgent(slug, prompt.trim());
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Test run failed");
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium">Test run — {slug}</p>
        <button
          type="button"
          onClick={onClose}
          className="text-xs text-fg-muted hover:text-fg"
        >
          Close
        </button>
      </div>

      <textarea
        rows={4}
        placeholder="Enter a test prompt…"
        value={prompt}
        maxLength={8192}
        onChange={(e) => setPrompt(e.target.value)}
        disabled={running}
        className="w-full rounded-card border border-border bg-bg-app px-3 py-2 text-xs resize-none"
      />
      <p className={`text-right text-[10px] ${prompt.length >= 8000 ? "text-bad" : "text-fg-muted"}`}>
        {prompt.length} / 8192
      </p>

      <button
        type="button"
        disabled={running || !prompt.trim() || prompt.length > 8192}
        onClick={() => void run()}
        className="rounded-pill bg-accent px-3 py-1.5 text-xs font-medium text-accent-fg disabled:opacity-50"
      >
        {running ? "Running…" : "Run"}
      </button>

      {error && <p className="text-xs text-bad">{error}</p>}

      {result && (
        <div className="space-y-2">
          {result.error && (
            <p className="rounded-card border border-bad/40 bg-bad/10 px-3 py-2 text-xs text-bad">
              {result.error}
            </p>
          )}
          <div className="rounded-card border border-border bg-bg-app p-3 space-y-1">
            <p className="text-[10px] font-medium uppercase tracking-wider text-fg-muted">
              Transcript
            </p>
            <pre className="whitespace-pre-wrap text-xs text-fg">{result.transcript || "(empty)"}</pre>
          </div>
          {result.tool_calls.length > 0 && (
            <div className="rounded-card border border-border bg-bg-app p-3 space-y-1">
              <p className="text-[10px] font-medium uppercase tracking-wider text-fg-muted">
                Tool calls ({result.tool_calls.length})
              </p>
              {result.tool_calls.map((tc, i) => (
                <pre key={i} className="whitespace-pre-wrap text-[10px] text-fg-muted">
                  {JSON.stringify(tc, null, 2)}
                </pre>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
