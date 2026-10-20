import { api } from "@/lib/api"

/** Estado del enlace de sólo lectura de un cliente. El token nunca vuelve del servidor. */
export interface ShareLinkStatus {
  active: boolean
  created_at: string | null
  created_by_name: string | null
  last_viewed_at: string | null
}

/** Respuesta al crear: el único momento en que se conoce el enlace completo. */
export interface CreatedShareLink extends ShareLinkStatus {
  path: string
}

export interface PublicTrafficMonth {
  month: string
  clicks: number
  impressions: number
  position: number | null
}

export interface PublicDigest {
  period_start: string
  period_end: string
  period_label: string
  delivered_at: string | null
  html: string
}

export interface PublicClientView {
  client_name: string
  traffic: { months: PublicTrafficMonth[]; complete_through: string } | null
  digests: PublicDigest[]
}

export const clientShareLinkApi = {
  status: (clientId: number) =>
    api.get<ShareLinkStatus>(`/clients/${clientId}/share-link`).then((r) => r.data),
  create: (clientId: number) =>
    api.post<CreatedShareLink>(`/clients/${clientId}/share-link`).then((r) => r.data),
  revoke: (clientId: number) => api.delete<void>(`/clients/${clientId}/share-link`).then(() => undefined),
  publicView: (token: string) =>
    api.get<PublicClientView>(`/public/clients/${encodeURIComponent(token)}`).then((r) => r.data),
}
