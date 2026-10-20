import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, within } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import type { Client, ClientStatusRow, Task } from "@/lib/types"
import { ClientOverview } from "./client-overview"

const mocks = vi.hoisted(() => ({ contacts: vi.fn() }))
vi.mock("@/lib/api", () => ({ contactsApi: { list: mocks.contacts } }))

const client = { id: 5, name: "Parklex", context: "Fabricante de paneles. Decide Marta.", engine_project_id: 9 } as unknown as Client
const status: ClientStatusRow = {
  client_id: 5, client_name: "Parklex", status: "act",
  reasons: ["3 tareas vencidas"],
  seo: null,
  digest: { cadence: "monthly", last_sent_period_end: null, expected_period_end: "2026-09-30", state: "late" },
  tasks: { overdue: 3, waiting: 1, followups_late: 1 },
  month: { hours: 12.5 },
  ready: { since: "2026-09-01", count: 7, items: [{ id: 9, title: "Informe de enlaces", completed_on: "2026-10-14" }] },
  vigil: null,
}
const task = (id: number, title: string, extra: Partial<Task>) => ({ id, title, status: "pending", due_date: null, ...extra }) as Task
const tasks = [
  task(1, "Entrega tarde", { due_date: "2020-01-10" }),
  task(2, "Entrega futura", { due_date: "2099-01-10" }),
  task(3, "Revisar textos", { status: "in_review" }),
  task(4, "Accesos GSC", { status: "waiting", waiting_for: "cliente", follow_up_date: "2020-01-14" }),
  task(5, "Hecha", { status: "completed" }),
]

function show(props: Partial<React.ComponentProps<typeof ClientOverview>> = {}) {
  const onNavigate = vi.fn()
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <ClientOverview client={client} status={status} statusFailed={false} onRetryStatus={vi.fn()} tasks={tasks}
        canReadDigests canReadContacts engineReportsUrl="https://engine/p/9/reports" onNavigate={onNavigate} {...props} />
    </QueryClientProvider>,
  )
  return { onNavigate }
}

const block = (title: string) => screen.getByRole("heading", { name: title }).closest("div.space-y-3") as HTMLElement

describe("ClientOverview", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.contacts.mockResolvedValue([{ id: 1, name: "Marta", position: "CMO", email: "marta@parklex.es", is_primary: true }])
  })

  it("shows the status and the three blocks", async () => {
    show()
    expect(screen.getByText("3 tareas vencidas")).toBeInTheDocument()

    const work = block("Trabajo")
    expect(within(work).getByText(/4 abiertas · 12,5 h este mes/)).toBeInTheDocument()
    expect(within(work).getByText("Entrega tarde")).toBeInTheDocument()
    expect(within(work).queryByText("Accesos GSC")).not.toBeInTheDocument()
    expect(within(work).queryByText("Hecha")).not.toBeInTheDocument()
    expect(within(work).getByText("Por revisar (1)")).toBeInTheDocument()

    const results = block("Resultados")
    expect(within(results).getByRole("link", { name: /Informe SEO en PDF/ })).toHaveAttribute("href", "https://engine/p/9/reports")

    const relation = block("Relación")
    expect(await within(relation).findByText("Marta")).toBeInTheDocument()
    expect(within(relation).getByText("Esperando al cliente (1)")).toBeInTheDocument()
    expect(within(relation).getByText("Accesos GSC")).toBeInTheDocument()
    expect(within(relation).getByText(/Fabricante de paneles/)).toBeInTheDocument()
  })

  it("shows what is ready to deliver in the work block", () => {
    show()
    const work = block("Trabajo")
    expect(within(work).getByText("Listo para entregar (7)")).toBeInTheDocument()
    expect(within(work).getByText(/Terminado desde el 1 sept/)).toBeInTheDocument()
    expect(within(work).getByText("Informe de enlaces")).toBeInTheDocument()
    expect(within(work).getByText("14 oct")).toBeInTheDocument()
  })

  it("says when nothing is pending to deliver", () => {
    show({ status: { ...status, ready: { since: "2026-10-01", count: 0, items: [] } } })
    expect(screen.getByText("Nada pendiente de contar.")).toBeInTheDocument()
  })

  it("leaves the ready block out when the status has none", () => {
    show({ status: { ...status, ready: null } })
    expect(screen.queryByText(/Listo para entregar/)).not.toBeInTheDocument()
  })

  it("links each block to its tab", () => {
    const { onNavigate } = show()
    fireEvent.click(screen.getByText("Ver tareas"))
    fireEvent.click(screen.getByText("Abrir resúmenes"))
    fireEvent.click(screen.getByText("Ver contexto"))
    expect(onNavigate.mock.calls.map(([section]) => section)).toEqual(["tareas", "resumenes", "contexto"])
  })

  it("leaves out what the viewer cannot read", () => {
    show({ tasks: null, canReadDigests: false, canReadContacts: false })
    expect(screen.getByText("Sin acceso a las tareas.")).toBeInTheDocument()
    expect(screen.queryByText("Esperando al cliente (0)")).not.toBeInTheDocument()
    expect(screen.queryByText("Abrir resúmenes")).not.toBeInTheDocument()
    expect(screen.queryByText("Interlocutor")).not.toBeInTheDocument()
    expect(mocks.contacts).not.toHaveBeenCalled()
  })

  it("offers a retry when the status fails", () => {
    const onRetryStatus = vi.fn()
    show({ status: undefined, statusFailed: true, onRetryStatus })
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }))
    expect(onRetryStatus).toHaveBeenCalled()
  })

  it("shows Vigil's unreviewed changes with a link to Vigil", () => {
    show({ status: { ...status, vigil: {
      slug: "parklex", critical: 2, warning: 1, info: 4, watches_active: 12, watches_with_error: 1,
      last_checked_at: "2026-10-20T04:32:00+00:00", last_run_status: "done",
      fetched_at: "2026-10-20T07:00:00+00:00", fresh: true, url: "https://vigil.magnifytools.com",
    } } })
    const results = block("Resultados")
    expect(within(results).getByText("2 críticos · 1 aviso sin revisar")).toHaveClass("text-red-600")
    expect(within(results).getByText(/12 páginas vigiladas · 1 con error/)).toBeInTheDocument()
    expect(within(results).getByRole("link", { name: /Abrir en Vigil/ })).toHaveAttribute("href", "https://vigil.magnifytools.com")
  })

  it("leaves Vigil out for clients that are not linked", () => {
    show()
    expect(screen.queryByText("Cambios en la web")).not.toBeInTheDocument()
  })
})
