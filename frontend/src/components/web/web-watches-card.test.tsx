import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, expect, it, vi } from "vitest"
import { WebWatchesCard, urlsFromText } from "./web-watches-card"

const api = vi.hoisted(() => ({
  list: vi.fn(), progress: vi.fn(), checkAll: vi.fn(), check: vi.fn(), update: vi.fn(), archive: vi.fn(), restore: vi.fn(),
  create: vi.fn(), bulk: vi.fn(), importSitemap: vi.fn(), get: vi.fn(), history: vi.fn(), preview: vi.fn(),
}))
const perms = vi.hoisted(() => ({ write: true }))
vi.mock("@/lib/api", () => ({ webWatchesApi: api }))
vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ hasPermission: (module: string, write = false) => module === "web" && (!write || perms.write) }),
}))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const watch = {
  id: "w1", client_id: 7, url: "https://fit.es/master", label: "Máster", is_active: true, archived_at: null,
  watch_seo: true, watch_content: true, watch_links: false, watch_html: false, content_selector: null,
  ignore_selectors: null, ignore_regexes: null, muted: false, source: "manual", check_requested_at: null,
  created_at: null, updated_at: null, checking: false,
  state: { last_checked_at: "2026-10-21T06:40:00+00:00", last_changed_at: null, last_status_code: 200, last_final_url: null,
    last_error: "timeout", consecutive_errors: 2, needs_js_render: false, scope_missed: false, title: "Máster", word_count: 900 },
}
const idle = { enabled: true, is_running: false, checking: [], queued: [], last_run: null }

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={client}><MemoryRouter><WebWatchesCard clientId={7} /></MemoryRouter></QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.resetAllMocks()
  perms.write = true
})

it("lists watched URLs with their state", async () => {
  api.list.mockResolvedValue({ enabled: true, monitored: true, watches: [watch] })
  api.progress.mockResolvedValue(idle)
  setup()
  expect(await screen.findByText("/master")).toBeInTheDocument()
  expect(screen.getByText("Error")).toBeInTheDocument()
  expect(api.list).toHaveBeenCalledWith(7, { include_archived: false })
})

it("check all asks the job and shows the progress", async () => {
  api.list.mockResolvedValue({ enabled: true, monitored: true, watches: [watch] })
  api.progress.mockResolvedValueOnce(idle).mockResolvedValue({
    ...idle, is_running: true,
    last_run: { id: "r1", status: "running", trigger: "manual", watches_total: 12, watches_done: 3, watches_error: 0,
      changes_found: 0, started_at: null, finished_at: null },
  })
  api.checkAll.mockResolvedValue({ status: "accepted", watches: 12, requested_at: "x", enabled: true })
  setup()
  await screen.findByText("/master")
  fireEvent.click(screen.getByRole("button", { name: /Comprobar todas/ }))
  await waitFor(() => expect(api.checkAll).toHaveBeenCalledWith(7))
  expect(await screen.findByText(/Comprobando/)).toHaveTextContent("Comprobando 3 de 12…")
})

it("with the sweep off, queued checks say they are waiting", async () => {
  api.list.mockResolvedValue({ enabled: false, monitored: true, watches: [watch] })
  api.progress.mockResolvedValue({ ...idle, enabled: false, queued: ["w1"] })
  setup()
  expect(await screen.findByText(/1 URL pedida espera a que se encienda el barrido/)).toBeInTheDocument()
  expect(screen.getByText(/El barrido de cambios está apagado/)).toBeInTheDocument()
})

it("archives and mutes from the row", async () => {
  api.list.mockResolvedValue({ enabled: true, monitored: true, watches: [watch] })
  api.progress.mockResolvedValue(idle)
  api.archive.mockResolvedValue({ ...watch, archived_at: "2026-10-21T08:00:00+00:00" })
  api.update.mockResolvedValue({ ...watch, muted: true })
  setup()
  fireEvent.click(await screen.findByRole("button", { name: "Archivar https://fit.es/master" }))
  await waitFor(() => expect(api.archive).toHaveBeenCalledWith("w1"))
  fireEvent.click(screen.getByRole("button", { name: "Silenciar https://fit.es/master" }))
  await waitFor(() => expect(api.update).toHaveBeenCalledWith("w1", { muted: true }))
})

it("adds a pasted list and reports the honest count", async () => {
  api.list.mockResolvedValue({ enabled: true, monitored: true, watches: [] })
  api.progress.mockResolvedValue(idle)
  api.bulk.mockResolvedValue({ created: 2, restored: 0, skipped_duplicates: 1, invalid: [], truncated: false })
  setup()
  fireEvent.click(await screen.findByRole("button", { name: /Añadir URLs/ }))
  fireEvent.click(within(screen.getByRole("group", { name: "Cómo añadir" })).getByRole("button", { name: "Lista o CSV" }))
  fireEvent.change(screen.getByLabelText("URLs, una por línea"), { target: { value: "https://fit.es/a\nhttps://fit.es/b\nnota" } })
  fireEvent.click(screen.getByRole("button", { name: "Añadir" }))
  await waitFor(() => expect(api.bulk).toHaveBeenCalledWith(7, { urls: ["https://fit.es/a", "https://fit.es/b"], source: "bulk" }))
  expect(await screen.findByText(/añadidas/)).toHaveTextContent("2 añadidas · 1 ya estaban")
})

it("readers see the list but no management controls", async () => {
  perms.write = false
  api.list.mockResolvedValue({ enabled: true, monitored: true, watches: [watch] })
  api.progress.mockResolvedValue(idle)
  setup()
  await screen.findByText("/master")
  expect(screen.queryByRole("button", { name: /Comprobar todas/ })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: /Añadir URLs/ })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: /Archivar/ })).not.toBeInTheDocument()
})

it("reads the first cell of a CSV", () => {
  expect(urlsFromText('url;nombre\n"https://fit.es/a";A\nhttps://fit.es/b,B\n')).toEqual(["https://fit.es/a", "https://fit.es/b"])
})
