import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query"
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { MemoryRouter } from "react-router-dom"
import DashboardPage from "./dashboard-page"
import { dashboardKeys } from "@/lib/query-keys"

const mocks = vi.hoisted(() => ({
  user: null as null | { id: number; role: "admin" | "member"; permissions: Array<{ module: string; can_read: boolean; can_write: boolean }> },
  financeEnabled: false,
  usersEnabled: false,
  overview: vi.fn(), financialOverview: vi.fn(), profitability: vi.fn(), team: vi.fn(), utilization: vi.fn(),
  monthlyClose: vi.fn(), financialSettings: vi.fn(), updateMonthlyClose: vi.fn(), updateFinancialSettings: vi.fn(), exportMonthlyClose: vi.fn(),
  preview: vi.fn(), send: vi.fn(), settings: vi.fn(), weekly: vi.fn(),
  tasks: vi.fn(), taskUpdate: vi.fn(), timeWeekly: vi.fn(), active: vi.fn(), start: vi.fn(), stop: vi.fn(),
  users: vi.fn(), clients: vi.fn(), engine: vi.fn(), leads: vi.fn(), proposals: vi.fn(),
  toastSuccess: vi.fn(), toastError: vi.fn(),
}))

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({
    user: mocks.user,
    hasPermission: (module: string, write = false) => mocks.user?.role === "admin" || !!mocks.user?.permissions.find((item) => item.module === module && item.can_read && (!write || item.can_write)),
  }),
}))
vi.mock("@/lib/hidden-modules", () => ({
  isEnabled: (module: string) => module === "finance" ? mocks.financeEnabled : module === "users" ? mocks.usersEnabled : module === "tasks" || module === "timesheet",
}))
vi.mock("@/hooks/use-business-date", () => ({ useBusinessDate: () => "2026-09-20" }))
vi.mock("@/lib/api", () => ({
  dashboardApi: { overview: mocks.overview, financialOverview: mocks.financialOverview, profitability: mocks.profitability, team: mocks.team, utilization: mocks.utilization, monthlyClose: mocks.monthlyClose, financialSettings: mocks.financialSettings, updateMonthlyClose: mocks.updateMonthlyClose, updateFinancialSettings: mocks.updateFinancialSettings, exportMonthlyClose: mocks.exportMonthlyClose },
  discordApi: { preview: mocks.preview, send: mocks.send, settings: mocks.settings, sendWeeklyReport: mocks.weekly },
  tasksApi: { listAll: mocks.tasks, update: mocks.taskUpdate }, timeEntriesApi: { weekly: mocks.timeWeekly }, timerApi: { active: mocks.active, start: mocks.start, stop: mocks.stop },
  usersApi: { listAll: mocks.users }, clientsApi: { listAll: mocks.clients }, engineApi: { getConfig: mocks.engine }, leadsApi: { reminders: mocks.leads }, proposalsApi: { list: mocks.proposals }, holdedApi: { config: vi.fn(), dashboard: vi.fn() },
}))
vi.mock("@/components/dashboard/daily-update-widget", () => ({ DailyUpdateWidget: () => <div /> }))
vi.mock("@/components/dashboard/deberes-widget", () => ({ DeberesWidget: () => <div /> }))
vi.mock("@/components/dashboard/today-block", () => ({ TodayBlock: () => <div /> }))
vi.mock("@/components/dashboard/inbox-widget", () => ({ InboxWidget: () => <div /> }))
vi.mock("@/components/dashboard/engine-alerts-widget", () => ({ EngineAlertsWidget: () => <div /> }))
vi.mock("@/components/pm/insights-panel", () => ({ InsightsPanel: () => <div /> }))
vi.mock("@/components/pm/daily-briefing", () => ({ DailyBriefingButton: () => <div /> }))
vi.mock("@/components/delivery-receipts", () => ({ ManualDeliveryReceipts: () => <div />, deliveryToast: vi.fn() }))
vi.mock("sonner", () => ({ toast: { success: mocks.toastSuccess, error: mocks.toastError } }))

