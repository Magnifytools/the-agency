import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import type { ClientBingConnection } from "@/lib/types"
import { ClientBingCard } from "./client-bing-card"

const mocks = vi.hoisted(() => ({
  admin: true,
  connection: vi.fn(),
  sites: vi.fn(),
  connect: vi.fn(),
  disconnect: vi.fn(),
}))

vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ isAdmin: mocks.admin }) }))
vi.mock("@/lib/api", () => ({
  clientBingApi: { connection: mocks.connection, sites: mocks.sites, connect: mocks.connect, disconnect: mocks.disconnect },
}))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const SITE = "https://www.acme.com/"
const OFF: ClientBingConnection = { connected: false, site_url: null, status: null, last_error: null,
                                    connected_at: null, connected_by_name: null }
const ON: ClientBingConnection = { connected: true, site_url: SITE, status: "ok", last_error: null,
                                   connected_at: "2026-11-11T09:00:00Z", connected_by_name: "David" }

function show() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><ClientBingCard clientId={5} /></QueryClientProvider>)
}

describe("ClientBingCard", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.admin = true
    mocks.connection.mockResolvedValue(OFF)
  })

  it("conecta: comprueba la clave, preselecciona el sitio de la web y guarda", async () => {
    mocks.sites.mockResolvedValue({ sites: ["https://otra.com/", SITE], suggested: SITE })
    mocks.connect.mockResolvedValue(ON)
    show()

    await userEvent.type(await screen.findByLabelText("API key de Bing"), "  clave-secreta-123 ")
    await userEvent.click(screen.getByRole("button", { name: "Comprobar clave" }))
    expect(mocks.sites).toHaveBeenCalledWith(5, "clave-secreta-123")
    expect(await screen.findByRole("radio", { name: /www\.acme\.com/ })).toBeChecked()

    await userEvent.click(screen.getByRole("button", { name: "Conectar" }))
    expect(mocks.connect).toHaveBeenCalledWith(5, "clave-secreta-123", SITE)
    expect(await screen.findByText(/Conectado/)).toBeInTheDocument()
    expect(screen.queryByLabelText("API key de Bing")).not.toBeInTheDocument()
  })

  it("sin sitio que coincida no elige por su cuenta", async () => {
    mocks.sites.mockResolvedValue({ sites: ["https://uno.com/", "https://dos.com/"], suggested: null })
    show()
    await userEvent.type(await screen.findByLabelText("API key de Bing"), "clave-secreta-123")
    await userEvent.click(screen.getByRole("button", { name: "Comprobar clave" }))
    await screen.findByRole("radio", { name: /uno\.com/ })
    expect(screen.getByRole("button", { name: "Conectar" })).toBeDisabled()
  })

  it("una cuenta sin sitios verificados lo dice", async () => {
    mocks.sites.mockResolvedValue({ sites: [], suggested: null })
    show()
    await userEvent.type(await screen.findByLabelText("API key de Bing"), "clave-secreta-123")
    await userEvent.click(screen.getByRole("button", { name: "Comprobar clave" }))
    expect(await screen.findByText("Esa cuenta no tiene ningún sitio verificado en Bing.")).toBeInTheDocument()
  })

  it("conectada: el admin puede cambiar la clave o desconectar avisando de que sigue viva en Bing", async () => {
    mocks.connection.mockResolvedValue(ON)
    mocks.disconnect.mockResolvedValue(OFF)
    show()
    expect(await screen.findByText(SITE)).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Cambiar clave" }))
    expect(screen.getByLabelText("API key de Bing")).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Cancelar" }))

    await userEvent.click(screen.getByRole("button", { name: "Desconectar" }))
    expect(screen.getByText(/sigue activa en Bing Webmaster Tools/)).toBeInTheDocument()
    await userEvent.click(screen.getAllByRole("button", { name: "Desconectar" }).at(-1)!)
    expect(mocks.disconnect).toHaveBeenCalledWith(5)
  })

  it("quien no es admin sólo ve el estado", async () => {
    mocks.admin = false
    mocks.connection.mockResolvedValue({ ...ON, status: "invalid", last_error: "InvalidApiKey" })
    show()
    expect(await screen.findByText(/Bing ya no acepta la clave \(InvalidApiKey\)\. Avisa a un admin\./)).toBeInTheDocument()
    expect(screen.queryByRole("button")).not.toBeInTheDocument()
    expect(screen.queryByLabelText("API key de Bing")).not.toBeInTheDocument()
  })
})
