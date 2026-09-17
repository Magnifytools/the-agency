import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TimeLogDialog } from "./time-log-dialog";

const mocks = vi.hoisted(() => ({
  canRead: true,
  canWrite: true,
  isAdmin: false,
  userId: 7,
  list: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  remove: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({
    user: { id: mocks.userId, role: mocks.isAdmin ? "admin" : "member" },
    isAdmin: mocks.isAdmin,
    hasPermission: (_module: string, write?: boolean) =>
      write ? mocks.canWrite : mocks.canRead,
  }),
}));
vi.mock("@/hooks/use-business-date", () => ({
  useBusinessDate: () => "2026-09-17",
}));
vi.mock("@/lib/api", () => ({
  timeEntriesApi: {
    list: mocks.list,
    create: mocks.create,
    update: mocks.update,
    delete: mocks.remove,
  },
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: mocks.toastError },
}));

const ownEntry = {
  id: 1,
  minutes: 30,
  started_at: null,
  date: "2026-09-16T00:00:00",
  notes: "Revisión",
  task_id: 9,
  user_id: 7,
  created_at: "",
  updated_at: "",
  task_title: "Auditoría",
  client_name: "Acme",
};

function setup() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <TimeLogDialog
        taskId={9}
        taskTitle="Auditoría"
        open
        onOpenChange={vi.fn()}
      />
    </QueryClientProvider>,
  );
}

describe("TimeLogDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.canRead = true;
    mocks.canWrite = true;
    mocks.isAdmin = false;
    mocks.userId = 7;
    mocks.list.mockResolvedValue([ownEntry]);
  });

  it("keeps history readable without exposing write actions", async () => {
    mocks.canWrite = false;
    setup();

    expect(await screen.findByText("Revisión")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Añadir manual" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Editar registro/ }),
    ).not.toBeInTheDocument();
  });

  it("only lets an owner or admin change an entry and confirms deletion", async () => {
    mocks.list.mockResolvedValue([
      ownEntry,
      { ...ownEntry, id: 2, user_id: 8, notes: "Ajena" },
    ]);
    mocks.remove.mockResolvedValue(undefined);
    const confirm = vi
      .spyOn(window, "confirm")
      .mockReturnValueOnce(false)
      .mockReturnValueOnce(true);
    setup();

    const deletes = await screen.findAllByRole("button", {
      name: /Eliminar registro/,
    });
    expect(deletes).toHaveLength(1);
    expect(
      screen.getAllByRole("button", { name: /Editar registro/ }),
    ).toHaveLength(1);
    await userEvent.click(deletes[0]);
    expect(mocks.remove).not.toHaveBeenCalled();
    await userEvent.click(deletes[0]);
    expect(mocks.remove).toHaveBeenCalledWith(1);
    expect(confirm).toHaveBeenCalledTimes(2);
    confirm.mockRestore();
  });

  it("shows loading and a retryable list error", async () => {
    let reject!: (error: Error) => void;
    mocks.list
      .mockReturnValueOnce(
        new Promise((_resolve, nextReject) => {
          reject = nextReject;
        }),
      )
      .mockResolvedValueOnce([]);
    setup();

    expect(screen.getByText("Cargando registros…")).toBeInTheDocument();
    reject(new Error("Sin conexión"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Sin conexión");
    await userEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    await waitFor(() => expect(mocks.list).toHaveBeenCalledTimes(2));
    expect(
      await screen.findByText("No hay entradas de tiempo"),
    ).toBeInTheDocument();
  });

  it("sends the chosen civil date once while creation is pending", async () => {
    let resolve!: (value: unknown) => void;
    mocks.create.mockReturnValue(
      new Promise((nextResolve) => {
        resolve = nextResolve;
      }),
    );
    setup();

    await userEvent.click(
      await screen.findByRole("button", { name: "Añadir manual" }),
    );
    expect(screen.getByLabelText("Fecha")).toHaveValue("2026-09-17");
    await userEvent.clear(screen.getByLabelText("Fecha"));
    await userEvent.type(screen.getByLabelText("Fecha"), "2026-09-15");
    await userEvent.type(screen.getByLabelText("Minutos"), "25");
    const save = screen.getByRole("button", { name: "Guardar" });
    await userEvent.click(save);
    await userEvent.click(save);

    expect(mocks.create).toHaveBeenCalledTimes(1);
    expect(mocks.create).toHaveBeenCalledWith({
      minutes: 25,
      task_id: 9,
      notes: undefined,
      date: "2026-09-15",
    });
    resolve({ ...ownEntry, date: "2026-09-15T00:00:00", minutes: 25 });
  });
});
