import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TaskPanel } from "./task-panel";
import { clientKeys, taskKeys } from "@/lib/query-keys";

const mocks = vi.hoisted(() => ({
  canWrite: true,
  canReadProjects: true,
  canReadTime: true,
  user: { id: 2 },
  isAdmin: false,
  get: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  restore: vi.fn(),
  recurrencePreview: vi.fn(),
  list: vi.fn(),
  checklist: vi.fn(),
  attachments: vi.fn(),
  comments: vi.fn(),
  createChecklist: vi.fn(),
  createComment: vi.fn(),
  upload: vi.fn(),
  toastError: vi.fn(),
  listTasks: vi.fn(),
  listProjects: vi.fn(),
  getProject: vi.fn(),
  updateChecklist: vi.fn(),
  deleteChecklist: vi.fn(),
  deleteAttachment: vi.fn(),
  deleteComment: vi.fn(),
  draft: vi.fn(),
}));
vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({
    user: mocks.user,
    isAdmin: mocks.isAdmin,
    hasPermission: (module: string, write?: boolean) =>
      module === "timesheet" ? mocks.canReadTime : module === "projects" ? (!write && mocks.canReadProjects) : !write || mocks.canWrite,
  }),
}));
vi.mock("@/lib/api", () => ({
  clientsApi: {
    listAll: () =>
      Promise.resolve([
        { id: 4, name: "Acme" },
        { id: 6, name: "Beta" },
      ]),
  },
  projectsApi: {
    listAll: mocks.listProjects,
    get: mocks.getProject,
  },
  usersApi: {
    listAll: () => Promise.resolve([{ id: 2, full_name: "Violeta", is_active: true }, { id: 5, full_name: "Nacho Pérez", short_name: "Nacho", is_active: true }]),
  },
  categoriesApi: { list: () => Promise.resolve([]) },
  tasksApi: {
    get: mocks.get,
    listAll: mocks.listTasks,
    create: mocks.create,
    update: mocks.update,
    restore: mocks.restore,
    recurrencePreview: mocks.recurrencePreview,
    draft: mocks.draft,
    checklist: {
      list: mocks.checklist,
      create: mocks.createChecklist,
      update: mocks.updateChecklist,
      delete: mocks.deleteChecklist,
    },
    comments: {
      list: mocks.comments,
      create: mocks.createComment,
      delete: mocks.deleteComment,
    },
    attachments: {
      list: mocks.attachments,
      upload: mocks.upload,
      delete: mocks.deleteAttachment,
      download: vi.fn(),
    },
  },
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: mocks.toastError },
}));

const task = {
  id: 9,
  title: "Auditar",
  description: null,
  status: "pending",
  priority: "medium",
  estimated_minutes: null,
  actual_minutes: null,
  start_date: null,
  due_date: null,
  client_id: 4,
  category_id: null,
  assigned_to: null,
  project_id: 7,
  phase_id: 3,
  is_inbox: false,
  depends_on: 11,
  created_by: 1,
  scheduled_date: null,
  follow_up_date: "2026-09-24",
  waiting_for: "Aprobación",
  is_recurring: true,
  recurrence_pattern: "biweekly",
  recurrence_day: 2,
  recurrence_end_date: "2026-12-31",
  recurrence_anchor_date: null,
  recurrence_paused_at: null,
  recurrence_summary: null,
  recurring_parent_id: null,
  link_url: null,
  created_at: "",
  updated_at: "",
  client_name: "Acme",
  category_name: null,
  assigned_user_name: null,
  project_name: "SEO",
  phase_name: null,
  dependency_title: null,
  created_by_name: null,
  recurring_parent_title: null,
  project_requires_task_review: false,
  project_review_owner_id: null,
  checklist_count: 0,
} as const;

function setup(props: Partial<React.ComponentProps<typeof TaskPanel>> = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const onOpenChange = vi.fn();
  const onOpenTime = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <TaskPanel
        open
        onOpenChange={onOpenChange}
        onOpenTime={onOpenTime}
        {...props}
      />
    </QueryClientProvider>,
  );
  return { client, onOpenChange, onOpenTime };
}

