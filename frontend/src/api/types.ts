/** Friendly names for the generated API schema (src/api/schema.d.ts). */
import type { components } from "./schema";

type Schemas = components["schemas"];

export type AuthState = Schemas["AuthState"];
export type LoginResponse = Schemas["LoginResponse"];
export type UserOut = Schemas["UserOut"];
export type UserList = Schemas["UserList"];
export type UserCreate = Schemas["UserCreate"];
export type UserUpdate = Schemas["UserUpdate"];
export type PasswordReset = Schemas["PasswordReset"];
export type RoleOut = Schemas["RoleOut"];
export type RoleList = Schemas["RoleList"];
export type AuditEventOut = Schemas["AuditEventOut"];
export type AuditEventList = Schemas["AuditEventList"];
export type SessionOut = Schemas["SessionOut"];
export type SessionList = Schemas["SessionList"];
export type SetupStatus = Schemas["SetupStatus"];
export type SetupRequest = Schemas["SetupRequest"];
export type SystemInfo = Schemas["SystemInfo"];
export type SystemStatus = Schemas["SystemStatus"];
export type ComponentDetail = Schemas["ComponentDetail"];
export type ReadyResponse = Schemas["ReadyResponse"];
export type FeatureList = Schemas["FeatureList"];
export type FeatureOut = Schemas["FeatureOut"];
export type DashboardResponse = Schemas["DashboardResponse"];
export type Metric = Schemas["Metric"];
export type ActivityItem = Schemas["ActivityItem"];
export type ProviderList = Schemas["ProviderList"];
export type ProviderOut = Schemas["ProviderOut"];
export type ChangePasswordResponse = Schemas["ChangePasswordResponse"];

export type HealthStatus = Schemas["ComponentSummary"]["status"];
export type FeatureStatus = FeatureOut["status"];
