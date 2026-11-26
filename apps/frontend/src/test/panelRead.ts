// A fake `PanelRead<T>` for component tests that render one observability panel
// in isolation (the page owns the real fetch). `data: null` means the read has
// not resolved, so the panel owes a loading skeleton; override `status` for the
// error/retry path.

import { vi } from "vitest";

import type { PanelRead } from "@/lib/operator/usePanelRead";

export function panelRead<T>(
  overrides: Partial<PanelRead<T>> & { data: T | null },
): PanelRead<T> {
  return {
    status: overrides.data === null ? "loading" : "ready",
    errorTraceId: undefined,
    error: null,
    bannerOpen: false,
    reload: vi.fn(),
    dismissBanner: vi.fn(),
    ...overrides,
  };
}