describe("TaskPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.canWrite = true;
    mocks.canReadProjects = true;
    mocks.user = { id: 2 };
    mocks.isAdmin = false;
  mocks.canReadTime = true;
    mocks.get.mockResolvedValue(task);
    mocks.checklist.mockResolvedValue([]);
    mocks.attachments.mockResolvedValue([]);
    mocks.comments.mockResolvedValue([]);
    mocks.listTasks.mockResolvedValue([
      { ...task, id: 11, title: "Preparar datos" },
    ]);
    mocks.listProjects.mockResolvedValue([
      { id: 7, name: "SEO archivado", client_id: 4, status: "completed" },
      { id: 8, name: "SEO nuevo", client_id: 4, status: "active" },
    ]);
    mocks.getProject.mockResolvedValue({
      id: 7,
      name: "SEO archivado",
      client_id: 4,
      phases: [
        { id: 3, name: "Auditoría" },
        { id: 4, name: "Entrega" },
      ],
    });
  });

  it("creates in the fixed project/client scope with an explicit null assignee", async () => {
    mocks.create.mockResolvedValue({ ...task, title: "Nueva" });
    setup({ defaults: { clientId: 4, projectId: 7, phaseId: 3 } });
    await userEvent.type(screen.getByLabelText("Título"), "Nueva");
    await userEvent.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() =>
      expect(mocks.create).toHaveBeenCalledWith(
        expect.objectContaining({
          title: "Nueva",
          client_id: 4,
          project_id: 7,
          phase_id: 3,
          assigned_to: null,
        }),
      ),
    );
    expect(screen.getByLabelText("Cliente")).toBeDisabled();
    expect(screen.getByLabelText("Proyecto")).toBeDisabled();
  });

  it("keeps the draft after a save error and allows retry", async () => {
    mocks.create
      .mockRejectedValueOnce(new Error("timeout"))
      .mockResolvedValueOnce({ ...task, title: "Borrador" });
    setup({ defaults: { clientId: 4 } });
    await userEvent.type(screen.getByLabelText("Título"), "Borrador");
    await userEvent.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    expect(screen.getByLabelText("Título")).toHaveValue("Borrador");
    await userEvent.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(2));
  });

  it("does not expose time history when timesheet is not readable", async () => {
    mocks.canReadTime = false;
    setup({ taskId: 9 });
    await screen.findByDisplayValue("Auditar");
    expect(screen.queryByRole("button", { name: "Ver horas y registrar tiempo" })).not.toBeInTheDocument();
  });

  it("hides cached task details after a task read error", async () => {
    mocks.get.mockRejectedValue(new Error("forbidden"));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    client.setQueryData(taskKeys.detail(9), task);
    render(<QueryClientProvider client={client}><TaskPanel open taskId={9} onOpenChange={vi.fn()} /></QueryClientProvider>);
    expect(await screen.findByRole("alert")).toHaveTextContent("forbidden");
    expect(screen.queryByLabelText("Título")).not.toBeInTheDocument();
  });

  it("does not fetch or clear a project scope without projects read", async () => {
    mocks.canReadProjects = false;
    setup({ taskId: 9 });
    await screen.findByLabelText("Proyecto");
    expect(mocks.listProjects).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Proyecto")).toBeDisabled();
    expect(screen.getByLabelText("Cliente")).toBeDisabled();
    expect(screen.getByLabelText("Proyecto")).toHaveValue("7");
  });

  it("respects read-only permission and keeps time behind an explicit action", async () => {
    mocks.canWrite = false;
    const { onOpenTime } = setup({ taskId: 9 });
    expect(
      await screen.findByText("Puedes consultar esta tarea, pero no editarla."),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Guardar" }),
    ).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Ver horas y registrar tiempo" }),
    );
    expect(onOpenTime).toHaveBeenCalledWith(task);
    expect(mocks.update).not.toHaveBeenCalled();
  });

  it("preserves inactive project and follow-up values, and invalidates old and new scopes", async () => {
    mocks.update.mockResolvedValue({ ...task, project_id: 8, client_id: 5 });
    const { client } = setup({ taskId: 9 });
    client.setQueryData(["projects", "detail", 7], {});
    client.setQueryData(["projects", "detail", 8], {});
    client.setQueryData(clientKeys.summary(4), {});
    client.setQueryData(clientKeys.summary(5), {});
    expect(
      await screen.findByRole("option", { name: "SEO archivado" }),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByText("Espera y seguimiento"));
    expect(screen.getByLabelText("Respuesta pendiente")).toHaveValue("Aprobación");
    expect(screen.getByLabelText("Revisar el")).toHaveValue("2026-09-24");
    await userEvent.selectOptions(screen.getByLabelText("Proyecto"), "8");
    await userEvent.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(mocks.update).toHaveBeenCalled());
    expect(client.getQueryState(clientKeys.summary(4))?.isInvalidated).toBe(
      true,
    );
    expect(client.getQueryState(clientKeys.summary(5))?.isInvalidated).toBe(
      true,
    );
  });

  it("shows secondary mutation errors and blocks duplicate checklist submission", async () => {
    let reject!: (error: Error) => void;
    mocks.createChecklist.mockReturnValue(
      new Promise((_resolve, nextReject) => {
        reject = nextReject;
      }),
    );
    setup({ taskId: 9 });
    await screen.findByDisplayValue("Auditar");
    await userEvent.click(
      screen.getByText("Checklist, comentarios y archivos"),
    );
    await userEvent.type(
      screen.getByLabelText("Nueva entrada de checklist"),
      "Revisar datos",
    );
    const add = screen.getByRole("button", { name: "Añadir al checklist" });
    await userEvent.click(add);
    await userEvent.click(add);
    expect(mocks.createChecklist).toHaveBeenCalledTimes(1);
    reject(new Error("timeout"));
    await waitFor(() =>
      expect(mocks.toastError).toHaveBeenCalledWith("timeout"),
    );
  });

  it("preserves recurrence and dependency while allowing a phase move", async () => {
    mocks.update.mockResolvedValue({ ...task, phase_id: 4 });
    setup({ taskId: 9 });
    await screen.findByDisplayValue("Auditar");
    await userEvent.click(screen.getByText("Más opciones"));
    expect(screen.getByLabelText("Depende de")).toHaveValue("11");
    expect(screen.getByLabelText("Patrón")).toHaveValue("biweekly");
    expect(screen.getByLabelText("Día")).toHaveValue("2");
    expect(screen.getByLabelText("Finaliza")).toHaveValue("2026-12-31");
    await userEvent.selectOptions(screen.getByLabelText("Fase"), "4");
    await userEvent.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() =>
      expect(mocks.update).toHaveBeenCalledWith(
        9,
        expect.objectContaining({
          phase_id: 4,
          depends_on: 11,
          is_recurring: true,
          recurrence_pattern: "biweekly",
          recurrence_day: 2,
          recurrence_end_date: "2026-12-31",
        }),
      ),
    );
  });

  it("clears project and phase when the client scope changes", async () => {
    setup({ taskId: 9 });
    await screen.findByDisplayValue("Auditar");
    await userEvent.selectOptions(screen.getByLabelText("Cliente"), "6");
    expect(screen.getByLabelText("Proyecto")).toHaveValue("");
    expect(screen.getByLabelText("Fase")).toHaveValue("");
  });

  it("updates and deletes checklist items and deletes attachments", async () => {
    mocks.checklist.mockResolvedValue([
      {
        id: 21,
        text: "Comprobar",
        description: "Detalle anterior",
        is_done: false,
        assigned_to: null,
        due_date: null,
      },
    ]);
    mocks.attachments.mockResolvedValue([{ id: 31, name: "brief.pdf" }]);
    mocks.comments.mockResolvedValue([
      { id: 41, text: "Hecho", user_name: "Violeta" },
    ]);
    mocks.updateChecklist.mockResolvedValue({});
    mocks.deleteChecklist.mockResolvedValue({});
    mocks.deleteAttachment.mockResolvedValue({});
    setup({ taskId: 9 });
    await screen.findByDisplayValue("Auditar");
    await userEvent.click(
      screen.getByText("Checklist, comentarios y archivos"),
    );
    await userEvent.click(await screen.findByLabelText("Completar Comprobar"));
    expect(mocks.updateChecklist).toHaveBeenCalledWith(9, 21, {
      is_done: true,
    });
    await userEvent.selectOptions(
      screen.getByLabelText("Responsable de Comprobar"),
      "2",
    );
    expect(mocks.updateChecklist).toHaveBeenCalledWith(9, 21, {
      assigned_to: 2,
    });
    await userEvent.type(
      screen.getByLabelText("Fecha de Comprobar"),
      "2026-10-01",
    );
    expect(mocks.updateChecklist).toHaveBeenCalledWith(9, 21, {
      due_date: "2026-10-01",
    });
    await userEvent.click(
      screen.getByRole("button", { name: "Eliminar Comprobar" }),
    );
    expect(mocks.deleteChecklist).toHaveBeenCalledWith(9, 21);
    await userEvent.click(
      await screen.findByRole("button", { name: "Eliminar archivo brief.pdf" }),
    );
    await waitFor(() =>
      expect(mocks.deleteAttachment).toHaveBeenCalledWith(9, 31),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Eliminar comentario de Violeta" }),
    );
    expect(mocks.deleteComment).toHaveBeenCalledWith(9, 41);
  });

  it("shows load failures for every secondary source", async () => {
    mocks.checklist.mockRejectedValue(new Error("checklist"));
    mocks.comments.mockRejectedValue(new Error("comments"));
    mocks.attachments.mockRejectedValue(new Error("attachments"));
    setup({ taskId: 9 });
    await screen.findByDisplayValue("Auditar");
    await userEvent.click(
      screen.getByText("Checklist, comentarios y archivos"),
    );
    expect(
      await screen.findByText("No se pudieron cargar checklist."),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("No se pudieron cargar comentarios."),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("No se pudieron cargar archivos."),
    ).toBeInTheDocument();
  });

  it("previews a biweekly template with human days and preserves a legacy calendar until the anchor is explicit", async () => {
    mocks.recurrencePreview.mockResolvedValue({
      state: "active",
      reason: null,
      label: "Cada dos semanas, los miércoles",
      next_dates: ["2026-10-07", "2026-10-21"],
    });
    setup({ taskId: 9 });
    await screen.findByDisplayValue("Auditar");
    await userEvent.click(screen.getByText("Más opciones"));
    expect(screen.getByText(/mantiene el calendario actual/)).toBeInTheDocument();
    expect(screen.getByLabelText("Día")).toHaveDisplayValue("Miércoles");
    await userEvent.click(screen.getByRole("button", { name: "Ver próximas fechas" }));
    await waitFor(() => expect(mocks.recurrencePreview).toHaveBeenCalledWith(expect.objectContaining({
      recurrence_pattern: "biweekly",
      recurrence_anchor_date: null,
      recurrence_paused: false,
    })));
    expect(await screen.findByText("Cada dos semanas, los miércoles")).toBeInTheDocument();
    expect(screen.getByText(/2026-10-07/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Comparar calendario actual" }));
    expect(await screen.findByText("Calendario actual")).toBeInTheDocument();
    expect(screen.getByText("Con este cambio")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Aplicar este cambio" }));
    expect(screen.getByLabelText("Repetir cada dos semanas desde")).not.toHaveValue("");
  });

  it("pauses and resumes a recurrence without closing the task panel", async () => {
    mocks.update
      .mockResolvedValueOnce({ ...task, recurrence_paused_at: "2026-09-20T09:00:00Z" })
      .mockResolvedValueOnce({ ...task, recurrence_paused_at: null });
    const { onOpenChange } = setup({ taskId: 9 });
    await screen.findByDisplayValue("Auditar");
    await userEvent.click(screen.getByText("Más opciones"));
    await userEvent.click(screen.getByRole("button", { name: "Pausar recurrencia" }));
    await waitFor(() => expect(mocks.update).toHaveBeenCalledWith(9, { recurrence_paused: true }));
    await userEvent.click(await screen.findByRole("button", { name: "Reanudar recurrencia" }));
    await waitFor(() => expect(mocks.update).toHaveBeenCalledWith(9, { recurrence_paused: false }));
    expect(onOpenChange).not.toHaveBeenCalled();
  });

  it("does not show a late preview after its recurrence rule changed", async () => {
    let resolve!: (value: { state: "active"; reason: null; label: string; next_dates: string[] }) => void;
    mocks.recurrencePreview.mockReturnValue(new Promise((done) => { resolve = done; }));
    setup({ taskId: 9 });
    await screen.findByDisplayValue("Auditar");
    await userEvent.click(screen.getByText("Más opciones"));
    await userEvent.click(screen.getByRole("button", { name: "Ver próximas fechas" }));
    await userEvent.selectOptions(screen.getByLabelText("Día"), "4");
    resolve({ state: "active", reason: null, label: "Resultado antiguo", next_dates: ["2026-10-07"] });
    await waitFor(() => expect(screen.queryByText("Resultado antiguo")).not.toBeInTheDocument());
  });

  it("uses valid defaults when a new template changes from weekly to monthly", async () => {
    setup();
    await userEvent.type(screen.getByLabelText("Título"), "Nueva plantilla");
    await userEvent.click(screen.getByLabelText("Repetir tarea"));
    expect(screen.getByLabelText("Día")).toHaveValue("0");
    await userEvent.selectOptions(screen.getByLabelText("Patrón"), "monthly");
    expect(screen.getByLabelText("Día")).toHaveValue(1);
  });

  it("requires a legacy calendar comparison before saving an explicit biweekly anchor", async () => {
    mocks.recurrencePreview.mockResolvedValue({ state: "active", reason: null, label: "Calendario", next_dates: ["2026-10-07"] });
    setup({ taskId: 9 });
    await screen.findByDisplayValue("Auditar");
    await userEvent.click(screen.getByText("Más opciones"));
    await userEvent.type(screen.getByLabelText("Repetir cada dos semanas desde"), "2026-10-01");
    expect(screen.getByRole("button", { name: "Guardar" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Comparar calendario actual" }));
    await screen.findByText("Calendario actual");
    expect(screen.getByRole("button", { name: "Guardar" })).toBeEnabled();
  });

  it("compares the saved legacy calendar against changed weekday and end date", async () => {
    mocks.recurrencePreview.mockResolvedValue({ state: "active", reason: null, label: "Calendario", next_dates: ["2026-10-07"] });
    setup({ taskId: 9 });
    await screen.findByDisplayValue("Auditar");
    await userEvent.click(screen.getByText("Más opciones"));
    await userEvent.selectOptions(screen.getByLabelText("Día"), "0");
    await userEvent.clear(screen.getByLabelText("Finaliza"));
    await userEvent.type(screen.getByLabelText("Finaliza"), "2027-01-15");
    await userEvent.click(screen.getByRole("button", { name: "Comparar calendario actual" }));
    await waitFor(() => expect(mocks.recurrencePreview).toHaveBeenLastCalledWith(expect.objectContaining({
      recurrence_day: 0,
      recurrence_end_date: "2027-01-15",
    })));
    const [current] = mocks.recurrencePreview.mock.calls.slice(-2);
    expect(current[0]).toMatchObject({ recurrence_day: 2, recurrence_end_date: "2026-12-31", recurrence_anchor_date: null });
  });

  it("anchors an existing weekly template when it becomes every two weeks", async () => {
    mocks.get.mockResolvedValue({ ...task, recurrence_pattern: "weekly", recurrence_anchor_date: null });
    mocks.recurrencePreview.mockResolvedValue({ state: "active", reason: null, label: "Cada dos semanas", next_dates: ["2026-10-07"] });
    setup({ taskId: 9 });
    await screen.findByDisplayValue("Auditar");
    await userEvent.click(screen.getByText("Más opciones"));
    await userEvent.selectOptions(screen.getByLabelText("Patrón"), "biweekly");
    expect(screen.getByLabelText("Repetir cada dos semanas desde")).not.toHaveValue("");
    await userEvent.click(screen.getByRole("button", { name: "Ver próximas fechas" }));
    await waitFor(() => expect(mocks.recurrencePreview).toHaveBeenCalledWith(expect.objectContaining({ recurrence_anchor_date: expect.any(String) })));
  });

  it("compares real future dates for a paused legacy template", async () => {
    mocks.get.mockResolvedValue({ ...task, recurrence_paused_at: "2026-09-20T09:00:00Z" });
    mocks.recurrencePreview.mockResolvedValue({ state: "active", reason: null, label: "Al reanudar", next_dates: ["2026-10-07"] });
    setup({ taskId: 9 });
    await screen.findByDisplayValue("Auditar");
    await userEvent.click(screen.getByText("Más opciones"));
    await userEvent.click(screen.getByRole("button", { name: "Comparar calendario actual" }));
    expect(await screen.findByText("Fechas al reanudar")).toBeInTheDocument();
    await waitFor(() => expect(mocks.recurrencePreview).toHaveBeenCalledTimes(2));
    expect(mocks.recurrencePreview).toHaveBeenNthCalledWith(1, expect.objectContaining({ recurrence_paused: false }));
    expect(mocks.recurrencePreview).toHaveBeenNthCalledWith(2, expect.objectContaining({ recurrence_paused: false }));
  });

  it("does not invent a completion date for a historical completed task", async () => {
    mocks.get.mockResolvedValue({ ...task, status: "completed", completed_at: null });
    setup({ taskId: 9 });
    expect(await screen.findByText(/No se registró la fecha de finalización/)).toBeInTheDocument();
  });

  it("keeps a legacy incomplete wait editable until its wait fields change", async () => {
    mocks.get.mockResolvedValue({ ...task, status: "waiting", waiting_for: null, follow_up_date: null });
    mocks.update.mockResolvedValue({ ...task, status: "waiting", title: "Auditar nota" });
    setup({ taskId: 9 });
    const title = await screen.findByLabelText("Título");
    await userEvent.clear(title);
    await userEvent.type(title, "Auditar nota");
    await userEvent.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(mocks.update).toHaveBeenCalledWith(9, expect.objectContaining({ title: "Auditar nota" })));
  });

  it("keeps an existing past review date when only the waiting reason changes", async () => {
    mocks.get.mockResolvedValue({ ...task, status: "waiting", assigned_to: 2, waiting_for: "Respuesta antigua", follow_up_date: "2026-09-01" });
    mocks.update.mockResolvedValue({ ...task, status: "waiting", assigned_to: 2, waiting_for: "Respuesta actualizada", follow_up_date: "2026-09-01" });
    setup({ taskId: 9 });
    await screen.findByDisplayValue("Auditar");
    await userEvent.click(screen.getByText("Espera y seguimiento"));
    const reason = screen.getByLabelText("Respuesta pendiente");
    await userEvent.clear(reason);
    await userEvent.type(reason, "Respuesta actualizada");
    expect(screen.getByRole("button", { name: "Guardar" })).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(mocks.update).toHaveBeenCalledWith(9, expect.objectContaining({ follow_up_date: "2026-09-01" })));
  });

  it("requires a review date when editing the reason of a legacy wait that has none", async () => {
    mocks.get.mockResolvedValue({ ...task, status: "waiting", assigned_to: 2, waiting_for: "Respuesta antigua", follow_up_date: null });
    setup({ taskId: 9 });
    await screen.findByDisplayValue("Auditar");
    await userEvent.click(screen.getByText("Espera y seguimiento"));
    const reason = screen.getByLabelText("Respuesta pendiente");
    await userEvent.clear(reason);
    await userEvent.type(reason, "Respuesta actualizada");
    expect(screen.getByRole("button", { name: "Guardar" })).toBeDisabled();
    expect(screen.getByText(/Indica la respuesta pendiente/)).toBeInTheDocument();
  });

  it("requires complete wait details when entering a wait", async () => {
    setup({ taskId: 9 });
    await screen.findByDisplayValue("Auditar");
    await userEvent.selectOptions(screen.getByLabelText("Estado"), "waiting");
    expect(screen.getByText(/Completa Espera y seguimiento/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Guardar" })).toBeDisabled();
  });

  it("honors an explicit waiting intent when opened from an inline action", async () => {
    setup({ taskId: 9, defaults: { initialStatus: "waiting" } });
    await screen.findByDisplayValue("Auditar");
    expect(screen.getByLabelText("Estado")).toHaveValue("waiting");
    expect(screen.getByLabelText("Respuesta pendiente")).toBeVisible();
    expect(screen.getByLabelText("Revisar el")).toBeVisible();
    expect(screen.getByRole("button", { name: "Guardar" })).toBeDisabled();
  });

  it("lets a person resume an advanced task without changing its planned date", async () => {
    mocks.get.mockResolvedValue({ ...task, status: "advanced", scheduled_date: "2026-09-20" });
    mocks.update.mockResolvedValue({ ...task, status: "in_progress", scheduled_date: "2026-09-20" });
    setup({ taskId: 9 });
    await screen.findByRole("button", { name: "Retomar ahora" });
    await userEvent.click(screen.getByRole("button", { name: "Retomar ahora" }));
    await userEvent.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(mocks.update).toHaveBeenCalledWith(9, expect.objectContaining({ status: "in_progress", scheduled_date: "2026-09-20" })));
  });

  it("lets a person remove a dated legacy task from backlog explicitly", async () => {
    mocks.get.mockResolvedValue({ ...task, status: "backlog", scheduled_date: "2026-09-20" });
    mocks.update.mockResolvedValue({ ...task, status: "pending", scheduled_date: "2026-09-20" });
    setup({ taskId: 9 });
    await screen.findByRole("button", { name: "Sacar del backlog" });
    await userEvent.click(screen.getByRole("button", { name: "Sacar del backlog" }));
    await userEvent.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(mocks.update).toHaveBeenCalledWith(9, expect.objectContaining({ status: "pending", scheduled_date: "2026-09-20" })));
  });

  it("sends a non-owner task to review when its project requires review", async () => {
    mocks.get.mockResolvedValue({
      ...task,
      is_recurring: false,
      project_requires_task_review: true,
      project_review_owner_id: 3,
    });
    mocks.update.mockResolvedValue({ ...task, status: "in_review", project_requires_task_review: true, project_review_owner_id: 3 });
    setup({ taskId: 9 });
    await screen.findByDisplayValue("Auditar");
    await screen.findByText(/El responsable del proyecto revisa/);
    await userEvent.selectOptions(screen.getByLabelText("Estado"), "completed");
    await userEvent.click(await screen.findByRole("button", { name: "Enviar a revisión" }));
    await waitFor(() => expect(mocks.update).toHaveBeenCalledWith(9, expect.objectContaining({ status: "in_review" })));
  });

  it("lets the project owner approve or return a task in review", async () => {
    mocks.get.mockResolvedValue({
      ...task,
      is_recurring: false,
      status: "in_review",
      project_requires_task_review: true,
      project_review_owner_id: 2,
    });
    mocks.update.mockResolvedValue({ ...task, status: "completed" });
    setup({ taskId: 9 });
    await screen.findByRole("button", { name: "Aprobar y completar" });
    await userEvent.click(screen.getByRole("button", { name: "Aprobar y completar" }));
    await userEvent.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(mocks.update).toHaveBeenCalledWith(9, expect.objectContaining({ status: "completed" })));
  });

  it("keeps a retired task readable but blocks operational controls until restore", async () => {
    mocks.get.mockResolvedValue({ ...task, retired_at: "2026-09-20T10:00:00Z", retired_reason: "Ya no aplica", due_date: "2026-09-18T00:00:00Z" });
    mocks.restore.mockResolvedValue({ ...task, retired_at: null, retired_reason: null });
    const { onOpenTime } = setup({ taskId: 9 });
    expect(await screen.findByText(/Motivo: Ya no aplica/)).toBeInTheDocument();
    expect(screen.getByLabelText("Título")).toBeEnabled();
    expect(screen.getByLabelText("Estado")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Ver horas" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Restaurar tarea" }));
    await waitFor(() => expect(mocks.restore).toHaveBeenCalledWith(9, task.updated_at));
    expect(onOpenTime).not.toHaveBeenCalled();
  });

  it("saves only editable fields on a retired task", async () => {
    const retired = { ...task, retired_at: "2026-09-17T23:30:00Z", retired_reason: "Ya no aplica" };
    mocks.get.mockResolvedValue(retired);
    mocks.update.mockResolvedValue({ ...retired, title: "Auditar archivo" });
    setup({ taskId: 9 });
    const title = await screen.findByLabelText("Título");
    await userEvent.clear(title);
    await userEvent.type(title, "Auditar archivo");
    await userEvent.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(mocks.update).toHaveBeenCalledWith(9, {
      title: "Auditar archivo",
      description: null,
      link_url: null,
    }));
  });

  it("edits the procedure on a recurring template", async () => {
    const template = { ...task, recurrence_pattern: "weekly", recurrence_day: 0, procedure_text: null, procedure_url: null };
    mocks.get.mockResolvedValue(template);
    mocks.update.mockResolvedValue({ ...template, procedure_text: "1. Exportar" });
    setup({ taskId: 9 });
    const steps = await screen.findByLabelText("Pasos");
    expect(screen.getByText(/no afecta a las repeticiones ya creadas/)).toBeInTheDocument();
    await userEvent.type(steps, "1. Exportar");
    await userEvent.type(screen.getByLabelText("Documento de referencia"), "https://docs.example.test/proc");
    await userEvent.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(mocks.update).toHaveBeenCalledWith(9, expect.objectContaining({
      procedure_text: "1. Exportar",
      procedure_url: "https://docs.example.test/proc",
    })));
  });

  it("shows the copied procedure read-only on an occurrence", async () => {
    mocks.get.mockResolvedValue({
      ...task,
      is_recurring: false,
      recurrence_pattern: null,
      recurrence_day: null,
      recurrence_end_date: null,
      recurring_parent_id: 5,
      recurring_parent_title: "Informe mensual",
      recurrence_occurrence_date: "2026-09-21",
      procedure_text: "1. Exportar\n2. Revisar",
      procedure_url: "https://docs.example.test/proc",
    });
    setup({ taskId: 9 });
    expect(await screen.findByText(/1\. Exportar/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Abrir documento de referencia/ })).toHaveAttribute("href", "https://docs.example.test/proc");
    expect(screen.getByText(/Copiado de Informe mensual/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Pasos")).not.toBeInTheDocument();
  });

  describe("AI draft from the procedure", () => {
    const occurrence = {
      ...task,
      is_recurring: false,
      recurrence_pattern: null,
      recurrence_day: null,
      recurrence_end_date: null,
      recurring_parent_id: 5,
      recurring_parent_title: "Informe mensual",
      procedure_text: "1. Exportar\n2. Revisar",
      procedure_url: null,
    };
    const aiDraft = {
      id: 51, task_id: 9, user_id: 2, text: "## Informe\n- [PENDIENTE: clics]",
      user_name: "Violeta", is_ai_draft: true,
      created_at: "2026-10-20T08:00:00", updated_at: "2026-10-20T08:00:00",
    };

    it("generates a draft with a loading state and shows it labeled with a copy button", async () => {
      mocks.get.mockResolvedValue(occurrence);
      let resolveDraft: (value: unknown) => void = () => {};
      mocks.draft.mockReturnValue(new Promise((resolve) => { resolveDraft = resolve; }));
      const writeText = vi.fn().mockResolvedValue(undefined);
      Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
      setup({ taskId: 9 });
      await userEvent.click(await screen.findByRole("button", { name: "Generar borrador" }));
      expect(mocks.draft).toHaveBeenCalledWith(9);
      const pending = screen.getByRole("button", { name: /Generando borrador/ });
      expect(pending).toBeDisabled();
      mocks.comments.mockResolvedValue([aiDraft, { id: 41, text: "Hecho", user_name: "Violeta", is_ai_draft: false }]);
      resolveDraft(aiDraft);
      await screen.findByRole("button", { name: "Generar borrador" });
      await userEvent.click(screen.getByText("Checklist, comentarios y archivos"));
      const card = await screen.findByRole("article", { name: "Borrador de IA pedido por Violeta" });
      expect(card).toHaveTextContent("Borrador de IA — revisar antes de usar");
      expect(card).toHaveTextContent("Pedido por Violeta");
      expect(card).toHaveTextContent("[PENDIENTE: clics]");
      await userEvent.click(screen.getByRole("button", { name: "Copiar borrador" }));
      expect(writeText).toHaveBeenCalledWith(aiDraft.text);
      expect(mocks.update).not.toHaveBeenCalled();
    });

    it("shows the error and keeps the button available after a failure", async () => {
      mocks.get.mockResolvedValue(occurrence);
      mocks.draft.mockRejectedValue(new Error("boom"));
      setup({ taskId: 9 });
      await userEvent.click(await screen.findByRole("button", { name: "Generar borrador" }));
      await waitFor(() => expect(mocks.toastError).toHaveBeenCalled());
      expect(screen.getByRole("button", { name: "Generar borrador" })).toBeEnabled();
    });

    it("hides the button when the procedure has no written steps", async () => {
      mocks.get.mockResolvedValue({ ...occurrence, procedure_text: null, procedure_url: "https://docs.example.test/proc" });
      setup({ taskId: 9 });
      await screen.findByDisplayValue("Auditar");
      expect(screen.queryByRole("button", { name: "Generar borrador" })).not.toBeInTheDocument();
    });

    it("hides the button for readers", async () => {
      mocks.canWrite = false;
      mocks.get.mockResolvedValue(occurrence);
      setup({ taskId: 9 });
      expect(await screen.findByText(/1\. Exportar/)).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Generar borrador" })).not.toBeInTheDocument();
    });
  });

  it("comenta mencionando a alguien y le pasa su id al servidor", async () => {
    mocks.createComment.mockResolvedValue({ id: 1 });
    setup({ taskId: 9 });
    await userEvent.click(await screen.findByText(/Checklist, comentarios/));
    const input = await screen.findByRole("combobox", { name: "Nuevo comentario" });
    await userEvent.type(input, "Revisa @Na");
    await userEvent.keyboard("{Enter}");
    await userEvent.type(input, "por favor{Enter}");
    await waitFor(() => expect(mocks.createComment).toHaveBeenCalledWith(9, "Revisa @Nacho por favor", [5]));
    expect(mocks.update).not.toHaveBeenCalled();
  });

  it("pasa a la tarea anterior o siguiente con los botones y con ↑/↓ fuera de los campos", async () => {
    const onNavigate = vi.fn();
    setup({ taskId: 9, navigation: { position: 1, total: 3, onNavigate } });
    expect(await screen.findByDisplayValue("Auditar")).toBeInTheDocument();
    expect(screen.getByText("1 de 3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tarea anterior" })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: "Tarea siguiente" }));
    expect(onNavigate).toHaveBeenLastCalledWith(1);

    // Escribiendo en un campo, las flechas son del campo.
    screen.getByLabelText("Título").focus();
    await userEvent.keyboard("{ArrowDown}");
    expect(onNavigate).toHaveBeenCalledTimes(1);

    screen.getByRole("button", { name: "Tarea siguiente" }).focus();
    await userEvent.keyboard("{ArrowDown}");
    expect(onNavigate).toHaveBeenCalledTimes(2);
    // En la primera no hay anterior.
    await userEvent.keyboard("{ArrowUp}");
    expect(onNavigate).toHaveBeenCalledTimes(2);
  });

  it("pregunta antes de pasar a otra tarea con cambios sin guardar", async () => {
    const onNavigate = vi.fn();
    setup({ taskId: 9, navigation: { position: 2, total: 3, onNavigate } });
    await userEvent.type(await screen.findByDisplayValue("Auditar"), " web");
    await userEvent.click(screen.getByRole("button", { name: "Tarea anterior" }));
    expect(onNavigate).not.toHaveBeenCalled();
    expect(screen.getByText("¿Descartar los cambios?")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Descartar cambios" }));
    expect(onNavigate).toHaveBeenCalledWith(-1);
  });
});
