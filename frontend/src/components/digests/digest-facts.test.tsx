import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { DigestFacts } from "./digest-facts"
const auth = vi.hoisted(() => ({ canReadTasks: true, canReadProjects: true }))
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ hasPermission: (module: string) => module === "tasks" ? auth.canReadTasks : module === "projects" && auth.canReadProjects }) }))
const tasks = Array.from({ length: 10 }, (_, index) => ({ id: index + 1, title: `Hecho ${index + 1}` }))
const v2 = {
  context_version: 2,
  totals: { project_count: 2, unresolved_project_count: 1, completed_total: 12, in_progress_total: 1, pending_total: 3, total_minutes: 195 },
  projects: [
    { project_id: 4, project_name: "Web", resolution: "resolved", progress_percent: 75, task_total: 16, completed_total: 12, completed_tasks: tasks, in_progress_total: 1, in_progress_tasks: [{ id: 20, title: "Revisión" }], pending_total: 2, pending_tasks: [{ id: 21, title: "Publicar" }, { id: 22, title: "Medir" }], total_minutes: 180, historical_template_minutes: 30 },
    { project_id: 5, project_name: "SEO", resolution: "resolved", progress_percent: 20, task_total: 1, completed_total: 0, completed_tasks: [], in_progress_total: 1, in_progress_tasks: [{ id: 23, title: "Auditar keywords" }], pending_total: 0, pending_tasks: [], total_minutes: 45, historical_template_minutes: 0 },
  ],
  unresolved_projects: [{ project_id: 99, project_name: "Proyecto no resuelto (ID 99)", resolution: "unresolved", progress_percent: null, task_total: 1, completed_total: 0, completed_tasks: [], in_progress_total: 0, in_progress_tasks: [], pending_total: 1, pending_tasks: [{ id: 30, title: "Referencia antigua" }], total_minutes: 0, historical_template_minutes: 0 }],
  unassigned: { project_id: null, project_name: null, resolution: "unassigned", progress_percent: null, task_total: 1, completed_total: 0, completed_tasks: [], in_progress_total: 0, in_progress_tasks: [], pending_total: 1, pending_tasks: [{ id: 31, title: "Tarea del cliente" }], total_minutes: 15, historical_template_minutes: 0 },
  pending_followups: [{ id: 8, subject: "Confirmar acceso", summary: "Falta permiso", contact_name: "Ana", followup_date: "2026-09-20" }],
}
function renderFacts(context: Record<string, unknown>) { return render(<MemoryRouter><DigestFacts context={context} /></MemoryRouter>) }
beforeEach(() => { auth.canReadTasks = true; auth.canReadProjects = true })
describe("DigestFacts", () => {
  it("presents V2 totals, bounded samples and separate project buckets", async () => {
    renderFacts(v2); await userEvent.click(screen.getByText("Hechos fuente del resumen"))
    expect(screen.getByText("12 en total · mostrando 10")).toBeInTheDocument()
    expect(screen.getByText("Progreso al generar: 75% · no corresponde solo al período")).toBeInTheDocument()
    expect(screen.getByText(/30 min reales registrados históricamente sobre plantillas/)).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Web" })).toHaveAttribute("href", "/projects/4")
    expect(screen.getByRole("link", { name: "SEO" })).toHaveAttribute("href", "/projects/5")
    expect(screen.queryByRole("link", { name: "Proyecto no resuelto (ID 99)" })).not.toBeInTheDocument()
    expect(screen.getByText("Tarea del cliente")).toBeInTheDocument()
    expect(screen.getByText("Confirmar acceso")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Hecho 1" })).toHaveAttribute("href", "/tasks?task=1")
    expect(screen.getAllByText(/fecha registrada dentro del período/).length).toBeGreaterThan(0)
  })
  it("does not expose task links without tasks read permission", async () => {
    auth.canReadTasks = false; renderFacts(v2); await userEvent.click(screen.getByText("Hechos fuente del resumen"))
    expect(screen.getByText("Hecho 1")).toBeInTheDocument(); expect(screen.queryByRole("link", { name: "Hecho 1" })).not.toBeInTheDocument()
  })
  it("does not expose project links without projects read permission", async () => {
    auth.canReadProjects = false; renderFacts(v2); await userEvent.click(screen.getByText("Hechos fuente del resumen"))
    expect(screen.getByText("Web")).toBeInTheDocument(); expect(screen.queryByRole("link", { name: "Web" })).not.toBeInTheDocument()
  })
  it("renders legacy facts without inventing project grouping", async () => {
    const pending = Array.from({ length: 10 }, (_, index) => ({ id: 71 + index, title: `Pendiente legado ${index + 1}` }))
    renderFacts({ client_name: "Anterior", project_name: "Proyecto antiguo", project_progress: 40, completed_tasks: [{ id: 70, title: "Hecho legado" }], in_progress_tasks: [], pending_tasks: pending, total_minutes: 90, pending_followups: [] })
    await userEvent.click(screen.getByText("Hechos fuente del resumen"))
    expect(screen.getByText(/muestras sin totales conocidos/)).toBeInTheDocument(); expect(screen.getByText("Progreso histórico de Proyecto antiguo")).toBeInTheDocument()
    expect(screen.getByText("11 tareas en la muestra guardada")).toBeInTheDocument(); expect(screen.queryByText(/en total/)).not.toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Hecho legado" })).toHaveAttribute("href", "/tasks?task=70")
  })
  it("keeps unsupported context available as technical fallback", async () => {
    renderFacts({ future_shape: { preserved: true } }); await userEvent.click(screen.getByText("Hechos fuente del resumen")); await userEvent.click(screen.getByText("Ver datos técnicos no reconocidos"))
    expect(screen.getByText(/future_shape/)).toBeInTheDocument(); expect(screen.getByText(/preserved/)).toBeInTheDocument()
  })
})
