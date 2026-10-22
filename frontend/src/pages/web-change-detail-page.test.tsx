import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { beforeEach, expect, it, vi } from "vitest"
import WebChangeDetailPage from "./web-change-detail-page"

const changesApi = vi.hoisted(() => ({ get: vi.fn(), diff: vi.fn(), htmlDiff: vi.fn(), ack: vi.fn() }))
const watchesApi = vi.hoisted(() => ({ get: vi.fn(), history: vi.fn() }))
const perms = vi.hoisted(() => ({ write: true }))
vi.mock("@/lib/api", () => ({ webChangesApi: changesApi, webWatchesApi: watchesApi }))
vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ hasPermission: (module: string, write = false) => module === "web" && (!write || perms.write) }),
}))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const htmlItem = { id: "h", kind: "html", field: "raw_html", severity: "info", rule_code: "HTML_CHANGED",
  rule_label: "cambió el HTML", before_val: null, after_val: null, detail: { added: 14, removed: 9, after_lines: 3837 } }
const contentItem = { id: "t", kind: "content", field: "text", severity: "warning", rule_code: "CONTENT_CHANGED_MAJOR",
  rule_label: "contenido reescrito", before_val: "120 palabras", after_val: "180 palabras", detail: { diff: { hunks: [] } } }

const detail = (items: unknown[], extra: object = {}) => ({
  change: {
    id: "c1", client_id: 7, client_name: "Fit", watch_id: "w1", url: "https://fit.es/master", label: "Máster", run_id: null,
    max_severity: "warning", detected_at: "2026-10-21T06:40:00+00:00", acknowledged_at: null, acknowledged_by: null,
    acknowledged_by_label: null, note: null, has_diff: true, items, ...extra,
  },
  watch: { id: "w1", url: "https://fit.es/master", label: "Máster", client_id: 7, archived_at: null, watch_html: true },
})

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/web/cambios/c1"]}>
        <Routes><Route path="/web/cambios/:id" element={<WebChangeDetailPage />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.resetAllMocks()
  perms.write = true
})

it("an empty HTML diff explains its reason instead of a blank panel", async () => {
  changesApi.get.mockResolvedValue(detail([htmlItem]))
  changesApi.htmlDiff.mockResolvedValue({ available: false, reason: "sin_anterior" })
  setup()
  expect(await screen.findByText(/Es el primer cambio con HTML guardado para esta URL/)).toBeInTheDocument()
  // El tamaño del cambio de maquetación, también en la ficha.
  expect(screen.getByText("+14")).toBeInTheDocument()
  expect(screen.getByText("−9")).toBeInTheDocument()
  expect(changesApi.htmlDiff).toHaveBeenCalledWith("c1")
  // Sin item de contenido no se pide el texto.
  expect(changesApi.diff).not.toHaveBeenCalled()
})

it("shows the text diff in mono and the HTML hunks", async () => {
  changesApi.get.mockResolvedValue(detail([contentItem, htmlItem]))
  changesApi.diff.mockResolvedValue({ before: "Hola. Precio 100 €. Adiós.", after: "Hola. Precio 120 €. Adiós." })
  changesApi.htmlDiff.mockResolvedValue({
    available: true, stats: { before_lines: 10, after_lines: 10, added: 1, removed: 1 }, hunks_total: 1, truncated: false,
    hunks: [{ before_start: 4, after_start: 4, lines_total: 2, lines: [{ t: "-", s: "<p>100</p>" }, { t: "+", s: "<p>120</p>" }] }],
  })
  setup()
  expect(await screen.findByText("Precio 120 €.")).toBeInTheDocument()
  expect(screen.getByText("Precio 100 €.").closest(".mono")).not.toBeNull()
  expect(await screen.findByText("<p>120</p>")).toBeInTheDocument()
  expect(screen.getByText("línea 4 → 4")).toBeInTheDocument()
})

it("acknowledges with a note", async () => {
  changesApi.get.mockResolvedValue(detail([contentItem]))
  changesApi.diff.mockResolvedValue({ before: null, after: "x" })
  changesApi.ack.mockResolvedValue({})
  setup()
  fireEvent.change(await screen.findByPlaceholderText(/Cambio previsto/), { target: { value: "Lo cambió el cliente" } })
  fireEvent.click(screen.getByRole("button", { name: /Marcar revisado/ }))
  await waitFor(() => expect(changesApi.ack).toHaveBeenCalledWith("c1", "Lo cambió el cliente"))
  await waitFor(() => expect(changesApi.get).toHaveBeenCalledTimes(2))
})

it("says who acknowledged and when, with the note", async () => {
  changesApi.get.mockResolvedValue(detail([contentItem], {
    acknowledged_at: "2026-10-21T09:00:00+00:00", acknowledged_by: 1, acknowledged_by_label: "David", note: "Previsto",
  }))
  changesApi.diff.mockResolvedValue({ before: null, after: "x" })
  setup()
  expect(await screen.findByText("David")).toBeInTheDocument()
  expect(screen.getByText("«Previsto»")).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: /Marcar revisado/ })).not.toBeInTheDocument()
  expect(await screen.findByText(/No se guardó el texto anterior/)).toBeInTheDocument()
})

it("readers cannot acknowledge", async () => {
  perms.write = false
  changesApi.get.mockResolvedValue(detail([htmlItem]))
  changesApi.htmlDiff.mockResolvedValue({ available: false, reason: "sin_actual" })
  setup()
  expect(await screen.findByText(/Vigilar HTML/)).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: /Marcar revisado/ })).not.toBeInTheDocument()
  expect(screen.getByText("Sin revisar.")).toBeInTheDocument()
})
