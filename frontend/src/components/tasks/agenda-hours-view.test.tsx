import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import type { Task } from "@/lib/types"
import { AgendaHoursView } from "./agenda-hours-view"

const api = vi.hoisted(() => ({ list: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn(), events: vi.fn() }))
vi.mock("@/lib/api", () => ({
  timeBlocksApi: { list: api.list, create: api.create, update: api.update, delete: api.remove },
  calendarApi: { events: api.events },
}))
vi.mock("@/components/timer/timer-button", () => ({ TimerButton: ({ taskTitle }: { taskTitle?: string }) => <button type="button">Cronómetro de {taskTitle}</button> }))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const task = (id: number, title: string, extra: Partial<Task> = {}) => ({ id, title, status: "pending", estimated_minutes: 90, client_name: "Acme", ...extra }) as Task
const block = { id: 7, task_id: 1, starts_at: "2026-10-27T10:00:00", ends_at: "2026-10-27T11:30:00", task_title: "Informe", task_status: "pending", task_estimated_minutes: 90, client_name: "Acme" }

function show(props: Partial<Parameters<typeof AgendaHoursView>[0]> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const handlers = { onAnchorChange: vi.fn(), onModeChange: vi.fn(), onOpenTask: vi.fn() }
  render(
    <QueryClientProvider client={client}>
      <AgendaHoursView mode="day" anchor="2026-10-27" today="2026-10-27" candidates={[task(1, "Informe"), task(2, "Auditoría")]} canWrite {...handlers} {...props} />
    </QueryClientProvider>,
  )
  return handlers
}

describe("AgendaHoursView", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.list.mockResolvedValue([block])
    api.events.mockResolvedValue([{ id: 3, title: "Llamada con Acme", start_time: "2026-10-27T12:00:00", end_time: "2026-10-27T12:30:00", is_all_day: false, source: "google" }])
    api.create.mockImplementation(async (data) => ({ ...block, id: 8, ...data, task_title: "Auditoría" }))
    api.remove.mockResolvedValue(undefined)
  })

  it("pinta reuniones y bloques del día y deja en la lista lo que no tiene hora", async () => {
    show()
    expect(await screen.findByText("Llamada con Acme")).toBeInTheDocument()
    expect(screen.getByLabelText("Bloque de Informe, de 10:00 a 11:30")).toBeInTheDocument()
    expect(api.list).toHaveBeenCalledWith("2026-10-27", "2026-10-27")
    const aside = screen.getByRole("complementary", { name: "Tareas sin hora" })
    await waitFor(() => expect(within(aside).queryByText("Informe")).not.toBeInTheDocument())
    expect(within(aside).getByText("Auditoría")).toBeInTheDocument()
    expect(within(aside).getByText("Acme · 90 min")).toBeInTheDocument()
  })

  it("la semana pide de lunes a viernes y se mueve de semana en semana", async () => {
    const handlers = show({ mode: "week", anchor: "2026-10-29" })
    await waitFor(() => expect(api.list).toHaveBeenCalledWith("2026-10-26", "2026-10-30"))
    expect(screen.getAllByRole("region", { name: /^Horas del/ })).toHaveLength(5)
    await userEvent.click(screen.getByRole("button", { name: "Semana siguiente" }))
    expect(handlers.onAnchorChange).toHaveBeenCalledWith("2026-11-05")
  })

  it("pone hora sin arrastrar y quita un bloque", async () => {
    show()
    await userEvent.click(await screen.findByRole("button", { name: "Poner hora a Auditoría" }))
    fireEvent.change(screen.getByLabelText("Hoy a las"), { target: { value: "16:00" } })
    await userEvent.click(screen.getByRole("button", { name: "Añadir bloque" }))
    await waitFor(() => expect(api.create).toHaveBeenCalledWith({ task_id: 2, starts_at: "2026-10-27T16:00", ends_at: "2026-10-27T17:30" }))

    await userEvent.click(screen.getByRole("button", { name: "Quitar el bloque de Informe" }))
    await waitFor(() => expect(api.remove).toHaveBeenCalledWith(7))
  })

  it("cambia la hora de un bloque con el teclado", async () => {
    show()
    await userEvent.click(await screen.findByRole("button", { name: "Cambiar la hora del bloque de Informe" }))
    fireEvent.change(screen.getByLabelText("De"), { target: { value: "09:00" } })
    fireEvent.change(screen.getByLabelText("A"), { target: { value: "09:45" } })
    await userEvent.click(screen.getByRole("button", { name: "Guardar" }))
    await waitFor(() => expect(api.update).toHaveBeenCalledWith(7, { starts_at: "2026-10-27T09:00", ends_at: "2026-10-27T09:45" }))
  })

  it("sin escritura se ve pero no se toca", async () => {
    show({ canWrite: false })
    expect(await screen.findByLabelText("Bloque de Informe, de 10:00 a 11:30")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /Quitar el bloque/ })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /Poner hora/ })).not.toBeInTheDocument()
    expect(screen.getByText("Sin permiso para planificar.")).toBeInTheDocument()
  })
})
