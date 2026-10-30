import type { WebChange, WebChangeKind, WebHtmlDiff, WebSeverity, WebWatch } from "@/lib/types"

/** Funciones puras de la vigilancia de cambios (portadas de Vigil, `lib/types.ts`). */

export const SEVERITY_LABEL: Record<WebSeverity, string> = {
  critical: "Crítico",
  warning: "Aviso",
  info: "Menor",
}

/** Plural para los filtros: "Críticos 1 · Avisos 3 · Menores 7". */
export const SEVERITY_FILTERS: Array<{ id: WebSeverity | "all"; label: string }> = [
  { id: "all", label: "Todos" },
  { id: "critical", label: "Críticos" },
  { id: "warning", label: "Avisos" },
  { id: "info", label: "Menores" },
]

export const KIND_LABEL: Record<WebChangeKind, string> = {
  availability: "Disponibilidad",
  seo: "SEO",
  content: "Contenido",
  links: "Enlaces",
  html: "Maquetación",
}

/** Entero con punto de miles SIEMPRE: es-ES no agrupa los de 4 cifras ("3837"). */
export function formatInt(value: number): string {
  return Math.round(value).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".")
}

export function isSeverity(value: string | null): value is WebSeverity {
  return value === "critical" || value === "warning" || value === "info"
}

/** Sólo la ruta: repetir el dominio en cada fila estorba. La home enseña el
 *  dominio, que es lo que se reconoce (un `/` suelto no dice nada). */
export function pathOf(url: string | null): string {
  if (!url) return "—"
  try {
    const u = new URL(url)
    const path = (u.pathname || "/") + u.search
    return path === "/" ? u.hostname.replace(/^www\./, "") : path
  } catch {
    return url
  }
}

/**
 * Un cambio de SÓLO maquetación se resume en una frase con su tamaño (lección
 * 0decies de Vigil): cinco filas que dicen "cambió el HTML" a secas no dejan
 * distinguir un plugin actualizado de un falso positivo. El clasificador sólo
 * emite HTML_CHANGED cuando nada más se movió, así que la nota es verdad. Sin
 * medida no se inventa un cero.
 */
export function htmlOnlySummary(change: Pick<WebChange, "items">): { headline: string; note: string } | null {
  if (change.items.length !== 1 || change.items[0].rule_code !== "HTML_CHANGED") return null
  const detail = change.items[0].detail ?? {}
  const added = typeof detail.added === "number" ? detail.added : null
  const removed = typeof detail.removed === "number" ? detail.removed : null
  const total = typeof detail.after_lines === "number" ? detail.after_lines : null
  if (added === null || removed === null) {
    return {
      headline: "Solo maquetación",
      note: "Ni el texto visible ni el SEO se movieron. No se pudo medir el tamaño del cambio.",
    }
  }
  return {
    headline: `Solo maquetación · +${added}/−${removed} líneas${total !== null ? ` de ${formatInt(total)}` : ""}`,
    note: "Ni el texto visible ni el SEO se movieron.",
  }
}

/** Por qué no hay diff de HTML. Un panel en blanco se lee como "está roto"
 *  (lección 0septies): el servidor SIEMPRE manda `reason` y aquí se explica. */
export const HTML_DIFF_REASON: Record<NonNullable<WebHtmlDiff["reason"]>, string> = {
  sin_anterior:
    "Es el primer cambio con HTML guardado para esta URL, así que no hay versión anterior con la que " +
    "compararlo. El siguiente ya saldrá con su antes y su después.",
  sin_actual:
    "No se guardó el HTML de esta captura: «Vigilar HTML» se activó después. A partir del próximo barrido se guarda.",
  demasiado_grande:
    "La página es demasiado grande para calcular el diff aquí sin bloquear el servidor.",
}

export function htmlDiffReason(reason: WebHtmlDiff["reason"] | undefined): string {
  return HTML_DIFF_REASON[reason ?? "sin_actual"] ?? HTML_DIFF_REASON.sin_actual
}

export type WatchHealth = "archived" | "paused" | "checking" | "error" | "review" | "stable" | "unchecked"

