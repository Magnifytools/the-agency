import { useEffect, useRef, useState } from "react";
import { Link2, Loader2, Search, Undo2, Zap } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  changesApi,
  clientsApi,
  commandsApi,
  inboxApi,
  projectsApi,
} from "@/lib/api";
import {
  inboxKeys,
  invalidateProjectChange,
  invalidateTaskChange,
  invalidateTimeChange,
  projectKeys,
} from "@/lib/query-keys";
import type { CommandContext, CommandEntity, CommandReceipt } from "@/lib/types";
import { showUndoResult } from "@/lib/undo-feedback";
import { getErrorMessage } from "@/lib/utils";
import { formatCivilDate } from "@/lib/dates";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type Mode = "command" | "capture";

function requestKey() {
  return crypto.randomUUID();
}

function entityHref(entity: CommandEntity) {
  if (entity.type === "task") return `/tasks?id=${entity.id}`;
  if (entity.type === "project") return `/projects/${entity.id}`;
  if (entity.type === "client") return `/clients/${entity.id}`;
  return "/timesheet";
}

const appliedFieldLabels: Record<string, string> = {
  project_id: "Proyecto",
  client_id: "Cliente",
  owner_id: "Responsable del proyecto",
  assigned_to: "Responsable de la tarea",
  scheduled_date: "Fecha planificada",
  target_date: "Fecha objetivo",
  entry_date: "Fecha del registro",
  minutes: "Tiempo registrado",
  user_id: "Persona",
  status: "Estado",
  priority: "Prioridad",
};

const statusLabels: Record<string, string> = {
  backlog: "Backlog",
  pending: "Pendiente",
  in_progress: "En curso",
  waiting: "En espera",
  in_review: "En revisión",
  advanced: "Avanzada",
  completed: "Completada",
};

const priorityLabels: Record<string, string> = {
  low: "Baja",
  medium: "Media",
  high: "Alta",
  urgent: "Urgente",
};

function appliedValue(
  field: string,
  value: string | number | null,
  labels: Record<string, string>,
) {
  if (["project_id", "client_id", "owner_id", "assigned_to", "user_id"].includes(field)) {
    if (value == null) return field === "project_id" || field === "client_id" ? "Sin vincular" : "Sin asignar";
    return labels[field] ?? "Vinculado";
  }
  if (["scheduled_date", "target_date", "entry_date"].includes(field)) {
    return typeof value === "string"
      ? formatCivilDate(value, { day: "numeric", month: "long", year: "numeric" })
      : "Sin fecha";
  }
  if (field === "minutes") return `${value} min`;
  if (field === "status" && typeof value === "string") return statusLabels[value] ?? value;
  if (field === "priority" && typeof value === "string") return priorityLabels[value] ?? value;
  return String(value ?? "Sin valor");
}

