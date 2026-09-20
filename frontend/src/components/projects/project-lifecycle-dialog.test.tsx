import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { MemoryRouter } from "react-router-dom"
import { ProjectLifecycleDialog } from "./project-lifecycle-dialog"

const api = vi.hoisted(() => ({ closePreview: vi.fn(), close: vi.fn(), reopenPreview: vi.fn(), reopen: vi.fn() }))
const auth = vi.hoisted(() => ({ canWrite: true }))

vi.mock("@/lib/api", () => ({ projectsApi: api }))
vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({
    user: { id: 7, permissions: [{ module: "projects", can_read: true, can_write: auth.canWrite }] },
    hasPermission: (_module: string, write = false) => !write || auth.canWrite,
  }),
}))

const project = {
  id: 14,
  name: "Proyecto de prueba",
  client_id: 4,
  updated_at: "2026-09-21T09:00:00Z",
}

const preview = {
  project_id: 14,
  target: "completed" as const,
  current_status: "active" as const,
  expected_updated_at: "2026-09-21T09:00:00Z",
  preview_revision: "revision-a",
  can_close: false,
  blockers: {
    active_tasks: { total: 1, sample: [{ id: 8, title: "Preparar entrega", status: "waiting", href: "/tasks?task=8" }] },
    waiting_count: 1,
    in_review_count: 0,
    active_timers: { total: 0, sample: [] },
  },
  recurrence: { templates: 2, paused: 1, suppressed_after_close: 1 },
}

function setup(action: "completed" | "cancelled" | "reopen" = "completed") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const onOpenChange = vi.fn()
  render(<QueryClientProvider client={queryClient}><MemoryRouter><ProjectLifecycleDialog project={project as never} action={action} open onOpenChange={onOpenChange} /></MemoryRouter></QueryClientProvider>)
  return { onOpenChange }
}

describe("ProjectLifecycleDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    auth.canWrite = true
    api.closePreview.mockResolvedValue(preview)
  })

  it("shows exact blockers and does not offer a false close", async () => {
    setup()
    expect(await screen.findByText("Preparar entrega")).toBeInTheDocument()
    expect(screen.getByText("1 tarea activa")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Preparar entrega" })).toHaveAttribute("href", "/tasks?task=8")
    expect(screen.getByRole("button", { name: "Cerrar proyecto" })).toBeDisabled()
    expect(screen.getByText(/dejará de crear tareas mientras el proyecto esté archivado/i)).toBeInTheDocument()
  })

  it("confirms only with the reviewed revision and invalidates after success", async () => {
    api.closePreview.mockResolvedValue({ ...preview, can_close: true, blockers: { ...preview.blockers, active_tasks: { total: 0, sample: [] } } })
    api.close.mockResolvedValue({ ...project, status: "completed" })
    const { onOpenChange } = setup()
    await screen.findByRole("button", { name: "Cerrar proyecto" })
    await userEvent.click(screen.getByRole("button", { name: "Cerrar proyecto" }))
    await waitFor(() => expect(api.close).toHaveBeenCalledWith(14, {
      target: "completed",
      expected_updated_at: "2026-09-21T09:00:00Z",
      preview_revision: "revision-a",
    }))
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
  })

  it("hides cached blockers after a denied confirmation until a fresh successful check", async () => {
    api.closePreview
      .mockResolvedValueOnce({ ...preview, can_close: true, blockers: { ...preview.blockers, active_tasks: { total: 0, sample: [] } } })
      .mockRejectedValueOnce({ response: { status: 403 } })
      .mockResolvedValueOnce(preview)
    api.close.mockRejectedValueOnce({ response: { status: 403 } })
    setup()
    await screen.findByRole("button", { name: "Cerrar proyecto" })
    await userEvent.click(screen.getByRole("button", { name: "Cerrar proyecto" }))
    expect(await screen.findByText(/Tus permisos cambiaron/i)).toBeInTheDocument()
    expect(screen.queryByText("Preparar entrega")).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Cerrar proyecto" })).toBeDisabled()
    await userEvent.click(screen.getByRole("button", { name: "Reintentar" }))
    expect(await screen.findByText("Preparar entrega")).toBeInTheDocument()
  })

  it("refreshes the surrounding project instead of repeating a lifecycle action after a plain conflict", async () => {
    api.closePreview.mockResolvedValue({ ...preview, can_close: true, blockers: { ...preview.blockers, active_tasks: { total: 0, sample: [] } } })
    api.close.mockRejectedValueOnce({ response: { status: 409, data: { detail: "El proyecto ya cambió" } } })
    const { onOpenChange } = setup()
    await screen.findByRole("button", { name: "Cerrar proyecto" })
    await userEvent.click(screen.getByRole("button", { name: "Cerrar proyecto" }))
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
    expect(api.close).toHaveBeenCalledTimes(1)
  })

  it("keeps manual pauses explicit when reopening", async () => {
    api.reopenPreview.mockResolvedValue({
      project_id: 14,
      current_status: "completed",
      expected_updated_at: "2026-09-21T09:00:00Z",
      preview_revision: "reopen-a",
      can_reopen: true,
      recurrence: { templates: 2, paused: 1, suppressed_after_close: 1 },
      message: "Las plantillas no pausadas volverán a operar desde la fecha civil actual.",
    })
    setup("reopen")
    expect(await screen.findByText(/volverá a crear tareas desde hoy/i)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Reabrir proyecto" })).toBeEnabled()
  })
})
