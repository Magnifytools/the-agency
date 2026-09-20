import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import InboxPage from "./inbox-page"

const mocks = vi.hoisted(() => ({ list: vi.fn(), count: vi.fn(), user: { id: 7 } }))
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: mocks.user, hasPermission: () => true }) }))
vi.mock("@/lib/api", () => ({ inboxApi: { list: mocks.list, count: mocks.count } }))
vi.mock("@/components/inbox/inbox-note-card", () => ({ InboxNoteCard: ({ note }: { note: { raw_text: string } }) => <p>{note.raw_text}</p> }))
vi.mock("@/components/inbox/quick-capture-dialog", () => ({ QuickCaptureDialog: () => null }))

function setup() {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><InboxPage /></QueryClientProvider>)
}

describe("InboxPage", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.count.mockResolvedValue({ count: 1 })
  })

  it("shows a retryable loading error instead of an empty Inbox", async () => {
    mocks.list.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce([])
    setup()
    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo cargar el Inbox")
    expect(screen.queryByText("Inbox vacío")).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Reintentar" }))
    await waitFor(() => expect(screen.getByText("Inbox vacío")).toBeInTheDocument())
  })

  it("requests the current user's active notes", async () => {
    mocks.list.mockResolvedValue([{ id: 9, raw_text: "Revisar contrato", status: "pending" }])
    setup()
    expect(await screen.findByText("Revisar contrato")).toBeInTheDocument()
    expect(mocks.list).toHaveBeenCalledWith({ status: "pending,classified", limit: 50, offset: 0 })
  })

  it("loads the next page without dropping the first page", async () => {
    const firstPage = Array.from({ length: 50 }, (_, id) => ({ id: id + 1, raw_text: `Nota ${id + 1}`, status: "pending" }))
    mocks.list.mockResolvedValueOnce(firstPage).mockResolvedValueOnce([{ id: 51, raw_text: "Nota anterior", status: "processed" }])
    setup()
    expect(await screen.findByText("Nota 50")).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Cargar más" }))
    expect(await screen.findByText("Nota anterior")).toBeInTheDocument()
    expect(screen.getByText("Nota 1")).toBeInTheDocument()
    expect(mocks.list).toHaveBeenLastCalledWith({ status: "pending,classified", limit: 50, offset: 50 })
  })
})