export function QuickCaptureDialog({ open, onOpenChange }: Props) {
  const [mode, setMode] = useState<Mode>("command");
  const [text, setText] = useState("");
  const [receipt, setReceipt] = useState<CommandReceipt | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [networkUncertain, setNetworkUncertain] = useState(false);
  const [stepUncertain, setStepUncertain] = useState(false);
  const [undoneChangeId, setUndoneChangeId] = useState<number | null>(null);
  const commandKey = useRef<string>(requestKey());
  const commandReplayPayload = useRef<{
    channel: "app" | "extension";
    context?: CommandContext;
  } | null>(null);
  const stepKey = useRef<string>(requestKey());
  const stepPayload = useRef<{
    receiptId: string;
    revision: number;
    answers: Array<{ field: string; choice_id: string }>;
  } | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const queryClient = useQueryClient();

  const [captureText, setCaptureText] = useState("");
  const [linkUrl, setLinkUrl] = useState("");
  const [clientId, setClientId] = useState("");
  const [projectId, setProjectId] = useState("");

  const { data: clients = [] } = useQuery({
    queryKey: ["clients-active-list"],
    queryFn: () => clientsApi.listAll("active"),
    staleTime: 60_000,
    enabled: open && mode === "capture",
  });
  const { data: projects = [] } = useQuery({
    queryKey: projectKeys.list(["active"]),
    queryFn: () => projectsApi.listAll({ status: "active" }),
    staleTime: 60_000,
    enabled: open && mode === "capture",
  });
  const { data: recentCommands } = useQuery({
    queryKey: ["commands", "recent"],
    queryFn: () => commandsApi.list(1, 5),
    enabled: open && mode === "command" && !receipt,
    staleTime: 15_000,
  });

  async function refreshReceipt(result: CommandReceipt) {
    setNetworkUncertain(false);
    setStepUncertain(false);
    stepPayload.current = null;
    setUndoneChangeId(null);
    setReceipt(result);
    setAnswers({});
    if (result.status !== "executed") return;
    const entities = result.result?.entities ?? [];
    const impact = {
      projectIds: entities.map((entity) => entity.project_id),
      clientIds: entities.map((entity) => entity.client_id),
    };
    if (result.intent?.kind === "log_time")
      await invalidateTimeChange(queryClient, impact);
    else if (entities.some((entity) => entity.type === "project"))
      await invalidateProjectChange(queryClient, impact);
    else if (entities.some((entity) => entity.type === "task"))
      await invalidateTaskChange(queryClient, impact);
    await queryClient.invalidateQueries({ queryKey: ["changes", "recent"] });
    await queryClient.invalidateQueries({ queryKey: ["commands", "recent"] });
  }

  const commandMutation = useMutation({
    mutationFn: () =>
      commandsApi.create({
        request_key: commandKey.current,
        text: text.trim(),
        channel: commandReplayPayload.current?.channel ?? "app",
        context: commandReplayPayload.current?.context,
      }),
    onSuccess: refreshReceipt,
    onError: (error) => {
      const status = (error as { response?: { status?: number } }).response
        ?.status;
      if (status != null && status < 500) {
        commandKey.current = requestKey();
        setNetworkUncertain(false);
      } else {
        setNetworkUncertain(true);
      }
      toast.error(
        getErrorMessage(error, "No se ha podido procesar la petición"),
      );
    },
  });
  const resolveMutation = useMutation({
    mutationFn: () => {
      const payload = stepPayload.current ?? {
        receiptId: receipt!.id,
        revision: receipt!.revision,
        answers: Object.entries(answers).map(([field, choice_id]) => ({ field, choice_id })),
      };
      stepPayload.current = payload;
      return commandsApi.resolve(payload.receiptId, {
        request_key: stepKey.current,
        revision: payload.revision,
        answers: payload.answers,
      });
    },
    onSuccess: (result) => {
      stepKey.current = requestKey();
      void refreshReceipt(result);
    },
    onError: async (error) => {
      const status = (error as { response?: { status?: number } }).response?.status;
      if ((status === 403 || status === 409) && receipt) {
        try {
          const durable = await commandsApi.get(receipt.id);
          stepKey.current = requestKey();
          await refreshReceipt(durable);
          return;
        } catch (recoveryError) {
          toast.error(getErrorMessage(recoveryError, "No se pudo recuperar el recibo actual"));
        }
      }
      if (status == null || status >= 500) setStepUncertain(true);
      else {
        stepPayload.current = null;
        stepKey.current = requestKey();
      }
      toast.error(
        getErrorMessage(error, "No se ha podido aplicar la respuesta"),
      );
    },
  });
  const executeMutation = useMutation({
    mutationFn: () =>
      commandsApi.execute(receipt!.id, {
        request_key: stepKey.current,
        revision: receipt!.revision,
      }),
    onSuccess: (result) => {
      stepKey.current = requestKey();
      void refreshReceipt(result);
    },
    onError: (error) =>
      toast.error(getErrorMessage(error, "No se ha podido ejecutar el cambio")),
  });
  const undoMutation = useMutation({
    mutationFn: (id: number) => changesApi.undo(id),
    onSuccess: (result) => {
      setUndoneChangeId(result.id);
      showUndoResult(result);
      void queryClient.invalidateQueries();
    },
    onError: (error) =>
      toast.error(getErrorMessage(error, "No se ha podido deshacer")),
  });
  const queryPageMutation = useMutation({
    mutationFn: () =>
      commandsApi.query(
        receipt!.id,
        (receipt!.result!.query?.page ?? 1) + 1,
        receipt!.result!.query?.page_size ?? 25,
      ),
    onSuccess: (page) => {
      setReceipt((current) => {
        if (!current?.result?.query) return current;
        return {
          ...current,
          result: {
            ...current.result,
            query: {
              ...page,
              items: [...current.result.query.items, ...page.items],
            },
          },
        };
      });
    },
    onError: (error) =>
      toast.error(
        getErrorMessage(error, "No se pudieron cargar más resultados"),
      ),
  });

  const captureMutation = useMutation({
    mutationFn: () =>
      inboxApi.create({
        raw_text: captureText.trim(),
        source: "quick_capture",
        client_id: clientId ? Number(clientId) : undefined,
        project_id: projectId ? Number(projectId) : undefined,
        link_url: linkUrl.trim() || undefined,
      }),
    onSuccess: () => {
      setCaptureText("");
      setLinkUrl("");
      setClientId("");
      setProjectId("");
      void queryClient.invalidateQueries({ queryKey: inboxKeys.all() });
      void queryClient.invalidateQueries({ queryKey: inboxKeys.count() });
      toast.success("Guardado para aclarar");
      onOpenChange(false);
    },
    onError: (error) =>
      toast.error(getErrorMessage(error, "Error al capturar")),
  });

  useEffect(() => {
    if (!open) return;
    const id = window.setTimeout(() => textareaRef.current?.focus(), 100);
    return () => window.clearTimeout(id);
  }, [open]);

  const resetCommand = () => {
    setText("");
    setReceipt(null);
    setAnswers({});
    setNetworkUncertain(false);
    setStepUncertain(false);
    stepPayload.current = null;
    setUndoneChangeId(null);
    commandKey.current = requestKey();
    commandReplayPayload.current = null;
    stepKey.current = requestKey();
    window.setTimeout(() => textareaRef.current?.focus(), 0);
  };
  const editCommand = () => {
    setReceipt(null);
    setAnswers({});
    setNetworkUncertain(false);
    setStepUncertain(false);
    stepPayload.current = null;
    setUndoneChangeId(null);
    commandKey.current = requestKey();
    commandReplayPayload.current = null;
    stepKey.current = requestKey();
    window.setTimeout(() => textareaRef.current?.focus(), 0);
  };
  const isPending =
    commandMutation.isPending ||
    resolveMutation.isPending ||
    executeMutation.isPending;
  const questions = receipt?.prompt?.questions ?? [];
  const allAnswered = questions.every(
    (question) => question.kind === "notice" || answers[question.field],
  );
  const openRecentReceipt = (item: CommandReceipt) => {
    setText(item.raw_text);
    commandKey.current = item.request_key;
    commandReplayPayload.current = {
      channel: item.channel,
      context: item.context ?? undefined,
    };
    stepKey.current = requestKey();
    stepPayload.current = null;
    setNetworkUncertain(false);
    setStepUncertain(false);
    setAnswers({});
    setReceipt(item);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader>
        <DialogTitle>¿Qué necesitas hacer?</DialogTitle>
      </DialogHeader>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <div className="flex gap-2" role="tablist" aria-label="Tipo de entrada">
          <Button
            type="button"
            variant={mode === "command" ? "default" : "outline"}
            role="tab"
            aria-selected={mode === "command"}
            onClick={() => setMode("command")}
          >
            Pedir una acción
          </Button>
          <Button
            type="button"
            variant={mode === "capture" ? "default" : "outline"}
            role="tab"
            aria-selected={mode === "capture"}
            onClick={() => setMode("capture")}
          >
            Guardar para aclarar
          </Button>
        </div>

        {mode === "command" ? (
          <div className="space-y-4">
            {!receipt && (
              <>
                <Textarea
                  ref={textareaRef}
                  value={text}
                  onChange={(event) => setText(event.target.value)}
                  onKeyDown={(event) => {
                    if (
                      (event.metaKey || event.ctrlKey) &&
                      event.key === "Enter" &&
                      text.trim()
                    ) {
                      event.preventDefault();
                      commandMutation.mutate();
                    }
                  }}
                  placeholder="Ej. Completa la tarea Revisar portada, crea una tarea o consulta bloqueos"
                  className="min-h-28 resize-none"
                  disabled={isPending || networkUncertain}
                  aria-label="Petición"
                />
                {networkUncertain && (
                  <div
                    role="alert"
                    className="space-y-2 rounded-lg border border-amber-500/40 p-3 text-sm"
                  >
                    <p>
                      No hemos recibido respuesta. La petición puede haberse
                      completado.
                    </p>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        variant="outline"
                        onClick={() => commandMutation.mutate()}
                        disabled={isPending}
                      >
                        Reintentar la misma petición
                      </Button>
                      <Button variant="outline" onClick={editCommand}>
                        Editar como petición nueva
                      </Button>
                    </div>
                  </div>
                )}
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-xs text-muted-foreground">
                    Las acciones reversibles se ejecutan directamente y muestran
                    un recibo.
                  </p>
                  <Button
                    onClick={() => commandMutation.mutate()}
                    disabled={!text.trim() || isPending || networkUncertain}
                  >
                    {isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Zap className="h-4 w-4" />
                    )}
                    Hacer
                  </Button>
                </div>
                {(recentCommands?.items.length ?? 0) > 0 && (
                  <details className="rounded-lg border border-border p-3">
                    <summary className="cursor-pointer text-sm font-medium">
                      Peticiones recientes
                    </summary>
                    <div className="mt-2 space-y-1">
                      {recentCommands!.items.map((item) => (
                        <button
                          key={item.id}
                          type="button"
                          className="block w-full rounded-md px-2 py-2 text-left text-sm hover:bg-muted"
                          onClick={() => openRecentReceipt(item)}
                        >
                          <span className="block truncate">
                            {item.result?.message ?? item.raw_text}
                          </span>
                          <span className="text-xs text-muted-foreground">
                            {item.status === "executed"
                              ? "Completada"
                              : item.status === "failed"
                                ? "No realizada"
                                : "Pendiente"}
                          </span>
                        </button>
                      ))}
                    </div>
                  </details>
                )}
              </>
            )}

            {receipt?.status === "needs_input" && (
              <div className="space-y-4" role="status" aria-live="polite">
                {questions.map((question) => (
                  <fieldset key={question.field} className="space-y-2">
                    <legend className="text-sm font-medium">
                      {question.label}
                    </legend>
                    {question.kind === "choice" &&
                      question.choices.map((choice) => (
                        <label
                          key={choice.id}
                          className="flex min-h-11 cursor-pointer items-center gap-3 rounded-lg border border-border px-3 py-2 has-[:checked]:border-brand has-[:checked]:bg-brand/5"
                        >
                          <input
                            type="radio"
                            name={question.field}
                            value={choice.id}
                            checked={answers[question.field] === choice.id}
                            disabled={isPending || stepUncertain}
                            onChange={() =>
                              setAnswers((current) => ({
                                ...current,
                                [question.field]: choice.id,
                              }))
                            }
                          />
                          <span>
                            <span className="block text-sm">
                              {choice.label}
                            </span>
                            {choice.subtitle && (
                              <span className="block text-xs text-muted-foreground">
                                {choice.subtitle}
                              </span>
                            )}
                          </span>
                        </label>
                      ))}
                  </fieldset>
                ))}
                {questions.some((question) => question.kind === "notice") ? (
                  <Button variant="outline" onClick={resetCommand}>
                    Escribir otra petición
                  </Button>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    <Button
                      onClick={() => resolveMutation.mutate()}
                      disabled={!allAnswered || isPending}
                    >
                      {isPending && <Loader2 className="h-4 w-4 animate-spin" />}
                      {stepUncertain ? "Reintentar la misma respuesta" : "Continuar"}
                    </Button>
                    <Button variant="outline" onClick={resetCommand} disabled={isPending}>
                      Escribir otra petición
                    </Button>
                  </div>
                )}
              </div>
            )}

            {receipt?.status === "needs_review" && (
              <div className="space-y-3" role="status">
                <p className="text-sm">
                  {receipt.result?.message ??
                    "Revisa el cambio antes de continuar."}
                </p>
                <div className="flex gap-2">
                  <Button
                    onClick={() => executeMutation.mutate()}
                    disabled={isPending}
                  >
                    Ejecutar
                  </Button>
                  <Button variant="outline" onClick={resetCommand}>
                    Cancelar
                  </Button>
                </div>
              </div>
            )}

            {receipt?.status === "failed" && (
              <div
                role="alert"
                className="space-y-3 rounded-lg border border-destructive/40 p-3"
              >
                <p className="text-sm">
                  {receipt.error?.detail ??
                    "No se ha podido realizar la petición."}
                </p>
                <div className="flex gap-2">
                  <Button variant="outline" onClick={editCommand}>
                    Editar petición
                  </Button>
                  <Button
                    onClick={() => commandMutation.mutate()}
                    disabled={isPending}
                  >
                    Reintentar
                  </Button>
                </div>
              </div>
            )}

            {receipt?.status === "executed" && receipt.result && (
              <div
                className="space-y-3 rounded-lg border border-brand/40 bg-brand/5 p-4"
                role="status"
                aria-live="polite"
              >
                <p className="font-medium">{receipt.result.message}</p>
                {receipt.result.applied && (
                  <dl className="grid gap-x-4 gap-y-1 rounded-md bg-background/70 p-3 text-sm sm:grid-cols-[max-content_1fr]">
                    {Object.entries(receipt.result.applied).map(([field, value]) => (
                      <div className="contents" key={field}>
                        <dt className="text-muted-foreground">{appliedFieldLabels[field] ?? field}</dt>
                        <dd className="font-medium">{appliedValue(field, value, receipt.result?.applied_labels ?? {})}</dd>
                      </div>
                    ))}
                  </dl>
                )}
                {receipt.result.query ? (
                  <div className="space-y-2">
                    {receipt.result.query.items.map((entity) => (
                      <Link
                        className="block rounded-md border border-border bg-card px-3 py-2 text-sm hover:border-brand"
                        key={`${entity.type}-${entity.id}`}
                        to={entityHref(entity)}
                        onClick={() => onOpenChange(false)}
                      >
                        {entity.label}
                      </Link>
                    ))}
                    {receipt.result.query.has_more && (
                      <div className="space-y-2">
                        <p className="text-xs text-muted-foreground">
                          Se muestran {receipt.result.query.items.length} de{" "}
                          {receipt.result.query.total} resultados.
                        </p>
                        <Button
                          variant="outline"
                          onClick={() => queryPageMutation.mutate()}
                          disabled={queryPageMutation.isPending}
                        >
                          {queryPageMutation.isPending && (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          )}
                          Cargar más
                        </Button>
                      </div>
                    )}
                  </div>
                ) : (
                  receipt.result.entities.map((entity) => (
                    <Link
                      className="block text-sm text-brand underline"
                      key={`${entity.type}-${entity.id}`}
                      to={entityHref(entity)}
                      onClick={() => onOpenChange(false)}
                    >
                      {entity.label}
                    </Link>
                  ))
                )}
                <div className="flex flex-wrap gap-2">
                  {receipt.result.undo_available && receipt.change_log_id && (
                    <Button
                      variant="outline"
                      onClick={() =>
                        undoMutation.mutate(receipt.change_log_id!)
                      }
                      disabled={
                        undoMutation.isPending ||
                        undoneChangeId === receipt.change_log_id
                      }
                    >
                      <Undo2 className="h-4 w-4" />
                      {undoneChangeId === receipt.change_log_id
                        ? "Deshecho"
                        : "Deshacer"}
                    </Button>
                  )}
                  <Button onClick={resetCommand}>Hacer otra cosa</Button>
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            <Textarea
              value={captureText}
              onChange={(event) => setCaptureText(event.target.value)}
              placeholder="Nota o idea que quieres revisar después"
              className="min-h-24 resize-none"
              aria-label="Contenido para aclarar"
            />
            <div className="flex items-center gap-2">
              <Link2 className="h-4 w-4 text-muted-foreground" />
              <Input
                type="url"
                value={linkUrl}
                onChange={(event) => setLinkUrl(event.target.value)}
                placeholder="Enlace de referencia (opcional)"
              />
            </div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              <Select
                aria-label="Cliente"
                value={clientId}
                onChange={(event) => {
                  setClientId(event.target.value);
                  setProjectId("");
                }}
              >
                <option value="">Cliente (opcional)</option>
                {clients.map((client) => (
                  <option key={client.id} value={client.id}>
                    {client.name}
                  </option>
                ))}
              </Select>
              <Select
                aria-label="Proyecto"
                value={projectId}
                onChange={(event) => setProjectId(event.target.value)}
              >
                <option value="">Proyecto (opcional)</option>
                {projects
                  .filter(
                    (project) =>
                      !clientId || String(project.client_id) === clientId,
                  )
                  .map((project) => (
                    <option key={project.id} value={project.id}>
                      {project.name}
                    </option>
                  ))}
              </Select>
            </div>
            <div className="flex justify-end">
              <Button
                onClick={() => captureMutation.mutate()}
                disabled={!captureText.trim() || captureMutation.isPending}
              >
                {captureMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Search className="h-4 w-4" />
                )}
                Guardar para aclarar
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
