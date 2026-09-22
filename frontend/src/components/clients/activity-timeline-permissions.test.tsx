import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { ActivityTimeline } from "./activity-timeline"

const mocks = vi.hoisted(() => ({
  permissions: new Set<string>(),
  list: vi.fn(),
}))

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ hasPermission: (module: string) => mocks.permissions.has(module) }),
}))
vi.mock("@/lib/hidden-modules", () => ({ isEnabled: () => true }))
vi.mock("@/lib/api", () => ({ clientActivityApi: { list: mocks.list } }))

const activity = [
  { id: "task-1", type: "task_completed", subtype: "medium", timestamp: "2026-09-20T12:00:00", title: "Tarea completada", description: "Título privado", detail: null, user_name: null, icon: "check" },
  { id: "comm-1", type: "communication", subtype: "email", timestamp: "2026-09-21T12:00:00", title: "Email saliente", description: "Correo permitido", detail: null, user_name: null, icon: "message" },
]

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const tree = () => <QueryClientProvider client={client}><ActivityTimeline clientId={5} /></QueryClientProvider>
  const view = render(tree())
  return { ...view, refresh: () => view.rerender(tree()) }
}

describe("client activity permissions", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.permissions = new Set(["clients", "tasks", "communications"])
    mocks.list.mockResolvedValue(activity)
  })

  it("hides cached task events immediately after task access is revoked", async () => {
    const view = show()
    expect(await screen.findByText("Título privado")).toBeInTheDocument()
    expect(screen.getByText("Correo permitido")).toBeInTheDocument()

    mocks.permissions.delete("tasks")
    view.refresh()
    expect(screen.queryByText("Título privado")).not.toBeInTheDocument()
    expect(await screen.findByText("Correo permitido")).toBeInTheDocument()
  })

  it("does not query any source when the client has no source permission", async () => {
    mocks.permissions = new Set(["clients"])
    show()
    expect(screen.getByText("No hay fuentes de actividad disponibles para tu acceso.")).toBeInTheDocument()
    await waitFor(() => expect(mocks.list).not.toHaveBeenCalled())
  })
})
