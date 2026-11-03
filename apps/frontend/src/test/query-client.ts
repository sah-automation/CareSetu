import { QueryClient } from "@tanstack/react-query";

import { QUERY_CLIENT_DEFAULTS } from "@/lib/queryClient";

/**
 * Test-only query client: same production defaults, but retries disabled so a
 * mocked failure surfaces immediately instead of after the retry delay.
 */
export function makeTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { ...QUERY_CLIENT_DEFAULTS, retry: false },
    },
  });
}
