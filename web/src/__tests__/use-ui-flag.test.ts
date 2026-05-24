import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useUiFlag, useUiFlagStore } from "@/store/uiFlag";

function setSearch(search: string) {
  window.history.replaceState({}, "", search ? `/?${search.replace(/^\?/, "")}` : "/");
  useUiFlagStore.getState().resetUiFlagFromUrl();
}

beforeEach(() => {
  setSearch("");
});

describe("useUiFlag", () => {
  it("returns false when ?ui=v2 is absent", () => {
    setSearch("");
    const { result } = renderHook(() => useUiFlag());
    expect(result.current).toBe(false);
  });

  it("returns true when ?ui=v2 is present", () => {
    setSearch("ui=v2");
    const { result } = renderHook(() => useUiFlag());
    expect(result.current).toBe(true);
  });

  it("setUiFlag(false) flips the value", () => {
    setSearch("ui=v2");
    const { result } = renderHook(() => useUiFlag());
    expect(result.current).toBe(true);
    act(() => {
      useUiFlagStore.getState().setUiFlag(false);
    });
    expect(result.current).toBe(false);
  });
});
