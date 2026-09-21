import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter, Route, Routes, useLocation, createMemoryRouter, RouterProvider } from "react-router-dom"
import { beforeEach, expect, it, vi } from "vitest"
import DigestEditPage from "./digest-edit-page"

const api = vi.hoisted(() => ({ get: vi.fn(), recoverGeneration: vi.fn(), update: vi.fn(), render: vi.fn() }))
const auth = vi.hoisted(() => ({ canWrite: true }))
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: { id: 1 }, hasPermission: () => auth.canWrite }) }))
vi.mock("@/lib/api", () => ({ digestsApi: api }))
vi.mock("@/components/digests/digest-external-delivery", () => ({ DigestExternalDelivery: ({ unsaved }: { unsaved: boolean }) => <output data-testid="delivery-unsaved">{String(unsaved)}</output> }))
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
  localStorage.clear()
  auth.canWrite = true
  api.get.mockResolvedValue(source)
  api.update.mockImplementation(async (_id, request) => ({ ...source, id: 11, ...request }))
  api.render.mockResolvedValue({ rendered: "Versión nueva", format: "slack" })
})
it("lets a reader consult a version and return without offering writable fields", async () => {
  auth.canWrite = false; setup()
  expect(await screen.findByLabelText("Saludo")).toBeDisabled()
  expect(screen.getByRole("button", { name: "Guardar" })).toBeDisabled()
  expect(screen.getByRole("button", { name: "Volver" })).not.toBeDisabled()
  expect(api.update).not.toHaveBeenCalled()
})
it("exposes a failed fetch as a retryable error instead of an empty digest", async () => {
  api.get.mockRejectedValueOnce(new Error("offline")); setup()
  expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo cargar")
  fireEvent.click(screen.getByRole("button", { name: "Reintentar" }))
  expect(await screen.findByLabelText("Saludo")).toBeInTheDocument()
})
it("saves metrics and navigates to the returned version without changing the reporting period", async () => {
  setup()
  const greeting = await screen.findByLabelText("Saludo")
  await waitFor(() => expect(greeting).toHaveValue("Hola Acme"))
  fireEvent.change(greeting, { target: { value: "Hola, equipo" } })
  expect(screen.getByTestId("delivery-unsaved")).toHaveTextContent("true")
  expect(screen.getByLabelText("Período del informe")).toHaveAttribute("readonly")
  fireEvent.click(screen.getByRole("button", { name: "Guardar" }))
  await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/digests/11/edit"))
  expect(api.update).toHaveBeenCalledWith(10, expect.objectContaining({ content: expect.objectContaining({ greeting: "Hola, equipo", sections: expect.objectContaining({ metrics: source.content.sections.metrics }) }) }))
})
it("shows assertion sources and removes their certification when the text is edited", async () => {
  api.get.mockResolvedValueOnce({
    ...source,
    raw_context: { context_version: 2, projects: [], source_catalog: { "task:8": { kind: "task", class: "task_completed", id: 8, label: "Revisar portada" } } },
    content: { ...source.content, sections: { ...source.content.sections, done: [{ title: "Portada revisada", description: "Lista", source_keys: ["task:8"] }] } },
  })
  setup()
  expect(await screen.findByRole("link", { name: "Revisar portada" })).toHaveAttribute("href", "/tasks?task=8")
  fireEvent.change(screen.getByLabelText("Hecho: título 1"), { target: { value: "Portada aprobada" } })
  expect(screen.getAllByText(/Sin referencias verificadas/).length).toBeGreaterThan(0)
  fireEvent.click(screen.getByRole("button", { name: "Guardar" }))
  await waitFor(() => expect(api.update).toHaveBeenCalledWith(10, expect.objectContaining({ content: expect.objectContaining({ sections: expect.objectContaining({ done: [expect.objectContaining({ source_keys: [] })] }) }) })))
})
it("explains that legacy versions have no assertion references", async () => {
  setup()
  expect(await screen.findByText(/se creó sin referencias por afirmación/)).toBeInTheDocument()
})
it("renders the saved ID, including when switching the preview format", async () => {
  setup()
  await screen.findByLabelText("Saludo")
  fireEvent.click(screen.getByRole("button", { name: "Vista previa" }))
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
  expect(api.update).toHaveBeenNthCalledWith(2, 11, { tone: "formal", generation_key: expect.stringMatching(/^[A-Za-z0-9_-]{16,64}$/) })
  expect(screen.getByLabelText("Saludo")).toHaveValue("Trabajo revisado")
  expect(screen.getByLabelText("Tono")).toHaveValue("cercano")
})
it("recovers a tone generation persisted before a response was lost", async () => {
  const key = "tone-recovery-stable-key"
  localStorage.setItem(`agency:digest-generation:1:${key}`, JSON.stringify({ kind: "tone", operation_key: key, generation_key: key, digest_id: 10, tone: "formal" }))
  api.recoverGeneration.mockResolvedValueOnce({ ...source, id: 12, tone: "formal" })
  setup()
  await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/digests/12/edit"))
  expect(api.recoverGeneration).toHaveBeenCalledWith(key)
  expect(localStorage.getItem(`agency:digest-generation:1:${key}`)).toBeNull()
})
it("retains unsaved edits after save failure and prevents overlapping operations", async () => {
  let reject!: (error: Error) => void
  api.update.mockReturnValue(new Promise((_resolve, fail) => { reject = fail }))
  setup()
  const greeting = await screen.findByLabelText("Saludo")
  await waitFor(() => expect(greeting).toHaveValue("Hola Acme"))
  fireEvent.change(greeting, { target: { value: "Borrador sin perder" } })
  fireEvent.click(screen.getByRole("button", { name: "Guardar" }))
  await waitFor(() => expect(screen.getByRole("button", { name: "Vista previa" })).toBeDisabled())
  expect(greeting).toBeDisabled()
  reject(new Error("Sin conexión"))
  await waitFor(() => expect(greeting).not.toBeDisabled())
  expect(greeting).toHaveValue("Borrador sin perder")
  expect(screen.getByTestId("location")).toHaveTextContent("/digests/10/edit")
})

