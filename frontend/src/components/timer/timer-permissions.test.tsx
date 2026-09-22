import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, expect, it, vi } from "vitest"
import { ActiveTimerBar } from "./active-timer-bar"
import { TimerButton } from "./timer-button"
import { taskKeys } from "@/lib/query-keys"

const mocks = vi.hoisted(() => ({
  active: vi.fn(), start: vi.fn(), stop: vi.fn(), create: vi.fn(), tasks: vi.fn(), clients: vi.fn(), permission: vi.fn(),
}))
vi.mock("@/context/auth-context", () => ({useAuth: () => ({user: {id: 2}, hasPermission: mocks.permission})}))
vi.mock("@/lib/api", () => ({
  timerApi: {active: mocks.active, start: mocks.start, stop: mocks.stop}, tasksApi: {listAll: mocks.tasks, create: mocks.create}, clientsApi: {listAll: mocks.clients}, projectsApi: {listAll: vi.fn().mockResolvedValue([])}, timeEntriesApi: {},
}))
vi.mock("@/hooks/use-business-date", () => ({useBusinessDate: () => "2026-09-19"}))
function setup() {
  const client = new QueryClient({defaultOptions: {queries: {retry: false}}})
  const view = render(<QueryClientProvider client={client}><ActiveTimerBar /><TimerButton taskId={1} /></QueryClientProvider>)
  return { ...view, client }
}
beforeEach(() => {vi.resetAllMocks(); mocks.active.mockResolvedValue(null); mocks.tasks.mockResolvedValue([]); mocks.clients.mockResolvedValue([])})
it.each([false, true])("does not poll or offer timer writes without timesheet write permission (read=%s)", async read => {
  mocks.permission.mockImplementation((module, write) => module === "timesheet" && read && !write)
  const view = setup()
  await Promise.resolve()
  expect(view.container).toBeEmptyDOMElement()
  expect(mocks.active).not.toHaveBeenCalled()
  expect(mocks.tasks).not.toHaveBeenCalled()
  expect(mocks.clients).not.toHaveBeenCalled()
})

it("drops cached task choices immediately when task read access is revoked", async () => {
  let canReadTasks = true
  mocks.permission.mockImplementation((module, write) => module === "timesheet" || (module === "tasks" && canReadTasks && !write))
  mocks.tasks.mockResolvedValue([{ id: 4, title: "Tarea privada" }])
  const view = setup()
  await screen.findByRole("option", { name: "Tarea privada" })

  mocks.tasks.mockRejectedValueOnce({ response: { status: 403 } })
  await view.client.invalidateQueries({ queryKey: taskKeys.assigned("timer", "me", "2026-09-19") })
  await waitFor(() => expect(screen.queryByRole("option", { name: "Tarea privada" })).not.toBeInTheDocument())

  canReadTasks = false
  view.rerender(<QueryClientProvider client={view.client}><ActiveTimerBar /><TimerButton taskId={1} /></QueryClientProvider>)
  expect(screen.queryByRole("option", { name: "Tarea privada" })).not.toBeInTheDocument()
})

it("does not submit a previously selected task after task read is revoked", async () => {
  let canReadTasks = true
  mocks.permission.mockImplementation((module, write) => module === "timesheet" || (module === "tasks" && canReadTasks && !write))
  mocks.tasks.mockResolvedValue([{ id: 4, title: "Tarea privada" }])
  const view = setup()
  await screen.findByRole("option", { name: "Tarea privada" })
  fireEvent.change(screen.getByLabelText("Tarea del cronómetro"), { target: { value: "4" } })
  const input = screen.getByPlaceholderText("¿En qué estás trabajando?")
  fireEvent.change(input, { target: { value: "Nota sin tarea" } })

  canReadTasks = false
  view.rerender(<QueryClientProvider client={view.client}><ActiveTimerBar /><TimerButton taskId={1} /></QueryClientProvider>)
  fireEvent.submit(input.closest("form")!)
  await waitFor(() => expect(mocks.start).toHaveBeenCalledWith({ notes: "Nota sin tarea" }))
})

