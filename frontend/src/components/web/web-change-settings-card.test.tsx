import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { beforeEach, expect, it, vi } from "vitest"
import { WebChangeSettingsCard } from "./web-change-settings-card"

const api = vi.hoisted(() => ({ settings: vi.fn(), saveCalendar: vi.fn(), saveCapture: vi.fn(), holidays: vi.fn() }))
vi.mock("@/lib/api", () => ({ webWatchesApi: api }))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const settings = {
  enabled: true, sweep_local_time: "06:30", slack: "revoked", updated_at: null,
  stored: { default_content_selector: null, default_ignore_selectors: null, default_ignore_regexes: null, max_concurrency: null,
    request_timeout_s: null, crawl_delay_ms: null, digest_min_severity: null, sweep_weekdays: null, sweep_skip_dates: null,
    sweep_summary_to_slack: null },
  effective: { default_content_selector: null, default_ignore_selectors: [".cookie"], default_ignore_regexes: [], max_concurrency: 4,
    request_timeout_s: 20, crawl_delay_ms: 250, digest_min_severity: "info", sweep_weekdays: [1, 2, 3, 4, 5], sweep_skip_dates: [],
    sweep_summary_to_slack: true },
  code_defaults: { default_ignore_selectors: [".cookie"], default_ignore_regexes: [], max_concurrency: 4, request_timeout_s: 20,
    crawl_delay_ms: 250, digest_min_severity: "info", sweep_weekdays: [1, 2, 3, 4, 5], sweep_summary_to_slack: true },
}

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><WebChangeSettingsCard clientId={7} /></QueryClientProvider>)
}

beforeEach(() => {
  vi.resetAllMocks()
  api.settings.mockResolvedValue(settings)
})

it("saves weekdays and skip dates", async () => {
  api.saveCalendar.mockResolvedValue(settings)
  api.holidays.mockResolvedValue({ year: 2026, holidays: ["2026-12-25"] })
  setup()
  fireEvent.click(await screen.findByRole("button", { name: "viernes" }))
  fireEvent.click(screen.getByRole("button", { name: "sábado" }))
  fireEvent.click(screen.getByRole("button", { name: /Festivos nacionales/ }))
  await within(screen.getByRole("list", { name: "Días sin barrido" })).findByText(/25 dic/)
  fireEvent.click(screen.getByRole("button", { name: "Guardar calendario" }))
  await waitFor(() => expect(api.saveCalendar).toHaveBeenCalledWith(7, {
    sweep_weekdays: [1, 2, 3, 4, 6], sweep_skip_dates: ["2026-12-25"], sweep_summary_to_slack: true,
  }))
})

it("capture: empty fields go back to the code default and the Slack digest threshold is a control", async () => {
  api.saveCapture.mockResolvedValue(settings)
  setup()
  // Revocado ≠ sin configurar: se dice qué hacer.
  expect(await screen.findByText(/Slack revocó el webhook/)).toBeInTheDocument()
  const digest = screen.getByRole("group", { name: "Severidad mínima del aviso a Slack" })
  expect(within(digest).getByRole("button", { name: /Todo \(por defecto\)/ })).toHaveAttribute("aria-pressed", "true")
  fireEvent.click(within(digest).getByRole("button", { name: "Sólo críticos" }))
  fireEvent.click(screen.getByRole("button", { name: "Guardar captura" }))
  await waitFor(() => expect(api.saveCapture).toHaveBeenCalledWith(7, {
    default_content_selector: null, default_ignore_selectors: null, default_ignore_regexes: null,
    max_concurrency: null, request_timeout_s: null, crawl_delay_ms: null, digest_min_severity: "critical",
  }))
})
