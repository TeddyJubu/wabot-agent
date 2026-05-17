import {
  SignedIn,
  SignedOut,
  SignInButton,
  SignUpButton,
  UserButton,
} from "@clerk/clerk-react";
import clsx from "clsx";

const clerkEnabled = Boolean(import.meta.env.VITE_CLERK_PUBLISHABLE_KEY);

interface ClerkNavAuthProps {
  /** Extra classes for the outer wrapper (e.g. borders in the top bar). */
  className?: string;
}

/**
 * Sign in / sign up / user menu. Renders nothing when `VITE_CLERK_PUBLISHABLE_KEY` is unset.
 */
export function ClerkNavAuth({ className }: ClerkNavAuthProps) {
  if (!clerkEnabled) return null;

  return (
    <div className={clsx("flex items-center gap-0.5", className)}>
      <SignedOut>
        <SignInButton mode="modal">
          <button
            type="button"
            className="rounded-pill px-2.5 py-1.5 text-sm font-medium text-fg-muted transition hover:bg-bg-card hover:text-fg"
          >
            Sign in
          </button>
        </SignInButton>
        <SignUpButton mode="modal">
          <button
            type="button"
            className="rounded-pill px-2.5 py-1.5 text-sm font-semibold text-fg transition hover:bg-bg-card"
          >
            Sign up
          </button>
        </SignUpButton>
      </SignedOut>
      <SignedIn>
        <UserButton
          appearance={{
            elements: {
              avatarBox: "size-9 ring-1 ring-border",
            },
          }}
        />
      </SignedIn>
    </div>
  );
}