const operational = { active_clients: 2, pending_tasks: 3, in_progress_tasks: 1, hours_this_month: 7, availability: { clients: true, tasks: true, timesheet: true }, hours_scope: "mine" as const }
function show(client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })) {
  const tree = <MemoryRouter><QueryClientProvider client={client}><DashboardPage /></QueryClientProvider></MemoryRouter>
  return { ...render(tree), client, tree }
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.financeEnabled = false
  mocks.usersEnabled = false
  mocks.overview.mockResolvedValue(operational)
  mocks.financialOverview.mockResolvedValue({ total_budget: 10, total_cost: 2, margin: 8, margin_percent: 80 })
  mocks.team.mockResolvedValue([]); mocks.utilization.mockResolvedValue({ global_utilization_pct: 0, total_logged_hours: 0, total_available_hours: 0 })
  mocks.monthlyClose.mockResolvedValue({}); mocks.financialSettings.mockResolvedValue({}); mocks.users.mockResolvedValue([]); mocks.clients.mockResolvedValue([]); mocks.engine.mockResolvedValue({})
  mocks.tasks.mockResolvedValue([]); mocks.timeWeekly.mockResolvedValue({ users: [] }); mocks.active.mockResolvedValue(null); mocks.settings.mockResolvedValue({ webhook_configured: true }); mocks.preview.mockResolvedValue({ summary: "Resumen", date: "2026-09-20", revision: "sha-1" })
})

