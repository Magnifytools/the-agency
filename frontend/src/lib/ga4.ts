/** Motivo legible de un error de importación de GA4 (o null si no hay). */
export function ga4ErrorLabel(code: string | null | undefined): string | null {
  switch (code) {
    case null:
    case undefined:
      return null
    case "missing_scope":
      return "La cuenta de Google se conectó antes de pedir permiso de Analytics: reconéctala en Ajustes."
    case "no_access":
      return "Ninguna cuenta conectada tiene acceso a esta propiedad de GA4."
    case "not_found":
      return "La propiedad de GA4 no existe o el ID está mal."
    case "rate_limited":
      return "Google ha limitado las peticiones; se reintentará."
    default:
      return "No se pudo importar; se reintentará."
  }
}

const group = (digits: string) => digits.replace(/\B(?=(\d{3})+(?!\d))/g, ".")
/** 1.234 / 12,3 — mismo formato que el bloque del email. */
export function ga4Number(value: number): string {
  if (Number.isInteger(value)) return group(String(value))
  const [whole, fraction] = value.toFixed(1).split(".")
  return `${group(whole)},${fraction}`
}

export function ga4Change(value: number | null | undefined): string | null {
  if (value == null) return null
  return `${value > 0 ? "+" : ""}${value.toFixed(1).replace(".", ",")} %`
}
