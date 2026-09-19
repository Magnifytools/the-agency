import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, expect, it, vi } from "vitest"
import DigestsPage from "./digests-page"
const mocks = vi.hoisted(() => ({ api: {list: vi.fn(), render: vi.fn(), generate: vi.fn(), updateStatus: vi.fn(), delete: vi.fn()}, clients: vi.fn(), send: vi.fn(), auth: { id: 1, write: true } }))
vi.mock("@/lib/api", () => ({digestsApi: mocks.api, clientsApi: {listAll: mocks.clients}, discordApi: {sendDigest: mocks.send}}))
vi.mock("@/context/auth-context", () => ({useAuth: () => ({user: {id: mocks.auth.id}, isAdmin: true, hasPermission: (_module: string, write?: boolean) => !write || mocks.auth.write})}))
vi.mock("@/components/digests/digest-cohort", () => ({DigestCohort: () => <div>Selección de clientes</div>}))
vi.mock("@/components/delivery-receipts", () => ({DeliveryReceipts: ({sourceId}: {sourceId: number}) => <p>Recibos #{sourceId}</p>, deliveryToast: vi.fn()}))
const source = {id: 10, client_id: 1, client_name: "Acme", status: "draft", tone: "cercano", period_start: "2026-09-07", period_end: "2026-09-13", generated_at: null, created_by: 1}
function setup() {
  const client = new QueryClient({defaultOptions: {queries: {retry: false}, mutations: {retry: false}}})
  const node = () => <QueryClientProvider client={client}><MemoryRouter><DigestsPage /></MemoryRouter></QueryClientProvider>
  return {...render(node()), node}
}
beforeEach(() => {vi.resetAllMocks(); mocks.auth = {id: 1, write: true}; mocks.api.list.mockResolvedValue([source, {...source, id: 20, client_id: 2, client_name: "Other"}]); mocks.clients.mockResolvedValue([{id: 1, name: "Acme"}]); mocks.api.render.mockResolvedValue({rendered: "Rendered"}); mocks.api.generate.mockResolvedValue({...source, id: 30}); mocks.send.mockResolvedValue({status: "pending"})})
it("keeps individual generation and removes the unreviewed generate-all action", async () => {
  setup()
  await screen.findByRole("cell", {name: "Acme"})
  expect(screen.queryByRole("button", {name: "Generar todos"})).not.toBeInTheDocument()
  expect(screen.queryByTitle("Marcar como enviado (histórico)")).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", {name: "Preparar uno"}))
  fireEvent.change(screen.getByLabelText("Cliente"), {target: {value: "1"}})
  fireEvent.click(screen.getByRole("button", {name: "Generar"}))
  await waitFor(() => expect(mocks.api.generate).toHaveBeenCalledWith({client_id: 1, tone: "cercano", period_start: undefined, period_end: undefined}))
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
it("read-only history allows copying but disables writes and internal sharing", async () => {
  mocks.auth.write = false
  setup(); await screen.findByRole("cell", {name: "Acme"})
  expect(screen.queryByRole("button", {name: "Preparar uno"})).not.toBeInTheDocument()
  expect(screen.getAllByTitle("Consultar versión")[0]).not.toBeDisabled()
  expect(screen.getAllByTitle("Discord (interno)")[0]).toBeDisabled()
  expect(screen.getByLabelText("Estado histórico de versión #10")).toBeDisabled()
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
  fireEvent.click(await screen.findByRole("button", {name: "Cargar versiones anteriores"}))
  await screen.findByRole("cell", {name: "Version 21"})
  expect(screen.getAllByRole("cell", {name: "Version 20"})).toHaveLength(1)
  expect(screen.getByText("Mostrando 21 versiones.")).toBeInTheDocument()
  expect(mocks.api.list).toHaveBeenCalledWith(expect.objectContaining({limit: 20, offset: 20}))
  fireEvent.change(screen.getByLabelText("Filtrar por estado"), {target: {value: "reviewed"}})
  await screen.findByRole("cell", {name: "Filtered version"})
  expect(mocks.api.list).toHaveBeenLastCalledWith(expect.objectContaining({status: "reviewed", offset: 0}))
  expect(screen.queryByRole("cell", {name: "Version 21"})).not.toBeInTheDocument()
  expect(screen.getByText("Mostrando 1 versión.")).toBeInTheDocument()
})
it("a failed next page keeps loaded history and offers retry", async () => {
  const first = Array.from({length: 20}, (_,index) => ({...source, id: index+1, client_name: `Version ${index+1}`}))
  mocks.api.list.mockResolvedValueOnce(first).mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce([{...source, id: 21, client_name: "Older version"}])
  setup()
  fireEvent.click(await screen.findByRole("button", {name: "Cargar versiones anteriores"}))
  const retry = await screen.findByRole("button", {name: "Reintentar versiones anteriores"})
  expect(screen.getByRole("cell", {name: "Version 1"})).toBeInTheDocument()
  fireEvent.click(retry)
  await screen.findByRole("cell", {name: "Older version"})
})
