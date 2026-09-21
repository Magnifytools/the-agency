import { beforeEach, expect, it, vi } from "vitest"
import { reportPolicyApi } from "./report-policy-api"
const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }))
vi.mock("@/lib/api", () => ({ api }))
beforeEach(() => { vi.resetAllMocks(); for (const fn of Object.values(api)) fn.mockResolvedValue({ data: { ok: true } }) })
it("uses scoped preview and submits only the reviewed cohort and exact periods", async () => {
  await reportPolicyApi.generationPreview("mine")
  expect(api.get).toHaveBeenCalledWith("/digests/generation-preview", { params: { scope: "mine" } })
  const body = { items: [{ generation_key: "stable-generation-key", client_id: 12, policy_revision: 3, period_start: "2026-08-01", period_end: "2026-08-31" }], tone: "formal" as const }
  await reportPolicyApi.generateCohort(body)
  expect(api.post).toHaveBeenCalledWith("/digests/generate-cohort", body, { timeout: 300_000 })
})
it("preserves revision and explicit external event identity", async () => {
  const body = { enabled: true, cadence: "monthly" as const, responsible_user_id: 2, revision: 4 }
  await reportPolicyApi.getPolicy(9)
  await reportPolicyApi.updatePolicy(9, body)
  await reportPolicyApi.responsibles()
  await reportPolicyApi.externalEvents(21)
  await reportPolicyApi.recordExternalEvent(21, "revoked", "stable-intention")
  expect(api.get).toHaveBeenCalledWith("/digests/policies/9")
  expect(api.put).toHaveBeenCalledWith("/digests/policies/9", body)
  expect(api.get).toHaveBeenCalledWith("/digests/policy-responsibles")
  expect(api.get).toHaveBeenCalledWith("/digests/21/external-delivery-events")
  expect(api.post).toHaveBeenCalledWith("/digests/21/external-delivery-events", { action: "revoked" }, { headers: { "X-Agency-Request-Key": "stable-intention" } })
})
