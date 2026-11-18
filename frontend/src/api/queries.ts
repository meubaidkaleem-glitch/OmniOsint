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
  AdapterList,
  AuditEventList,
  ClassificationOut,
  EvidenceDetailOut,
  EvidenceList,
  HealthOut,
  HistoryList,
  InputTypeList,
  JobDetailOut,
  JobOut,
  PlanOut,
  PlanRequest,
  RawOut,
  RequestDetailOut,
  RequestList,
  RequestOut,
  SavedSearchIn,
  SavedSearchList,
  SavedSearchOut,
  ScopeDecisionOut,
  ScopeDetailOut,
  ScopeIn,
  ScopeList,
  ScopeRuleIn,
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
  inputTypes: ["search", "types"] as const,
  history: ["search", "history"] as const,
  saved: ["search", "saved"] as const,
  requests: ["collection", "requests"] as const,
  request: (id: string) => ["collection", "requests", id] as const,
  job: (id: string) => ["collection", "jobs", id] as const,
  jobEvidence: (id: string) => ["evidence", "job", id] as const,
  evidence: (id: string) => ["evidence", id] as const,
  raw: (id: string, unmasked: boolean) => ["evidence", id, "raw", unmasked] as const,
  scopes: ["scopes"] as const,
  scope: (id: string) => ["scopes", id] as const,
  adapters: ["providers", "adapters"] as const,
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

// --------------------------------------------------------------------------- universal search
export function useClassify() {
  return useMutation({
    mutationFn: (payload: { input: string; remember?: boolean }) =>
      api.post<ClassificationOut>("/search/classify", payload),
  });
}

export function useInputTypes() {
  return useQuery({
    queryKey: queryKeys.inputTypes,
    queryFn: ({ signal }) => api.get<InputTypeList>("/search/types", undefined, signal),
    staleTime: Infinity,
  });
}

export function useSearchHistory() {
  return useQuery({
    queryKey: queryKeys.history,
    queryFn: ({ signal }) => api.get<HistoryList>("/search/history", { limit: 20 }, signal),
  });
}

export function useClearHistory() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.delete("/search/history"),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.history }),
  });
}

export function useSavedSearches() {
  return useQuery({
    queryKey: queryKeys.saved,
    queryFn: ({ signal }) => api.get<SavedSearchList>("/search/saved", undefined, signal),
  });
}

export function useSaveSearch() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: SavedSearchIn) => api.post<SavedSearchOut>("/search/saved", payload),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.saved }),
  });
}

export function useDeleteSavedSearch() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/search/saved/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.saved }),
  });
}

// --------------------------------------------------------------------------- collection
export function usePlan() {
  return useMutation({
    mutationFn: (payload: PlanRequest) => api.post<PlanOut>("/collection/plan", payload),
  });
}

export function useSubmitCollection() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: PlanRequest) => api.post<RequestOut>("/collection/requests", payload),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: queryKeys.requests });
      await client.invalidateQueries({ queryKey: queryKeys.history });
      await client.invalidateQueries({ queryKey: queryKeys.dashboard });
    },
  });
}

export function useCollectionRequests() {
  return useInfiniteQuery({
    queryKey: queryKeys.requests,
    queryFn: ({ pageParam, signal }) =>
      api.get<RequestList>("/collection/requests", { cursor: pageParam, limit: 50 }, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    refetchInterval: 5_000,
  });
}

const UNSETTLED = new Set(["queued", "running"]);

export function useCollectionRequest(id: string) {
  return useQuery({
    queryKey: queryKeys.request(id),
    queryFn: ({ signal }) => api.get<RequestDetailOut>(`/collection/requests/${id}`, undefined, signal),
    // Poll while any job is still waiting to run or running.
    refetchInterval: (query) =>
      query.state.data?.jobs.some((job) => UNSETTLED.has(job.status)) ? 1_500 : false,
  });
}

export function useJob(id: string | null) {
  return useQuery({
    queryKey: queryKeys.job(id ?? ""),
    queryFn: ({ signal }) => api.get<JobDetailOut>(`/collection/jobs/${id}`, undefined, signal),
    enabled: id !== null,
    refetchInterval: (query) => (query.state.data && UNSETTLED.has(query.state.data.job.status) ? 1_500 : false),
  });
}

export function useJobAction() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: "approve" | "cancel" | "retry" }) =>
      api.post<JobOut>(`/collection/jobs/${id}/${action}`),
    onSuccess: async (job) => {
      await client.invalidateQueries({ queryKey: queryKeys.request(job.request_id) });
      await client.invalidateQueries({ queryKey: queryKeys.job(job.id) });
      await client.invalidateQueries({ queryKey: queryKeys.requests });
    },
  });
}

