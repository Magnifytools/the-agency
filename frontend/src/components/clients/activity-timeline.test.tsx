import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, cleanup, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"
import { ActivityTimeline } from "./activity-timeline"

const api = vi.hoisted(() => ({ list: vi.fn() }))
vi.mock("@/lib/api", () => ({ clientActivityApi: { list: api.list } }))

describe("ActivityTimeline recovery", () => {
  it("hides cached events after failure and restores only a fresh success", async () => {
    const event = { id: "task-1", type: "task_completed", subtype: "", timestamp: "2026-09-21T10:00:00Z", title: "Tarea terminada", description: null, detail: null, user_name: null, icon: "check" }
    api.list.mockResolvedValueOnce([event])
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><ActivityTimeline clientId={3} /></QueryClientProvider>)
    expect(await screen.findByText("Tarea terminada")).toBeInTheDocument()
    api.list.mockRejectedValueOnce(new Error("offline"))
    await act(async () => { await client.invalidateQueries({ queryKey: ["client-activity", 3] }) })
    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo cargar")
    expect(screen.queryByText("Tarea terminada")).not.toBeInTheDocument()
    expect(screen.queryByText("Sin actividad registrada")).not.toBeInTheDocument()
    api.list.mockResolvedValueOnce([event])
    await userEvent.click(screen.getByRole("button", { name: "Reintentar" }))
    expect(await screen.findByText("Tarea terminada")).toBeInTheDocument()
    expect(screen.getByText(/fecha de finalización registrada/)).toBeInTheDocument()
  })

  it("does not resurrect denied cache after remount and a later server error", async () => {
    const event = { id: "task-2", type: "task_completed", subtype: "", timestamp: "2026-09-21T10:00:00Z", title: "Dato privado", description: null, detail: null, user_name: null, icon: "check" }
    api.list.mockResolvedValueOnce([event])
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const tree = <QueryClientProvider client={client}><ActivityTimeline clientId={7} /></QueryClientProvider>
    render(tree)
    expect(await screen.findByText("Dato privado")).toBeInTheDocument()
    api.list.mockRejectedValueOnce({ response: { status: 403 } })
    await act(async () => { await client.invalidateQueries({ queryKey: ["client-activity", 7] }) })
    expect(await screen.findByRole("alert")).toBeInTheDocument()
    cleanup()
    api.list.mockRejectedValueOnce({ response: { status: 503 } })
    render(tree)
    expect(await screen.findByRole("alert")).toBeInTheDocument()
    expect(screen.queryByText("Dato privado")).not.toBeInTheDocument()
  })
})
