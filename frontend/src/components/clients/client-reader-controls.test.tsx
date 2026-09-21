import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, fireEvent, render, screen } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { ClientAiAdvisor } from "./client-ai-advisor"
import { ContactList } from "./contact-list"
import { FichaTab } from "./ficha-tab"

const mocks = vi.hoisted(() => ({
  canWrite: false,
  isAdmin: false,
  contacts: vi.fn(),
  documents: vi.fn(),
  update: vi.fn(),
}))

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ isAdmin: mocks.isAdmin, hasPermission: (_module: string, write = false) => write ? mocks.canWrite : true }),
}))
vi.mock("@/lib/api", () => ({
  api: { post: vi.fn() },
  clientsApi: {
    update: mocks.update,
    documents: {
      list: mocks.documents,
      upload: vi.fn(),
      delete: vi.fn(),
      downloadUrl: vi.fn(),
    },
  },
  contactsApi: { list: mocks.contacts, create: vi.fn(), update: vi.fn(), delete: vi.fn() },
}))
vi.mock("@/lib/query-keys", () => ({ invalidateClientChange: vi.fn() }))

const client = { id: 5, website: "https://example.com", context: "Contexto existente" } as never

function show(node: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{node}</QueryClientProvider>)
}

describe("client reader controls", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.canWrite = false
    mocks.isAdmin = false
    mocks.contacts.mockResolvedValue([{ id: 7, name: "Ana", is_primary: false }])
    mocks.documents.mockResolvedValue([{ id: 9, name: "Brief.pdf", mime_type: "application/pdf", size_bytes: 1, created_at: "2026-01-01" }])
  })

  it("keeps the ficha readable while hiding client write actions", async () => {
    show(<FichaTab client={client} />)

    expect(screen.getByDisplayValue("Contexto existente")).toHaveAttribute("readonly")
    expect(screen.queryByRole("button", { name: /Subir documento/ })).not.toBeInTheDocument()
    expect(await screen.findByText("Brief.pdf")).toBeInTheDocument()
    expect(screen.queryByTitle("Eliminar")).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Generar" })).not.toBeInTheDocument()
  })

  it("restores persisted context and cancels its pending autosave when write access is revoked", () => {
    vi.useFakeTimers()
    mocks.canWrite = true
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const tree = () => <QueryClientProvider client={queryClient}><FichaTab client={client} /></QueryClientProvider>
    const view = render(tree())
    const context = screen.getByDisplayValue("Contexto existente")
    fireEvent.change(context, { target: { value: "Cambio sin guardar" } })

    mocks.canWrite = false
    view.rerender(tree())
    expect(screen.getByDisplayValue("Contexto existente")).toHaveAttribute("readonly")

    act(() => { vi.advanceTimersByTime(1_500) })
    expect(mocks.update).not.toHaveBeenCalled()
    vi.useRealTimers()
  })

  it("keeps contacts readable while hiding client write actions", async () => {
    show(<ContactList clientId={5} />)

    expect(await screen.findByText("Ana")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /Nuevo contacto/ })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Editar contacto" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Eliminar contacto" })).not.toBeInTheDocument()
  })

  it("hides AI requests from a client reader", () => {
    show(<ClientAiAdvisor clientId={5} />)

    expect(screen.queryByRole("button", { name: "Pedir recomendaciones" })).not.toBeInTheDocument()
  })

  it("retains client writer actions and limits onboarding intelligence to admins", async () => {
    mocks.canWrite = true
    show(<><FichaTab client={client} /><ContactList clientId={5} /><ClientAiAdvisor clientId={5} /></>)

    expect(await screen.findByText("Ana")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /Subir documento/ })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /Nuevo contacto/ })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Pedir recomendaciones" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Generar" })).not.toBeInTheDocument()
  })

  it("shows onboarding intelligence generation to an admin", () => {
    mocks.isAdmin = true
    show(<FichaTab client={client} />)

    expect(screen.getByRole("button", { name: "Generar" })).toBeInTheDocument()
  })
})