describe("DashboardPage", () => {
  it("names the person and reporting period selectors", async () => {
    mocks.user = { id: 1, role: "admin", permissions: [] }
    mocks.usersEnabled = true
    mocks.users.mockResolvedValue([{ id: 2, full_name: "Nacho", role: "member", is_active: true }])
    show()
    expect(screen.getByRole("heading", { name: "Visión general" })).toBeInTheDocument()
    expect(await screen.findByRole("combobox", { name: "Persona del dashboard" })).toBeInTheDocument()
    expect(screen.getByRole("combobox", { name: "Mes del dashboard" })).toBeInTheDocument()
    expect(screen.getByRole("combobox", { name: "Año del dashboard" })).toBeInTheDocument()
  })

  it("labels the weekly report action as an immediate closed-workweek DM delivery", async () => {
    mocks.user = { id: 1, role: "admin", permissions: [] }
    show()

    const button = await screen.findByRole("button", { name: "Enviar informe semanal" })
    expect(button).toHaveAttribute(
      "title",
      "Enviar por Discord DM el último informe laboral cerrado (lunes a viernes)",
    )
  })

  it("does not fetch team, finance, or task sources for a member without those permissions", async () => {
    mocks.user = { id: 4, role: "member", permissions: [] }
    show()
    await screen.findByText("Clientes externos activos")
    expect(mocks.overview).toHaveBeenCalled()
    expect(mocks.financialOverview).not.toHaveBeenCalled()
    expect(mocks.team).not.toHaveBeenCalled()
    expect(mocks.tasks).not.toHaveBeenCalled()
  })

  it("links personal tasks for readers without offering task or timer mutations", async () => {
    mocks.user = { id: 4, role: "member", permissions: [{ module: "tasks", can_read: true, can_write: false }] }
    mocks.tasks.mockImplementation(({ status }: { status: string }) => Promise.resolve(status === "in_progress"
      ? [{ id: 12, title: "Revisar propuesta", status, client_name: null, due_date: null }]
      : [{ id: 13, title: "Preparar cierre", status, client_name: null, due_date: null }]))
    show()
    expect(await screen.findByRole("link", { name: "Revisar propuesta" })).toHaveAttribute("href", "/tasks?task=12")
    expect(await screen.findByRole("link", { name: "Preparar cierre" })).toHaveAttribute("href", "/tasks?task=13")
    expect(screen.queryByRole("button", { name: /Completar:|Enviar a revisión:/ })).not.toBeInTheDocument()
    expect(screen.queryByTitle("Iniciar timer")).not.toBeInTheDocument()
  })

  it("uses consultation copy for a reader with no in-progress tasks", async () => {
    mocks.user = { id: 4, role: "member", permissions: [{ module: "tasks", can_read: true, can_write: false }] }
    show()
    expect(await screen.findByText("Sin tareas en curso")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Consulta tus tareas en Trabajo" })).toHaveAttribute("href", "/tasks?view=all")
  })

  it("keeps the timer available when a task reader can write time entries", async () => {
    mocks.user = { id: 4, role: "member", permissions: [
      { module: "tasks", can_read: true, can_write: false },
      { module: "timesheet", can_read: true, can_write: true },
    ] }
    mocks.tasks.mockImplementation(({ status }: { status: string }) => Promise.resolve(status === "in_progress"
      ? [{ id: 12, title: "Revisar propuesta", status, client_name: null, due_date: null }]
      : []))
    show()
    expect(await screen.findByRole("link", { name: "Revisar propuesta" })).toHaveAttribute("href", "/tasks?task=12")
    expect(await screen.findByTitle("Iniciar timer")).toBeEnabled()
    expect(screen.queryByRole("button", { name: /Completar:|Enviar a revisión:/ })).not.toBeInTheDocument()
  })

  it("sends a concrete project task to review for a member who is not the owner", async () => {
    mocks.user = { id: 4, role: "member", permissions: [{ module: "tasks", can_read: true, can_write: true }] }
    const task = {
      id: 12,
      title: "Revisar propuesta",
      status: "in_progress",
      client_name: null,
      due_date: null,
      is_recurring: false,
      project_requires_task_review: true,
      project_review_owner_id: 9,
      project_id: 3,
      client_id: 2,
    }
    mocks.tasks.mockImplementation((params) => Promise.resolve(params.status === "in_progress" ? [task] : []))
    mocks.taskUpdate.mockResolvedValue({ ...task, status: "in_review" })

    show()
    await userEvent.click(await screen.findByTitle("Enviar a revisión"))

    await waitFor(() => expect(mocks.taskUpdate).toHaveBeenCalledWith(12, { status: "in_review" }))
    expect(mocks.toastSuccess).toHaveBeenCalledWith("Tarea enviada a revisión")
  })

  it("lets the project owner complete a reviewed task directly", async () => {
    mocks.user = { id: 9, role: "member", permissions: [{ module: "tasks", can_read: true, can_write: true }] }
    const task = {
      id: 13,
      title: "Aprobar propuesta",
      status: "pending",
      client_name: null,
      due_date: null,
      is_recurring: false,
      project_requires_task_review: true,
      project_review_owner_id: 9,
      project_id: 3,
      client_id: 2,
    }
    mocks.tasks.mockImplementation((params) => Promise.resolve(params.status === "pending" ? [task] : []))
    mocks.taskUpdate.mockResolvedValue({ ...task, status: "completed" })

    show()
    await userEvent.click(await screen.findByTitle("Completar"))

    await waitFor(() => expect(mocks.taskUpdate).toHaveBeenCalledWith(13, { status: "completed" }))
    expect(mocks.toastSuccess).toHaveBeenCalledWith("Tarea completada")
  })

  it("does not claim review submission succeeded when the write fails", async () => {
    mocks.user = { id: 4, role: "member", permissions: [{ module: "tasks", can_read: true, can_write: true }] }
    const task = {
      id: 14,
      title: "Informe mensual",
      status: "in_progress",
      client_name: null,
      due_date: null,
      is_recurring: false,
      project_requires_task_review: true,
      project_review_owner_id: 9,
      project_id: 3,
      client_id: 2,
    }
    mocks.tasks.mockImplementation((params) => Promise.resolve(params.status === "in_progress" ? [task] : []))
    mocks.taskUpdate.mockRejectedValue(new Error("Sin conexión"))

    show()
    await userEvent.click(await screen.findByTitle("Enviar a revisión"))

    await waitFor(() => expect(mocks.toastError).toHaveBeenCalledWith("Sin conexión"))
    expect(mocks.toastSuccess).not.toHaveBeenCalled()
  })

  it("does not expose cached finance data after a 403", async () => {
    mocks.user = { id: 1, role: "admin", permissions: [] }
    mocks.financeEnabled = true
    mocks.financialOverview.mockRejectedValueOnce({ response: { status: 403 } })
    const { client } = show()
    client.setQueryData(dashboardKeys.financialOverview(2026, 9, 1, "admin::1"), { total_budget: 900, total_cost: 200, margin: 700, margin_percent: 77 })
    await waitFor(() => expect(mocks.financialOverview).toHaveBeenCalled())
    await waitFor(() => expect(screen.queryByText("Presupuesto total")).not.toBeInTheDocument())
  })

  it("keeps finance hidden from a 403 through a later 503 until a success", async () => {
    mocks.user = { id: 1, role: "admin", permissions: [] }
    mocks.financeEnabled = true
    const financial = { total_budget: 900, total_cost: 200, margin: 700, margin_percent: 77 }
    mocks.financialOverview.mockResolvedValueOnce(financial).mockRejectedValueOnce({ response: { status: 403 } }).mockRejectedValueOnce(new Error("503")).mockResolvedValueOnce(financial)
    const { client } = show()
    await screen.findByText("Presupuesto total")
    const key = dashboardKeys.financialOverview(2026, 9, 1, "admin::1")
    await client.invalidateQueries({ queryKey: key })
    await waitFor(() => expect(screen.queryByText("Presupuesto total")).not.toBeInTheDocument())
    expect(screen.queryByText("Fondo de impuestos bajo")).not.toBeInTheDocument()
    await client.invalidateQueries({ queryKey: key })
    expect(screen.queryByText("Presupuesto total")).not.toBeInTheDocument()
    expect(screen.queryByText("Fondo de impuestos bajo")).not.toBeInTheDocument()
    await client.invalidateQueries({ queryKey: key })
    expect(await screen.findByText("Presupuesto total")).toBeInTheDocument()
  })

  it("keeps the operational overview hidden through errors until a fresh success", async () => {
    mocks.user = { id: 4, role: "member", permissions: [] }
    mocks.overview.mockResolvedValueOnce(operational).mockRejectedValueOnce({ response: { status: 403 } }).mockRejectedValueOnce(new Error("503")).mockResolvedValueOnce(operational)
    const { client } = show()
    await screen.findByText("Clientes externos activos")
    const key = dashboardKeys.overview(2026, 9, 4, "member::0")
    await client.invalidateQueries({ queryKey: key })
    await waitFor(() => expect(screen.queryByText("Clientes externos activos")).not.toBeInTheDocument())
    await client.invalidateQueries({ queryKey: key })
    expect(screen.queryByText("Clientes externos activos")).not.toBeInTheDocument()
    await client.invalidateQueries({ queryKey: key })
    expect(await screen.findByText("Clientes externos activos")).toBeInTheDocument()
  })

  it("uses a new overview query after the signed-in identity changes", async () => {
    mocks.user = { id: 4, role: "member", permissions: [] }
    const { rerender, client } = show()
    await screen.findByText("Clientes externos activos")
    mocks.user = { id: 5, role: "member", permissions: [] }
    rerender(<MemoryRouter><QueryClientProvider client={client}><DashboardPage /></QueryClientProvider></MemoryRouter>)
    await waitFor(() => expect(mocks.overview).toHaveBeenCalledTimes(2))
  })

  it("does not flash revoked financial data while the next request is still pending", async () => {
    mocks.user = { id: 1, role: "admin", permissions: [] }
    mocks.financeEnabled = true
    mocks.financialOverview.mockResolvedValueOnce({ total_budget: 900, total_cost: 200, margin: 700, margin_percent: 77 })
    const { client } = show()
    await screen.findByText("Presupuesto total")
    const key = dashboardKeys.financialOverview(2026, 9, 1, "admin::1")
    mocks.financialOverview.mockRejectedValueOnce({ response: { status: 403 } })
    await act(async () => { await client.invalidateQueries({ queryKey: key }) })
    await waitFor(() => expect(screen.queryByText("Presupuesto total")).not.toBeInTheDocument())
    let rejectRequest!: (reason: Error) => void
    mocks.financialOverview.mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectRequest = reject }))
    let request!: Promise<void>
    await act(async () => { request = client.invalidateQueries({ queryKey: key }) })
    expect(client.isFetching({ queryKey: key })).toBe(1)
    expect(screen.queryByText("Presupuesto total")).not.toBeInTheDocument()
    await act(async () => { rejectRequest(new Error("503")); await request })
    expect(screen.queryByText("Presupuesto total")).not.toBeInTheDocument()
  })

  it("loads the selected month's close without carrying the previous inputs", async () => {
    mocks.user = { id: 1, role: "admin", permissions: [] }
    mocks.financeEnabled = true
    mocks.monthlyClose.mockImplementation(({ month }: { month: number }) => Promise.resolve({
      responsible_name: month === 9 ? "Responsable septiembre" : "Responsable agosto",
      notes: month === 9 ? "Notas septiembre" : "Notas agosto",
    }))
    show()
    expect(await screen.findByDisplayValue("Notas septiembre")).toBeInTheDocument()
    fireEvent.click(screen.getByTitle("Mes anterior"))
    expect(await screen.findByDisplayValue("Notas agosto")).toBeInTheDocument()
    expect(screen.getByLabelText("Responsable")).toHaveValue("Responsable agosto")
    expect(screen.queryByDisplayValue("Notas septiembre")).not.toBeInTheDocument()
    expect(mocks.monthlyClose).toHaveBeenLastCalledWith({ year: 2026, month: 8 })
    expect(mocks.overview).toHaveBeenLastCalledWith({ year: 2026, month: 8 })
  })

  it("shows a retryable overview error rather than zeros", async () => {
    mocks.user = { id: 4, role: "member", permissions: [] }
    mocks.overview.mockRejectedValueOnce(new Error("503"))
    show()
    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo cargar la visión operativa")
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }))
    await waitFor(() => expect(mocks.overview).toHaveBeenCalledTimes(2))
  })

  it("requires a verified Discord preview revision and does not replay after a conflict", async () => {
    mocks.user = { id: 1, role: "admin", permissions: [] }
    mocks.send.mockRejectedValueOnce({ response: { status: 409 } })
    show()
    await userEvent.click(await screen.findByRole("button", { name: /Vista previa antes de enviar/ }))
    expect(await screen.findByText("Resumen")).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Enviar" }))
    await waitFor(() => expect(mocks.send).toHaveBeenCalledWith({ date: "2026-09-20", expected_revision: "sha-1" }))
    expect(mocks.send).toHaveBeenCalledTimes(1)
    await waitFor(() => expect(mocks.preview).toHaveBeenCalledTimes(2))
  })
})


