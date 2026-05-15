import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import PairView from "./components/PairView";
import "./styles.css";

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
  return <App />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>{selectRoot()}</StrictMode>,
);
