import type { DigestSeo } from "@/lib/types/integration"

/** Motivo legible de un fallo de importación de una propiedad. */
export function gscErrorLabel(code: string | null | undefined): string | null {
  switch (code) {
    case null:
    case undefined:
      return null
    case "no_access":
      return "La cuenta conectada no tiene acceso a esta propiedad."
    case "not_found":
      return "La propiedad no existe en Search Console. Revisa cómo está escrita."
    case "rate_limited":
      return "Google ha limitado las peticiones. Se reintentará en la próxima pasada."
    default:
      return "Search Console no respondió. Se reintentará en la próxima pasada."
  }
}

/** Por qué un resumen mensual no lleva el bloque de Search Console. */
export function digestSeoUnavailableReason(seo: Exclude<DigestSeo, { status: "ok" }>): string {
  switch (seo.status) {
    case "no_property":
      return "El cliente no tiene propiedad de Search Console. Añádela en su ficha (Ajustes del cliente)."
    case "not_connected":
      return "Search Console no está conectado. Un admin puede conectarlo en Ajustes."
    case "reconnect_required":
      return "La conexión con Search Console necesita reconectarse (Ajustes)."
    case "not_synced":
      return gscErrorLabel(seo.error_code) ?? "La propiedad aún no se ha importado. Se hará en la próxima pasada diaria."
    case "incomplete":
      return `Google todavía no tiene datos finales de todo el mes${seo.last_data_date ? ` (último día con datos: ${formatDay(seo.last_data_date)})` : ""}. Vuelve a generar el resumen en un par de días.`
    case "no_data":
      return "Search Console no tiene datos de este mes para la propiedad."
  }
}

export function formatDay(value: string): string {
  return new Date(`${value}T12:00:00`).toLocaleDateString("es-ES", { day: "numeric", month: "long", year: "numeric" })
}
