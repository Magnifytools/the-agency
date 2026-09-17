import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { DeliveryReceipts, ManualDeliveryReceipts, deliveryToast } from "./delivery-receipts"
import type { DeliveryReceipt } from "@/lib/types"
import DailysPage from "@/pages/dailys-page"
import DigestsPage from "@/pages/digests-page"
import { MemoryRouter } from "react-router-dom"

const mock = vi.hoisted(() => ({ list: vi.fn(), listManual: vi.fn(), retry: vi.fn(), resend: vi.fn(), cancel: vi.fn(), success: vi.fn(), info: vi.fn(), warning: vi.fn(), error: vi.fn() }))
const daily = vi.hoisted(() => ({ list: vi.fn(), sendDiscord: vi.fn() }))
const digest = vi.hoisted(() => ({ list: vi.fn(), render: vi.fn(), sendDigest: vi.fn(), sendCustom: vi.fn(), listAll: vi.fn() }))
vi.mock("@/lib/api", () => ({ deliveriesApi: mock, dailysApi: daily, digestsApi: digest, discordApi: digest, clientsApi: digest }))
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: { id: 7 } }) }))
vi.mock("sonner", () => ({ toast: mock }))

function receipt(partial: Partial<DeliveryReceipt> = {}): DeliveryReceipt {
  return { delivery_id: "receipt-1", status: "pending", success: false, message: "El borrador está guardado", source_kind: "daily", source_id: 1, source_version: "hash", source_changed: false, content: "Texto original completo", created_at: "2026-09-17T12:00:00Z", sent_at: null, error_code: null, steps: [{ kind: "body", label: "Texto 1", status: "pending" }], can_retry: false, can_resend: false, can_cancel: true, worker_enabled: false, ...partial }
}

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(<QueryClientProvider client={client}><DeliveryReceipts sourceKind="daily" sourceId={1} /></QueryClientProvider>)
}

beforeEach(() => vi.resetAllMocks())

