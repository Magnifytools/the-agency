import { beforeEach, describe, expect, it, vi } from "vitest"
import { showUndoResult } from "./undo-feedback"

const mocks = vi.hoisted(() => ({ warning: vi.fn(), success: vi.fn() }))
vi.mock("sonner", () => ({ toast: mocks }))
const result = { id: 1, label: "Tarea editada", restored: 1, warnings: [] as string[] }

describe("Undo feedback respects protected later work", () => {
  beforeEach(() => vi.clearAllMocks())
  it("never claims success if no operation could be restored", () => {
    showUndoResult({ ...result, restored: 0, warnings: ["Otra persona cambió el título"] })
    expect(mocks.success).not.toHaveBeenCalled()
    expect(mocks.warning).toHaveBeenCalledWith("No se ha restaurado ningún cambio", expect.objectContaining({ description: "Otra persona cambió el título" }))
  })
  it("distinguishes partial recovery and preserves the reason", () => {
    showUndoResult({ ...result, warnings: ["La fecha se ha conservado"] })
    expect(mocks.warning).toHaveBeenCalledWith("Deshecho parcialmente: Tarea editada", expect.objectContaining({ description: "La fecha se ha conservado" }))
  })
  it("confirms a fully restored operation", () => {
    showUndoResult(result)
    expect(mocks.success).toHaveBeenCalledWith("Deshecho: Tarea editada")
    expect(mocks.warning).not.toHaveBeenCalled()
  })
})
