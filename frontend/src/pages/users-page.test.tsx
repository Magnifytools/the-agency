import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import UsersPage from "./users-page"

const api = vi.hoisted(() => ({ list: vi.fn(), permissions: vi.fn(), updatePermissions: vi.fn() }))
vi.mock("@/lib/api", () => ({ usersApi: { list: api.list, getPermissions: api.permissions, updatePermissions: api.updatePermissions, update: vi.fn(), create: vi.fn() } }))
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: { id: 1, role: "admin" } }) }))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const user = (id: number, name: string) => ({ id, full_name: name, short_name: name, email: `${id}@test.local`, role: "member", is_active: true, hourly_rate: null, job_title: null, locality: null })
const page = (items: ReturnType<typeof user>[]) => ({ items, total: items.length, page: 1, page_size: 25 })

function show(client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })) {
  return { client, ...render(<QueryClientProvider client={client}><UsersPage /></QueryClientProvider>) }
}

describe("UsersPage safe reads", () => {
  beforeEach(() => { vi.clearAllMocks(); api.list.mockResolvedValue(page([])); api.permissions.mockResolvedValue([]) })

  it("identifies the invitation password as a new password", async () => {
    show()
    await userEvent.click(await screen.findByRole("button", { name: /Invitar miembro/i }))
    expect(screen.getByLabelText("Contraseña inicial")).toHaveAttribute("autocomplete", "new-password")
  })

  it("hides cached users after refresh failure and restores only a fresh result", async () => {
    api.list.mockResolvedValueOnce(page([user(2, "Ana anterior")]))
    const { client } = show()
    expect((await screen.findAllByText("Ana anterior")).length).toBeGreaterThan(0)
    api.list.mockRejectedValueOnce({ response: { status: 503 } })
    await act(async () => { await client.invalidateQueries({ queryKey: ["users"] }) })
    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo cargar el equipo")
    expect(screen.queryByText("Ana anterior")).not.toBeInTheDocument()
    api.list.mockResolvedValueOnce(page([user(3, "Bea nueva")]))
    await userEvent.click(screen.getByRole("button", { name: "Reintentar" }))
    expect((await screen.findAllByText("Bea nueva")).length).toBeGreaterThan(0)
  })

  it("does not resurrect a denied user list after remount and a later 503", async () => {
    api.list.mockResolvedValueOnce(page([user(2, "Dato restringido")]))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    show(client)
    expect((await screen.findAllByText("Dato restringido")).length).toBeGreaterThan(0)
    api.list.mockRejectedValueOnce({ response: { status: 403 } })
    await act(async () => { await client.invalidateQueries({ queryKey: ["users"] }) })
    expect(await screen.findByRole("alert")).toBeInTheDocument()
    cleanup()
    api.list.mockRejectedValueOnce({ response: { status: 503 } })
    show(client)
    expect(await screen.findByRole("alert")).toBeInTheDocument()
    expect(screen.queryByText("Dato restringido")).not.toBeInTheDocument()
  })

  it("never exposes A permissions while B is denied and enables save only after B succeeds", async () => {
    api.list.mockResolvedValue(page([user(2, "Ana"), user(3, "Bea")]))
    api.permissions.mockImplementation((id: number) => id === 2
      ? Promise.resolve([{ module: "clients", can_read: true, can_write: true }])
      : Promise.reject({ response: { status: 403 } }))
    show()
    await screen.findAllByText("Ana")
    await userEvent.click(screen.getAllByRole("button", { name: "Permisos" })[0])
    expect((await screen.findAllByRole("checkbox", { name: "Leer" }))[1]).toBeChecked()
    await userEvent.click(screen.getByRole("button", { name: "Cancelar" }))
    await userEvent.click(screen.getAllByRole("button", { name: "Permisos" })[1])
    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudieron cargar los permisos")
    expect(screen.queryByRole("checkbox", { name: "Leer" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Guardar permisos" })).not.toBeInTheDocument()
    api.permissions.mockResolvedValueOnce([{ module: "tasks", can_read: true, can_write: false }])
    await userEvent.click(screen.getByRole("button", { name: "Reintentar" }))
    await waitFor(() => expect(screen.getAllByRole("checkbox", { name: "Leer" })[3]).toBeChecked())
    expect(screen.getByRole("button", { name: "Guardar permisos" })).toBeEnabled()
  })
})
