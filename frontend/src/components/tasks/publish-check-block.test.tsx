import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, expect, it, vi } from "vitest"
import { PublishCheckBlock } from "./publish-check-block"

const api = vi.hoisted(() => ({ publishCheck: { get: vi.fn(), retry: vi.fn() } }))
vi.mock("@/lib/api", () => ({ tasksApi: api }))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

function setup(canWrite = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><PublishCheckBlock taskId={5} canWrite={canWrite} /></QueryClientProvider>)
}

const problems = {
  enabled: true, url: "https://fit.es/guia", status: "problems", checked_at: "2026-10-27T08:00:00+00:00", attempts: 1,
  next_attempt_at: null, http_status: 200, final_url: "https://fit.es/guia", error: null,
  results: [
    { code: "http", label: "La página responde", ok: true, detail: "Responde 200" },
    { code: "indexable", label: "Google puede indexarla", ok: false, detail: "Lleva noindex (meta robots)" },
  ],
}

beforeEach(() => vi.resetAllMocks())

it("lists each check and lets a writer queue it again", async () => {
  api.publishCheck.get.mockResolvedValue(problems)
  api.publishCheck.retry.mockResolvedValue({ ...problems, status: "pending", attempts: 0, results: [] })
  setup()
  expect(await screen.findByText("Página publicada: hay que revisar algo")).toBeInTheDocument()
  expect(screen.getByText("Lleva noindex (meta robots)")).toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", { name: /Volver a comprobar/ }))
  await waitFor(() => expect(api.publishCheck.retry).toHaveBeenCalledWith(5))
  expect(await screen.findByText(/En cola/)).toBeInTheDocument()
})

it("explains why a link is not checked and hides itself when there is nothing to check", async () => {
  api.publishCheck.get.mockResolvedValue({ enabled: true, url: "https://docs.google.com/x", status: "skipped",
    error: "El enlace no es de la web del cliente (por ejemplo, un documento)." })
  const { unmount } = setup(false)
  expect(await screen.findByText(/No se revisa: El enlace no es de la web del cliente/)).toBeInTheDocument()
  unmount()
  api.publishCheck.get.mockResolvedValue({ enabled: true, url: null, status: "none" })
  const { container } = setup()
  await waitFor(() => expect(api.publishCheck.get).toHaveBeenCalledTimes(2))
  expect(container).toBeEmptyDOMElement()
})

it("readers see the result without the retry button", async () => {
  api.publishCheck.get.mockResolvedValue(problems)
  setup(false)
  await screen.findByText("Lleva noindex (meta robots)")
  expect(screen.queryByRole("button", { name: /Volver a comprobar/ })).not.toBeInTheDocument()
})