export function useCancelRequest() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<RequestOut>(`/collection/requests/${id}/cancel`),
    onSuccess: (request) => client.invalidateQueries({ queryKey: queryKeys.request(request.id) }),
  });
}

// --------------------------------------------------------------------------- evidence
export function useJobEvidence(jobId: string | null) {
  return useQuery({
    queryKey: queryKeys.jobEvidence(jobId ?? ""),
    queryFn: ({ signal }) => api.get<EvidenceList>("/evidence", { job_id: jobId, limit: 200 }, signal),
    enabled: jobId !== null,
  });
}

export function useEvidence(id: string) {
  return useQuery({
    queryKey: queryKeys.evidence(id),
    queryFn: ({ signal }) => api.get<EvidenceDetailOut>(`/evidence/${id}`, undefined, signal),
  });
}

export function useRawEvidence(id: string, unmasked: boolean, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.raw(id, unmasked),
    queryFn: ({ signal }) =>
      api.get<RawOut>(`/evidence/${id}/raw`, unmasked ? { unmasked: true } : undefined, signal),
    enabled,
    retry: false,
  });
}

// --------------------------------------------------------------------------- scopes
export function useScopes(enabled = true) {
  return useQuery({
    queryKey: queryKeys.scopes,
    queryFn: ({ signal }) => api.get<ScopeList>("/scopes", undefined, signal),
    enabled,
  });
}

export function useScope(id: string | null) {
  return useQuery({
    queryKey: queryKeys.scope(id ?? ""),
    queryFn: ({ signal }) => api.get<ScopeDetailOut>(`/scopes/${id}`, undefined, signal),
    enabled: id !== null,
  });
}

function useScopeMutation<TVariables>(mutationFn: (variables: TVariables) => Promise<ScopeDetailOut>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: async (detail) => {
      client.setQueryData(queryKeys.scope(detail.scope.id), detail);
      await client.invalidateQueries({ queryKey: queryKeys.scopes });
    },
  });
}

export const useCreateScope = () =>
  useScopeMutation((payload: ScopeIn) => api.post<ScopeDetailOut>("/scopes", payload));

export const useAddScopeRule = () =>
  useScopeMutation(({ id, rule }: { id: string; rule: ScopeRuleIn }) =>
    api.post<ScopeDetailOut>(`/scopes/${id}/rules`, rule),
  );

export const useRemoveScopeRule = () =>
  useScopeMutation(({ id, ruleId }: { id: string; ruleId: string }) =>
    api.delete<ScopeDetailOut>(`/scopes/${id}/rules/${ruleId}`),
  );

export const useRevokeScope = () =>
  useScopeMutation(({ id, reason }: { id: string; reason: string }) =>
    api.post<ScopeDetailOut>(`/scopes/${id}/revoke`, { reason }),
  );

export function useCheckScope() {
  return useMutation({
    mutationFn: ({ id, input, operation }: { id: string; input: string; operation: "discovery" | "assessment" }) =>
      api.post<ScopeDecisionOut>(`/scopes/${id}/check`, { input, operation }),
  });
}

// --------------------------------------------------------------------------- adapters
export function useAdapters(enabled = true) {
  return useQuery({
    queryKey: queryKeys.adapters,
    queryFn: ({ signal }) => api.get<AdapterList>("/providers/adapters", undefined, signal),
    enabled,
  });
}

export function useHealthCheck() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<HealthOut>(`/providers/${id}/health`),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.adapters }),
  });
}
