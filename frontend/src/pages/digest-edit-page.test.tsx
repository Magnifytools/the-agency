import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom"
import { beforeEach, expect, it, vi } from "vitest"
import DigestEditPage from "./digest-edit-page"

const api = vi.hoisted(() => ({ get: vi.fn(), update: vi.fn(), render: vi.fn() }))
vi.mock("@/lib/api", () => ({ digestsApi: api }))
const source = {
  id: 10, client_id: 1, client_name: "Acme", status: "draft", tone: "cercano",
  period_start: "2026-09-07", period_end: "2026-09-13", raw_context: null,
  content: { greeting: "Hola Acme", date: "Período del 7 al 13 de septiembre de 2026", closing: "Gracias",
    sections: { done: [], need: [], next: [], metrics: [{ title: "Horas", description: "2 horas registradas" }] } },
}
function Location() { return <output data-testid="location">{useLocation().pathname}</output> }
function setup() {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 }, mutations: { retry: false } } })}>
    <MemoryRouter initialEntries={["/digests/10/edit"]}><Routes><Route path="/digests/:id/edit" element={<><DigestEditPage /><Location /></>} /></Routes></MemoryRouter>
  </QueryClientProvider>)
}
beforeEach(() => {
  vi.resetAllMocks()
  api.get.mockResolvedValue(source)
  api.update.mockImplementation(async (_id, request) => ({ ...source, id: 11, ...request }))
  api.render.mockResolvedValue({ rendered: "Versión nueva", format: "slack" })
})
it("saves metrics and navigates to the returned version without changing the reporting period", async () => {
  setup()
  const greeting = await screen.findByLabelText("Saludo")
  await waitFor(() => expect(greeting).toHaveValue("Hola Acme"))
  fireEvent.change(greeting, { target: { value: "Hola, equipo" } })
  expect(screen.getByLabelText("Período del informe")).toHaveAttribute("readonly")
  fireEvent.click(screen.getByRole("button", { name: "Guardar" }))
  await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/digests/11/edit"))
  expect(api.update).toHaveBeenCalledWith(10, expect.objectContaining({ content: expect.objectContaining({ greeting: "Hola, equipo", sections: expect.objectContaining({ metrics: source.content.sections.metrics }) }) }))
})
it("renders the saved ID, including when switching the preview format", async () => {
  setup()
  await screen.findByLabelText("Saludo")
  fireEvent.click(screen.getByRole("button", { name: "Preview" }))
  await screen.findByText("Versión nueva")
  expect(api.render).toHaveBeenCalledWith(11, "slack")
  fireEvent.click(screen.getByRole("button", { name: "Email" }))
  await waitFor(() => expect(api.render).toHaveBeenCalledWith(11, "email"))
})
it("cancelling a tone change neither saves nor regenerates", async () => {
  setup()
  await screen.findByLabelText("Tono")
  fireEvent.change(screen.getByLabelText("Tono"), { target: { value: "formal" } })
  fireEvent.click(screen.getByRole("button", { name: "Cancelar" }))
  expect(api.update).not.toHaveBeenCalled()
  expect(screen.getByLabelText("Tono")).toHaveValue("cercano")
})
it("preserves manual edits before regenerating and keeps the saved version when generation fails", async () => {
  setup()
  const greeting = await screen.findByLabelText("Saludo")
  await waitFor(() => expect(greeting).toHaveValue("Hola Acme"))
  fireEvent.change(greeting, { target: { value: "Trabajo revisado" } })
  api.update.mockImplementationOnce(async (_id, request) => ({ ...source, id: 11, ...request })).mockRejectedValueOnce(new Error("Proveedor no disponible"))
  fireEvent.change(screen.getByLabelText("Tono"), { target: { value: "formal" } })
  fireEvent.click(screen.getByRole("button", { name: "Guardar y generar" }))
  await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/digests/11/edit"))
  expect(api.update).toHaveBeenNthCalledWith(1, 10, expect.objectContaining({ content: expect.objectContaining({ greeting: "Trabajo revisado" }) }))
  expect(api.update).toHaveBeenNthCalledWith(2, 11, { tone: "formal" })
  expect(screen.getByLabelText("Saludo")).toHaveValue("Trabajo revisado")
  expect(screen.getByLabelText("Tono")).toHaveValue("cercano")
})
it("retains unsaved edits after save failure and prevents overlapping operations", async () => {
  let reject!: (error: Error) => void
  api.update.mockReturnValue(new Promise((_resolve, fail) => { reject = fail }))
  setup()
  const greeting = await screen.findByLabelText("Saludo")
  await waitFor(() => expect(greeting).toHaveValue("Hola Acme"))
  fireEvent.change(greeting, { target: { value: "Borrador sin perder" } })
  fireEvent.click(screen.getByRole("button", { name: "Guardar" }))
  await waitFor(() => expect(screen.getByRole("button", { name: "Preview" })).toBeDisabled())
  expect(greeting).toBeDisabled()
  reject(new Error("Sin conexión"))
  await waitFor(() => expect(greeting).not.toBeDisabled())
  expect(greeting).toHaveValue("Borrador sin perder")
  expect(screen.getByTestId("location")).toHaveTextContent("/digests/10/edit")
})
