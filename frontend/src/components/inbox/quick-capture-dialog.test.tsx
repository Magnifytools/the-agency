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
  canReadTasks: true,
}));
vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ user: { id: 7 }, hasPermission: (module: string) => module !== "tasks" || mocks.canReadTasks }),
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
    mocks.canReadTasks = true;
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

  it("rehydrates the exact historical payload before retrying or editing", async () => {
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
    mocks.createCommand.mockResolvedValue(historical);
    show();
    await userEvent.type(screen.getByLabelText("Petición"), "Borrador distinto");
    await userEvent.click(await screen.findByRole("button", { name: /Orden histórica exacta/ }));
    await userEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    await waitFor(() => expect(mocks.createCommand).toHaveBeenCalledWith(expect.objectContaining({
      request_key: "historical-request-key",
      text: "Orden histórica exacta",
      channel: "extension",
      context: { url: "https://example.test/tarea", title: "Contexto original" },
    })));
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

  it("keeps personal capture available without tasks permission", async () => {
    mocks.canReadTasks = false;
    mocks.createInbox.mockResolvedValue({ id: 3 });
    show();
    await userEvent.click(screen.getByRole("tab", { name: "Guardar para aclarar" }));
    await userEvent.type(screen.getByLabelText("Contenido para aclarar"), "Nota personal");
    await userEvent.click(screen.getByRole("button", { name: "Guardar para aclarar" }));
    await waitFor(() => expect(mocks.createInbox).toHaveBeenCalledWith(expect.objectContaining({ raw_text: "Nota personal", source: "quick_capture" })));
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
