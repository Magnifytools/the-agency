/**
 * Importar accesos desde el CSV que exportan 1Password, Bitwarden o Chrome.
 *
 * El fichero se lee en el navegador: al servidor sólo llegan las filas que se
 * marcan, una vez, por HTTPS y como cualquier alta (la contraseña y la clave
 * 2FA se cifran allí). Nada se guarda en la caché ni en localStorage.
 */
import type { Credential, CredentialImportItem, ImportSource } from "@/lib/credentials-api"

export const MAX_IMPORT_ROWS = 500
const LIMITS = { name: 200, url: 500, username: 255, notes: 5000, secret: 2000 } as const

/** CSV (RFC 4180): comillas dobles, "" dentro de comillas, saltos de línea en campos, BOM. */
export function parseCsv(text: string): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let field = ""
  let quoted = false
  const input = text.replace(/^\uFEFF/, "")
  for (let i = 0; i < input.length; i++) {
    const char = input[i]
    if (quoted) {
      if (char === '"') {
        if (input[i + 1] === '"') {
          field += '"'
          i++
        } else quoted = false
      } else field += char
    } else if (char === '"') quoted = true
    else if (char === ",") {
      row.push(field)
      field = ""
    } else if (char === "\n" || char === "\r") {
      if (char === "\r" && input[i + 1] === "\n") i++
      row.push(field)
      rows.push(row)
      row = []
      field = ""
    } else field += char
  }
  if (field !== "" || row.length) {
    row.push(field)
    rows.push(row)
  }
  return rows.filter((r) => r.some((cell) => cell.trim() !== ""))
}

// Nombres de columna de cada gestor (en minúsculas), por campo.
const COLUMNS = {
  name: ["title", "name"],
  url: ["url", "website", "login_uri", "urls"],
  username: ["username", "login_username", "user name", "email"],
  secret: ["password", "login_password"],
  totp: ["otpauth", "login_totp", "totp", "one-time password", "otp"],
  notes: ["notes", "note", "notesplain"],
  archived: ["archived"],
  type: ["type"],
} as const

export interface ImportRow {
  /** Fila del CSV (la cabecera es la 1). */
  line: number
  name: string
  url: string | null
  username: string | null
  secret: string
  totp: string | null
  notes: string | null
  /** Por qué no se puede importar; null si se puede. */
  problem: string | null
  /** Ya hay un acceso con el mismo nombre y usuario: sale sin marcar. */
  duplicate: boolean
  archived: boolean
}

export interface ParsedExport {
  source: ImportSource
  rows: ImportRow[]
}

function detectSource(headers: string[]): ImportSource {
  if (headers.includes("otpauth") || (headers.includes("title") && headers.includes("archived"))) return "1password"
  if (headers.includes("login_password")) return "bitwarden"
  if (headers.join(",") === "name,url,username,password,note") return "chrome"
  return "csv"
}

const key = (name: string, username: string | null) => `${name.trim().toLowerCase()}\u0000${(username ?? "").trim().toLowerCase()}`

function clip(value: string | undefined, max: number): string | null {
  const clean = (value ?? "").trim()
  if (!clean) return null
  return clean.length > max ? `${clean.slice(0, max - 1)}…` : clean
}

/** Lee el CSV. Lanza un Error con un mensaje para enseñar si no se reconoce. */
export function readExport(text: string, existing: Pick<Credential, "name" | "username">[] = []): ParsedExport {
  const [header, ...body] = parseCsv(text)
  if (!header) throw new Error("El fichero está vacío.")
  const headers = header.map((h) => h.trim().toLowerCase())
  const column = (field: keyof typeof COLUMNS) => headers.findIndex((h) => (COLUMNS[field] as readonly string[]).includes(h))
  const at = Object.fromEntries(Object.keys(COLUMNS).map((f) => [f, column(f as keyof typeof COLUMNS)])) as Record<keyof typeof COLUMNS, number>
  if (at.name < 0 || at.secret < 0) {
    throw new Error("No parece una exportación de 1Password, Bitwarden o Chrome: faltan las columnas de nombre y contraseña.")
  }
  const known = new Set(existing.map((c) => key(c.name, c.username)))
  const seen = new Set<string>()
  const cell = (row: string[], index: number) => (index >= 0 ? row[index] : undefined)
  const rows = body.map((row, i): ImportRow => {
    const url = (cell(row, at.url) ?? "").split(/[\n,]/)[0]
    const name = clip(cell(row, at.name), LIMITS.name) ?? clip(url, LIMITS.name) ?? "Sin nombre"
    const username = clip(cell(row, at.username), LIMITS.username)
    const secret = (cell(row, at.secret) ?? "").trim()
    const type = (cell(row, at.type) ?? "").trim().toLowerCase()
    let problem: string | null = null
    if (type && type !== "login") problem = "No es un inicio de sesión"
    else if (!secret) problem = "Sin contraseña"
    else if (secret.length > LIMITS.secret) problem = "Contraseña de más de 2.000 caracteres"
    const id = key(name, username)
    const duplicate = known.has(id) || seen.has(id)
    seen.add(id)
    const trimmedUrl = url.trim()
    return {
      line: i + 2,
      name,
      url: trimmedUrl && trimmedUrl.length <= LIMITS.url ? trimmedUrl : null,
      username,
      secret,
      totp: clip(cell(row, at.totp), 2000),
      notes: clip(cell(row, at.notes), LIMITS.notes),
      problem,
      duplicate,
      archived: ["true", "1", "yes"].includes((cell(row, at.archived) ?? "").trim().toLowerCase()),
    }
  })
  return { source: detectSource(headers), rows }
}

/** Lo que se marca por defecto: importable, no repetida y no archivada. */
export const selectedByDefault = (row: ImportRow) => !row.problem && !row.duplicate && !row.archived

export function toImportItem(row: ImportRow, clientId: number | null): CredentialImportItem {
  return { name: row.name, url: row.url, username: row.username, secret: row.secret, totp: row.totp, notes: row.notes, client_id: clientId }
}
