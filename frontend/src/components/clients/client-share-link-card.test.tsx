import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, expect, it, vi } from "vitest"
import { ClientShareLinkCard } from "./client-share-link-card"

const api = vi.hoisted(() => ({ status: vi.fn(), create: vi.fn(), revoke: vi.fn(), publicView: vi.fn() }))
const perms = vi.hoisted(() => ({ clientsWrite: true, digests: true }))
vi.mock("@/lib/client-share-link-api", () => ({ clientShareLinkApi: api }))
vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({
    hasPermission: (module: string, write = false) =>
      module === "clients" ? (write ? perms.clientsWrite : true) : module === "digests" ? perms.digests : false,
  }),
}))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const none = { active: false, created_at: null, created_by_name: null, last_viewed_at: null }
const active = { active: true, created_at: "2026-10-20T08:00:00+00:00", created_by_name: "David", last_viewed_at: null }

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><ClientShareLinkCard clientId={7} /></QueryClientProvider>)
}

beforeEach(() => {
  vi.resetAllMocks()
  perms.clientsWrite = true
  perms.digests = true
})

it("creates the link and shows the full URL only once, ready to copy", async () => {
  api.status.mockResolvedValue(none)
  api.create.mockResolvedValue({ ...active, path: "/c/tok_123" })
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.assign(navigator, { clipboard: { writeText } })
  setup()
  expect(await screen.findByText("No hay ningún enlace activo.")).toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", { name: "Crear enlace" }))
  const input = await screen.findByLabelText("Enlace para el cliente")
  expect(input).toHaveValue(`${window.location.origin}/c/tok_123`)
  expect(screen.getByText(/no se vuelve a mostrar/)).toBeInTheDocument()
  expect(screen.getByRole("status")).toHaveTextContent("Activo desde")
  fireEvent.click(screen.getByRole("button", { name: /Copiar/ }))
  await waitFor(() => expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/c/tok_123`))
})

it("an active link shows since when, never the token, and regenerating asks first", async () => {
  api.status.mockResolvedValue(active)
  api.create.mockResolvedValue({ ...active, path: "/c/nuevo" })
  setup()
  expect(await screen.findByRole("status")).toHaveTextContent(/Activo desde .* lo creó David/)
  expect(screen.getByText("Todavía no lo ha abierto nadie.")).toBeInTheDocument()
  expect(screen.queryByLabelText("Enlace para el cliente")).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", { name: "Regenerar enlace" }))
  expect(api.create).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole("button", { name: "Regenerar" }))
  await waitFor(() => expect(api.create).toHaveBeenCalledWith(7))
})

it("revoking asks for confirmation and then calls the API", async () => {
  api.status.mockResolvedValueOnce(active).mockResolvedValue(none)
  api.revoke.mockResolvedValue(undefined)
  setup()
  fireEvent.click(await screen.findByRole("button", { name: "Revocar" }))
  expect(screen.getByText(/dejará de poder abrirlo/)).toBeInTheDocument()
  const buttons = screen.getAllByRole("button", { name: "Revocar" })
  fireEvent.click(buttons[buttons.length - 1])
  await waitFor(() => expect(api.revoke).toHaveBeenCalledWith(7))
  expect(await screen.findByText("No hay ningún enlace activo.")).toBeInTheDocument()
})

it("without reading digests the link can be seen but not managed", async () => {
  perms.digests = false
  api.status.mockResolvedValue(active)
  setup()
  expect(await screen.findByRole("status")).toHaveTextContent("Activo desde")
  expect(screen.queryByRole("button", { name: "Revocar" })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "Regenerar enlace" })).not.toBeInTheDocument()
  expect(screen.getByText(/hace falta poder editar clientes y leer resúmenes/)).toBeInTheDocument()
})
