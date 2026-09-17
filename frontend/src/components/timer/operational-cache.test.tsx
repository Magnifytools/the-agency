import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ActiveTimerBar } from "./active-timer-bar"
import { TimeLogDialog } from "./time-log-dialog"
import { clientKeys, dashboardKeys, myWeekKeys, projectKeys, taskKeys, timeKeys } from "@/lib/query-keys"

const api = vi.hoisted(() => ({
  active: vi.fn(),
  stop: vi.fn(),
  listEntries: vi.fn(),
  createEntry: vi.fn(),
  empty: vi.fn(),
}))

vi.mock("@/lib/api", () => ({
  timerApi: { active: api.active, stop: api.stop, start: vi.fn(), pause: vi.fn(), resume: vi.fn() },
  timeEntriesApi: { list: api.listEntries, create: api.createEntry, update: vi.fn(), delete: vi.fn() },
  tasksApi: { listAll: api.empty, create: vi.fn() },
  clientsApi: { listAll: api.empty },
  projectsApi: { listAll: api.empty },
}))

vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() }) }))

function setup(element: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const affectedKeys = [
    timeKeys.week("2026-09-14"),
    taskKeys.project(3),
    projectKeys.detail(3),
    dashboardKeys.overview(2026, 9),
    myWeekKeys.week("2026-09-14"),
    clientKeys.summary(2),
  ]
  affectedKeys.forEach((key) => client.setQueryData(key, { cached: true }))
  const unrelatedKey = ["settings", "holidays"] as const
  client.setQueryData(unrelatedKey, { cached: true })
  render(<QueryClientProvider client={client}>{element}</QueryClientProvider>)
  return { client, affectedKeys, unrelatedKey }
}

describe("time mutation cache surfaces", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.empty.mockResolvedValue([])
    api.listEntries.mockResolvedValue([])
  })

  it("manual hours refresh timesheet, task/project counters, dashboard, week and client summary", async () => {
    api.createEntry.mockResolvedValue({ id: 40, minutes: 30, task_id: 9 })
    const { client, affectedKeys, unrelatedKey } = setup(
      <TimeLogDialog taskId={9} taskTitle="Auditoría" open onOpenChange={vi.fn()} />,
    )

    await userEvent.click(screen.getByRole("button", { name: "Añadir manual" }))
    await userEvent.type(screen.getByLabelText("Minutos"), "30")
    await userEvent.click(screen.getByRole("button", { name: "Guardar" }))

    await waitFor(() => expect(api.createEntry).toHaveBeenCalledWith({ minutes: 30, task_id: 9, notes: undefined }))
    affectedKeys.forEach((key) => expect(client.getQueryState(key)?.isInvalidated).toBe(true))
    expect(client.getQueryState(unrelatedKey)?.isInvalidated).toBe(false)
  })

  it("stopping the global timer refreshes the same real consumers", async () => {
    api.active.mockResolvedValue({ id: 1, task_id: 9, task_title: "Auditoría", client_name: "Cliente", started_at: new Date().toISOString() })
    api.stop.mockResolvedValue({ id: 41, minutes: 5, task_id: 9 })
    const { client, affectedKeys, unrelatedKey } = setup(<ActiveTimerBar />)

    await userEvent.click(await screen.findByRole("button", { name: /Detener/ }))

    await waitFor(() => expect(api.stop).toHaveBeenCalled())
    affectedKeys.forEach((key) => expect(client.getQueryState(key)?.isInvalidated).toBe(true))
    expect(client.getQueryState(unrelatedKey)?.isInvalidated).toBe(false)
  })
})
