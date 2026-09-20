import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TaskPanel } from "./task-panel";
import { clientKeys } from "@/lib/query-keys";

const mocks = vi.hoisted(() => ({
  canWrite: true,
  canReadTime: true,
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
  getProject: vi.fn(),
  updateChecklist: vi.fn(),
  deleteChecklist: vi.fn(),
  deleteAttachment: vi.fn(),
  deleteComment: vi.fn(),
}));
vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({
    hasPermission: (_module: string, write?: boolean) =>
      _module === "timesheet" ? mocks.canReadTime : !write || mocks.canWrite,
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
    listAll: () =>
      Promise.resolve([
        { id: 7, name: "SEO archivado", client_id: 4, status: "completed" },
        { id: 8, name: "SEO nuevo", client_id: 4, status: "active" },
      ]),
    get: mocks.getProject,
  },
  usersApi: {
    listAll: () => Promise.resolve([{ id: 2, full_name: "Violeta" }]),
  },
  categoriesApi: { list: () => Promise.resolve([]) },
  tasksApi: {
    get: mocks.get,
    listAll: mocks.listTasks,
    create: mocks.create,
    update: mocks.update,
    restore: mocks.restore,
    recurrencePreview: mocks.recurrencePreview,
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
  unit_cost: null,
  invoiced_at: null,
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
  mocks.canReadTime = true;
    mocks.get.mockResolvedValue(task);
    mocks.checklist.mockResolvedValue([]);
    mocks.attachments.mockResolvedValue([]);
    mocks.comments.mockResolvedValue([]);
    mocks.listTasks.mockResolvedValue([
      { ...task, id: 11, title: "Preparar datos" },
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
    await userEvent.click(screen.getByText("Seguimiento"));
    expect(screen.getByLabelText("Esperando a")).toHaveValue("Aprobación");
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
    await userEvent.click(screen.getByText("Dependencias y recurrencia"));
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
    await userEvent.click(screen.getByText("Dependencias y recurrencia"));
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
    await userEvent.click(screen.getByText("Dependencias y recurrencia"));
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
    await userEvent.click(screen.getByText("Dependencias y recurrencia"));
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
    await userEvent.click(screen.getByText("Dependencias y recurrencia"));
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
    await userEvent.click(screen.getByText("Dependencias y recurrencia"));
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
    await userEvent.click(screen.getByText("Dependencias y recurrencia"));
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
    await userEvent.click(screen.getByText("Dependencias y recurrencia"));
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
});
