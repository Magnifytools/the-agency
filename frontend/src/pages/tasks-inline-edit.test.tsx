import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import type { TaskPanelProps } from "@/components/tasks/task-panel"
import TasksPage from "./tasks-page"

const api = vi.hoisted(() => ({
  list: vi.fn(), update: vi.fn(), bulkUpdate: vi.fn(), users: vi.fn(), canWrite: true,
  user: { id: 1, role: "admin" },
}))
vi.mock("@/hooks/use-business-date", () => ({ useBusinessDate: () => "2026-10-01" }))
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: api.user, isAdmin: true, hasPermission: () => api.canWrite }) }))
vi.mock("@/lib/api", () => ({
  tasksApi: { list: api.list, listAll: vi.fn().mockResolvedValue([]), agenda: vi.fn(), update: api.update, bulkUpdate: api.bulkUpdate },
  clientsApi: { listAll: vi.fn().mockResolvedValue([]) }, categoriesApi: { list: vi.fn().mockResolvedValue([]) },
  usersApi: { listAll: api.users }, projectsApi: { listAll: vi.fn() }, timeEntriesApi: {}, changesApi: { recent: vi.fn(), undo: vi.fn() },
}))
// El panel tiene su propio test: aquí sólo importa qué tarea abre y cómo pasa a otra.
vi.mock("@/components/tasks/task-panel", () => ({
  TaskPanel: ({ open, taskId, navigation }: TaskPanelProps) => open ? (
    <div role="dialog" aria-label="Panel">
      <p>Tarea {taskId}</p>
      {navigation && <p>{navigation.position} de {navigation.total}</p>}
      <button onClick={() => navigation?.onNavigate(1)}>Siguiente</button>
    </div>
  ) : null,
}))

const row = (id: number, title: string, extra: Record<string, unknown> = {}) => ({
  id, title, status: "pending", priority: "medium", assigned_to: null, assigned_user_name: null,
  scheduled_date: null, estimated_minutes: null, actual_minutes: null, due_date: null, checklist_count: 0, ...extra,
})

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/tasks?view=all"]}><TasksPage /></MemoryRouter></QueryClientProvider>)
}

describe("Tareas: edición en línea", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.canWrite = true
    api.list.mockResolvedValue({ items: [row(8, "Preparar informe"), row(9, "Revisar enlaces")], total: 2, page: 1, page_size: 25 })
    api.update.mockImplementation(async (id: number, data: object) => ({ ...row(id, "x"), ...data }))
    api.bulkUpdate.mockResolvedValue({ updated: 1, requested: 1, results: [] })
    api.users.mockResolvedValue([{ id: 3, full_name: "Nacho", is_active: true }, { id: 4, full_name: "Antiguo", is_active: false }])
  })

  it("cambia la prioridad desde la celda y se ve al momento", async () => {
    let resolve: (value: unknown) => void = () => {}
    api.update.mockReturnValueOnce(new Promise((done) => { resolve = done }))
    show()
    await userEvent.click(await screen.findByRole("button", { name: "Prioridad de Preparar informe: Media" }))
    await userEvent.click(within(screen.getByRole("listbox", { name: "Prioridad de Preparar informe" })).getByRole("option", { name: "Alta" }))
    expect(api.update).toHaveBeenCalledWith(8, { priority: "high" })
    // Antes de que conteste el servidor.
    expect(screen.getByRole("button", { name: "Prioridad de Preparar informe: Alta" })).toBeInTheDocument()
    resolve(row(8, "Preparar informe", { priority: "high" }))
  })

  it("asigna responsable entre las personas activas", async () => {
    api.update.mockReturnValueOnce(new Promise(() => {}))
    show()
    await userEvent.click(await screen.findByRole("button", { name: "Responsable de Preparar informe: Sin asignar" }))
    const listbox = screen.getByRole("listbox", { name: "Responsable de Preparar informe" })
    expect(within(listbox).getAllByRole("option").map((option) => option.textContent)).toEqual(["Sin asignar", "Nacho"])
    await userEvent.click(within(listbox).getByRole("option", { name: "Nacho" }))
    expect(api.update).toHaveBeenCalledWith(8, { assigned_to: 3 })
    expect(screen.getByRole("button", { name: "Responsable de Preparar informe: Nacho" })).toBeInTheDocument()
  })

  it("planifica con un atajo y estima con texto libre", async () => {
    show()
    await userEvent.click(await screen.findByRole("button", { name: "Planificada de Preparar informe: sin fecha" }))
    await userEvent.click(screen.getByRole("option", { name: /Mañana/ }))
    expect(api.update).toHaveBeenCalledWith(8, { scheduled_date: "2026-10-02" })

    await userEvent.click(screen.getByRole("button", { name: "Estimación de Revisar enlaces: sin estimar" }))
    await userEvent.type(screen.getByLabelText("Otra"), "1h 30m{Enter}")
    expect(api.update).toHaveBeenCalledWith(9, { estimated_minutes: 90 })
  })

  it("cambia el título sin abrir la tarea; Escape lo deja como estaba", async () => {
    show()
    await userEvent.click(await screen.findByRole("button", { name: "Cambiar título de Preparar informe" }))
    await userEvent.keyboard("{Escape}")
    expect(api.update).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole("button", { name: "Cambiar título de Preparar informe" }))
    const input = screen.getByRole("textbox", { name: "Título de Preparar informe" })
    await userEvent.clear(input)
    await userEvent.type(input, "Informe de octubre{Enter}")
    expect(api.update).toHaveBeenCalledWith(8, { title: "Informe de octubre" })
  })

  it("sin escritura en Tareas los valores se ven pero no se editan", async () => {
    api.canWrite = false
    show()
    expect(await screen.findByText("Preparar informe")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /Prioridad de/ })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /Responsable de/ })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /Planificada de/ })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /Cambiar título/ })).not.toBeInTheDocument()
    expect(within(screen.getByRole("table")).getAllByText("Media")).toHaveLength(2)
  })

  it("planifica varias tareas a la vez", async () => {
    show()
    await userEvent.click(await screen.findByRole("checkbox", { name: "Seleccionar todas las tareas visibles" }))
    await userEvent.click(screen.getByRole("button", { name: /Planificar las tareas seleccionadas/ }))
    await userEvent.click(screen.getByRole("option", { name: /El lunes/ }))
    await waitFor(() => expect(api.bulkUpdate).toHaveBeenCalledWith(expect.arrayContaining([8, 9]), { scheduled_date: "2026-10-05" }))

    await userEvent.click(screen.getByRole("checkbox", { name: "Seleccionar todas las tareas visibles" }))
    await userEvent.click(screen.getByRole("button", { name: /Planificar las tareas seleccionadas/ }))
    await userEvent.click(screen.getByRole("option", { name: "Sin planificar" }))
    await waitFor(() => expect(api.bulkUpdate).toHaveBeenLastCalledWith(expect.arrayContaining([8, 9]), { scheduled_date: null }))
  })

  it("el panel pasa a la siguiente tarea de la lista", async () => {
    show()
    await userEvent.click(await screen.findByRole("button", { name: "Preparar informe" }))
    const panel = screen.getByRole("dialog", { name: "Panel" })
    expect(within(panel).getByText("Tarea 8")).toBeInTheDocument()
    expect(within(panel).getByText("1 de 2")).toBeInTheDocument()
    await userEvent.click(within(panel).getByRole("button", { name: "Siguiente" }))
    expect(within(panel).getByText("Tarea 9")).toBeInTheDocument()
    expect(within(panel).getByText("2 de 2")).toBeInTheDocument()
  })
})
