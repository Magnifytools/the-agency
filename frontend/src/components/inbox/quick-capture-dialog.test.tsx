import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { QuickCaptureDialog } from "./quick-capture-dialog";

const mocks = vi.hoisted(() => ({
  createCommand: vi.fn(),
  resolveCommand: vi.fn(),
  executeCommand: vi.fn(),
  queryCommand: vi.fn(),
  listCommands: vi.fn(),
  getCommand: vi.fn(),
  undo: vi.fn(),
  createInbox: vi.fn(),
  userId: 7,
  canReadTasks: true,
  canWriteTasks: true,
  canWriteProjects: true,
  canWriteTime: true,
  canReadClients: true,
  canReadProjects: true,
}));
vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ user: { id: mocks.userId }, hasPermission: (module: string, write?: boolean) => ({
    tasks: write ? mocks.canWriteTasks : mocks.canReadTasks,
    projects: write ? mocks.canWriteProjects : mocks.canReadProjects,
    timesheet: write ? mocks.canWriteTime : true,
    clients: mocks.canReadClients,
  })[module] ?? true }),
}));
vi.mock("@/lib/api", () => ({
  commandsApi: {
    create: mocks.createCommand,
    resolve: mocks.resolveCommand,
    execute: mocks.executeCommand,
    query: mocks.queryCommand,
    list: mocks.listCommands,
    get: mocks.getCommand,
  },
  changesApi: { undo: mocks.undo },
  inboxApi: { create: mocks.createInbox },
  clientsApi: { listAll: vi.fn().mockResolvedValue([]) },
  projectsApi: { listAll: vi.fn().mockResolvedValue([]) },
}));

const baseReceipt = {
  id: "receipt-1",
  request_key: "request-key-123456",
  raw_text: "",
  channel: "app",
  context: null,
  intent: { kind: "complete_task" },
  prompt: null,
  error: null,
  revision: 1,
  created_at: "2026-09-18T08:00:00Z",
  updated_at: "2026-09-18T08:00:00Z",
};
function show() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <QuickCaptureDialog open onOpenChange={vi.fn()} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

