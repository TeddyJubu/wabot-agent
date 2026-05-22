import { useCallback, useEffect, useRef, useState } from "react";

import {
  cancelCodexDeviceLogin,
  disconnectCodexLogin,
  fetchCodexLogin,
  startCodexDeviceLogin,
  type CodexLoginView,
} from "@/api/codex";

interface UseCodexLoginOptions {
  /** When false, any in-flight poll is cancelled and refresh stops. */
  active: boolean;
  /** Called when sign-in succeeds (parent typically refetches /api/settings). */
  onLoginComplete?: () => void;
  /** Called when ChatGPT is disconnected (parent typically refetches). */
  onDisconnect?: () => void;
  /** Called with human-readable status messages — bubbled into the parent's status line. */
  onStatus?: (message: string) => void;
}

interface UseCodexLoginResult {
  codexLogin: CodexLoginView | null;
  busy: boolean;
  refresh: () => Promise<CodexLoginView | null>;
  startLogin: () => Promise<void>;
  cancelLogin: () => Promise<void>;
  disconnect: () => Promise<void>;
}

const POLL_INTERVAL_MS = 2000;

/**
 * Owns the ChatGPT / Codex device-login dance. Carved out of `SettingsPanel.tsx`
 * as part of MASTER ME-6 so the dashboard's settings UI can be split into
 * per-provider sections without each section reaching back into the parent for
 * polling state.
 *
 * What this hook does:
 *   - tracks the current `CodexLoginView` snapshot from the server
 *   - exposes `busy` so the section's buttons can disable themselves
 *   - starts a 2-second poll after `startLogin()` and stops it on
 *     completion, failure, cancel, disconnect, or when `active` flips false
 *     (e.g. operator switches to another provider)
 *
 * What this hook does NOT do:
 *   - own the page's status string (caller passes `onStatus`)
 *   - refetch `/api/settings` (caller passes `onLoginComplete` / `onDisconnect`
 *     — keeps the hook independent of the parent's data model)
 */
export function useCodexLogin({
  active,
  onLoginComplete,
  onDisconnect,
  onStatus,
}: UseCodexLoginOptions): UseCodexLoginResult {
  const [codexLogin, setCodexLogin] = useState<CodexLoginView | null>(null);
  const [busy, setBusy] = useState(false);
  const pollRef = useRef<number | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const refresh = useCallback(async (): Promise<CodexLoginView | null> => {
    try {
      const next = await fetchCodexLogin();
      setCodexLogin(next);
      return next;
    } catch {
      return null;
    }
  }, []);

  const startLogin = useCallback(async () => {
    setBusy(true);
    onStatus?.("Starting ChatGPT sign-in…");
    try {
      const next = await startCodexDeviceLogin();
      setCodexLogin(next);
      stopPolling();
      pollRef.current = window.setInterval(() => {
        void refresh().then((view) => {
          if (!view) return;
          if (view.session.status === "complete" || view.logged_in) {
            stopPolling();
            setCodexLogin(view);
            onStatus?.("ChatGPT sign-in complete.");
            onLoginComplete?.();
          } else if (view.session.status === "failed" && !view.logged_in) {
            stopPolling();
            setCodexLogin(view);
            onStatus?.(view.session.detail ?? "Sign-in failed.");
          }
        });
      }, POLL_INTERVAL_MS);
    } catch (err) {
      onStatus?.(`Sign-in error: ${String(err)}`);
    } finally {
      setBusy(false);
    }
  }, [onLoginComplete, onStatus, refresh, stopPolling]);

  const cancelLogin = useCallback(async () => {
    setBusy(true);
    try {
      const next = await cancelCodexDeviceLogin();
      setCodexLogin(next);
      stopPolling();
      onStatus?.("Sign-in cancelled.");
    } finally {
      setBusy(false);
    }
  }, [onStatus, stopPolling]);

  const disconnect = useCallback(async () => {
    if (
      !window.confirm(
        "Disconnect this ChatGPT subscription from the bot? You can sign in again with a different account afterward.",
      )
    ) {
      return;
    }
    setBusy(true);
    onStatus?.("Disconnecting ChatGPT…");
    try {
      const next = await disconnectCodexLogin();
      setCodexLogin(next);
      stopPolling();
      onDisconnect?.();
      onStatus?.("ChatGPT disconnected.");
    } catch (err) {
      onStatus?.(`Disconnect error: ${String(err)}`);
    } finally {
      setBusy(false);
    }
  }, [onDisconnect, onStatus, stopPolling]);

  useEffect(() => {
    if (!active) {
      stopPolling();
      return;
    }
    void refresh();
    return () => {
      stopPolling();
    };
  }, [active, refresh, stopPolling]);

  return { codexLogin, busy, refresh, startLogin, cancelLogin, disconnect };
}
