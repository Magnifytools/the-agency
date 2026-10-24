import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, expect, it, vi } from "vitest"
import SuggestionsPage from "./suggestions-page"
import { SuggestionButton } from "@/components/layout/suggestion-button"

const api = vi.hoisted(() => ({
  list: vi.fn(), create: vi.fn(), update: vi.fn(), addImage: vi.fn(),
  imageUrl: (id: number, imageId: number) => `/api/suggestions/${id}/images/${imageId}`,
}))
const auth = vi.hoisted(() => ({ isAdmin: true }))
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), warning: vi.fn() }))
vi.mock("@/lib/api", () => ({ suggestionsApi: api }))
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ isAdmin: auth.isAdmin }) }))
vi.mock("sonner", () => ({ toast }))

const open = {
  id: 3, text: "Al subir un informe en HTML no pasa nada", page_path: "/clients/12?tab=contexto",
  author_id: 2, author_name: "Nacho", created_at: new Date().toISOString(), done_at: null, done_by_name: null,
  images: [] as { id: number; name: string; size_bytes: number }[],
}

function setup(ui: React.ReactNode, url = "/sugerencias") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[url]}>{ui}</MemoryRouter></QueryClientProvider>)
}

beforeEach(() => {
  vi.clearAllMocks()
  let n = 0
  URL.createObjectURL = vi.fn(() => `blob:preview-${++n}`)
  URL.revokeObjectURL = vi.fn()
  api.addImage.mockResolvedValue({ id: 9, name: "captura.png", size_bytes: 10 })
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


const png = (name = "captura.png", size = 10) => new File([new Uint8Array(size)], name, { type: "image/png" })

it("shows the screenshots of a suggestion as thumbnails that open the full image", async () => {
  api.list.mockResolvedValue([{ ...open, images: [{ id: 9, name: "captura.png", size_bytes: 10 }] }])
  setup(<SuggestionsPage />)
  const img = await screen.findByAltText("captura.png")
  expect(img).toHaveAttribute("src", "/api/suggestions/3/images/9")
  expect(img.closest("a")).toHaveAttribute("href", "/api/suggestions/3/images/9")
})

it("attaches chosen and pasted screenshots and uploads them after creating the suggestion", async () => {
  const user = userEvent.setup()
  setup(<SuggestionButton />, "/tasks")
  await user.click(screen.getByRole("button", { name: /Sugerencias o fallos/ }))
  await user.type(screen.getByLabelText(/Una idea para mejorar/), "Mira este fallo")
  await user.upload(screen.getByLabelText("Pantallazos"), png("elegida.png"))
  const pasted = png("pegada.png")
  const event = new Event("paste", { bubbles: true, cancelable: true })
  Object.defineProperty(event, "clipboardData", { value: { files: [pasted] } })
  screen.getByLabelText(/Una idea para mejorar/).dispatchEvent(event)
  const list = await screen.findByRole("list", { name: "Pantallazos adjuntos" })
  expect(within(list).getAllByRole("img").map((i) => i.getAttribute("alt"))).toEqual(["elegida.png", "pegada.png"])

  await user.click(screen.getByRole("button", { name: "Enviar" }))
  await waitFor(() => expect(api.addImage).toHaveBeenCalledTimes(2))
  expect(api.create).toHaveBeenCalledWith({ text: "Mira este fallo", page_path: "/tasks" })
  expect(api.addImage.mock.calls.map(([id, file]) => [id, (file as File).name])).toEqual([[4, "elegida.png"], [4, "pegada.png"]])
  await waitFor(() => expect(toast.success).toHaveBeenCalled())
})

it("rejects what is not an image or too big, caps at five, and lets you remove one", async () => {
  const user = userEvent.setup({ applyAccept: false })
  setup(<SuggestionButton />)
  await user.click(screen.getByRole("button", { name: /Sugerencias o fallos/ }))
  const input = screen.getByLabelText("Pantallazos")
  await user.upload(input, new File(["<p>"], "informe.html", { type: "text/html" }))
  expect(screen.getByRole("alert")).toHaveTextContent("Sólo imágenes PNG, JPG, GIF o WebP")
  await user.upload(input, png("enorme.png", 5 * 1024 * 1024 + 1))
  expect(screen.getByRole("alert")).toHaveTextContent("enorme.png pasa de 5 MB")
  await user.upload(input, [1, 2, 3, 4, 5, 6].map((n) => png(`c${n}.png`)))
  expect(screen.getByRole("alert")).toHaveTextContent("Como mucho 5 imágenes")
  expect(screen.getAllByRole("button", { name: /^Quitar / })).toHaveLength(5)
  expect(screen.getByRole("button", { name: /Añadir pantallazo/ })).toBeDisabled()
  await user.click(screen.getByRole("button", { name: "Quitar c1.png" }))
  expect(screen.getAllByRole("button", { name: /^Quitar / })).toHaveLength(4)
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:preview-1")
})

it("keeps the suggestion and says so when a screenshot fails to upload", async () => {
  const user = userEvent.setup()
  api.addImage.mockRejectedValueOnce(new Error("413"))
  setup(<SuggestionButton />)
  await user.click(screen.getByRole("button", { name: /Sugerencias o fallos/ }))
  await user.type(screen.getByLabelText(/Una idea para mejorar/), "Con dos capturas")
  await user.upload(screen.getByLabelText("Pantallazos"), [png("a.png"), png("b.png")])
  await user.click(screen.getByRole("button", { name: "Enviar" }))
  await waitFor(() => expect(toast.warning).toHaveBeenCalled())
  expect(toast.warning.mock.calls[0][0]).toBe("Sugerencia enviada, pero una imagen no se pudo subir.")
  expect(api.addImage).toHaveBeenCalledTimes(2)
})
