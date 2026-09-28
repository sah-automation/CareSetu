// #578: the shared handoff navigation seam. Two verified-login flows host the
// same handoff screen, and both have to answer one question - when do we leave?
// - which is answered once, here: wait for the flow to be ready, hold a
// sub-second confirmation beat measured from that readiness, and leave exactly
// once. The screen's "Go to Dashboard" control can cut the beat short, but can
// never leave before readiness. This suite pins that rule once, at the rule's
// own level, so the partner login (#579) and the patient login (#580) each
// assert only their own wiring. Prior art is the shared profile-photo
// resolution hook's suite, which pins a shared hook's own lifecycle contract
// directly for the same reason.

import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  HANDOFF_MINIMUM_DWELL_MS,
  useHandoffNavigation,
} from "./useHandoffNavigation";

beforeEach(() => {
  // The rule is nothing but a scheduled delay, so only the timer is faked.
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

function advance(milliseconds: number): void {
  act(() => {
    vi.advanceTimersByTime(milliseconds);
  });
}

describe("useHandoffNavigation", () => {
  it("does nothing before the flow is ready, however long the wait", () => {
    const navigate = vi.fn();
    renderHook(() => useHandoffNavigation(false, navigate));

    advance(HANDOFF_MINIMUM_DWELL_MS * 10);
    expect(navigate).not.toHaveBeenCalled();
  });

  it("navigates once the minimum dwell has passed since the flow became ready", () => {
    const navigate = vi.fn();
    renderHook(() => useHandoffNavigation(true, navigate));

    advance(HANDOFF_MINIMUM_DWELL_MS - 1);
    expect(navigate).not.toHaveBeenCalled();

    advance(1);
    expect(navigate).toHaveBeenCalledTimes(1);
  });

  it("skips the minimum dwell when the caller asks to go", () => {
    const navigate = vi.fn();
    const { result } = renderHook(() => useHandoffNavigation(true, navigate));

    act(() => {
      result.current();
    });
    expect(navigate).toHaveBeenCalledTimes(1);

    advance(HANDOFF_MINIMUM_DWELL_MS * 3);
    expect(navigate).toHaveBeenCalledTimes(1);
  });

  it("will not honour the caller's ask before the flow is ready", () => {
    const navigate = vi.fn();
    const { result } = renderHook(() => useHandoffNavigation(false, navigate));

    act(() => {
      result.current();
    });
    advance(HANDOFF_MINIMUM_DWELL_MS * 10);
    expect(navigate).not.toHaveBeenCalled();
  });

  it("skips the dwell entirely when the caller asked to go before readiness", () => {
    // The rule schedules the ask honoured at once - a no-wait schedule - rather
    // than leaving, which is what makes the press feel answered.
    const navigate = vi.fn();
    const { result, rerender } = renderHook(
      ({ ready }: { ready: boolean }) => useHandoffNavigation(ready, navigate),
      { initialProps: { ready: false } },
    );
    act(() => {
      result.current();
    });

    rerender({ ready: true });
    advance(0);
    expect(navigate).toHaveBeenCalledTimes(1);
  });

  it("navigates once when the caller asks to go twice within a single tick", () => {
    // Both presses see the same render's closure, so a latch held in state
    // would read itself as still unset on the second press and leave twice -
    // the exact shape of a double-clicked button. A ref is written as it is
    // read, which is why the once-only latch is a ref and not state.
    const navigate = vi.fn();
    const { result } = renderHook(() => useHandoffNavigation(true, navigate));

    act(() => {
      result.current();
      result.current();
    });
    expect(navigate).toHaveBeenCalledTimes(1);

    advance(HANDOFF_MINIMUM_DWELL_MS * 3);
    expect(navigate).toHaveBeenCalledTimes(1);
  });

  it("navigates once however many times the caller asks to go", () => {
    const navigate = vi.fn();
    const { result } = renderHook(() => useHandoffNavigation(true, navigate));

    act(() => {
      result.current();
    });
    act(() => {
      result.current();
    });
    act(() => {
      result.current();
    });
    advance(HANDOFF_MINIMUM_DWELL_MS * 3);
    expect(navigate).toHaveBeenCalledTimes(1);
  });

  it("navigates once when the dwell has already fired and the caller then asks to go", () => {
    const navigate = vi.fn();
    const { result } = renderHook(() => useHandoffNavigation(true, navigate));

    advance(HANDOFF_MINIMUM_DWELL_MS);
    expect(navigate).toHaveBeenCalledTimes(1);

    act(() => {
      result.current();
    });
    advance(HANDOFF_MINIMUM_DWELL_MS * 3);
    expect(navigate).toHaveBeenCalledTimes(1);
  });

  it("measures the dwell from readiness, so a slow flow keeps its full beat", () => {
    const navigate = vi.fn();
    const { rerender } = renderHook(
      ({ ready }: { ready: boolean }) => useHandoffNavigation(ready, navigate),
      { initialProps: { ready: false } },
    );

    // A flow that takes a long time to become ready must not have the time it
    // spent loading counted against the beat it still owes the reader.
    advance(HANDOFF_MINIMUM_DWELL_MS * 4);
    expect(navigate).not.toHaveBeenCalled();

    rerender({ ready: true });
    advance(HANDOFF_MINIMUM_DWELL_MS - 1);
    expect(navigate).not.toHaveBeenCalled();

    advance(1);
    expect(navigate).toHaveBeenCalledTimes(1);
  });

  it("clears the scheduled navigation when the host goes away first", () => {
    const navigate = vi.fn();
    const { result, unmount } = renderHook(() =>
      useHandoffNavigation(true, navigate),
    );

    advance(HANDOFF_MINIMUM_DWELL_MS - 1);
    unmount();
    // The pending leave is dropped, not merely ignored when it fires.
    expect(vi.getTimerCount()).toBe(0);

    // Neither the pending timer nor a later press of the button may reach a
    // host that is no longer on the page.
    act(() => {
      result.current();
    });
    advance(HANDOFF_MINIMUM_DWELL_MS * 3);
    expect(navigate).not.toHaveBeenCalled();
  });

  it("does not re-arm or restart the dwell when the navigate routine arrives as a fresh function each render", () => {
    // Both hosts wire the button to an inline closure, so a fresh identity on
    // every render is the normal case. If the routine were a per-render input
    // the timer would re-arm and the dwell would restart on each one, and the
    // symptom would be a handoff whose button does nothing and which never
    // navigates - indistinguishable from the frozen screen this work removes.
    const navigate = vi.fn();
    const { rerender } = renderHook(() =>
      useHandoffNavigation(true, () => navigate()),
    );

    // The rerenders land inside the dwell, which is where a per-render re-arm
    // shows: the beat restarts, so the time already served is thrown away.
    advance(HANDOFF_MINIMUM_DWELL_MS - 1);
    rerender();
    rerender();
    expect(navigate).not.toHaveBeenCalled();

    advance(1);
    expect(navigate).toHaveBeenCalledTimes(1);
  });

  it("asks the latest navigate routine when the caller asks to go", () => {
    const first = vi.fn();
    const second = vi.fn();
    const { result, rerender } = renderHook(
      ({ navigate }: { navigate: () => void }) =>
        useHandoffNavigation(true, navigate),
      { initialProps: { navigate: first } },
    );

    rerender({ navigate: second });
    act(() => {
      result.current();
    });
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
  });
});