/** Un solo estado por URL, en orden de lo que más pide atención. */
export function watchHealth(watch: WebWatch): WatchHealth {
  if (watch.archived_at) return "archived"
  if (!watch.is_active) return "paused"
  if (watch.checking) return "checking"
  if (watch.state?.last_error) return "error"
  if (watch.state?.scope_missed || watch.state?.needs_js_render) return "review"
  if (watch.state?.last_checked_at) return "stable"
  return "unchecked"
}

/** Estado del aviso a Slack de un barrido. "No tocaba" no es "falta Slack":
 *  una URL suelta no avisa por diseño (lección 0sexies). */
export function notifyLabel(status: string | null): { text: string; warn: boolean } {
  switch (status) {
    case "sent": return { text: "Avisado en Slack", warn: false }
    case "summary_sent": return { text: "Resumen enviado a Slack", warn: false }
    case "skipped_no_changes": return { text: "Sin cambios que avisar", warn: false }
    case "no_procede": return { text: "No tocaba avisar", warn: false }
    case "disabled": return { text: "Sin Slack activo", warn: true }
    case "revoked": return { text: "Slack revocó el webhook", warn: true }
    case "failed": return { text: "Falló el aviso a Slack", warn: true }
    default: return { text: "Sin aviso", warn: false }
  }
}

export const RUN_STATUS_LABEL: Record<string, string> = {
  running: "En curso",
  done: "Completo",
  partial: "Con errores",
  failed: "Falló",
}

// ── Diff de texto ────────────────────────────────────────────────────

export interface DiffOp { op: "+" | "-" | " " | "…"; text: string }

export function sentences(text: string): string[] {
  return text.replace(/([.!?])\s+/g, "$1\n").split("\n").map((s) => s.trim()).filter(Boolean)
}

/** Por encima de esto la tabla LCS (n × m) pesaría demasiado en el navegador. */
export const MAX_LCS_CELLS = 4_000_000

/**
 * Diff por frases (no por caracteres: uno de caracteres sobre 2.000 palabras no
 * se lee), con 2 frases de contexto alrededor de cada cambio. Devuelve null si
 * los textos son demasiado largos para compararlos aquí.
 */
export function sentenceDiff(before: string, after: string, context = 2): DiffOp[] | null {
  // Lo común al principio y al final no entra en la tabla: abarata el caso
  // típico (una frase cambiada en una página larga).
  const a = sentences(before)
  const b = sentences(after)
  let start = 0
  while (start < a.length && start < b.length && a[start] === b[start]) start++
  let endA = a.length
  let endB = b.length
  while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) { endA--; endB-- }
  const midA = a.slice(start, endA)
  const midB = b.slice(start, endB)
  const n = midA.length
  const m = midB.length
  if (n * m > MAX_LCS_CELLS) return null

  const table: Uint32Array[] = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1))
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      table[i][j] = midA[i] === midB[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1])

  const all: DiffOp[] = a.slice(0, start).map((text) => ({ op: " ", text }))
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (midA[i] === midB[j]) { all.push({ op: " ", text: midA[i] }); i++; j++ }
    else if (table[i + 1][j] >= table[i][j + 1]) { all.push({ op: "-", text: midA[i] }); i++ }
    else { all.push({ op: "+", text: midB[j] }); j++ }
  }
  while (i < n) all.push({ op: "-", text: midA[i++] })
  while (j < m) all.push({ op: "+", text: midB[j++] })
  for (const text of a.slice(endA)) all.push({ op: " ", text })

  const keep = new Set<number>()
  all.forEach((o, idx) => {
    if (o.op === " ") return
    for (let k = Math.max(0, idx - context); k <= Math.min(all.length - 1, idx + context); k++) keep.add(k)
  })
  const out: DiffOp[] = []
  let skipping = false
  all.forEach((o, idx) => {
    if (keep.has(idx)) { out.push(o); skipping = false }
    else if (!skipping) { out.push({ op: "…", text: "" }); skipping = true }
  })
  return out
}

/** Elementos de una lista de `detail` (enlaces, H2, schema, hreflang) como texto. */
export function detailEntries(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((entry) => {
    if (typeof entry === "string") return entry
    if (entry && typeof entry === "object") {
      const { lang, href } = entry as { lang?: string; href?: string }
      if (href) return lang ? `${lang} → ${href}` : href
      return JSON.stringify(entry)
    }
    return String(entry)
  })
}