describe("Delivery receipts", () => {
  it("shows the receipt for a daily without AI data after queuing", async () => {
    daily.list.mockResolvedValue([{ id: 1, user_id: 7, user_name: "Test", date: "2026-09-17", raw_text: "Texto sin parsear", parsed_data: null, status: "draft" }])
    daily.sendDiscord.mockResolvedValue(receipt())
    mock.list.mockResolvedValue([receipt()])
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><DailysPage /></QueryClientProvider>)
    fireEvent.click(await screen.findByTitle("Enviar a Discord"))
    expect(await screen.findByRole("region", { name: "Recibos de Discord" })).toBeInTheDocument()
    expect(mock.info).toHaveBeenCalled()
    expect(mock.success).not.toHaveBeenCalled()
  })

  it("binds the editable digest preview to the digest delivery endpoint", async () => {
    digest.listAll.mockResolvedValue([])
    digest.list.mockResolvedValue([{ id: 8, client_id: 1, client_name: "Test client", period_start: "2026-09-14", period_end: "2026-09-20", status: "draft", tone: "cercano", created_by: 7 }])
    digest.render.mockResolvedValue({ rendered: "Texto revisado del digest" })
    digest.sendDigest.mockResolvedValue(receipt({ source_kind: "digest", source_id: 8 }))
    mock.list.mockResolvedValue([])
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><MemoryRouter><DigestsPage /></MemoryRouter></QueryClientProvider>)
    fireEvent.click(await screen.findByTitle("Discord (interno)"))
    await screen.findByText("Texto revisado del digest")
    fireEvent.click(screen.getByRole("button", { name: "Enviar a Discord" }))
    await waitFor(() => expect(digest.sendDigest).toHaveBeenCalledWith(8, "Texto revisado del digest"))
    expect(digest.sendCustom).not.toHaveBeenCalled()
  })

  it("shows a paused queue honestly and never announces success for pending", async () => {
    const queued = receipt()
    mock.list.mockResolvedValue([queued])
    show()
    expect(await screen.findByText(/El procesamiento está pausado/)).toBeInTheDocument()
    expect(screen.getByRole("status")).toHaveTextContent("En cola")
    expect(screen.queryByText("Confirmado")).not.toBeInTheDocument()
    deliveryToast(queued)
    expect(mock.info).toHaveBeenCalledWith(queued.message)
    expect(mock.success).not.toHaveBeenCalled()
  })

  it("loads actor-scoped manual history and shows its destination and period", async () => {
    mock.listManual.mockResolvedValue([receipt({
      source_kind: "communication",
      source_id: 42,
      title: "Briefing del día",
      scope: "team",
      destination_label: "#operaciones",
      period_start: "2026-09-17",
    })])
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><ManualDeliveryReceipts kind="pm_briefing" scope="team" /></QueryClientProvider>)

    expect(await screen.findByText(/Briefing del día · #operaciones · 2026-09-17/)).toBeInTheDocument()
    expect(mock.listManual).toHaveBeenCalledWith("pm_briefing", "team")
    expect(mock.list).not.toHaveBeenCalled()
  })

  it("keeps the previous version and each real provider receipt visible", async () => {
    mock.list.mockResolvedValue([receipt({ status: "sent", success: true, source_changed: true, can_cancel: false, steps: [{ kind: "header", label: "Cabecera", status: "sent", message_id: "12345" }, { kind: "body", label: "Texto 1", status: "sent", message_id: "67890" }] })])
    show()
    expect(await screen.findByText(/Tu borrador actual se conserva/)).toBeInTheDocument()
    expect(screen.getByText(/Cabecera: Confirmado · ID Discord 12345/)).toBeInTheDocument()
    expect(screen.getByText(/Texto 1: Confirmado · ID Discord 67890/)).toBeInTheDocument()
    fireEvent.click(screen.getByText("Ver el texto de esta versión"))
    expect(screen.getByText("Texto original completo")).toBeInTheDocument()
  })

  it("offers retry only for confirmed failure and shows the successful prefix", async () => {
    mock.list.mockResolvedValue([receipt({ status: "failed", can_retry: true, can_cancel: false, steps: [{ kind: "header", label: "Cabecera", status: "sent", message_id: "123" }, { kind: "thread", label: "Hilo", status: "failed", error: "Discord rechazó esta parte" }] })])
    mock.retry.mockResolvedValue(receipt())
    show()
    fireEvent.click(await screen.findByRole("button", { name: "Reintentar partes pendientes" }))
    await waitFor(() => expect(mock.retry).toHaveBeenCalledWith("receipt-1"))
    expect(screen.getByText(/Cabecera: Confirmado/)).toBeInTheDocument()
    expect(mock.resend).not.toHaveBeenCalled()
  })

  it("requires reviewing exact text and acknowledging uncertainty before a new intention", async () => {
    mock.list.mockResolvedValue([receipt({ status: "uncertain", can_resend: true, can_cancel: false })])
    mock.resend.mockResolvedValue(receipt({ delivery_id: "new-receipt" }))
    show()
    fireEvent.click(await screen.findByRole("button", { name: "Revisar posible reenvío" }))
    const button = screen.getByRole("button", { name: "Crear nuevo envío de este texto" })
    expect(button).toBeDisabled()
    expect(screen.getByRole("group", { name: "Revisar reenvío incierto" })).toHaveTextContent("Texto original completo")
    expect(screen.queryByRole("button", { name: "Reintentar partes pendientes" })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole("checkbox"))
    fireEvent.click(button)
    await waitFor(() => expect(mock.resend).toHaveBeenCalledWith("receipt-1", expect.any(String)))
    expect(mock.retry).not.toHaveBeenCalled()
  })

  it("distinguishes a failed receipt query from no history", async () => {
    mock.list.mockRejectedValue(new Error("offline"))
    show()
    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudieron cargar los recibos")
    expect(screen.queryByText(/Sin recibos de envío registrados/)).not.toBeInTheDocument()
    mock.list.mockResolvedValue([])
    fireEvent.click(screen.getByRole("button", { name: "Reintentar consulta" }))
    expect(await screen.findByText(/Sin recibos de envío registrados/)).toBeInTheDocument()
  })
})
