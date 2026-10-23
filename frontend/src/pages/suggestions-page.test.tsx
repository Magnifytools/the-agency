import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, expect, it, vi } from "vitest"
import SuggestionsPage from "./suggestions-page"
import { SuggestionButton } from "@/components/layout/suggestion-button"

const api = vi.hoisted(() => ({ list: vi.fn(), create: vi.fn(), update: vi.fn() }))
const auth = vi.hoisted(() => ({ isAdmin: true }))
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }))
vi.mock("@/lib/api", () => ({ suggestionsApi: api }))
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ isAdmin: auth.isAdmin }) }))
vi.mock("sonner", () => ({ toast }))

const open = {
  id: 3, text: "Al subir un informe en HTML no pasa nada", page_path: "/clients/12?tab=contexto",
  author_id: 2, author_name: "Nacho", created_at: new Date().toISOString(), done_at: null, done_by_name: null,
}

function setup(ui: React.ReactNode, url = "/sugerencias") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[url]}>{ui}</MemoryRouter></QueryClientProvider>)
}

beforeEach(() => {
  vi.clearAllMocks()
  auth.isAdmin = true
  api.list.mockResolvedValue([open])
  api.create.mockResolvedValue({ ...open, id: 4 })
  api.update.mockResolvedValue({ ...open, done_at: new Date().toISOString(), done_by_name: "David" })
})

it("lets an admin see who sent what from where and mark it as done", async () => {
  setup(<SuggestionsPage />)
  const row = (await screen.findByText(open.text)).closest("li")!
  expect(within(row).getByText(/Nacho/)).toBeInTheDocument()
  expect(within(row).getByRole("link", { name: open.page_path })).toHaveAttribute("href", open.page_path)
  expect(api.list).toHaveBeenCalledWith("open")

  await userEvent.click(within(row).getByRole("button", { name: "Marcar como hecha" }))
  await waitFor(() => expect(api.update).toHaveBeenCalledWith(3, { done: true }))
  expect(toast.success).toHaveBeenCalledWith("Marcada como hecha")

  await userEvent.click(screen.getByRole("button", { name: "Hechas" }))
  await waitFor(() => expect(api.list).toHaveBeenLastCalledWith("done"))
})

it("shows members their own suggestions without the done button", async () => {
  auth.isAdmin = false
  api.list.mockResolvedValue([{ ...open, done_at: new Date().toISOString(), done_by_name: "David" }])
  setup(<SuggestionsPage />)
  expect(await screen.findByText(/Hecha por David/)).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: /Marcar como hecha|Reabrir/ })).not.toBeInTheDocument()
})

it("sends a suggestion from the sidebar with the page it was written on", async () => {
  setup(<SuggestionButton />, "/clients/12?tab=contexto")
  await userEvent.click(screen.getByRole("button", { name: "Sugerencias o fallos" }))
  const dialog = screen.getByRole("dialog")
  const send = within(dialog).getByRole("button", { name: "Enviar" })
  expect(send).toBeDisabled()

  await userEvent.type(within(dialog).getByRole("textbox"), "  Poder subir ZIP  ")
  await userEvent.click(send)
  await waitFor(() => expect(api.create).toHaveBeenCalledWith({ text: "Poder subir ZIP", page_path: "/clients/12?tab=contexto" }))
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
  expect(toast.success).toHaveBeenCalledWith("Sugerencia enviada. ¡Gracias!", expect.anything())
})

it("keeps the text and says why when sending fails", async () => {
  api.create.mockRejectedValue(new Error("Sin conexión"))
  setup(<SuggestionButton />)
  await userEvent.click(screen.getByRole("button", { name: "Sugerencias o fallos" }))
  await userEvent.type(screen.getByRole("textbox"), "Idea")
  await userEvent.click(screen.getByRole("button", { name: "Enviar" }))
  await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Sin conexión"))
  expect(screen.getByRole("textbox")).toHaveValue("Idea")
})
