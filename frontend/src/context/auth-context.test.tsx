import { useState } from "react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import type { User } from "@/lib/types"
import { AuthProvider, useAuth } from "./auth-context"

const api = vi.hoisted(() => ({ me: vi.fn(), login: vi.fn(), logout: vi.fn(), beginApiSessionTransition: vi.fn() }))
vi.mock("@/lib/api", () => ({ authApi: api, beginApiSessionTransition: api.beginApiSessionTransition }))

const admin: User = { id: 1, email: "admin@example.com", full_name: "Admin", role: "admin", hourly_rate: null, is_active: true, permissions: [] }
const member: User = { id: 2, email: "member@example.com", full_name: "Member", role: "member", hourly_rate: null, is_active: true, permissions: [] }

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

function Controls() {
  const { user, login, logout } = useAuth()
  const [loginError, setLoginError] = useState("")
  return <>
    <p>{user?.email ?? "anonymous"}</p>
    {loginError && <p role="alert">{loginError}</p>}
    <button onClick={() => void login("member@example.com", "password").catch(() => setLoginError("No se pudo iniciar sesión"))}>Cambiar identidad</button>
    <button onClick={() => void logout()}>Cerrar sesión</button>
  </>
}

function setup() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={queryClient}><AuthProvider><Controls /></AuthProvider></QueryClientProvider>)
  return queryClient
}

describe("AuthProvider session cache", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.logout.mockResolvedValue(undefined)
  })

  it("cancels and clears admin data before a member session starts", async () => {
    api.me.mockResolvedValueOnce(admin).mockResolvedValueOnce(member)
    api.login.mockResolvedValue(undefined)
    const queryClient = setup()
    await screen.findByText(admin.email)
    queryClient.setQueryData(["clients"], ["admin-only"])

    await userEvent.click(screen.getByRole("button", { name: "Cambiar identidad" }))
    await screen.findByText(member.email)

    expect(queryClient.getQueryData(["clients"])).toBeUndefined()
  })

  it("does not restore a cancelled late response after logout", async () => {
    api.me.mockResolvedValue(admin)
    const queryClient = setup()
    await screen.findByText(admin.email)
    const late = deferred<string>()
    void queryClient.fetchQuery({ queryKey: ["private", "admin"], queryFn: () => late.promise }).catch(() => undefined)
    await waitFor(() => expect(queryClient.getQueryState(["private", "admin"])?.fetchStatus).toBe("fetching"))

    await userEvent.click(screen.getByRole("button", { name: "Cerrar sesión" }))
    expect(screen.getByText("anonymous")).toBeInTheDocument()
    expect(queryClient.getQueryData(["private", "admin"])).toBeUndefined()

    await act(async () => { late.resolve("should not return") })
    expect(queryClient.getQueryData(["private", "admin"])).toBeUndefined()
  })

  it("invalidates an in-flight identity read when the session expires", async () => {
    const lateMe = deferred<User>()
    api.me.mockReturnValue(lateMe.promise)
    const queryClient = setup()
    queryClient.setQueryData(["dashboard"], { owner: "admin" })

    await act(async () => { window.dispatchEvent(new Event("auth:expired")) })
    expect(screen.getByText("anonymous")).toBeInTheDocument()
    expect(queryClient.getQueryData(["dashboard"])).toBeUndefined()

    await act(async () => { lateMe.resolve(admin) })
    expect(screen.getByText("anonymous")).toBeInTheDocument()
  })

  it("leaves the previous identity cleared when a new login fails", async () => {
    api.me.mockResolvedValueOnce(admin)
    api.login.mockRejectedValueOnce(new Error("invalid credentials"))
    const queryClient = setup()
    await screen.findByText(admin.email)
    queryClient.setQueryData(["clients"], ["admin-only"])

    await userEvent.click(screen.getByRole("button", { name: "Cambiar identidad" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo iniciar sesión")
    expect(screen.getByText("anonymous")).toBeInTheDocument()
    expect(queryClient.getQueryData(["clients"])).toBeUndefined()
  })

  it("waits for logout to finish before starting a new login", async () => {
    const pendingLogout = deferred<void>()
    api.me.mockResolvedValueOnce(admin).mockResolvedValueOnce(member)
    api.logout.mockReturnValueOnce(pendingLogout.promise)
    api.login.mockResolvedValueOnce(undefined)
    setup()
    await screen.findByText(admin.email)

    await userEvent.click(screen.getByRole("button", { name: "Cerrar sesión" }))
    await userEvent.click(screen.getByRole("button", { name: "Cambiar identidad" }))
    expect(api.login).not.toHaveBeenCalled()

    await act(async () => { pendingLogout.resolve(undefined) })
    await screen.findByText(member.email)
    expect(api.login).toHaveBeenCalledOnce()
  })
})
