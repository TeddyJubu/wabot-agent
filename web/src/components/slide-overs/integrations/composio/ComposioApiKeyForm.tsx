import { useState } from "react";
import { setComposioApiKey, type ComposioStatus } from "@/api/composio";

interface Props {
  onSaved: (status: ComposioStatus) => void;
  onCancel?: () => void;
}

export function ComposioApiKeyForm({ onSaved, onCancel }: Props) {
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isValid = value.length >= 8 && value.length <= 200;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!isValid) return;
    setSaving(true);
    setError(null);
    try {
      const status = await setComposioApiKey(value);
      setValue("");
      onSaved(status);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save API key");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={(e) => void handleSubmit(e)} className="space-y-2">
      <div className="space-y-1">
        <label htmlFor="composio-api-key" className="text-[10px] text-fg-muted">
          Composio API key
        </label>
        <input
          id="composio-api-key"
          type="password"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Paste your Composio API key"
          autoComplete="off"
          className="w-full rounded-card border border-border bg-bg-app px-3 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-border"
        />
        <p className="text-right text-[9px] text-fg-muted">
          {value.length}/200
        </p>
      </div>

      {error && (
        <p className="rounded-card border border-bad/40 bg-bad/10 px-3 py-2 text-xs text-bad">
          {error}
        </p>
      )}

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={!isValid || saving}
          aria-label="Save API key"
          className="rounded-pill border border-border px-2.5 py-1 text-xs hover:bg-bg-app disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save API key"}
        </button>
        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
            className="rounded-pill border border-border px-2.5 py-1 text-xs hover:bg-bg-app"
          >
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}
