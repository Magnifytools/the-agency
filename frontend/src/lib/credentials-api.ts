import { api } from "@/lib/api"

/** Un acceso tal como lo ve quien tiene permiso. La contraseña nunca viene aquí. */
export interface Credential {
  id: number
  name: string
  url: string | null
  username: string | null
  notes: string | null
  client_id: number | null
  client_name: string | null
  created_by: number | null
  created_by_name: string | null
  updated_at: string
  can_manage: boolean
  /** Sólo para quien puede gestionarlo; al resto le llega vacío. */
  shared_with: SharedUser[]
}

export interface SharedUser {
  id: number
  full_name: string
}

export interface CredentialInput {
  name: string
  url: string | null
  username: string | null
  notes: string | null
  client_id: number | null
  /** Al crear es obligatoria; al editar, sólo si se cambia. */
  secret?: string
  shared_user_ids?: number[]
}

export type CredentialLogAction = "reveal" | "copy" | "create" | "update" | "share" | "delete"

export interface CredentialLogEntry {
  id: number
  action: CredentialLogAction
  user_id: number | null
  user_name: string | null
  detail: string | null
  at: string
}

export const credentialsApi = {
  list: (params?: { q?: string; client_id?: number }) =>
    api.get<Credential[]>("/credentials", { params }).then((r) => r.data),
  shareableUsers: () => api.get<SharedUser[]>("/credentials/shareable-users").then((r) => r.data),
  create: (data: CredentialInput) => api.post<Credential>("/credentials", data).then((r) => r.data),
  update: (id: number, data: Partial<CredentialInput>) =>
    api.patch<Credential>(`/credentials/${id}`, data).then((r) => r.data),
  setShares: (id: number, userIds: number[]) =>
    api.put<Credential>(`/credentials/${id}/shares`, { user_ids: userIds }).then((r) => r.data),
  /** Cada llamada queda registrada (quién y cuándo). No se cachea en TanStack a propósito. */
  reveal: (id: number, purpose: "reveal" | "copy") =>
    api.post<{ secret: string }>(`/credentials/${id}/reveal`, { purpose }).then((r) => r.data.secret),
  log: (id: number) => api.get<CredentialLogEntry[]>(`/credentials/${id}/log`).then((r) => r.data),
  remove: (id: number) => api.delete<void>(`/credentials/${id}`).then(() => undefined),
}
