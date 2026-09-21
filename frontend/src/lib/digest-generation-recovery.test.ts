import { beforeEach, describe, expect, it, vi } from "vitest"
import { clearDigestGeneration, isConfirmedFailure, newDigestGenerationKey, persistDigestGeneration, readDigestGenerations } from "./digest-generation-recovery"

describe("digest generation recovery storage", () => {
  beforeEach(() => localStorage.clear())

  it("isolates pending generation metadata by user without storing content", () => {
    const operation_key = newDigestGenerationKey()
    const generation_key = newDigestGenerationKey()
    expect(persistDigestGeneration(7, { kind: "individual", operation_key, generation_key, client_id: 4, tone: "cercano" })).toBe(true)
    expect(readDigestGenerations(8).intents).toEqual([])
    expect(readDigestGenerations(7).intents).toEqual([{ kind: "individual", operation_key, generation_key, client_id: 4, tone: "cercano" }])
    expect(JSON.stringify(localStorage)).not.toContain("greeting")
    clearDigestGeneration(7, operation_key)
    expect(readDigestGenerations(7).intents).toEqual([])
  })

  it("fails closed when storage cannot persist the recovery key", () => {
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementationOnce(() => { throw new Error("blocked") })
    const key = newDigestGenerationKey()
    expect(persistDigestGeneration(7, { kind: "tone", operation_key: key, generation_key: key, digest_id: 2, tone: "formal" })).toBe(false)
    spy.mockRestore()
  })

  it("keeps the recovery key after sources change so the exact intent can retry", () => {
    expect(isConfirmedFailure({ response: { status: 409, data: { detail: { code: "sources_changed" } } } })).toBe(false)
    expect(isConfirmedFailure({ response: { status: 409, data: { detail: { code: "generation_key_conflict" } } } })).toBe(true)
  })
})