it("offers own active work beyond today and puts today's task first", async () => {
  mocks.permission.mockReturnValue(true)
  mocks.tasks.mockResolvedValue([
    { id: 1, title: "Sin fecha", scheduled_date: null },
    { id: 2, title: "Futura", scheduled_date: "2026-09-23" },
    { id: 3, title: "Arrastre", scheduled_date: "2026-09-18" },
    { id: 4, title: "Para hoy", scheduled_date: "2026-09-19" },
    { id: 5, title: "Backlog", scheduled_date: null, status: "backlog" },
  ])

  setup()

  const selector = await screen.findByRole("combobox", { name: "Tarea del cronómetro" })
  expect(mocks.tasks).toHaveBeenCalledWith({
    assigned_to: "me",
    is_recurring: false,
    status: "backlog,pending,in_progress,advanced,waiting,in_review",
    timer_eligible: true,
  })
  expect(within(selector).getAllByRole("option").map((option) => option.textContent)).toEqual([
    "Sin tarea",
    "Para hoy",
    "Arrastre",
    "Backlog",
    "Sin fecha",
    "Futura",
  ])

  fireEvent.change(selector, { target: { value: "1" } })
  fireEvent.submit(selector.closest("form")!)
  await waitFor(() => expect(mocks.start).toHaveBeenCalledWith({ task_id: 1, notes: undefined }))
})

it("distinguishes a loading task selector from an empty one", async () => {
  mocks.permission.mockReturnValue(true)
  mocks.tasks.mockImplementation(() => new Promise(() => undefined))

  setup()

  const selector = await screen.findByRole("combobox", { name: "Tarea del cronómetro" })
  expect(selector).toBeDisabled()
  expect(within(selector).getByRole("option", { name: "Cargando tareas…" })).toBeInTheDocument()
})

it("uses the same eligible task choices after stopping an unassigned timer", async () => {
  mocks.permission.mockReturnValue(true)
  mocks.active.mockResolvedValue({ id: 9, task_id: null, task_title: "Nota", started_at: new Date().toISOString() })
  mocks.stop.mockResolvedValue({ id: 18, task_id: null })
  mocks.tasks.mockResolvedValue([
    { id: 1, title: "Sin fecha", scheduled_date: null },
    { id: 2, title: "Para hoy", scheduled_date: "2026-09-19" },
  ])

  setup()
  await userEvent.click(await screen.findByRole("button", { name: "Detener" }))

  const selector = await screen.findByRole("combobox", { name: "Tarea para asignar el registro" })
  expect(within(selector).getAllByRole("option").map((option) => option.textContent)).toEqual([
    "Selecciona tarea",
    "Para hoy",
    "Sin fecha",
  ])
})

it("keeps a newly created unassigned task visible, then clears it on task-read revocation", async () => {
  let canReadTasks = true
  mocks.permission.mockImplementation((module) => module === "timesheet" || (module === "tasks" && canReadTasks) || module === "clients")
  mocks.tasks.mockResolvedValue([])
  mocks.clients.mockResolvedValue([{ id: 7, name: "Cliente" }])
  mocks.active.mockResolvedValue(null)
  mocks.create.mockResolvedValue({ id: 12, title: "Tarea recién creada", client_id: 7, project_id: null })

  const view = setup()
  await userEvent.click(await screen.findByRole("button", { name: "Crear tarea rápida" }))
  const dialog = screen.getByRole("dialog", { name: "Crear tarea rápida" })
  await userEvent.type(within(dialog).getByPlaceholderText("Nombre de la tarea"), "Tarea recién creada")
  await userEvent.selectOptions(within(dialog).getByRole("combobox"), "7")
  await userEvent.click(within(dialog).getByRole("button", { name: "Crear" }))

  const selector = await screen.findByRole("combobox", { name: "Tarea del cronómetro" })
  expect(within(selector).getByRole("option", { name: "Tarea recién creada" })).toBeInTheDocument()
  expect(selector).toHaveValue("12")

  canReadTasks = false
  view.rerender(<QueryClientProvider client={view.client}><ActiveTimerBar /><TimerButton taskId={1} /></QueryClientProvider>)
  expect(screen.queryByRole("option", { name: "Tarea recién creada" })).not.toBeInTheDocument()
  expect(screen.getByRole("combobox", { name: "Tarea del cronómetro" })).toBeDisabled()

  canReadTasks = true
  view.rerender(<QueryClientProvider client={view.client}><ActiveTimerBar /><TimerButton taskId={1} /></QueryClientProvider>)
  const restoredSelector = screen.getByRole("combobox", { name: "Tarea del cronómetro" })
  expect(restoredSelector).toHaveValue("")
  expect(mocks.start).not.toHaveBeenCalled()
})

