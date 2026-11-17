/** TanStack Query hooks for every API call the interface makes. */
import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { api, ApiError, setCsrfToken } from "./client";
import type {
  AuditEventList,
  AuthState,
  ChangePasswordResponse,
  DashboardResponse,
  FeatureList,
  LoginResponse,
  PasswordReset,
  ProviderList,
  ReadyResponse,
  RoleList,
  SessionList,
  SetupRequest,
  SetupStatus,
  SystemInfo,
  SystemStatus,
  UserCreate,
  UserList,
  UserOut,
  UserUpdate,
} from "./types";

export const queryKeys = {
  me: ["auth", "me"] as const,
  info: ["system", "info"] as const,
  setupStatus: ["auth", "setup-status"] as const,
  live: ["system", "live"] as const,
  ready: ["system", "ready"] as const,
  features: ["system", "features"] as const,
  status: ["system", "status"] as const,
  dashboard: ["dashboard"] as const,
  providers: ["providers"] as const,
  sessions: ["auth", "sessions"] as const,
  users: (search: string) => ["admin", "users", search] as const,
  usersAll: ["admin", "users"] as const,
  roles: ["admin", "roles"] as const,
  audit: (filters: AuditFilters) => ["admin", "audit", filters] as const,
};

// --------------------------------------------------------------------------- session
/** The signed-in user, or null when nobody is signed in. */
export function useMe() {
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: async ({ signal }): Promise<AuthState | null> => {
      try {
        const state = await api.get<AuthState>("/auth/me", undefined, signal);
        setCsrfToken(state.csrf_token);
        return state;
      } catch (error) {
        if (error instanceof ApiError && error.isAuthentication) {
          setCsrfToken(null);
          return null;
        }
        throw error;
      }
    },
    staleTime: 60_000,
    retry: (failures, error) => !(error instanceof ApiError && error.status < 500) && failures < 2,
  });
}

export function useSystemInfo() {
  return useQuery({
    queryKey: queryKeys.info,
    queryFn: ({ signal }) => api.get<SystemInfo>("/system/info", undefined, signal),
    staleTime: 30_000,
  });
}

export function useSetupStatus(enabled = true) {
  return useQuery({
    queryKey: queryKeys.setupStatus,
    queryFn: ({ signal }) => api.get<SetupStatus>("/auth/setup-status", undefined, signal),
    enabled,
  });
}

export function useLogin() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (credentials: { username: string; password: string }) =>
      api.post<LoginResponse>("/auth/login", { ...credentials, session_type: "cookie" }),
    onSuccess: async (result) => {
      setCsrfToken(result.csrf_token);
      client.clear();
      await client.invalidateQueries({ queryKey: queryKeys.me });
    },
  });
}

export function useCompleteSetup() {
  return useMutation({
    mutationFn: (payload: SetupRequest) => api.post<{ user: UserOut }>("/auth/setup", payload),
  });
}

export function useLogout() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<void>("/auth/logout"),
    onSettled: () => {
      setCsrfToken(null);
      client.clear();
      client.setQueryData(queryKeys.me, null);
    },
  });
}

export function useChangePassword() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: { current_password: string; new_password: string }) =>
      api.post<ChangePasswordResponse>("/auth/change-password", payload),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: queryKeys.me });
      await client.invalidateQueries({ queryKey: queryKeys.sessions });
    },
  });
}

export function useSessions() {
  return useQuery({
    queryKey: queryKeys.sessions,
    queryFn: ({ signal }) => api.get<SessionList>("/auth/sessions", undefined, signal),
  });
}

export function useRevokeSession() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (sessionId: string) => api.delete(`/auth/sessions/${sessionId}`),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.sessions }),
  });
}

