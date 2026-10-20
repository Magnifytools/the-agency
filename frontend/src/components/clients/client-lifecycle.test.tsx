import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import type { Client } from "@/lib/types"
import { ClientLifecycleButton, FormerClientNotice } from "./client-lifecycle"

const mocks = vi.hoisted(() => ({ update: vi.fn(), canWrite: true }))
vi.mock("@/lib/api", () => ({ clientsApi: { update: mocks.update } }))
vi.mock("@/lib/query-keys", () => ({ invalidateClientChange: vi.fn() }))
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ hasPermission: () => mocks.canWrite }) }))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const client = (status: string) => ({ id: 21, name: "Denarius", status }) as unknown as Client
const show = (ui: React.ReactNode) => render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>)

describe("Client lifecycle", () => {
  beforeEach(() => { vi.clearAllMocks(); mocks.canWrite = true; mocks.update.mockResolvedValue({}) })

  it("marks an active client as former after confirming, without deleting it", async () => {
    show(<ClientLifecycleButton client={client("active")} />)
    await userEvent.click(screen.getByRole("button", { name: /Marcar como antiguo/ }))
    expect(screen.getByText(/No se borra nada/)).toBeInTheDocument()
    await userEvent.click(screen.getAllByRole("button", { name: "Marcar como antiguo" }).at(-1)!)
    expect(mocks.update).toHaveBeenCalledWith(21, { status: "finished" })
  })

  it("reactivates a former client and explains it in the record", async () => {
    show(<><FormerClientNotice client={client("finished")} /><ClientLifecycleButton client={client("finished")} /></>)
    expect(screen.getByText(/Cliente antiguo/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: /Reactivar/ }))
    expect(mocks.update).toHaveBeenCalledWith(21, { status: "active" })
  })

  it("hides the actions from readers", () => {
    mocks.canWrite = false
    show(<ClientLifecycleButton client={client("active")} />)
    expect(screen.queryByRole("button")).not.toBeInTheDocument()
  })
})
