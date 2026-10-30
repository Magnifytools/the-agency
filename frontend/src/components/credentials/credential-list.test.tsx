import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { CredentialList } from "./credential-list"
import { REVEAL_SECONDS } from "./credential-secret"
import type { Credential } from "@/lib/credentials-api"

const api = vi.hoisted(() => ({
  list: vi.fn(), reveal: vi.fn(), log: vi.fn(), remove: vi.fn(), update: vi.fn(), create: vi.fn(),
  setShares: vi.fn(), shareableUsers: vi.fn(), totp: vi.fn(), notes: vi.fn(),
}))
const auth = vi.hoisted(() => ({ isAdmin: false, write: false }))
vi.mock("@/lib/credentials-api", () => ({ credentialsApi: api }))
vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({
    isAdmin: auth.isAdmin,
    user: { id: 1 },
    hasPermission: (module: string, write = false) => module === "credentials" && (!write || auth.write || auth.isAdmin),
  }),
}))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const wp: Credential = {
  id: 7, name: "WordPress Fit", url: "fit.example/wp-admin", username: "magnify", has_notes: false,
  client_id: 3, client_name: "Fit Generation", created_by: 2, created_by_name: "David",
  updated_at: "2026-10-20T08:00:00+00:00", can_manage: false, has_totp: false, shared_with: [],
}

function setup(props: Parameters<typeof CredentialList>[0] = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter><CredentialList {...props} /></MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.resetAllMocks()
  auth.isAdmin = false
  auth.write = false
})
afterEach(() => vi.useRealTimers())

it("lists without any secret and reveals it only on demand, then hides it again", async () => {
  api.list.mockResolvedValue([wp])
  api.reveal.mockResolvedValue("Cl4ve!")
  setup()
  expect(await screen.findByText("WordPress Fit")).toBeInTheDocument()
  expect(screen.getByText("Fit Generation")).toBeInTheDocument()
  expect(screen.getByTestId("secret-7")).toHaveTextContent("••••••••")
  expect(screen.queryByText("Cl4ve!")).not.toBeInTheDocument()
  // Sin permiso de gestión: ni editar, ni compartir, ni registro, ni borrar.
  expect(screen.queryByRole("button", { name: /Editar|Compartir|Registro|Borrar/ })).not.toBeInTheDocument()

  fireEvent.click(screen.getByRole("button", { name: "Ver contraseña de WordPress Fit" }))
  await waitFor(() => expect(screen.getByTestId("secret-7")).toHaveTextContent("Cl4ve!"))
  expect(api.reveal).toHaveBeenCalledWith(7, "reveal")
  fireEvent.click(screen.getByRole("button", { name: "Ocultar contraseña de WordPress Fit" }))
  expect(screen.getByTestId("secret-7")).toHaveTextContent("••••••••")
})

it("a revealed secret hides itself after a while", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  api.list.mockResolvedValue([wp])
  api.reveal.mockResolvedValue("Cl4ve!")
  setup()
  fireEvent.click(await screen.findByRole("button", { name: "Ver contraseña de WordPress Fit" }))
  await waitFor(() => expect(screen.getByTestId("secret-7")).toHaveTextContent("Cl4ve!"))
  await act(async () => { vi.advanceTimersByTime(REVEAL_SECONDS * 1000) })
  expect(screen.getByTestId("secret-7")).toHaveTextContent("••••••••")
})

it("copy asks the server with purpose copy (so it is logged) and writes the clipboard", async () => {
  api.list.mockResolvedValue([wp])
  api.reveal.mockResolvedValue("Cl4ve!")
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.assign(navigator, { clipboard: { writeText } })
  setup()
  fireEvent.click(await screen.findByRole("button", { name: "Copiar contraseña de WordPress Fit" }))
  await waitFor(() => expect(writeText).toHaveBeenCalledWith("Cl4ve!"))
  expect(api.reveal).toHaveBeenCalledWith(7, "copy")
  expect(screen.getByTestId("secret-7")).toHaveTextContent("••••••••")
})