// --------------------------------------------------------------------------- system
/** Liveness, polled to detect that the backend has stopped. */
export function useLiveness() {
  return useQuery({
    queryKey: queryKeys.live,
    queryFn: ({ signal }) => api.get<{ status: string }>("/system/health/live", undefined, signal),
    refetchInterval: 15_000,
    retry: false,
    refetchOnWindowFocus: true,
  });
}

export function useReadiness() {
  return useQuery({
    queryKey: queryKeys.ready,
    queryFn: async ({ signal }): Promise<ReadyResponse> => {
      try {
        return await api.get<ReadyResponse>("/system/health/ready", undefined, signal);
      } catch (error) {
        // A 503 means "not ready"; the client raises it as an error.
        if (error instanceof ApiError && error.status === 503) {
          return { status: "unavailable", checked_at: new Date().toISOString(), components: [] };
        }
        throw error;
      }
    },
    refetchInterval: 30_000,
  });
}

export function useFeatures() {
  return useQuery({
    queryKey: queryKeys.features,
    queryFn: ({ signal }) => api.get<FeatureList>("/system/features", undefined, signal),
    staleTime: 5 * 60_000,
  });
}

export function useSystemStatus() {
  return useQuery({
    queryKey: queryKeys.status,
    queryFn: ({ signal }) => api.get<SystemStatus>("/system/status", undefined, signal),
    refetchInterval: 30_000,
  });
}

export function useDashboard() {
  return useQuery({
    queryKey: queryKeys.dashboard,
    queryFn: ({ signal }) => api.get<DashboardResponse>("/dashboard", undefined, signal),
    refetchInterval: 60_000,
  });
}

export function useProviders() {
  return useQuery({
    queryKey: queryKeys.providers,
    queryFn: ({ signal }) => api.get<ProviderList>("/providers", undefined, signal),
    staleTime: 5 * 60_000,
  });
}

// --------------------------------------------------------------------------- admin
export function useUsers(search: string) {
  return useInfiniteQuery({
    queryKey: queryKeys.users(search),
    queryFn: ({ pageParam, signal }) =>
      api.get<UserList>("/admin/users", { search, cursor: pageParam, limit: 50 }, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    placeholderData: keepPreviousData,
  });
}

export function useRoles() {
  return useQuery({
    queryKey: queryKeys.roles,
    queryFn: ({ signal }) => api.get<RoleList>("/admin/roles", undefined, signal),
    staleTime: 60_000,
  });
}

function useUserMutation<TVariables>(mutationFn: (variables: TVariables) => Promise<unknown>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: queryKeys.usersAll });
      await client.invalidateQueries({ queryKey: queryKeys.roles });
      await client.invalidateQueries({ queryKey: queryKeys.dashboard });
      await client.invalidateQueries({ queryKey: queryKeys.me });
    },
  });
}

export const useCreateUser = () =>
  useUserMutation((payload: UserCreate) => api.post<UserOut>("/admin/users", payload));

export const useUpdateUser = () =>
  useUserMutation(({ id, changes }: { id: string; changes: UserUpdate }) =>
    api.patch<UserOut>(`/admin/users/${id}`, changes),
  );

export const useResetPassword = () =>
  useUserMutation(({ id, payload }: { id: string; payload: PasswordReset }) =>
    api.post<UserOut>(`/admin/users/${id}/reset-password`, payload),
  );

export const useUnlockUser = () =>
  useUserMutation((id: string) => api.post<UserOut>(`/admin/users/${id}/unlock`));

export const useDeleteUser = () =>
  useUserMutation((id: string) => api.delete(`/admin/users/${id}`));

export interface AuditFilters {
  category?: string;
  outcome?: string;
  action?: string;
}

export function useAuditEvents(filters: AuditFilters) {
  return useInfiniteQuery({
    queryKey: queryKeys.audit(filters),
    queryFn: ({ pageParam, signal }) =>
      api.get<AuditEventList>(
        "/admin/audit-events",
        { ...filters, cursor: pageParam, limit: 50 },
        signal,
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    placeholderData: keepPreviousData,
  });
}
