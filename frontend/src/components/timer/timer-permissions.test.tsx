import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import { beforeEach, expect, it, vi } from "vitest"
import { ActiveTimerBar } from "./active-timer-bar"
import { TimerButton } from "./timer-button"

const mocks = vi.hoisted(() => ({
  active: vi.fn(), tasks: vi.fn(), clients: vi.fn(), permission: vi.fn(),
}))
vi.mock("@/context/auth-context", () => ({useAuth: () => ({user: {id: 2}, hasPermission: mocks.permission})}))
vi.mock("@/lib/api", () => ({
  timerApi: {active: mocks.active}, tasksApi: {listAll: mocks.tasks}, clientsApi: {listAll: mocks.clients}, projectsApi: {}, timeEntriesApi: {},
}))
vi.mock("@/hooks/use-business-date", () => ({useBusinessDate: () => "2026-09-19"}))
function setup() {
  const client = new QueryClient({defaultOptions: {queries: {retry: false}}})
  return render(<QueryClientProvider client={client}><ActiveTimerBar /><TimerButton taskId={1} /></QueryClientProvider>)
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
it("a timer writer without task/client access can use the timer without fetching forbidden modules", async () => {
  mocks.permission.mockImplementation(module => module === "timesheet")
  setup()
  await waitFor(() => expect(mocks.active).toHaveBeenCalled())
  expect(screen.getByRole("button", {name:"Crear tarea rápida"})).toBeDisabled()
  expect(mocks.tasks).not.toHaveBeenCalled()
  expect(mocks.clients).not.toHaveBeenCalled()
})