it("a timer writer without task/client access can use the timer without fetching forbidden modules", async () => {
  mocks.permission.mockImplementation(module => module === "timesheet")
  setup()
  await waitFor(() => expect(mocks.active).toHaveBeenCalled())
  expect(await screen.findByRole("button", {name:"Crear tarea rápida"})).toBeDisabled()
  expect(mocks.tasks).not.toHaveBeenCalled()
  expect(mocks.clients).not.toHaveBeenCalled()
})

it("blocks a new timer while the initial timer state is unavailable and retries it", async () => {
  mocks.permission.mockReturnValue(true)
  mocks.active.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(null)
  setup()
  await screen.findByText("No se pudo comprobar el cronómetro. Espera a actualizarlo antes de iniciar otro.")
  expect(screen.queryByTitle("Iniciar timer")).not.toBeInTheDocument()
  within(screen.getByRole("alert")).getByRole("button", { name: "Reintentar" }).click()
  await waitFor(() => expect(mocks.active).toHaveBeenCalledTimes(2))
  await waitFor(() => expect(screen.queryByText(/No se pudo comprobar el cronómetro/)).not.toBeInTheDocument())
})

it("does not offer a start while the initial timer request is pending", async () => {
  mocks.permission.mockReturnValue(true)
  mocks.active.mockImplementationOnce(() => new Promise(() => undefined))
  setup()
  expect(await screen.findByRole("status")).toHaveTextContent("Comprobando el cronómetro")
  expect(screen.getByRole("button", { name: "Comprobando el cronómetro" })).toBeDisabled()
  expect(screen.queryByTitle("Iniciar timer")).not.toBeInTheDocument()
})

it("keeps a rejected timer cache hidden after 403, 503 and remount until success", async () => {
  mocks.permission.mockReturnValue(true)
  mocks.active.mockResolvedValueOnce({ id: 9, task_id: 1, task_title: "Privada", started_at: new Date().toISOString() })
  const view = setup()
  await screen.findByText("Privada")

  mocks.active.mockRejectedValueOnce({ response: { status: 403 } })
  await view.client.invalidateQueries({ queryKey: ["active-timer"] })
  await screen.findByText("No se pudo comprobar el cronómetro. Espera a actualizarlo antes de iniciar otro.")
  expect(screen.queryByText("Privada")).not.toBeInTheDocument()

  view.unmount()
  mocks.active.mockRejectedValueOnce({ response: { status: 503 } })
  render(<QueryClientProvider client={view.client}><ActiveTimerBar /><TimerButton taskId={1} /></QueryClientProvider>)
  await screen.findByText("No se pudo comprobar el cronómetro. Espera a actualizarlo antes de iniciar otro.")
  expect(screen.queryByText("Privada")).not.toBeInTheDocument()

  mocks.active.mockResolvedValueOnce(null)
  await view.client.invalidateQueries({ queryKey: ["active-timer"] })
  await waitFor(() => expect(screen.queryByText(/No se pudo comprobar el cronómetro/)).not.toBeInTheDocument())
  expect(await screen.findByTitle("Iniciar timer")).toBeEnabled()
})
