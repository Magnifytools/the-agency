import type { DigestTone } from "@/lib/types"

const PREFIX = "agency:digest-generation:"
const KEY_PATTERN = /^[A-Za-z0-9_-]{16,64}$/

export interface IndividualDigestIntent {
  kind: "individual"
  operation_key: string
  generation_key: string
  client_id: number
  tone: DigestTone
  period_start?: string
  period_end?: string
}

export interface ToneDigestIntent {
  kind: "tone"
  operation_key: string
  generation_key: string
  digest_id: number
  tone: DigestTone
}

export interface CohortDigestIntent {
  kind: "cohort"
  operation_key: string
  tone: DigestTone
  items: Array<{
    generation_key: string
    client_id: number
    policy_revision: number
    period_start: string
    period_end: string
  }>
}

export type DigestGenerationIntent = IndividualDigestIntent | ToneDigestIntent | CohortDigestIntent

function storageKey(userId: number, operationKey: string) {
  return `${PREFIX}${userId}:${operationKey}`
}

function validKey(value: unknown): value is string {
  return typeof value === "string" && KEY_PATTERN.test(value)
}

function validIntent(value: unknown): value is DigestGenerationIntent {
  if (!value || typeof value !== "object") return false
  const intent = value as { kind?: unknown; operation_key?: unknown }
  if (!validKey(intent.operation_key) || !["individual", "tone", "cohort"].includes(String(intent.kind))) return false
  if (intent.kind === "individual") {
    const individual = value as Partial<IndividualDigestIntent>
    return validKey(individual.generation_key) && Number.isInteger(individual.client_id) && !!individual.tone
  }
  if (intent.kind === "tone") {
    const tone = value as Partial<ToneDigestIntent>
    return validKey(tone.generation_key) && Number.isInteger(tone.digest_id) && !!tone.tone
  }
  const cohort = value as Partial<CohortDigestIntent>
  return !!cohort.tone && Array.isArray(cohort.items) && cohort.items.length > 0 && cohort.items.every(item =>
    validKey(item.generation_key) && Number.isInteger(item.client_id) && Number.isInteger(item.policy_revision)
      && typeof item.period_start === "string" && typeof item.period_end === "string",
  )
}

export function newDigestGenerationKey() {
  return crypto.randomUUID()
}

export function persistDigestGeneration(userId: number, intent: DigestGenerationIntent) {
  try {
    localStorage.setItem(storageKey(userId, intent.operation_key), JSON.stringify(intent))
    return true
  } catch {
    return false
  }
}

export function clearDigestGeneration(userId: number, operationKey: string) {
  try {
    localStorage.removeItem(storageKey(userId, operationKey))
  } catch {
    // A confirmed server result must not remain blocked by unavailable storage.
  }
}

export function readDigestGenerations(userId: number) {
  const prefix = `${PREFIX}${userId}:`
  const intents: DigestGenerationIntent[] = []
  try {
    for (let index = 0; index < localStorage.length; index += 1) {
      const key = localStorage.key(index)
      if (!key?.startsWith(prefix)) continue
      const raw = localStorage.getItem(key)
      if (!raw) continue
      const parsed: unknown = JSON.parse(raw)
      if (validIntent(parsed)) intents.push(parsed)
    }
    return { intents, failed: false }
  } catch {
    return { intents: [], failed: true }
  }
}

export function httpStatus(error: unknown) {
  return (error as { response?: { status?: number } })?.response?.status
}

function errorCode(error: unknown) {
  return (error as { response?: { data?: { detail?: { code?: unknown } } } })?.response?.data?.detail?.code
}

export function isConfirmedFailure(error: unknown) {
  const status = httpStatus(error)
  // A changed source is a definite rejection, but the same persisted intent is
  // still the safe retry vehicle: the server will collect fresh facts under its
  // original generation key.
  if (errorCode(error) === "sources_changed" || errorCode(error) === "source_changed") return false
  return status !== undefined && status >= 400 && status < 500
}
