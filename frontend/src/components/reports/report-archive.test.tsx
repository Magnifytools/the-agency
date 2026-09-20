import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, expect, it, vi } from "vitest"
import { ReportArchive } from "./report-archive"

const mocks = vi.hoisted(() => ({ list: vi.fn(), del: vi.fn(), download: vi.fn(), id: 7, write: false }))
vi.mock("@/lib/api", () => ({ reportsApi: { list: mocks.list, delete: mocks.del, downloadPdf: mocks.download } }))
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: { id: mocks.id, role: "member" }, hasPermission: (_name: string, write = false) => !write || mocks.write }) }))
vi.mock("@/lib/hidden-modules", () => ({ isEnabled: () => true }))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
const report = (id: number) => ({ id, title: `Informe ${id}`, generated_at: "2026-09-01T22:30:00", summary: "Contenido guardado", sections: [{ title: "Original", content: "Horas históricas" }] })
function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const element = () => <QueryClientProvider client={client}><MemoryRouter><ReportArchive /></MemoryRouter></QueryClientProvider>
  return { client, element, ...render(element()) }
}
beforeEach(() => { vi.clearAllMocks(); mocks.id = 7; mocks.write = false; mocks.list.mockResolvedValue([report(1)]); mocks.download.mockResolvedValue(undefined); mocks.del.mockResolvedValue({}) })

it("shows the preserved archive with a canonical link and no duplicate generator", async () => {
  setup()
  fireEvent.click(await screen.findByRole("button", { name: /Informe 1/ }))
  expect(await screen.findByRole("dialog")).toHaveTextContent("Horas históricas")
  fireEvent.click(screen.getByRole("button", { name: "Descargar PDF" }))
  await waitFor(() => expect(mocks.download).toHaveBeenCalledWith(1))
  expect(screen.getByRole("link", { name: "Ir a Resúmenes de clientes" })).toHaveAttribute("href", "/digests")
  expect(screen.queryByRole("button", { name: /Generar|Narrativa|Eliminar/ })).not.toBeInTheDocument()
})
it("distinguishes failed initial load from empty and recovers", async () => {
  mocks.list.mockRejectedValueOnce(new Error("503"))
  setup()
  expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo cargar")
  expect(screen.queryByText("No hay informes anteriores.")).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", { name: "Reintentar" }))
  expect(await screen.findByRole("button", { name: /Informe 1/ })).toBeInTheDocument()
})
it("preserves the first page when the next fails and retries its same offset", async () => {
  mocks.list.mockResolvedValueOnce(Array.from({ length: 20 }, (_, i) => report(i + 1))).mockRejectedValueOnce(new Error("503")).mockResolvedValueOnce([report(21)])
  setup()
  fireEvent.click(await screen.findByRole("button", { name: "Ver más informes" }))
  await screen.findByRole("alert")
  expect(screen.getByRole("button", { name: /Informe 20/ })).toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", { name: "Reintentar" }))
  expect(await screen.findByRole("button", { name: /Informe 21/ })).toBeInTheDocument()
  expect(mocks.list.mock.calls.map(([p]) => p.offset)).toEqual([0, 20, 20])
})
it("hides cached snapshots and their open panel after permission rejection", async () => {
  const { client } = setup()
  fireEvent.click(await screen.findByRole("button", { name: /Informe 1/ }))
  mocks.list.mockRejectedValue({ response: { status: 403 } })
  await act(async () => { await client.invalidateQueries({ queryKey: ["reports"] }) })
  await screen.findByRole("alert")
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
  expect(screen.queryByRole("button", { name: /Informe 1/ })).not.toBeInTheDocument()
  mocks.list.mockRejectedValue(new Error("503"))
  fireEvent.click(screen.getByRole("button", { name: "Reintentar" }))
  await waitFor(() => expect(mocks.list).toHaveBeenCalledTimes(3))
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
})
it("clears local selection across identity and permission changes", async () => {
  const view = setup()
  fireEvent.click(await screen.findByRole("button", { name: /Informe 1/ }))
  mocks.id = 8
  mocks.list.mockResolvedValue([report(2)])
  view.rerender(view.element())
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  expect(await screen.findByRole("button", { name: /Informe 2/ })).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: /Informe 1/ })).not.toBeInTheDocument()
})
it("requires explicit confirmation before deleting an archived report", async () => {
  mocks.write = true
  setup()
  fireEvent.click(await screen.findByRole("button", { name: "Eliminar Informe 1" }))
  expect(mocks.del).not.toHaveBeenCalled()
  expect(screen.getByRole("dialog")).toHaveTextContent("no se puede deshacer")
  fireEvent.click(screen.getByRole("button", { name: "Eliminar" }))
  await waitFor(() => expect(mocks.del).toHaveBeenCalledWith(1, expect.anything()))
})
