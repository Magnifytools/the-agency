import { gscErrorLabel } from "@/lib/gsc"
import type { SeoControlStatus, SeoPageGroup } from "@/lib/types"

// Mismos límites que `backend/services/seo_control.py` (el backend manda).
export const MAX_BRAND_TERMS = 20
export const MIN_TERM_LENGTH = 3
export const MAX_TERM_LENGTH = 60

/** Igual que el backend: sin acentos ni mayúsculas; lo que no es letra o número, espacio. */
export function normalizeSeoText(value: string): string {
  return value
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim()
}

/** Clave para detectar duplicados: "Fit-Generation" = "fit generation" = "FITGENERATION". */
export function brandKey(term: string): string {
  return normalizeSeoText(term).replace(/ /g, "")
}

/** Motivo por el que un término no vale, o null si vale. */
export function brandTermProblem(term: string, current: string[]): string | null {
  const clean = term.split(/\s+/).filter(Boolean).join(" ")
  if (clean.length < MIN_TERM_LENGTH || clean.length > MAX_TERM_LENGTH) {
    return `Entre ${MIN_TERM_LENGTH} y ${MAX_TERM_LENGTH} caracteres.`
  }
  if (brandKey(clean).length < MIN_TERM_LENGTH) return `Necesita al menos ${MIN_TERM_LENGTH} letras o números.`
  if (current.some((t) => brandKey(t) === brandKey(clean))) return "Ya está en la lista."
  if (current.length >= MAX_BRAND_TERMS) return `Como mucho ${MAX_BRAND_TERMS} términos.`
  return null
}

const LEGAL_SUFFIXES = /\b(s\.?\s?l\.?\s?u?\.?|s\.?\s?a\.?|s\.?\s?c\.?|slp|sociedad limitada|inc\.?|ltd\.?|llc|gmbh)\s*$/i

const SECOND_LEVEL = new Set(["com", "co", "org", "net", "gob", "gov", "edu", "ac", "nom"])

function domainLabel(value: string | null | undefined): string | null {
  const raw = value?.trim()
  if (!raw) return null
  const host = raw.startsWith("sc-domain:")
    ? raw.slice("sc-domain:".length)
    : (() => {
        try {
          return new URL(/^https?:\/\//.test(raw) ? raw : `https://${raw}`).hostname
        } catch {
          return null
        }
      })()
  if (!host) return null
  const parts = host.toLowerCase().replace(/^www\./, "").split(".").filter(Boolean)
  if (parts.length === 0) return null
  // ejemplo.com → ejemplo; ejemplo.com.es / ejemplo.co.uk → ejemplo
  const secondLevel = parts.length > 2 && SECOND_LEVEL.has(parts[parts.length - 2])
  const label = parts[Math.max(parts.length - (secondLevel ? 3 : 2), 0)]
  return label.replace(/[-_]+/g, " ").trim() || null
}

/**
 * Propuesta de términos a partir del dominio (Search Console o web) y del
 * nombre del cliente. Sólo propone: no se guarda nada hasta aceptar y guardar.
 */
export function suggestBrandTerms(
  client: { name: string; website?: string | null; gsc_url?: string | null },
  current: string[],
): string[] {
  const candidates = [
    domainLabel(client.gsc_url),
    domainLabel(client.website),
    (client.name ?? "").replace(LEGAL_SUFFIXES, "").replace(/[,.]+$/, "").trim(),
  ]
  const out: string[] = []
  for (const candidate of candidates) {
    if (!candidate) continue
    const term = candidate.split(/\s+/).filter(Boolean).join(" ").toLowerCase()
    if (brandTermProblem(term, [...current, ...out]) === null) out.push(term)
  }
  return out
}

// Grupos de URL: mismos límites que el backend (que además valida las regex).
export const MAX_PAGE_GROUPS = 30
export const MAX_GROUP_RULES = 20
export const MAX_GROUP_NAME = 60
export const MAX_RULE_VALUE = 200
export const UNGROUPED = "Sin grupo"

/** Primer problema de los grupos que se están editando, o null. Las regex las revisa el servidor. */
export function pageGroupsProblem(groups: SeoPageGroup[]): string | null {
  if (groups.length > MAX_PAGE_GROUPS) return `Como mucho ${MAX_PAGE_GROUPS} grupos.`
  const seen = new Set<string>()
  for (const [index, group] of groups.entries()) {
    const name = group.name.split(/\s+/).filter(Boolean).join(" ")
    if (!name) return `El grupo ${index + 1} necesita un nombre.`
    if (name.length > MAX_GROUP_NAME) return `«${name}»: el nombre tiene más de ${MAX_GROUP_NAME} caracteres.`
    const key = name.toLocaleLowerCase("es")
    if (key === UNGROUPED.toLocaleLowerCase("es")) return `«${UNGROUPED}» está reservado.`
    if (seen.has(key)) return `Hay dos grupos llamados «${name}».`
    seen.add(key)
    if (group.rules.length === 0) return `«${name}» necesita al menos una regla.`
    if (group.rules.length > MAX_GROUP_RULES) return `«${name}» tiene más de ${MAX_GROUP_RULES} reglas.`
    for (const rule of group.rules) {
      const value = rule.value.trim()
      if (!value) return `«${name}» tiene una regla vacía.`
      if (value.length > MAX_RULE_VALUE) return `«${name}»: cada regla tiene como mucho ${MAX_RULE_VALUE} caracteres.`
    }
  }
  return null
}

/** Texto para el estado vacío de cada estado de la propiedad. */
export function seoStatusMessage(status: Exclude<SeoControlStatus, "ok">, errorCode: string | null): string {
  switch (status) {
    case "no_property":
      return "Este cliente no tiene propiedad de Search Console."
    case "not_connected":
      return "Search Console no está conectado."
    case "reconnect_required":
      return "La cuenta de Google de esta propiedad necesita reconectarse."
    case "not_synced":
    case "backfilling":
      return "Importando consultas y páginas; listo tras la próxima pasada."
    case "error":
      return gscErrorLabel(errorCode) ?? "Search Console no respondió. Se reintentará en la próxima pasada."
  }
}

export function formatInt(value: number): string {
  return value.toLocaleString("es-ES")
}

export function formatPosition(value: number | null): string {
  return value == null ? "—" : value.toLocaleString("es-ES", { minimumFractionDigits: 1, maximumFractionDigits: 1 })
}

export function formatShare(value: number | null): string {
  return value == null ? "—" : `${(value * 100).toLocaleString("es-ES", { maximumFractionDigits: 1 })} %`
}

/** "18 oct" */
export function formatShortDay(value: string): string {
  return new Date(`${value}T12:00:00`).toLocaleDateString("es-ES", { day: "numeric", month: "short" })
}
