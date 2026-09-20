import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { InboxNoteCard } from "./inbox-note-card"
import type { InboxNote } from "@/lib/types"

const mocks = vi.hoisted(() => ({
  classify: vi.fn(), update: vi.fn(), dismiss: vi.fn(), remove: vi.fn(), upload: vi.fn(), deleteAttachment: vi.fn(),
  convert: vi.fn(), projects: vi.fn(), clients: vi.fn(), users: vi.fn(),
  permissions: { tasks: true, projects: true, clients: true, users: true },
}))

vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: { id: 7 }, hasPermission: (module: keyof typeof mocks.permissions) => mocks.permissions[module] }) }))
vi.mock("@/lib/api", () => ({
  inboxApi: {
    classify: mocks.classify, update: mocks.update, dismiss: mocks.dismiss, delete: mocks.remove,
    uploadAttachment: mocks.upload, deleteAttachment: mocks.deleteAttachment, convertToTask: mocks.convert,
  },
  projectsApi: { listAll: mocks.projects }, clientsApi: { listAll: mocks.clients }, usersApi: { listAll: mocks.users },
}))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const note: InboxNote = {
  id: 31, user_id: 7, raw_text: "Llamar a Acme", source: "quick_capture", status: "pending",
  project_id: null, client_id: null, project_name: null, client_name: null, resolved_as: null, resolved_entity_id: null,
  ai_suggestion: null, link_url: null, attachments: [], created_at: "2026-09-20T10:00:00Z", updated_at: "2026-09-20T10:00:00Z",
  classification_error_code: "provider_unavailable" as const, classification_next_attempt_at: "2026-09-20T10:05:00",
}

function setup(overrides = {}) {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>
    <InboxNoteCard note={{ ...note, ...overrides }} />
  </QueryClientProvider>)
}

describe("InboxNoteCard classification", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.projects.mockResolvedValue([])
    mocks.clients.mockResolvedValue([])
    mocks.users.mockResolvedValue([])
    mocks.permissions = { tasks: true, projects: true, clients: true, users: true }
    mocks.classify.mockResolvedValue({ ...note, classification_error_code: null, classification_next_attempt_at: null })
  })

  it("keeps durable text and manual actions available after a classification failure", async () => {
    setup()
    expect(screen.getByText("Llamar a Acme")).toBeInTheDocument()
    expect(screen.getByText(/No se pudo generar una sugerencia/)).toBeInTheDocument()
    expect(screen.getByText("Capturada desde Captura rápida")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Crear tarea" })).toBeEnabled()
    await userEvent.click(screen.getByRole("button", { name: "Reintentar" }))
    await waitFor(() => expect(mocks.classify).toHaveBeenCalledWith(31))
    expect(screen.getByText("Llamar a Acme")).toBeInTheDocument()
  })

  it("shows a pending classification without polling copy or a fabricated source", () => {
    setup({ classification_error_code: null, classification_next_attempt_at: null, source: "legacy" })
    expect(screen.getByText("Pendiente de clasificación")).toBeInTheDocument()
    expect(screen.queryByText(/Capturada desde/)).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Reintentar" })).not.toBeInTheDocument()
  })

  it("clears a mismatched project when the client changes", async () => {
    mocks.projects.mockResolvedValue([{ id: 9, name: "Proyecto Acme", client_id: 4 }])
    mocks.clients.mockResolvedValue([{ id: 4, name: "Acme" }, { id: 5, name: "Beta" }])
    setup({ project_id: 9, client_id: 4 })
    await screen.findByRole("option", { name: "Beta" })
    await userEvent.selectOptions(screen.getByLabelText("Cliente"), "5")
    await waitFor(() => expect(mocks.update).toHaveBeenCalledWith(31, { client_id: 5, project_id: null }))
  })

  it("lets a member with projects but no clients permission associate only a project", async () => {
    mocks.permissions.clients = false
    mocks.projects.mockResolvedValue([{ id: 9, name: "Proyecto visible", client_id: 4 }])
    setup()
    await screen.findByRole("option", { name: "Proyecto visible" })
    expect(screen.queryByLabelText("Cliente")).not.toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText("Proyecto"), "9")
    await waitFor(() => expect(mocks.update).toHaveBeenCalledWith(31, { project_id: 9 }))
  })

  it("converts with a visible project without sending an unreadable client", async () => {
    mocks.permissions.clients = false
    mocks.convert.mockResolvedValue({ ok: true, task_id: 44, note })
    setup({ project_id: 9, client_id: null })
    await userEvent.click(screen.getByRole("button", { name: "Crear tarea" }))
    await userEvent.click(screen.getAllByRole("button", { name: "Crear tarea" }).at(-1)!)
    await waitFor(() => expect(mocks.convert).toHaveBeenCalledWith(31, expect.objectContaining({ project_id: 9, client_id: undefined })))
  })
})
