import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { NextMeeting } from "./next-meeting"
import { calendarKeys, invalidateCalendarViews } from "@/lib/calendar-queries"
import type { NextMeetingResponse } from "@/lib/api"

const mocks = vi.hoisted(() => ({ nextMeeting: vi.fn(), user: { id: 1 } as {id:number} | null }))
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: mocks.user }) }))
vi.mock("@/lib/api", () => ({ calendarApi: { nextMeeting: mocks.nextMeeting } }))
const saved: NextMeetingResponse = {
  meeting: { id: 2, title: "Revisión de propuesta", date: "2026-10-25", time: "02:45", source: "google" },
  timezone: "Europe/Madrid", connection_status: "connected", last_synced_at: "2026-10-25T00:00:00Z",
}
function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const tree = () => <QueryClientProvider client={client}><MemoryRouter><NextMeeting today="2026-10-25" /></MemoryRouter></QueryClientProvider>
  const view = render(tree())
  return { client, rerender: () => view.rerender(tree()) }
}

beforeEach(() => { vi.clearAllMocks(); mocks.user = { id: 1 }; mocks.nextMeeting.mockResolvedValue(saved) })
describe("NextMeeting", () => {
  it("shows saved civil time without inventing a UTC offset during DST", async () => {
    show()
    expect(await screen.findByText("Revisión de propuesta")).toBeInTheDocument()
    expect(screen.getByText("Hoy a las 02:45")).toHaveAttribute("datetime", "2026-10-25T02:45")
    expect(screen.getByText(/Hora de Madrid/)).toHaveTextContent("Google Calendar")
    expect(screen.getByText(/Última sincronización con Google/)).toBeInTheDocument()
  })
  it("distinguishes pending and failed requests from a verified empty calendar", async () => {
    mocks.nextMeeting.mockReturnValueOnce(new Promise(() => {}))
    const { client } = show()
    expect(screen.getByRole("status")).toHaveTextContent("Consultando reuniones")
    expect(screen.queryByText("No hay próximas reuniones guardadas.")).not.toBeInTheDocument()
    mocks.nextMeeting.mockRejectedValueOnce(new Error("offline"))
    await act(async () => { await client.cancelQueries(); await client.refetchQueries({ queryKey: calendarKeys.nextMeetings() }) })
    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudieron consultar las reuniones")
    mocks.nextMeeting.mockResolvedValueOnce({ ...saved, meeting: null })
    await userEvent.click(screen.getByRole("button", { name: "Reintentar reuniones" }))
    expect(await screen.findByText("No hay próximas reuniones guardadas.")).toBeInTheDocument()
  })
  it("keeps cached information visibly stale after a refresh failure", async () => {
    const { client } = show()
    await screen.findByText("Revisión de propuesta")
    mocks.nextMeeting.mockRejectedValueOnce(new Error("offline"))
    await act(async () => { await client.invalidateQueries({ queryKey: calendarKeys.nextMeetings() }) })
    expect(await screen.findByRole("alert")).toHaveTextContent("No se ha podido actualizar la reunión guardada")
    expect(screen.getByText("Revisión de propuesta")).toBeInTheDocument()
  })
  it("warns about retained Google data and links directly to reconnection", async () => {
    mocks.nextMeeting.mockResolvedValue({ ...saved, connection_status: "reconnect_required" })
    show()
    expect(await screen.findByText(/sus reuniones guardadas pueden haber cambiado/)).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Reconectar calendario" })).toHaveAttribute("href", "/settings#calendar")
  })
  it("does not reuse another person's meeting while their replacement is loading", async () => {
    const { rerender } = show()
    await screen.findByText("Revisión de propuesta")
    mocks.user = { id: 7 }
    mocks.nextMeeting.mockReturnValueOnce(new Promise(() => {}))
    rerender()
    expect(screen.queryByText("Revisión de propuesta")).not.toBeInTheDocument()
    expect(screen.getByRole("status")).toHaveTextContent("Consultando reuniones")
    await waitFor(() => expect(mocks.nextMeeting).toHaveBeenCalledTimes(2))
  })
  it("refreshes the upcoming meeting after calendar changes", async () => {
    const { client } = show()
    await screen.findByText("Revisión de propuesta")
    mocks.nextMeeting.mockResolvedValueOnce({ ...saved, meeting: null })
    await act(async () => { await invalidateCalendarViews(client) })
    expect(await screen.findByText("No hay próximas reuniones guardadas.")).toBeInTheDocument()
  })
})
