import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, expect, it, vi } from "vitest"
import { DailyUpdateWidget } from "./daily-update-widget"

const api = vi.hoisted(() => ({ list: vi.fn() }))
vi.mock("@/lib/api", () => ({ dailysApi: api }))
vi.mock("@/hooks/use-business-date", () => ({ useBusinessDate: () => "2026-09-20" }))
vi.mock("@/components/delivery-receipts", () => ({ DeliveryReceipts: () => <div>Recibos conservados</div> }))

beforeEach(() => vi.resetAllMocks())

function show(readOnly = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<MemoryRouter><QueryClientProvider client={client}><DailyUpdateWidget userId={7} readOnly={readOnly} /></QueryClientProvider></MemoryRouter>)
}

it("keeps a failed read distinct from an empty day and recovers the existing receipt", async () => {
  api.list.mockRejectedValueOnce(new Error("network"))
    .mockResolvedValue([{ id: 8, status: "draft", raw_text: "Texto guardado" }])
  show()
  expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo consultar")
  expect(screen.queryByText("Sin resumen guardado hoy.")).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", { name: "Reintentar" }))
  expect(await screen.findByText("Recibos conservados")).toBeInTheDocument()
  expect(screen.getByRole("link", { name: "Abrir mi resumen diario" })).toHaveAttribute("href", "/dailys")
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument()
})

it("keeps another person's summary read-only without the personal closing link", async () => {
  api.list.mockResolvedValue([{ id: 8, status: "sent", raw_text: "Resumen del equipo" }])
  show(true)
  await screen.findByText("Resumen de hoy enviado")
  fireEvent.click(screen.getByRole("button", { name: "Ver texto" }))
  expect(screen.getByText("Resumen del equipo")).toBeInTheDocument()
  expect(screen.queryByRole("link")).not.toBeInTheDocument()
  expect(screen.queryByText("Recibos conservados")).not.toBeInTheDocument()
  expect(api.list).toHaveBeenCalledWith({ user_id: 7, date_from: "2026-09-20", date_to: "2026-09-20", limit: 1 })
})