it("admins get the access log and delete; managers get edit and share", async () => {
  auth.isAdmin = true
  api.list.mockResolvedValue([{ ...wp, can_manage: true }])
  api.log.mockResolvedValue([
    { id: 1, action: "copy", user_id: 4, user_name: "Nacho", detail: null, at: "2026-10-20T09:00:00+00:00" },
  ])
  setup()
  fireEvent.click(await screen.findByRole("button", { name: "Registro de WordPress Fit" }))
  expect(await screen.findByText("Nacho")).toBeInTheDocument()
  expect(screen.getByText(/Copió la contraseña/)).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Editar WordPress Fit" })).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Compartir WordPress Fit" })).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Borrar WordPress Fit" })).toBeInTheDocument()
})

it("a client tab filters by client and never links unsafe URLs", async () => {
  api.list.mockResolvedValue([{ ...wp, url: "javascript:alert(1)" }])
  setup({ clientId: 3, showClient: false })
  expect(await screen.findByText("WordPress Fit")).toBeInTheDocument()
  expect(api.list).toHaveBeenCalledWith({ client_id: 3 })
  expect(screen.queryByRole("link")).not.toBeInTheDocument()
  expect(screen.queryByText("Fit Generation")).not.toBeInTheDocument()
})

it("only entries with a 2FA key offer the code; it counts down, rolls to the next one and hides", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  api.list.mockResolvedValue([{ ...wp, has_totp: true }, { ...wp, id: 8, name: "Semrush" }])
  api.totp.mockResolvedValue({ code: "123456", next_code: "654321", remaining: 3, period: 30, digits: 6 })
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.assign(navigator, { clipboard: { writeText } })
  setup()
  expect(await screen.findByRole("button", { name: "Ver código 2FA de WordPress Fit" })).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "Ver código 2FA de Semrush" })).not.toBeInTheDocument()

  fireEvent.click(screen.getByRole("button", { name: "Ver código 2FA de WordPress Fit" }))
  await waitFor(() => expect(screen.getByTestId("totp-7")).toHaveTextContent("123 456"))
  expect(api.totp).toHaveBeenCalledWith(7)
  fireEvent.click(screen.getByRole("button", { name: "Copiar código 2FA de WordPress Fit" }))
  await waitFor(() => expect(writeText).toHaveBeenCalledWith("123456"))

  await act(async () => { vi.advanceTimersByTime(3500) })
  expect(screen.getByTestId("totp-7")).toHaveTextContent("654 321")
  expect(api.totp).toHaveBeenCalledTimes(1)  // el siguiente no se vuelve a pedir
  await act(async () => { vi.advanceTimersByTime(30_000) })
  expect(screen.queryByTestId("totp-7")).not.toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Ver código 2FA de WordPress Fit" })).toBeInTheDocument()
})


it("opens the encrypted notes on demand and hides them again", async () => {
  api.list.mockResolvedValue([{ ...wp, has_notes: true }])
  api.notes.mockResolvedValue("PIN 1234")
  setup()
  await screen.findByText("WordPress Fit")
  expect(screen.queryByText("PIN 1234")).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", { name: "Ver notas de WordPress Fit" }))
  expect(await screen.findByText("PIN 1234")).toBeInTheDocument()
  expect(api.notes).toHaveBeenCalledWith(7)
  fireEvent.click(screen.getByRole("button", { name: "Ocultar notas de WordPress Fit" }))
  expect(screen.queryByText("PIN 1234")).not.toBeInTheDocument()
})

it("offers no notes button when there are none", async () => {
  api.list.mockResolvedValue([wp])
  setup()
  await screen.findByText("WordPress Fit")
  expect(screen.queryByRole("button", { name: /notas/ })).not.toBeInTheDocument()
})
