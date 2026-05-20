import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { ClerkProvider } from "@clerk/clerk-react";
import App from "./App";
import PairView from "./components/PairView";
import KnowledgePage from "./pages/KnowledgePage";
import "./styles.css";

const clerkPublishableKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY;

if (!clerkPublishableKey && import.meta.env.DEV) {
  console.warn(
    "[clerk] Set VITE_CLERK_PUBLISHABLE_KEY in web/.env to enable sign-in and the user menu.",
  );
}

/**
 * Path-based root selection. The FastAPI service serves the same
 * `index.html` at both `/` and `/pair`, so the React app picks which
 * top-level component to render based on `window.location.pathname`.
 *
 * Note: we don't ship a client-side router. The /pair page is read-only
 * (no internal navigation), and the dashboard handles its own state via
 * Zustand without URL changes. If we ever need real routing, swap this
 * for `react-router-dom`.
 */
function selectRoot() {
  const path = window.location.pathname.replace(/\/+$/, "");
  if (path === "/pair") return <PairView />;
  if (path === "/knowledge") return <KnowledgePage />;
  return <App />;
}

const app = <StrictMode>{selectRoot()}</StrictMode>;

createRoot(document.getElementById("root")!).render(
  clerkPublishableKey ? (
    <ClerkProvider
      publishableKey={clerkPublishableKey}
      appearance={{
        variables: {
          colorPrimary: "hsl(262 83% 58%)",
          borderRadius: "9999px",
        },
      }}
    >
      {app}
    </ClerkProvider>
  ) : (
    app
  ),
);
