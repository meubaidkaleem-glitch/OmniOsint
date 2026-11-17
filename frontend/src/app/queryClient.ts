import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";

import { ApiError } from "@/api/client";
import { queryKeys } from "@/api/queries";

/**
 * When any request reports that the session has ended, re-check who is
 * signed in; the route guard then sends the user to the sign-in page.
 */
function recheckSession(client: QueryClient, error: unknown, key?: readonly unknown[]): void {
  if (!(error instanceof ApiError)) return;
  const isMeQuery = key?.join("/") === queryKeys.me.join("/");
  if ((error.status === 401 && !isMeQuery) || error.code === "password_change_required") {
    void client.invalidateQueries({ queryKey: queryKeys.me });
  }
}

export function createQueryClient(): QueryClient {
  const client: QueryClient = new QueryClient({
    queryCache: new QueryCache({
      onError: (error, query) => recheckSession(client, error, query.queryKey),
    }),
    mutationCache: new MutationCache({ onError: (error) => recheckSession(client, error) }),
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        refetchOnWindowFocus: false,
        retry: (failures, error) =>
          !(error instanceof ApiError && error.status >= 400 && error.status < 500) && failures < 2,
      },
      mutations: { retry: false },
    },
  });
  return client;
}
