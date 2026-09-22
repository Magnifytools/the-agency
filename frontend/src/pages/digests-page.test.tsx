import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { Link, MemoryRouter } from "react-router-dom"
import { beforeEach, expect, it, vi } from "vitest"
import DigestsPage from "./digests-page"
const mocks = vi.hoisted(() => ({ api: {list: vi.fn(), render: vi.fn(), generate: vi.fn(), recoverGeneration: vi.fn(), updateStatus: vi.fn(), delete: vi.fn()}, clients: vi.fn(), send: vi.fn(), auth: { id: 1, write: true } }))
vi.mock("@/lib/api", () => ({digestsApi: mocks.api, clientsApi: {listAll: mocks.clients}, discordApi: {sendDigest: mocks.send}}))
vi.mock("@/context/auth-context", () => ({useAuth: () => ({user: {id: mocks.auth.id}, isAdmin: true, hasPermission: (_module: string, write?: boolean) => !write || mocks.auth.write})}))
vi.mock("@/components/digests/digest-cohort", () => ({DigestCohort: ({clientId, expectedPeriod}: {clientId?: number; expectedPeriod?: {start: string; end: string}}) => expectedPeriod ? <div>Período esperado {expectedPeriod.start} — {expectedPeriod.end} <Link to={`/digests?client_id=${clientId}`}>Ver períodos actuales</Link></div> : <div>Selección de clientes</div>}))
vi.mock("@/components/delivery-receipts", () => ({DeliveryReceipts: ({sourceId}: {sourceId: number}) => <p>Recibos #{sourceId}</p>, deliveryToast: vi.fn()}))
const source = {id: 10, client_id: 1, client_name: "Acme", status: "draft", can_delete: true, tone: "cercano", period_start: "2026-09-07", period_end: "2026-09-13", generated_at: null, created_by: 1}
function setup(route = "/digests") {
  const client = new QueryClient({defaultOptions: {queries: {retry: false}, mutations: {retry: false}}})
  const node = () => <QueryClientProvider client={client}><MemoryRouter initialEntries={[route]}><DigestsPage /></MemoryRouter></QueryClientProvider>
  return {...render(node()), node}
}
beforeEach(() => {vi.resetAllMocks(); localStorage.clear(); mocks.auth = {id: 1, write: true}; mocks.api.list.mockResolvedValue([source, {...source, id: 20, client_id: 2, client_name: "Other"}]); mocks.clients.mockResolvedValue([{id: 1, name: "Acme", status: "active", is_internal: false}]); mocks.api.render.mockResolvedValue({rendered: "Rendered"}); mocks.api.generate.mockResolvedValue({...source, id: 30}); mocks.send.mockResolvedValue({status: "pending"})})
it("offers deletion only when the server confirms the version can be deleted", async () => {
  mocks.api.list.mockResolvedValueOnce([{...source, status: "reviewed", can_delete: false}, {...source, id: 20, client_name: "Other", status: "sent", can_delete: true}, {...source, id: 30, client_name: "Free"}])
  setup()
  const acme = (await screen.findByRole("cell", {name: "Acme"})).closest("tr")!
  const other = screen.getByRole("cell", {name: "Other"}).closest("tr")!
  const free = screen.getByRole("cell", {name: "Free"}).closest("tr")!
  expect(within(acme).queryByTitle("Eliminar")).not.toBeInTheDocument()
  expect(within(other).queryByTitle("Eliminar")).not.toBeInTheDocument()
  expect(within(free).getByTitle("Eliminar")).toBeInTheDocument()
})
it("does not offer deletion to a reader even if a stale list says the version is deletable", async () => {
  mocks.auth.write = false
  setup()
  await screen.findByRole("cell", {name: "Acme"})
  expect(screen.queryByTitle("Eliminar")).not.toBeInTheDocument()
})
it("clears an exact incident period when returning to current periods on the same route", async () => {
  setup("/digests?client_id=1&period_start=2026-08-01&period_end=2026-08-31")
  await screen.findByText("Período esperado 2026-08-01 — 2026-08-31")
  fireEvent.click(screen.getByRole("link", {name: "Ver períodos actuales"}))
  await screen.findByText("Selección de clientes")
  expect(mocks.api.list).toHaveBeenLastCalledWith(expect.objectContaining({client_id: 1, period_from: undefined, period_to: undefined}))
})
it("keeps individual generation and removes the unreviewed generate-all action", async () => {
  setup()
  await screen.findByRole("cell", {name: "Acme"})
  expect(screen.queryByRole("button", {name: "Generar todos"})).not.toBeInTheDocument()
  expect(screen.queryByTitle("Marcar como enviado (histórico)")).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", {name: "Preparar uno"}))
  fireEvent.change(screen.getByLabelText("Cliente"), {target: {value: "1"}})
  fireEvent.click(screen.getByRole("button", {name: "Generar"}))
  await waitFor(() => expect(mocks.api.generate).toHaveBeenCalledWith({generation_key: expect.stringMatching(/^[A-Za-z0-9_-]{16,64}$/), client_id: 1, tone: "cercano", period_start: undefined, period_end: undefined}))
})
it("recovers an uncertain individual request after reload and retries the same key", async () => {
  const generationKey = "individual-recovery-key"
  localStorage.setItem(`agency:digest-generation:1:${generationKey}`, JSON.stringify({ kind: "individual", operation_key: generationKey, generation_key: generationKey, client_id: 1, tone: "formal" }))
  mocks.api.recoverGeneration.mockRejectedValueOnce({ response: { status: 404 } })
  setup()
  expect(await screen.findByText(/Todavía no hay una versión confirmada/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", { name: "Reintentar la misma solicitud" }))
  await waitFor(() => expect(mocks.api.generate).toHaveBeenCalledWith({ generation_key: generationKey, client_id: 1, tone: "formal", period_start: undefined, period_end: undefined }))
  expect(localStorage.getItem(`agency:digest-generation:1:${generationKey}`)).toBeNull()
})
it("cannot retry a persisted individual request after write permission is revoked", async () => {
  const generationKey = "individual-revoked-key"
  localStorage.setItem(`agency:digest-generation:1:${generationKey}`, JSON.stringify({ kind: "individual", operation_key: generationKey, generation_key: generationKey, client_id: 1, tone: "formal" }))
  mocks.auth.write = false
  mocks.api.recoverGeneration.mockRejectedValueOnce({ response: { status: 404 } })
  setup()
  expect(await screen.findByText(/Todavía no hay una versión confirmada/)).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "Reintentar la misma solicitud" })).not.toBeInTheDocument()
  expect(mocks.api.generate).not.toHaveBeenCalled()
})
it("late preview A cannot appear under B and only the current format wins", async () => {
  let old!: (value: unknown) => void
  mocks.api.render.mockImplementationOnce(() => new Promise(done => {old = done})).mockResolvedValueOnce({rendered: "B current"})
  setup()
  await screen.findByRole("cell", {name: "Acme"})
  fireEvent.click(screen.getAllByTitle("Vista previa")[0])
  fireEvent.keyDown(document, {key: "Escape"})
  fireEvent.click(screen.getAllByTitle("Vista previa")[1])
  await screen.findByText("B current")
  await act(async () => {old({rendered: "A stale"})})
  expect(screen.getByRole("dialog")).toHaveTextContent("Other · Versión #20")
  expect(screen.queryByText("A stale")).not.toBeInTheDocument()
})
it("same version reopen has a new epoch, so old success cannot replace the new render", async () => {
  let old!: (value: unknown) => void
  mocks.api.render.mockImplementationOnce(() => new Promise(done => {old = done})).mockResolvedValueOnce({rendered: "New render"})
  setup(); await screen.findByRole("cell", {name: "Acme"})
  fireEvent.click(screen.getAllByTitle("Vista previa")[0]); fireEvent.keyDown(document, {key: "Escape"}); fireEvent.click(screen.getAllByTitle("Vista previa")[0])
  await screen.findByText("New render")
  await act(async () => {old({rendered: "Old render"})})
  expect(screen.queryByText("Old render")).not.toBeInTheDocument()
})
it("Discord cannot share stale A content while B is loading or has failed", async () => {
  let old!: (value: unknown) => void
  let fail!: (value: unknown) => void
  mocks.api.render.mockImplementationOnce(() => new Promise(done => {old = done})).mockImplementationOnce(() => new Promise((_done, reject) => {fail = reject})).mockResolvedValueOnce({rendered: "B confirmed render"})
  setup(); await screen.findByRole("cell", {name: "Acme"})
  fireEvent.click(screen.getAllByTitle("Discord (interno)")[0]); await waitFor(() => expect(mocks.api.render).toHaveBeenCalledTimes(1)); fireEvent.keyDown(document, {key: "Escape"}); fireEvent.click(screen.getAllByTitle("Discord (interno)")[1]); await waitFor(() => expect(mocks.api.render).toHaveBeenCalledTimes(2))
  await act(async () => {old({rendered: "A stale"})})
  const share = screen.getByRole("button", {name: "Compartir en Discord interno"})
  expect(share).toBeDisabled(); expect(screen.queryByText("A stale")).not.toBeInTheDocument()
  await act(async () => {fail(new Error("Render failed"))})
  expect(share).toBeDisabled()
  fireEvent.click(screen.getByRole("button", {name: "Reintentar vista previa de Discord"}))
  await screen.findByText("B confirmed render")
  fireEvent.click(share)
  await waitFor(() => expect(mocks.send).toHaveBeenCalledWith(20, "B confirmed render"))
})
it("an old session cannot put its render in the new user's dialog", async () => {
  let old!: (value: unknown) => void
  mocks.api.render.mockImplementationOnce(() => new Promise(done => {old = done})).mockResolvedValueOnce({rendered: "New identity"})
  const view = setup(); await screen.findByRole("cell", {name: "Acme"})
  fireEvent.click(screen.getAllByTitle("Vista previa")[0])
  await waitFor(() => expect(mocks.api.render).toHaveBeenCalledTimes(1))
  mocks.auth.id = 2; view.rerender(view.node())
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
  fireEvent.click((await screen.findAllByTitle("Vista previa"))[1])
  await screen.findByText("New identity")
  await act(async () => {old({rendered: "Old identity"})})
  expect(screen.queryByText("Old identity")).not.toBeInTheDocument()
})
it("read-only history allows consultation and copying without dead write controls", async () => {
  mocks.auth.write = false
  setup(); await screen.findByRole("cell", {name: "Acme"})
  expect(screen.queryByRole("button", {name: "Preparar uno"})).not.toBeInTheDocument()
  expect(screen.getAllByTitle("Consultar versión")[0]).not.toBeDisabled()
  expect(screen.queryByTitle("Discord (interno)")).not.toBeInTheDocument()
  expect(screen.queryByLabelText("Estado histórico de versión #10")).not.toBeInTheDocument()
  expect(within(screen.getAllByRole("cell", {name: "Acme"})[0].closest("tr")!).getByText("Borrador")).toBeInTheDocument()
  expect(screen.getByText("Abre una versión para consultar su texto y sus fuentes.")).toBeInTheDocument()
  fireEvent.click(screen.getAllByTitle("Vista previa")[0])
  await screen.findByText("Rendered")
  expect(within(screen.getByRole("dialog")).getByRole("button", {name: "Copiar"})).not.toBeDisabled()
})
it("format switching ignores late failures from the previous rendering", async () => {
  let fail!: (value: unknown) => void
  mocks.api.render.mockImplementationOnce(() => new Promise((_done, reject) => {fail = reject})).mockResolvedValueOnce({rendered: "Email current"})
  setup(); await screen.findByRole("cell", {name: "Acme"})
  fireEvent.click(screen.getAllByTitle("Vista previa")[0])
  await waitFor(() => expect(mocks.api.render).toHaveBeenCalledTimes(1))
  fireEvent.click(screen.getByRole("button", {name: "Email"}))
  await screen.findByText("Email current")
  await act(async () => {fail(new Error("Old request failed"))})
  expect(screen.getByText("Email current")).toBeInTheDocument()
  expect(screen.queryByRole("button", {name: "Reintentar vista previa"})).not.toBeInTheDocument()
  expect(screen.getByRole("button", {name: "Copiar"})).not.toBeDisabled()
})
it("loads beyond 20 versions without duplicate rows and resets pagination when filters change", async () => {
  const first = Array.from({length: 20}, (_,index) => ({...source, id: index+1, client_name: `Version ${index+1}`}))
  mocks.api.list.mockImplementation(async params => params.status === "reviewed" ? [{...source, id: 99, client_name: "Filtered version", status: "reviewed"}] : params.offset === 0 ? first : [{...source, id: 20, client_name: "Version 20"}, {...source, id: 21, client_name: "Version 21"}])
  setup()
  fireEvent.click(await screen.findByText("Cargar versiones anteriores", {exact: true}))
  expect((await screen.findByText("Version 21", {exact: true})).closest("td")).not.toBeNull()
  expect(screen.getAllByText("Version 20", {exact: true})).toHaveLength(1)
  expect(screen.getByText("Mostrando 21 versiones.")).toBeInTheDocument()
  expect(mocks.api.list).toHaveBeenCalledWith(expect.objectContaining({limit: 20, offset: 20}))
  fireEvent.change(screen.getByLabelText("Filtrar por estado"), {target: {value: "reviewed"}})
  expect((await screen.findByText("Filtered version", {exact: true})).closest("td")).not.toBeNull()
  expect(mocks.api.list).toHaveBeenLastCalledWith(expect.objectContaining({status: "reviewed", offset: 0}))
  expect(screen.queryByText("Version 21", {exact: true})).not.toBeInTheDocument()
  expect(screen.getByText("Mostrando 1 versión.")).toBeInTheDocument()
})
it("a failed next page keeps loaded history and offers retry", async () => {
  const first = Array.from({length: 20}, (_,index) => ({...source, id: index+1, client_name: `Version ${index+1}`}))
  mocks.api.list.mockResolvedValueOnce(first).mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce([{...source, id: 21, client_name: "Older version"}])
  setup()
  fireEvent.click(await screen.findByText("Cargar versiones anteriores", {exact: true}))
  const retry = await screen.findByText("Reintentar versiones anteriores", {exact: true})
  expect(screen.getByText("Version 1", {exact: true})).toBeInTheDocument()
  fireEvent.click(retry)
  await screen.findByText("Older version", {exact: true})
})

it("keeps inactive clients in history without offering them for new reports", async () => {
  mocks.clients.mockResolvedValue([
    {id: 1, name: "Acme", status: "active", is_internal: false},
    {id: 2, name: "Finished client", status: "finished", is_internal: false},
    {id: 3, name: "Internal client", status: "active", is_internal: true},
  ])
  setup()
  await screen.findByRole("option", {name: "Finished client"})
  expect(mocks.clients).toHaveBeenCalledWith()
  expect(within(screen.getByLabelText("Filtrar por cliente")).getByRole("option", {name: "Finished client"})).toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", {name: "Preparar uno"}))
  const choices = within(screen.getByLabelText("Cliente"))
  expect(choices.getByRole("option", {name: "Acme"})).toBeInTheDocument()
  expect(choices.queryByRole("option", {name: "Finished client"})).not.toBeInTheDocument()
  expect(choices.queryByRole("option", {name: "Internal client"})).not.toBeInTheDocument()
})