describe("command entry", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.userId = 7;
    mocks.canReadTasks = true;
    mocks.canWriteTasks = true;
    mocks.canWriteProjects = true;
    mocks.canWriteTime = true;
    mocks.canReadClients = true;
    mocks.canReadProjects = true;
    mocks.listCommands.mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 5,
      has_more: false,
    });
    mocks.getCommand.mockReset();
  });

  it("shows a linked receipt and allows undo", async () => {
    mocks.createCommand.mockResolvedValue({
      ...baseReceipt,
      status: "executed",
      change_log_id: 9,
      result: {
        message: "Tarea completada",
        entities: [
          { type: "task", id: 4, label: "Revisar portada", client_id: 2 },
        ],
        applied: {
          project_id: 31,
          assigned_to: 8,
          scheduled_date: "2026-09-25",
          minutes: 45,
        },
        applied_labels: {
          project_id: "Web nueva",
          assigned_to: "María",
        },
        undo_available: true,
      },
    });
    mocks.undo.mockResolvedValue({
      id: 9,
      label: "Tarea completada",
      warnings: [],
    });
    show();
    await userEvent.type(
      screen.getByLabelText("Petición"),
      "Completa la tarea Revisar portada",
    );
    await userEvent.click(screen.getByRole("button", { name: "Hacer" }));
    expect(await screen.findByText("Tarea completada")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Revisar portada" }),
    ).toHaveAttribute("href", "/tasks?id=4");
    expect(screen.getByText("Web nueva")).toBeInTheDocument();
    expect(screen.getByText("María")).toBeInTheDocument();
    expect(screen.getByText("25 de septiembre de 2026")).toBeInTheDocument();
    expect(screen.getByText("45 min")).toBeInTheDocument();
    expect(screen.queryByText("31")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Deshacer" }));
    await waitFor(() => expect(mocks.undo).toHaveBeenCalledWith(9));
    expect(screen.getByRole("button", { name: "Deshecho" })).toBeDisabled();
  });

  it("offers a reviewable commercial handoff without claiming creation or undo", async () => {
    mocks.createCommand.mockResolvedValue({
      ...baseReceipt,
      raw_text: "Crea SEO con tarifa 500 EUR",
      status: "executed",
      change_log_id: null,
      intent: { kind: "project_commercial_handoff" },
      result: {
        kind: "derivation",
        message: "Esta orden contiene condiciones comerciales. Revísalas en el formulario de proyecto antes de crear.",
        entities: [],
        undo_available: false,
        action: { kind: "open_project_form", href: "/projects?new=1" },
      },
    });
    show();
    await userEvent.type(screen.getByLabelText("Petición"), "Crea SEO con tarifa 500 EUR");
    await userEvent.click(screen.getByRole("button", { name: "Hacer" }));
    expect(await screen.findByRole("link", { name: "Revisar proyecto" })).toHaveAttribute("href", "/projects?new=1");
    expect(screen.getByText("Crea SEO con tarifa 500 EUR")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Deshacer" })).not.toBeInTheDocument();
    expect(screen.queryByText(/proyecto creado/i)).not.toBeInTheDocument();
  });

  it("resolves ambiguity with the selected server choice", async () => {
    mocks.createCommand.mockResolvedValue({
      ...baseReceipt,
      status: "needs_input",
      change_log_id: null,
      result: null,
      prompt: {
        questions: [
          {
            field: "task_id",
            label: "¿Cuál Auditoría?",
            kind: "choice",
            choices: [
              { id: "task:4", label: "Auditoría web" },
              { id: "task:8", label: "Auditoría SEO" },
            ],
          },
        ],
      },
    });
    mocks.resolveCommand.mockResolvedValue({
      ...baseReceipt,
      revision: 2,
      status: "executed",
      change_log_id: 10,
      result: {
        message: "Tarea completada",
        entities: [{ type: "task", id: 8, label: "Auditoría SEO" }],
        undo_available: true,
      },
    });
    show();
    await userEvent.type(
      screen.getByLabelText("Petición"),
      "Completa la tarea Auditoría",
    );
    await userEvent.click(screen.getByRole("button", { name: "Hacer" }));
    await userEvent.click(await screen.findByLabelText("Auditoría SEO"));
    await userEvent.click(screen.getByRole("button", { name: "Continuar" }));
    await waitFor(() =>
      expect(mocks.resolveCommand).toHaveBeenCalledWith(
        "receipt-1",
        expect.objectContaining({
          revision: 1,
          answers: [{ field: "task_id", choice_id: "task:8" }],
        }),
      ),
    );
  });

  it("returns the semantic fields for date, literal title and user choices", async () => {
    mocks.createCommand.mockResolvedValue({
      ...baseReceipt,
      status: "needs_input",
      change_log_id: null,
      result: null,
      prompt: {
        questions: [
          { field: "scheduled_date", label: "¿Qué viernes?", kind: "choice", choices: [{ id: "date:2026-09-25", label: "25 de septiembre" }] },
          { field: "literal_title", label: "¿Conservar el título?", kind: "choice", choices: [{ id: "literal_title:confirm", label: "Sí, conservarlo" }] },
          { field: "assigned_to", label: "¿Quién?", kind: "choice", choices: [{ id: "user:8", label: "María" }] },
        ],
      },
    });
    mocks.resolveCommand.mockResolvedValue({
      ...baseReceipt,
      revision: 2,
      status: "executed",
      change_log_id: null,
      result: { message: "Tarea creada", entities: [], undo_available: false },
    });
    show();
    await userEvent.type(screen.getByLabelText("Petición"), "Crea la tarea");
    await userEvent.click(screen.getByRole("button", { name: "Hacer" }));
    await userEvent.click(await screen.findByLabelText("25 de septiembre"));
    await userEvent.click(screen.getByLabelText("Sí, conservarlo"));
    await userEvent.click(screen.getByLabelText("María"));
    await userEvent.click(screen.getByRole("button", { name: "Continuar" }));
    await waitFor(() => expect(mocks.resolveCommand).toHaveBeenCalledWith(
      "receipt-1",
      expect.objectContaining({ answers: [
        { field: "scheduled_date", choice_id: "date:2026-09-25" },
        { field: "literal_title", choice_id: "literal_title:confirm" },
        { field: "assigned_to", choice_id: "user:8" },
      ] }),
    ));
  });

  it("keeps the request key across a network retry", async () => {
    mocks.createCommand
      .mockRejectedValueOnce(new Error("timeout"))
      .mockResolvedValueOnce({
        ...baseReceipt,
        status: "failed",
        change_log_id: null,
        result: null,
        error: { code: "unsupported", detail: "No reconozco esa orden" },
      });
    show();
    await userEvent.type(screen.getByLabelText("Petición"), "Haz algo");
    await userEvent.click(screen.getByRole("button", { name: "Hacer" }));
    await waitFor(() => expect(mocks.createCommand).toHaveBeenCalledTimes(1));
    expect(screen.getByLabelText("Petición")).toBeDisabled();
    await userEvent.click(
      screen.getByRole("button", { name: "Reintentar la misma petición" }),
    );
    await waitFor(() => expect(mocks.createCommand).toHaveBeenCalledTimes(2));
    expect(mocks.createCommand.mock.calls[1][0].request_key).toBe(
      mocks.createCommand.mock.calls[0][0].request_key,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "No reconozco esa orden",
    );
  });

  it("recovers an uncertain manual retry with its new key", async () => {
    mocks.createCommand
      .mockResolvedValueOnce({
        ...baseReceipt,
        status: "failed",
        change_log_id: null,
        result: null,
        error: { code: "forbidden", detail: "Sin permiso" },
      })
      .mockRejectedValueOnce(new Error("timeout"))
      .mockResolvedValueOnce({
        ...baseReceipt,
        id: "retried-receipt",
        status: "executed",
        change_log_id: 12,
        error: null,
        result: { message: "Tarea creada", entities: [], undo_available: true },
      });
    show();
    await userEvent.type(screen.getByLabelText("Petición"), "Crea tarea Recuperada");
    await userEvent.click(screen.getByRole("button", { name: "Hacer" }));
    await screen.findByText("Sin permiso");
    await userEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    await waitFor(() => expect(mocks.createCommand).toHaveBeenCalledTimes(2));
    const retryKey = mocks.createCommand.mock.calls[1][0].request_key;
    expect(retryKey).not.toBe(mocks.createCommand.mock.calls[0][0].request_key);
    expect(await screen.findByRole("button", { name: "Comprobar el reintento" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Editar petición" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Comprobar el reintento" }));
    await waitFor(() => expect(mocks.createCommand).toHaveBeenCalledTimes(3));
    expect(mocks.createCommand.mock.calls[2][0].request_key).toBe(retryKey);
    expect(mocks.createCommand.mock.calls[2][0].text).toBe("Crea tarea Recuperada");
    expect(await screen.findByText("Tarea creada")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Deshacer" })).toBeInTheDocument();
  });

  it("starts another new request after a durable retry also fails", async () => {
    mocks.createCommand
      .mockResolvedValueOnce({
        ...baseReceipt,
        status: "failed",
        change_log_id: null,
        result: null,
        error: { code: "forbidden", detail: "Sin permiso" },
      })
      .mockResolvedValueOnce({
        ...baseReceipt,
        id: "second-failure",
        status: "failed",
        change_log_id: null,
        result: null,
        error: { code: "forbidden", detail: "Aún sin permiso" },
      })
      .mockResolvedValueOnce({
        ...baseReceipt,
        id: "third-attempt",
        status: "executed",
        change_log_id: 13,
        result: { message: "Tarea creada", entities: [], undo_available: true },
      });
    show();
    await userEvent.type(screen.getByLabelText("Petición"), "Crea tarea Recuperada");
    await userEvent.click(screen.getByRole("button", { name: "Hacer" }));
    await screen.findByText("Sin permiso");
    await userEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    await screen.findByText("Aún sin permiso");
    await userEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    await waitFor(() => expect(mocks.createCommand).toHaveBeenCalledTimes(3));
    const keys = mocks.createCommand.mock.calls.map(([request]) => request.request_key);
    expect(new Set(keys).size).toBe(3);
    expect(await screen.findByText("Tarea creada")).toBeInTheDocument();
  });

  it("rehydrates a recent receipt after reopening", async () => {
    mocks.listCommands.mockResolvedValue({
      items: [
        {
          ...baseReceipt,
          status: "executed",
          change_log_id: null,
          result: {
            message: "Consulta recuperada",
            entities: [],
            undo_available: false,
          },
        },
      ],
      total: 1,
      page: 1,
      page_size: 5,
      has_more: false,
    });
    show();
    await userEvent.click(await screen.findByText("Peticiones recientes"));
    await userEvent.click(
      screen.getByRole("button", { name: /Consulta recuperada/ }),
    );
    expect(await screen.findByText("Consulta recuperada")).toBeInTheDocument();
  });

  it("retries a terminal failure as a new app request and keeps editing separate", async () => {
    const historical = {
      ...baseReceipt,
      request_key: "historical-request-key",
      raw_text: "Orden histórica exacta",
      channel: "extension" as const,
      context: { url: "https://example.test/tarea", title: "Contexto original" },
      status: "failed",
      change_log_id: null,
      result: null,
      error: { code: "forbidden", detail: "Sin permiso" },
    };
    mocks.listCommands.mockResolvedValue({ items: [historical], total: 1, page: 1, page_size: 5, has_more: false });
    mocks.createCommand.mockResolvedValue({
      ...historical,
      id: "successful-retry",
      status: "executed",
      request_key: "successful-retry-key",
      channel: "app",
      context: null,
      change_log_id: 9,
      error: null,
      result: { message: "Tarea creada", entities: [], undo_available: true },
    });
    show();
    await userEvent.type(screen.getByLabelText("Petición"), "Borrador distinto");
    await userEvent.click(await screen.findByRole("button", { name: /Orden histórica exacta/ }));
    await userEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    await waitFor(() => expect(mocks.createCommand).toHaveBeenCalledWith(expect.objectContaining({
      text: "Orden histórica exacta",
      channel: "app",
    })));
    expect(mocks.createCommand.mock.calls[0][0].request_key).not.toBe("historical-request-key");
    expect(mocks.createCommand.mock.calls[0][0].context).toBeUndefined();
    expect(await screen.findByText("Tarea creada")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Deshacer" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Hacer otra cosa" }));
    await userEvent.click(screen.getByRole("button", { name: /Orden histórica exacta/ }));
    await userEvent.click(screen.getByRole("button", { name: "Editar petición" }));
    expect(screen.getByLabelText("Petición")).toHaveValue("Orden histórica exacta");
    await userEvent.click(screen.getByRole("button", { name: "Hacer" }));
    await waitFor(() => expect(mocks.createCommand).toHaveBeenCalledTimes(2));
    expect(mocks.createCommand.mock.calls[1][0]).toEqual(expect.objectContaining({
      text: "Orden histórica exacta",
      channel: "app",
    }));
    expect(mocks.createCommand.mock.calls[1][0].request_key).not.toBe("historical-request-key");
    expect(mocks.createCommand.mock.calls[1][0].context).toBeUndefined();
  });

  it("freezes an uncertain resolution payload and recovers the durable receipt on conflict", async () => {
    const pending = {
      ...baseReceipt,
      status: "needs_input",
      result: null,
      change_log_id: null,
      prompt: { questions: [{ field: "scheduled_date", label: "¿Qué fecha?", kind: "choice", choices: [
        { id: "date:2026-09-18", label: "18 de septiembre" },
        { id: "date:2026-09-25", label: "25 de septiembre" },
      ] }] },
    };
    const durable = { ...baseReceipt, revision: 2, status: "executed", result: { message: "Aplicada una vez", entities: [], undo_available: false }, change_log_id: null };
    mocks.createCommand.mockResolvedValue(pending);
    mocks.resolveCommand.mockRejectedValueOnce(new Error("timeout")).mockRejectedValueOnce({ response: { status: 409 }, message: "conflict" });
    mocks.getCommand.mockResolvedValue(durable);
    show();
    await userEvent.type(screen.getByLabelText("Petición"), "Reprograma tarea");
    await userEvent.click(screen.getByRole("button", { name: "Hacer" }));
    await userEvent.click(await screen.findByLabelText("18 de septiembre"));
    await userEvent.click(screen.getByRole("button", { name: "Continuar" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Reintentar la misma respuesta" })).toBeInTheDocument());
    expect(screen.getByLabelText("25 de septiembre")).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Reintentar la misma respuesta" }));
    await waitFor(() => expect(mocks.getCommand).toHaveBeenCalledWith("receipt-1"));
    expect(await screen.findByText("Aplicada una vez")).toBeInTheDocument();
    expect(mocks.resolveCommand.mock.calls[1][1].answers).toEqual([{ field: "scheduled_date", choice_id: "date:2026-09-18" }]);
    expect(mocks.resolveCommand.mock.calls[1][1].request_key).toBe(mocks.resolveCommand.mock.calls[0][1].request_key);
  });

  it("keeps the explicit capture form available", async () => {
    mocks.createInbox.mockResolvedValue({ id: 3 });
    show();
    await userEvent.click(
      screen.getByRole("tab", { name: "Guardar para aclarar" }),
    );
    expect(screen.getByLabelText("Cliente").parentElement).toHaveClass("sm:grid-cols-2");
    expect(screen.getByLabelText("Proyecto").parentElement).toHaveClass("sm:grid-cols-2");
    await userEvent.type(
      screen.getByLabelText("Contenido para aclarar"),
      "Idea pendiente de ordenar",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Guardar para aclarar" }),
    );
    await waitFor(() =>
      expect(mocks.createInbox).toHaveBeenCalledWith(
        expect.objectContaining({
          raw_text: "Idea pendiente de ordenar",
          source: "quick_capture",
        }),
      ),
    );
  });

  it("starts a task reader in capture, while retaining authorized work queries", async () => {
    mocks.canReadTasks = true;
    mocks.canWriteTasks = false;
    mocks.canWriteProjects = false;
    mocks.canWriteTime = false;
    mocks.createInbox.mockResolvedValue({ id: 3 });
    show();
    expect(screen.getByRole("tab", { name: "Guardar para aclarar" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByLabelText("Contenido para aclarar")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Pedir una acción" }));
    expect(screen.getByLabelText("Petición")).toHaveAttribute("placeholder", "Ej. Consulta prioridades o consulta bloqueos");
    expect(screen.queryByText('Completa la tarea "Preparar propuesta"')).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Petición"), "Completa la tarea Prohibida");
    expect(screen.getByRole("button", { name: "Consultar" })).toBeDisabled();
    await userEvent.clear(screen.getByLabelText("Petición"));
    await userEvent.type(screen.getByLabelText("Petición"), "Consulta prioridades");
    expect(screen.getByRole("button", { name: "Consultar" })).toBeEnabled();
    await userEvent.clear(screen.getByLabelText("Petición"));
    await userEvent.type(screen.getByLabelText("Petición"), "Consulta decisiones pendientes");
    expect(screen.getByRole("button", { name: "Consultar" })).toBeEnabled();
  });

  it("clears a write command and returns to capture when writing is revoked", async () => {
    const view = show();
    await userEvent.type(screen.getByLabelText("Petición"), "Completa la tarea Prohibida");
    mocks.canWriteTasks = false;
    mocks.canWriteProjects = false;
    mocks.canWriteTime = false;
    view.rerender(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter><QuickCaptureDialog open onOpenChange={vi.fn()} /></MemoryRouter>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getByLabelText("Contenido para aclarar")).toBeInTheDocument());
    expect(screen.queryByLabelText("Petición")).not.toBeInTheDocument();
  });

  it("describes project-only commands without promising task changes", () => {
    mocks.canReadTasks = true;
    mocks.canWriteTasks = false;
    mocks.canWriteProjects = true;
    mocks.canWriteTime = false;
    show();
    expect(screen.getByLabelText("Petición")).toHaveAttribute("placeholder", 'Ej. Crea proyecto "Web nueva" para cliente "Nombre del cliente"');
    expect(screen.getByText("Puedes crear proyectos. Las tareas y el tiempo requieren sus permisos de escritura.")).toBeInTheDocument();
  });

  it("keeps personal capture available without tasks permission", async () => {
    mocks.canReadTasks = false;
    mocks.canWriteTasks = false;
    mocks.canWriteProjects = false;
    mocks.canWriteTime = false;
    mocks.createInbox.mockResolvedValue({ id: 3 });
    show();
    await userEvent.click(screen.getByRole("tab", { name: "Guardar para aclarar" }));
    await userEvent.type(screen.getByLabelText("Contenido para aclarar"), "Nota personal");
    await userEvent.click(screen.getByRole("button", { name: "Guardar para aclarar" }));
    await waitFor(() => expect(mocks.createInbox).toHaveBeenCalledWith(expect.objectContaining({ raw_text: "Nota personal", source: "quick_capture" })));
  });

  it("keeps the decisions query available without task access", async () => {
    mocks.canReadTasks = false;
    mocks.canWriteTasks = false;
    mocks.canWriteProjects = false;
    mocks.canWriteTime = false;
    show();
    await userEvent.click(screen.getByRole("tab", { name: "Pedir una acción" }));
    await userEvent.type(screen.getByLabelText("Petición"), "Consulta decisiones pendientes");
    expect(screen.getByRole("button", { name: "Consultar" })).toBeEnabled();
    await userEvent.clear(screen.getByLabelText("Petición"));
    await userEvent.type(screen.getByLabelText("Petición"), "Crea tarea Prohibida");
    expect(screen.getByRole("button", { name: "Consultar" })).toBeDisabled();
  });

  it.each([
    { canReadClients: false, canReadProjects: true, hidden: "Cliente", visible: "Proyecto" },
    { canReadClients: true, canReadProjects: false, hidden: "Proyecto", visible: "Cliente" },
  ])("does not query or offer unavailable context", async ({ canReadClients, canReadProjects, hidden, visible }) => {
    mocks.canReadClients = canReadClients;
    mocks.canReadProjects = canReadProjects;
    mocks.createInbox.mockResolvedValue({ id: 3 });
    const { clientsApi, projectsApi } = await import("@/lib/api");
    show();
    await userEvent.click(screen.getByRole("tab", { name: "Guardar para aclarar" }));

    expect(await screen.findByLabelText(visible)).toBeInTheDocument();
    expect(screen.queryByLabelText(hidden)).not.toBeInTheDocument();
    expect(screen.getByLabelText(visible).parentElement).toHaveClass(
      canReadClients && canReadProjects ? "sm:grid-cols-2" : "sm:grid-cols-1",
    );
    expect(clientsApi.listAll).toHaveBeenCalledTimes(canReadClients ? 1 : 0);
    expect(projectsApi.listAll).toHaveBeenCalledTimes(canReadProjects ? 1 : 0);
    await userEvent.type(screen.getByLabelText("Contenido para aclarar"), "Nota personal");
    await userEvent.click(screen.getByRole("button", { name: "Guardar para aclarar" }));
    await waitFor(() => expect(mocks.createInbox).toHaveBeenCalled());
  });

  it("removes inaccessible context after permissions are revoked while capture is open", async () => {
    mocks.createInbox.mockResolvedValue({ id: 3 });
    const { clientsApi, projectsApi } = await import("@/lib/api");
    vi.mocked(clientsApi.listAll).mockResolvedValue([{ id: 12, name: "Cliente visible" }] as never);
    vi.mocked(projectsApi.listAll).mockResolvedValue([{ id: 31, name: "Proyecto visible", client_id: 12 }] as never);
    const view = show();
    await userEvent.click(screen.getByRole("tab", { name: "Guardar para aclarar" }));
    await screen.findByRole("option", { name: "Cliente visible" });
    await userEvent.selectOptions(screen.getByLabelText("Cliente"), "12");
    await userEvent.selectOptions(screen.getByLabelText("Proyecto"), "31");

    mocks.canReadClients = false;
    mocks.canReadProjects = false;
    view.rerender(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter><QuickCaptureDialog open onOpenChange={vi.fn()} /></MemoryRouter>
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(screen.queryByLabelText("Cliente")).not.toBeInTheDocument();
      expect(screen.queryByLabelText("Proyecto")).not.toBeInTheDocument();
    });
    expect(clientsApi.listAll).toHaveBeenCalledTimes(1);
    expect(projectsApi.listAll).toHaveBeenCalledTimes(1);
    await userEvent.type(screen.getByLabelText("Contenido para aclarar"), "Nota personal");
    await userEvent.click(screen.getByRole("button", { name: "Guardar para aclarar" }));
    await waitFor(() => expect(mocks.createInbox).toHaveBeenCalled());
    expect(mocks.createInbox.mock.calls.at(-1)?.[0]).not.toHaveProperty("client_id");
    expect(mocks.createInbox.mock.calls.at(-1)?.[0]).not.toHaveProperty("project_id");
  });

  it("clears selected context when the active identity changes", async () => {
    mocks.createInbox.mockResolvedValue({ id: 3 });
    const { clientsApi, projectsApi } = await import("@/lib/api");
    vi.mocked(clientsApi.listAll).mockResolvedValue([{ id: 12, name: "Cliente de la sesión" }] as never);
    vi.mocked(projectsApi.listAll).mockResolvedValue([{ id: 31, name: "Proyecto de la sesión", client_id: 12 }] as never);
    const view = show();
    await userEvent.click(screen.getByRole("tab", { name: "Guardar para aclarar" }));
    await screen.findByRole("option", { name: "Cliente de la sesión" });
    await userEvent.selectOptions(screen.getByLabelText("Cliente"), "12");
    await userEvent.selectOptions(screen.getByLabelText("Proyecto"), "31");

    mocks.userId = 8;
    view.rerender(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter><QuickCaptureDialog open onOpenChange={vi.fn()} /></MemoryRouter>
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(screen.getByLabelText("Cliente")).toHaveValue("");
      expect(screen.getByLabelText("Proyecto")).toHaveValue("");
    });
    expect(clientsApi.listAll).toHaveBeenCalledTimes(2);
    expect(projectsApi.listAll).toHaveBeenCalledTimes(2);
  });

  it("loads linked query results without inferring the total", async () => {
    mocks.createCommand.mockResolvedValue({
      ...baseReceipt,
      status: "executed",
      change_log_id: null,
      result: {
        message: "30 tareas",
        entities: [],
        query: {
          kind: "blockers",
          items: [{ type: "task", id: 1, label: "Primera" }],
          total: 30,
          page: 1,
          page_size: 25,
          has_more: true,
        },
        undo_available: false,
      },
    });
    mocks.queryCommand.mockResolvedValue({
      kind: "blockers",
      items: [{ type: "task", id: 2, label: "Segunda" }],
      total: 30,
      page: 2,
      page_size: 25,
      has_more: false,
    });
    show();
    await userEvent.type(
      screen.getByLabelText("Petición"),
      "Consulta bloqueos",
    );
    await userEvent.click(screen.getByRole("button", { name: "Hacer" }));
    await userEvent.click(
      await screen.findByRole("button", { name: "Cargar más" }),
    );
    expect(
      await screen.findByRole("link", { name: "Segunda" }),
    ).toBeInTheDocument();
    expect(mocks.queryCommand).toHaveBeenCalledWith("receipt-1", 2, 25);
  });
  it("does not append an old query page after starting a new command", async () => {
    const oldPage = deferred<{ kind: string; items: Array<{ type: string; id: number; label: string }>; total: number; page: number; page_size: number; has_more: boolean }>();
    mocks.createCommand
      .mockResolvedValueOnce({
        ...baseReceipt,
        status: "executed",
        result: { message: "Consulta A", entities: [], undo_available: false, query: { kind: "blockers", items: [{ type: "task", id: 1, label: "A" }], total: 2, page: 1, page_size: 25, has_more: true } },
      })
      .mockResolvedValueOnce({
        ...baseReceipt,
        id: "receipt-2",
        status: "executed",
        result: { message: "Consulta B", entities: [], undo_available: false },
      });
    mocks.queryCommand.mockReturnValueOnce(oldPage.promise);
    show();
    await userEvent.type(screen.getByLabelText("Petición"), "Consulta A");
    await userEvent.click(screen.getByRole("button", { name: "Hacer" }));
    await userEvent.click(await screen.findByRole("button", { name: "Cargar más" }));
    await userEvent.click(screen.getByRole("button", { name: "Hacer otra cosa" }));
    await userEvent.type(screen.getByLabelText("Petición"), "Consulta B");
    await userEvent.click(screen.getByRole("button", { name: "Hacer" }));
    expect(await screen.findByText("Consulta B")).toBeInTheDocument();
    oldPage.resolve({ kind: "blockers", items: [{ type: "task", id: 2, label: "Página antigua" }], total: 2, page: 2, page_size: 25, has_more: false });
    await waitFor(() => expect(screen.queryByText("Página antigua")).not.toBeInTheDocument());
    expect(screen.getByText("Consulta B")).toBeInTheDocument();
  });

  it("ignores a late execution after the command is replaced", async () => {
    const oldExecution = deferred<typeof baseReceipt & { status: string; result: { message: string; entities: never[]; undo_available: boolean }; change_log_id: null }>();
    mocks.createCommand
      .mockResolvedValueOnce({ ...baseReceipt, status: "needs_review", change_log_id: null, result: { message: "Revisar A", entities: [], undo_available: false } })
      .mockResolvedValueOnce({ ...baseReceipt, id: "receipt-2", status: "executed", change_log_id: null, result: { message: "Comando B", entities: [], undo_available: false } });
    mocks.executeCommand.mockReturnValueOnce(oldExecution.promise);
    show();
    await userEvent.type(screen.getByLabelText("Petición"), "A");
    await userEvent.click(screen.getByRole("button", { name: "Hacer" }));
    await userEvent.click(await screen.findByRole("button", { name: "Crear proyecto y tarea" }));
    await userEvent.click(screen.getByRole("tab", { name: "Guardar para aclarar" }));
    await userEvent.click(screen.getByRole("tab", { name: "Pedir una acción" }));
    await userEvent.type(screen.getByLabelText("Petición"), "B");
    await userEvent.click(screen.getByRole("button", { name: "Hacer" }));
    expect(await screen.findByText("Comando B")).toBeInTheDocument();
    expect(mocks.createCommand.mock.calls[1][0].request_key).not.toBe(
      mocks.createCommand.mock.calls[0][0].request_key,
    );
    oldExecution.resolve({ ...baseReceipt, status: "executed", change_log_id: null, result: { message: "Resultado antiguo", entities: [], undo_available: false } });
    await waitFor(() => expect(screen.queryByText("Resultado antiguo")).not.toBeInTheDocument());
    expect(screen.getByText("Comando B")).toBeInTheDocument();
  });
  it("reviews both entities and keeps the execute key after an uncertain response", async () => {
    const review = { ...baseReceipt, status: "needs_review", change_log_id: null,
      intent: { kind: "create_project_with_task" },
      result: { message: "Revisa el proyecto y su primera tarea", entities: [], undo_available: false,
        applied: { project_name: "Web nueva", client_id: 12, owner_id: null, target_date: null,
          task_title: "Preparar propuesta", assigned_to: 8, scheduled_date: "2026-09-25" },
        applied_labels: { client_id: "Cliente de prueba", assigned_to: "Nacho" } } };
    mocks.createCommand.mockResolvedValue(review);
    mocks.executeCommand.mockRejectedValueOnce(new Error("Timeout")).mockResolvedValueOnce({
      ...review, status: "executed", revision: 2, change_log_id: 4,
      result: { message: "Proyecto y tarea creados", entities: [{ type: "project", id: 42, label: "Web nueva" }, { type: "task", id: 43, label: "Preparar propuesta" }], undo_available: true },
    });
    show();
    await userEvent.type(screen.getByLabelText("Petición"), 'Crea proyecto "Web nueva" para cliente "Cliente de prueba" con primera tarea "Preparar propuesta"');
    await userEvent.click(screen.getByRole("button", { name: "Hacer" }));
    expect(await screen.findByText("Preparar propuesta")).toBeInTheDocument();
    expect(screen.getByText("Cliente de prueba")).toBeInTheDocument();
    expect(screen.getByText("Nacho")).toBeInTheDocument();
    expect(screen.getByText("25 de septiembre de 2026")).toBeInTheDocument();
    expect([...document.querySelectorAll("dt")].map((element) => element.textContent)).toEqual([
      "Nuevo proyecto",
      "Cliente",
      "Responsable del proyecto",
      "Fecha objetivo",
      "Primera tarea",
      "Responsable de la tarea",
      "Fecha planificada",
    ]);
    expect(mocks.executeCommand).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Deshacer" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Crear proyecto y tarea" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Crear proyecto y tarea" })).toBeEnabled());
    await userEvent.click(screen.getByRole("button", { name: "Crear proyecto y tarea" }));
    expect(await screen.findByText("Proyecto y tarea creados")).toBeInTheDocument();
    expect(mocks.executeCommand.mock.calls[0]).toEqual(mocks.executeCommand.mock.calls[1]);
    expect(screen.getByRole("link", { name: "Web nueva" })).toHaveAttribute("href", "/projects/42");
    expect(screen.getByRole("link", { name: "Preparar propuesta" })).toHaveAttribute("href", "/tasks?id=43");
  });

  it("recovers the current receipt when execution loses permission", async () => {
    mocks.createCommand.mockResolvedValue({ ...baseReceipt, status: "needs_review", result: { message: "Revisar", entities: [], undo_available: false } });
    mocks.executeCommand.mockRejectedValueOnce({ response: { status: 403 } });
    mocks.getCommand.mockResolvedValue({ ...baseReceipt, status: "failed", error: { code: "forbidden", detail: "Permiso retirado" }, result: null });
    show();
    await userEvent.type(screen.getByLabelText("Petición"), "Crear proyecto y tarea");
    await userEvent.click(screen.getByRole("button", { name: "Hacer" }));
    await userEvent.click(await screen.findByRole("button", { name: "Crear proyecto y tarea" }));
    expect(await screen.findByText("Permiso retirado")).toBeInTheDocument();
    expect(mocks.getCommand).toHaveBeenCalledWith("receipt-1");
    expect(screen.queryByRole("button", { name: "Crear proyecto y tarea" })).not.toBeInTheDocument();
  });

  it("links decisions to their actual source and explains deferred items", async () => {
    mocks.createCommand.mockResolvedValue({ ...baseReceipt, status: "executed", change_log_id: null,
      result: { message: "2 decisiones pendientes", entities: [], undo_available: false,
        query: { kind: "decisions", total: 2, page: 1, page_size: 25, has_more: false,
          items: [{ type: "incident", id: 9, label: "Proyecto sin siguiente paso", message: "Define la próxima acción", recipient_name: "Nacho", href: "/projects/21", revision: 2 },
            { type: "incident", id: 10, label: "Enlace no válido", href: "//external.invalid" }] } } });
    show();
    await userEvent.type(screen.getByLabelText("Petición"), "Consulta decisiones pendientes");
    await userEvent.click(screen.getByRole("button", { name: "Hacer" }));
    expect(await screen.findByRole("link", { name: /Proyecto sin siguiente paso/ })).toHaveAttribute("href", "/projects/21");
    expect(screen.getByText("Para Nacho")).toBeInTheDocument();
    expect(screen.getByText(/Los pospuestos quedan fuera/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Enlace no válido" })).toHaveAttribute("href", "/incidents");
    expect(screen.queryByRole("button", { name: "Deshacer" })).not.toBeInTheDocument();
  });

});