describe("Dashboard timer shared state", () => {
  it("updates a mounted timer consumer immediately after starting from Dashboard", async () => {
    mocks.user = { id: 4, role: "member", permissions: [{ module: "tasks", can_read: true, can_write: true }, { module: "timesheet", can_read: true, can_write: true }] }
    mocks.tasks.mockImplementation((params) => Promise.resolve(params.status === "in_progress" ? [{ id: 12, title: "Revisar propuesta", status: "in_progress", client_name: null, due_date: null }] : []))
    let running = false
    mocks.active.mockImplementation(() => Promise.resolve(running ? { id: 7, task_id: 12, task_title: "Revisar propuesta" } : null))
    mocks.start.mockImplementation(async () => { running = true; return { id: 7, task_id: 12 } })
    function OtherTimerConsumer() {
      const { data } = useQuery({ queryKey: ["active-timer"], queryFn: mocks.active, staleTime: Infinity })
      return <output data-testid="other-timer">{data?.task_id ?? "Sin cronómetro"}</output>
    }
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
    render(<MemoryRouter><QueryClientProvider client={client}><DashboardPage /><OtherTimerConsumer /></QueryClientProvider></MemoryRouter>)
    await screen.findByText("Revisar propuesta")
    expect(screen.getByTestId("other-timer")).toHaveTextContent("Sin cronómetro")
    await userEvent.click(screen.getByTitle("Iniciar timer"))
    await waitFor(() => expect(screen.getByTestId("other-timer")).toHaveTextContent("12"))
    expect(mocks.start).toHaveBeenCalledTimes(1)
  })

  it("does not offer start as if no timer existed when its state is unknown", async () => {
    mocks.user = { id: 4, role: "member", permissions: [{ module: "tasks", can_read: true, can_write: true }, { module: "timesheet", can_read: true, can_write: true }] }
    mocks.tasks.mockImplementation((params) => Promise.resolve(params.status === "in_progress" ? [{ id: 12, title: "Revisar propuesta", status: "in_progress", client_name: null, due_date: null }] : []))
    mocks.active.mockRejectedValueOnce(new Error("503"))
    show()
    await screen.findByText("No se pudo comprobar el cronómetro. Reintenta antes de iniciar otro.")
    expect(screen.getByTitle("Iniciar timer")).toBeDisabled()
    mocks.active.mockResolvedValue(null)
    await userEvent.click(screen.getByRole("button", { name: "Reintentar cronómetro" }))
    await waitFor(() => expect(screen.getByTitle("Iniciar timer")).toBeEnabled())
    expect(mocks.start).not.toHaveBeenCalled()
  })
})
