import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { ClientAiAdvisor } from "./client-ai-advisor"

const mocks = vi.hoisted(() => ({
  userId: 1,
  permissions: new Set<string>(),
  canWriteClients: true,
  advice: vi.fn(),
}))

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({
    user: { id: mocks.userId },
    hasPermission: (module: string, write = false) => write
      ? module === "clients" && mocks.canWriteClients
      : mocks.permissions.has(module),
  }),
}))
vi.mock("@/lib/hidden-modules", () => ({ isEnabled: () => true }))
vi.mock("@/lib/api", () => ({ clientsApi: { aiAdvice: mocks.advice } }))

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const tree = () => <QueryClientProvider client={client}><ClientAiAdvisor clientId={5} /></QueryClientProvider>
  const view = render(tree())
  return { ...view, refresh: () => view.rerender(tree()) }
}

describe("client AI advice permissions", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.userId = 1
    mocks.permissions = new Set(["clients", "tasks"])
    mocks.canWriteClients = true
    mocks.advice.mockResolvedValue({ recommendations: [{
      priority: "high", category: "tareas", title: "Tarea privada",
      description: "Hay una tarea pendiente", action: "Revisar tarea",
    }] })
  })

  it("hides a prior recommendation immediately when task access is revoked", async () => {
    const view = show()
    await userEvent.click(screen.getByRole("button", { name: "Pedir recomendaciones" }))
    expect(await screen.findByText("Tarea privada")).toBeInTheDocument()

    mocks.permissions.delete("tasks")
    view.refresh()
    expect(screen.queryByText("Tarea privada")).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Pedir recomendaciones" })).toBeInTheDocument()
  })

  it("hides prior recommendations after the account changes", async () => {
    const view = show()
    await userEvent.click(screen.getByRole("button", { name: "Pedir recomendaciones" }))
    expect(await screen.findByText("Tarea privada")).toBeInTheDocument()

    mocks.userId = 2
    view.refresh()
    expect(screen.queryByText("Tarea privada")).not.toBeInTheDocument()
  })
})