function navigableSetup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 }, mutations: { retry: false } } })
  const router = createMemoryRouter([{ path: "/digests/:id/edit", element: <><DigestEditPage /><Location /></> }], { initialEntries: ["/digests/10/edit"] })
  render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>)
  return { router, client }
}
it("old save completion cannot navigate away from another digest", async () => {
  let resolve!: (value: unknown) => void
  api.update.mockReturnValue(new Promise(done => { resolve = done }))
  api.get.mockImplementation(async id => ({ ...source, id, client_name: id === 20 ? "Other" : "Acme", content: {...source.content, greeting: id === 20 ? "Other draft" : "Hola Acme"} }))
  const { router } = navigableSetup()
  await screen.findByLabelText("Saludo")
  fireEvent.click(screen.getByRole("button", {name: "Guardar"}))
  await act(async () => { await router.navigate("/digests/20/edit") })
  await waitFor(() => expect(screen.getByLabelText("Saludo")).toHaveValue("Other draft"))
  await act(async () => { resolve({...source, id: 11}) })
  expect(screen.getByTestId("location")).toHaveTextContent("/digests/20/edit")
  expect(screen.getByLabelText("Saludo")).toHaveValue("Other draft")
})
it("navigation to another digest clears previous preview", async () => {
  api.update.mockResolvedValue(source)
  api.get.mockImplementation(async id => ({...source, id, client_name: id === 20 ? "Other" : "Acme"}))
  const {router} = navigableSetup()
  await screen.findByLabelText("Saludo")
  fireEvent.click(screen.getByRole("button", {name: "Vista previa"}))
  await screen.findByText("Versión nueva")
  await act(async () => { await router.navigate("/digests/20/edit") })
  await screen.findByRole("heading", {name: "Other"})
  expect(screen.queryByText("Versión nueva")).not.toBeInTheDocument()
})
it("navigation to contentless digest does not reuse another client text", async () => {
  api.get.mockImplementation(async id => id === 20 ? {...source, id, client_name: "Other", content: null} : source)
  const {router} = navigableSetup()
  await waitFor(() => expect(screen.getByLabelText("Saludo")).toHaveValue("Hola Acme"))
  await act(async () => { await router.navigate("/digests/20/edit") })
  await screen.findByRole("heading", {name: "Other"})
  expect(screen.getByLabelText("Saludo")).toHaveValue("")
  fireEvent.click(screen.getByRole("button", {name: "Guardar"}))
  await waitFor(() => expect(api.update).toHaveBeenCalledWith(20, expect.objectContaining({content: expect.objectContaining({greeting: ""})})))
})

it.each(["new visit", "browser back"])("an old save cannot replace a %s to the same digest", async (mode) => {
  let resolve!: (value: unknown) => void
  api.update.mockReturnValue(new Promise(done => { resolve = done }))
  api.get.mockImplementation(async id => ({ ...source, id }))
  const {router} = navigableSetup()
  await screen.findByLabelText("Saludo")
  fireEvent.click(screen.getByRole("button", {name: "Guardar"}))
  await act(async () => { await router.navigate("/digests/20/edit") })
  await act(async () => { if (mode === "browser back") await router.navigate(-1); else await router.navigate("/digests/10/edit") })
  await act(async () => { resolve({...source, id: 11}) })
  expect(screen.getByTestId("location")).toHaveTextContent("/digests/10/edit")
})
