import { setRuntimeHiddenModules } from "@/lib/hidden-modules"

const DEFAULT_AGENCY_TIMEZONE = "Europe/Madrid"

let agencyTimezone = DEFAULT_AGENCY_TIMEZONE
let configPromise: Promise<string> | null = null

export function setAgencyTimezone(timezone: string) {
  // Intl validates IANA zone names without adding another timezone registry.
  new Intl.DateTimeFormat("en", { timeZone: timezone }).format()
  agencyTimezone = timezone
}

export function getAgencyTimezone() {
  return agencyTimezone
}

export function agencyTimezoneLabel() {
  return agencyTimezone === "Europe/Madrid" ? "Hora de Madrid" : `Hora de ${agencyTimezone}`
}

export function loadAgencyTimezone(): Promise<string> {
  if (!configPromise) {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 5_000)
    configPromise = fetch("/api/config", { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Config HTTP ${response.status}`)
        const config = await response.json() as { timezone?: string; hidden_modules?: string[] }
        if (config.timezone) setAgencyTimezone(config.timezone)
        if (Array.isArray(config.hidden_modules)) setRuntimeHiddenModules(config.hidden_modules)
        return agencyTimezone
      })
      .catch(() => agencyTimezone)
      .finally(() => clearTimeout(timeout))
  }
  return configPromise
}

function zonedParts(value: Date, timezone = agencyTimezone) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(value)
  return Object.fromEntries(parts.map((part) => [part.type, part.value]))
}

export function businessDateString(value = new Date()) {
  const parts = zonedParts(value)
  return `${parts.year}-${parts.month}-${parts.day}`
}

export function businessHour(value = new Date()) {
  return Number(zonedParts(value).hour)
}

export function parseCivilDate(value: string) {
  const [year, month, day] = value.slice(0, 10).split("-").map(Number)
  return new Date(year, month - 1, day, 12)
}

export function formatCivilDate(value: string, options?: Intl.DateTimeFormatOptions) {
  return parseCivilDate(value).toLocaleDateString("es-ES", options)
}

export function addCivilDays(value: string, days: number) {
  const [year, month, day] = value.split("-").map(Number)
  const shifted = new Date(Date.UTC(year, month - 1, day + days))
  return shifted.toISOString().slice(0, 10)
}

export function civilDayDifference(from: string, to: string) {
  const [fromYear, fromMonth, fromDay] = from.split("-").map(Number)
  const [toYear, toMonth, toDay] = to.split("-").map(Number)
  return Math.round(
    (Date.UTC(toYear, toMonth - 1, toDay) - Date.UTC(fromYear, fromMonth - 1, fromDay)) / 86_400_000,
  )
}

export function parseApiInstant(value: string) {
  const explicit = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`
  return new Date(explicit)
}

export function timeEntryBusinessDate(entry: { date: string; started_at?: string | null }) {
  return entry.started_at
    ? businessDateString(parseApiInstant(entry.date))
    : entry.date.slice(0, 10)
}

function civilMidnightUtc(value: string) {
  const [year, month, day] = value.split("-").map(Number)
  let candidate = Date.UTC(year, month - 1, day)
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const parts = zonedParts(new Date(candidate))
    const represented = Date.UTC(
      Number(parts.year), Number(parts.month) - 1, Number(parts.day),
      Number(parts.hour), Number(parts.minute), Number(parts.second),
    )
    candidate -= represented - Date.UTC(year, month - 1, day)
  }
  return new Date(candidate)
}

export function civilDayUtcRange(value: string) {
  return {
    start: civilMidnightUtc(value).toISOString(),
    end: civilMidnightUtc(addCivilDays(value, 1)).toISOString(),
  }
}

export function civilDateRangeUtc(from: string, to: string) {
  const start = civilMidnightUtc(from)
  const endExclusive = civilMidnightUtc(addCivilDays(to, 1))
  return {
    start: start.toISOString(),
    endInclusive: new Date(endExclusive.getTime() - 1).toISOString(),
  }
}

export function millisecondsUntilNextBusinessDay(now = new Date()) {
  const today = businessDateString(now)
  let low = now.getTime()
  let high = low + 30 * 60 * 60 * 1000
  while (high - low > 1000) {
    const middle = Math.floor((low + high) / 2)
    if (businessDateString(new Date(middle)) === today) low = middle
    else high = middle
  }
  return Math.max(1, high - now.getTime())
}
