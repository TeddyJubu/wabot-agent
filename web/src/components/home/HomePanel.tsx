import { Component, useMemo, useState } from "react";
import type { ErrorInfo, ReactNode } from "react";
import { useUser } from "@clerk/clerk-react";
import { useStore } from "@/store";
import SetupChecklist from "./SetupChecklist";
import DailyDigest from "./DailyDigest";

const DISMISSED_KEY = "wabot:dismissedChecklist";

/**
 * Home route for the v2 shell. Picks between the first-time
 * {@link SetupChecklist} and the repeat-use {@link DailyDigest} based on
 * three signals:
 *
 * - whether the user is signed in (Clerk),
 * - whether WhatsApp is paired,
 * - whether a model is configured + live.
 *
 * Users can dismiss the checklist via "Skip setup"; the choice is persisted
 * in localStorage so the checklist doesn't reappear on every page load.
 */
export default function HomePanel() {
  return (
    // Some tests mount <App /> without a ClerkProvider. `useUser` throws in
    // that case, so we wrap the Clerk-touching slice in an error boundary
    // that degrades gracefully to "signed out, no name".
    <ClerkBoundary fallback={<HomePanelInner isSignedIn={false} firstName={null} />}>
      <HomePanelWithClerk />
    </ClerkBoundary>
  );
}

function HomePanelWithClerk() {
  const { isSignedIn, user } = useUser();
  return (
    <HomePanelInner
      isSignedIn={isSignedIn === true}
      firstName={user?.firstName ?? null}
    />
  );
}

interface HomePanelInnerProps {
  isSignedIn: boolean;
  firstName: string | null;
}

function HomePanelInner({ isSignedIn, firstName }: HomePanelInnerProps) {
  const pairing = useStore((s) => s.pairing);
  const modelVariant = useStore((s) => s.readiness.model.variant);

  const [dismissed, setDismissed] = useState<boolean>(() => {
    try {
      return localStorage.getItem(DISMISSED_KEY) === "1";
    } catch {
      return false;
    }
  });

  const showChecklist = useMemo(() => {
    if (dismissed) return false;
    if (!isSignedIn) return true;
    if (!pairing?.logged_in) return true;
    if (modelVariant !== "ok") return true;
    return false;
  }, [dismissed, isSignedIn, pairing, modelVariant]);

  const greetingName = firstName ?? "there";

  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-lg font-semibold text-fg">
          Welcome back, {greetingName}.
        </h2>
        <p className="mt-1 text-sm text-fg-muted">
          {showChecklist
            ? "Let's finish wiring things up."
            : "Here's what your bot has been up to."}
        </p>
      </header>

      {showChecklist ? (
        <SetupChecklist
          isSignedIn={isSignedIn}
          onDismiss={() => {
            try {
              localStorage.setItem(DISMISSED_KEY, "1");
            } catch {
              // localStorage may be unavailable (private mode); silent skip
              // matches the rest of the app.
            }
            setDismissed(true);
          }}
        />
      ) : (
        <DailyDigest />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Local error boundary — narrow on purpose. Only wraps the Clerk-touching
// subtree so a missing ClerkProvider degrades to "signed out" instead of
// crashing the whole home surface.
// ---------------------------------------------------------------------------

interface ClerkBoundaryProps {
  fallback: ReactNode;
  children: ReactNode;
}

interface ClerkBoundaryState {
  hasError: boolean;
}

class ClerkBoundary extends Component<ClerkBoundaryProps, ClerkBoundaryState> {
  state: ClerkBoundaryState = { hasError: false };

  static getDerivedStateFromError(): ClerkBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(_error: Error, _info: ErrorInfo): void {
    // Swallow — the only error we expect here is "ClerkProvider missing"
    // and the fallback already covers that case.
  }

  render(): ReactNode {
    if (this.state.hasError) return this.props.fallback;
    return this.props.children;
  }
}
