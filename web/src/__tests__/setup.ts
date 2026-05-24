import "@testing-library/jest-dom/vitest";
import { expect } from "vitest";
import { toHaveNoViolations } from "jest-axe";

expect.extend(toHaveNoViolations);

// ---------------------------------------------------------------------------
// Node 22+ ships an experimental built-in `localStorage` that's gated behind
// `--localstorage-file=<path>` and otherwise exposes the global as `undefined`.
// jsdom in this version doesn't supply its own shim, so test code that does
// `localStorage.clear()` / `getItem()` / `setItem()` blows up with
// "Cannot read properties of undefined (reading 'clear')".
//
// Fix: inject a minimal in-memory Storage implementation on both `globalThis`
// and `window`, replacing whatever broken accessor Node may have already
// defined. This is the same approach Vitest itself recommends in its jsdom
// caveats. Backed by a Map so iteration order is deterministic.
// ---------------------------------------------------------------------------
function makeMemoryStorage(): Storage {
  const data = new Map<string, string>();
  return {
    get length() {
      return data.size;
    },
    clear() {
      data.clear();
    },
    getItem(key: string) {
      return data.has(key) ? data.get(key)! : null;
    },
    setItem(key: string, value: string) {
      data.set(key, String(value));
    },
    removeItem(key: string) {
      data.delete(key);
    },
    key(index: number) {
      return Array.from(data.keys())[index] ?? null;
    },
  };
}

function installStorage(name: "localStorage" | "sessionStorage") {
  const instance = makeMemoryStorage();
  const targets: (typeof globalThis | (Window & typeof globalThis))[] = [
    globalThis,
  ];
  if (typeof window !== "undefined") targets.push(window);
  for (const target of targets) {
    try {
      // Overriding readonly lib.dom typings on purpose — we know better
      // than the types here because Node's accessor needs to be replaced.
      delete (target as unknown as Record<string, unknown>)[name];
    } catch {
      /* non-configurable Node accessor — defineProperty below still wins */
    }
    Object.defineProperty(target, name, {
      value: instance,
      writable: true,
      configurable: true,
    });
  }
}

installStorage("localStorage");
installStorage("sessionStorage");
