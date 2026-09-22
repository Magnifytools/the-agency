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
} from "@/lib/query-keys";
import type { CommandContext, CommandEntity, CommandReceipt } from "@/lib/types";
import { showUndoResult } from "@/lib/undo-feedback";
import { getErrorMessage } from "@/lib/utils";
import { formatCivilDate } from "@/lib/dates";
import { useAuth } from "@/context/auth-context";
import { isEnabled } from "@/lib/hidden-modules";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type Mode = "command" | "capture";

type ReceiptTarget = {
  receiptId: string;
  revision: number;
  generation: number;
};

type CommandTarget = {
  generation: number;
  request: {
    request_key: string;
    text: string;
    channel: "app" | "extension";
    context?: CommandContext;
  };
};

function requestKey() {
  return crypto.randomUUID();
}

function entityHref(entity: CommandEntity) {
  if (entity.type === "incident") return entity.href?.startsWith("/") && !entity.href.startsWith("//") ? entity.href : "/incidents";
  if (entity.type === "task") return `/tasks?id=${entity.id}`;
  if (entity.type === "project") return `/projects/${entity.id}`;
  if (entity.type === "client") return `/clients/${entity.id}`;
  return "/timesheet";
}

const appliedFieldLabels: Record<string, string> = {
  project_name: "Nuevo proyecto",
  task_title: "Primera tarea",
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

const reviewFieldOrder = [
  "project_name",
  "client_id",
  "owner_id",
  "target_date",
  "task_title",
  "assigned_to",
  "scheduled_date",
];

function orderedAppliedEntries(applied: Record<string, string | number | null>) {
  return Object.entries(applied).sort(([left], [right]) => {
    const leftIndex = reviewFieldOrder.indexOf(left);
    const rightIndex = reviewFieldOrder.indexOf(right);
    return (leftIndex === -1 ? reviewFieldOrder.length : leftIndex) -
      (rightIndex === -1 ? reviewFieldOrder.length : rightIndex);
  });
}

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
  const failedRetrySource = useRef<string | null>(null);
  const stepKey = useRef<string>(requestKey());
  const stepPayload = useRef<{
    receiptId: string;
    revision: number;
    answers: Array<{ field: string; choice_id: string }>;
  } | null>(null);
  const receiptRef = useRef<CommandReceipt | null>(null);
  const commandGeneration = useRef(0);
  const [activeGeneration, setActiveGeneration] = useState(0);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const queryClient = useQueryClient();
  const { user, hasPermission } = useAuth();
  const canReadClients = isEnabled("clients") && hasPermission("clients");
  const canReadProjects = isEnabled("projects") && hasPermission("projects");

  const [captureText, setCaptureText] = useState("");
  const [linkUrl, setLinkUrl] = useState("");
  const [clientId, setClientId] = useState("");
  const [projectId, setProjectId] = useState("");
  const captureAccessKey = `${user?.id ?? "anonymous"}:${canReadClients}:${canReadProjects}`;
  const previousCaptureAccessKey = useRef(captureAccessKey);
  const selectedContextOwnerId = useRef(user?.id);

  const { data: clients = [] } = useQuery({
    queryKey: ["quick-capture", user?.id, "clients-active"],
    queryFn: () => clientsApi.listAll("active"),
    staleTime: 60_000,
    enabled: open && mode === "capture" && canReadClients,
  });
  const { data: projects = [] } = useQuery({
    queryKey: ["quick-capture", user?.id, "projects-active"],
    queryFn: () => projectsApi.listAll({ status: "active" }),
    staleTime: 60_000,
    enabled: open && mode === "capture" && canReadProjects,
  });
  const { data: recentCommands } = useQuery({
    queryKey: ["commands", "recent"],
    queryFn: () => commandsApi.list(1, 5),
    enabled: open && mode === "command" && !receipt,
    staleTime: 15_000,
  });

  const isCurrentReceipt = (target: ReceiptTarget) =>
    commandGeneration.current === target.generation &&
    receiptRef.current?.id === target.receiptId;

  const replaceReceipt = (next: CommandReceipt | null) => {
    receiptRef.current = next;
    setReceipt(next);
  };

  const invalidateCommand = () => {
    commandGeneration.current += 1;
    setActiveGeneration(commandGeneration.current);
    replaceReceipt(null);
  };

  async function refreshReceipt(
    result: CommandReceipt,
    target?: ReceiptTarget | { generation: number },
  ) {
    if (target && commandGeneration.current !== target.generation) return;
    if (target && "receiptId" in target && !isCurrentReceipt(target)) return;
    setNetworkUncertain(false);
    setStepUncertain(false);
    stepPayload.current = null;
    setUndoneChangeId(null);
    replaceReceipt(result);
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
    mutationFn: (target: CommandTarget) => commandsApi.create(target.request),
    onSuccess: (result, target) => void refreshReceipt(result, target),
    onError: (error, target) => {
      if (commandGeneration.current !== target.generation) return;
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
    mutationFn: (target: ReceiptTarget) => {
      const payload = stepPayload.current ?? {
        receiptId: target.receiptId,
        revision: target.revision,
        answers: Object.entries(answers).map(([field, choice_id]) => ({ field, choice_id })),
      };
      stepPayload.current = payload;
      return commandsApi.resolve(payload.receiptId, {
        request_key: stepKey.current,
        revision: payload.revision,
        answers: payload.answers,
      });
    },
    onSuccess: (result, target) => {
      if (!isCurrentReceipt(target)) return;
      stepKey.current = requestKey();
      void refreshReceipt(result, target);
    },
    onError: async (error, target) => {
      if (!isCurrentReceipt(target)) return;
      const status = (error as { response?: { status?: number } }).response?.status;
      if (status === 403 || status === 409) {
        try {
          const durable = await commandsApi.get(target.receiptId);
          if (!isCurrentReceipt(target)) return;
          stepKey.current = requestKey();
          await refreshReceipt(durable, target);
          return;
        } catch (recoveryError) {
          if (!isCurrentReceipt(target)) return;
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
    mutationFn: (target: ReceiptTarget) =>
      commandsApi.execute(target.receiptId, {
        request_key: stepKey.current,
        revision: target.revision,
      }),
    onSuccess: (result, target) => {
      if (!isCurrentReceipt(target)) return;
      stepKey.current = requestKey();
      void refreshReceipt(result, target);
    },
    onError: async (error, target) => {
      if (!isCurrentReceipt(target)) return;
      const status = (error as { response?: { status?: number } }).response?.status;
      if (status === 403 || status === 409) {
        try {
          const durable = await commandsApi.get(target.receiptId);
          if (!isCurrentReceipt(target)) return;
          stepKey.current = requestKey();
          await refreshReceipt(durable, target);
          return;
        } catch (recoveryError) {
          if (!isCurrentReceipt(target)) return;
          toast.error(getErrorMessage(recoveryError, "No se pudo recuperar el recibo actual"));
        }
      }
      toast.error(getErrorMessage(error, "No se ha recibido confirmación. Reintenta para recuperar el resultado sin duplicar el cambio."));
    },
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
    mutationFn: (target: ReceiptTarget) =>
      commandsApi.query(
        target.receiptId,
        (receiptRef.current?.result?.query?.page ?? 1) + 1,
        receiptRef.current?.result?.query?.page_size ?? 25,
      ),
    onSuccess: (page, target) => {
      if (!isCurrentReceipt(target)) return;
      const current = receiptRef.current;
      if (!current?.result?.query) return;
      replaceReceipt({
        ...current,
          result: {
            ...current.result,
            query: {
              ...page,
              items: [...current.result.query.items, ...page.items],
            },
          },
      });
    },
    onError: (error, target) => {
      if (!isCurrentReceipt(target)) return;
      toast.error(getErrorMessage(error, "No se pudieron cargar más resultados"));
    },
  });

  const captureMutation = useMutation({
    mutationFn: () =>
      inboxApi.create({
        raw_text: captureText.trim(),
        source: "quick_capture",
        ...(canReadClients && selectedContextOwnerId.current === user?.id && clientId ? { client_id: Number(clientId) } : {}),
        ...(canReadProjects && selectedContextOwnerId.current === user?.id && projectId ? { project_id: Number(projectId) } : {}),
        link_url: linkUrl.trim() || undefined,
      }),
    onSuccess: () => {
      setCaptureText("");
      setLinkUrl("");
      setClientId("");
      setProjectId("");
      if (user) void queryClient.invalidateQueries({ queryKey: inboxKeys.all(user.id) });
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

  useEffect(() => {
    if (previousCaptureAccessKey.current === captureAccessKey) return;
    previousCaptureAccessKey.current = captureAccessKey;
    selectedContextOwnerId.current = user?.id;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- A revoked permission or changed identity invalidates local entity IDs.
    setClientId("");
    setProjectId("");
  }, [captureAccessKey, user?.id]);

  const resetCommand = () => {
    invalidateCommand();
    setText("");
    replaceReceipt(null);
    setAnswers({});
    setNetworkUncertain(false);
    setStepUncertain(false);
    stepPayload.current = null;
    setUndoneChangeId(null);
    commandKey.current = requestKey();
    commandReplayPayload.current = null;
    failedRetrySource.current = null;
    stepKey.current = requestKey();
    window.setTimeout(() => textareaRef.current?.focus(), 0);
  };
  const editCommand = () => {
    invalidateCommand();
    replaceReceipt(null);
    setAnswers({});
    setNetworkUncertain(false);
    setStepUncertain(false);
    stepPayload.current = null;
    setUndoneChangeId(null);
    commandKey.current = requestKey();
    commandReplayPayload.current = null;
    failedRetrySource.current = null;
    stepKey.current = requestKey();
    window.setTimeout(() => textareaRef.current?.focus(), 0);
  };
  const isPending =
    (commandMutation.isPending && commandMutation.variables?.generation === activeGeneration) ||
    (resolveMutation.isPending && resolveMutation.variables?.generation === activeGeneration) ||
    (executeMutation.isPending && executeMutation.variables?.generation === activeGeneration);
  const questions = receipt?.prompt?.questions ?? [];
  const allAnswered = questions.every(
    (question) => question.kind === "notice" || answers[question.field],
  );
  const openRecentReceipt = (item: CommandReceipt) => {
    invalidateCommand();
    setText(item.raw_text);
    commandKey.current = item.request_key;
    failedRetrySource.current = null;
    commandReplayPayload.current = {
      channel: item.channel,
      context: item.context ?? undefined,
    };
    stepKey.current = requestKey();
    stepPayload.current = null;
    setNetworkUncertain(false);
    setStepUncertain(false);
    setAnswers({});
    replaceReceipt(item);
  };
  const submitCommand = () => {
    const target: CommandTarget = {
      generation: commandGeneration.current,
      request: {
        request_key: commandKey.current,
        text: text.trim(),
        channel: commandReplayPayload.current?.channel ?? "app",
        context: commandReplayPayload.current?.context,
      },
    };
    commandMutation.mutate(target);
  };
  const retryFailedCommand = () => {
    if (!receipt || isPending) return;
    if (!networkUncertain && failedRetrySource.current !== receipt.id) {
      commandKey.current = requestKey();
      commandReplayPayload.current = null;
      failedRetrySource.current = receipt.id;
    }
    submitCommand();
  };
  const updateCommandText = (next: string) => {
    if (!receiptRef.current && !networkUncertain && next !== text) {
      commandKey.current = requestKey();
      commandReplayPayload.current = null;
    }
    setText(next);
  };
  const receiptTarget = (): ReceiptTarget | null => {
    const current = receiptRef.current;
    if (!current) return null;
    return {
      receiptId: current.id,
      revision: current.revision,
      generation: commandGeneration.current,
    };
  };
  const switchMode = (next: Mode) => {
    if (next !== mode) invalidateCommand();
    setMode(next);
  };
  const handleOpenChange = (next: boolean) => {
    if (!next) invalidateCommand();
    onOpenChange(next);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogHeader>
        <DialogTitle>¿Qué necesitas hacer?</DialogTitle>
      </DialogHeader>
      <DialogContent className="space-y-4">
        <div className="flex gap-2" role="tablist" aria-label="Tipo de entrada">
          <Button
            type="button"
            variant={mode === "command" ? "default" : "outline"}
            role="tab"
            aria-selected={mode === "command"}
            onClick={() => switchMode("command")}
          >
            Pedir una acción
          </Button>
          <Button
            type="button"
            variant={mode === "capture" ? "default" : "outline"}
            role="tab"
            aria-selected={mode === "capture"}
            onClick={() => switchMode("capture")}
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
                  onChange={(event) => updateCommandText(event.target.value)}
                  onKeyDown={(event) => {
                    if (
                      (event.metaKey || event.ctrlKey) &&
                      event.key === "Enter" &&
                      text.trim() && !isPending && !networkUncertain
                    ) {
                      event.preventDefault();
                      submitCommand();
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
                        onClick={submitCommand}
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
                    Las acciones simples muestran un recibo con Deshacer. Si creas un proyecto con su primera tarea, revisarás ambos antes de guardarlos.
                  </p>
                  <Button
                    onClick={submitCommand}
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
                <details className="rounded-lg border border-border p-3 text-sm">
                  <summary className="cursor-pointer font-medium">Ver ejemplos de peticiones</summary>
                  <ul className="mt-2 space-y-2 text-muted-foreground">
                    <li>Crea proyecto "Web nueva" para cliente "Nombre del cliente" con primera tarea "Preparar propuesta" para mañana</li>
                    <li>Consulta decisiones pendientes</li>
                    <li>Completa la tarea "Preparar propuesta"</li>
                  </ul>
                  <p className="mt-2 text-xs text-muted-foreground">Sustituye los nombres por los de tu trabajo. Las comillas separan los nombres del resto de la petición.</p>
                </details>
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
                      onClick={() => {
                        const target = receiptTarget();
                        if (target) resolveMutation.mutate(target);
                      }}
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
                {receipt.result?.applied && (
                  <dl className="grid gap-x-4 gap-y-1 rounded-md bg-muted/50 p-3 text-sm sm:grid-cols-[max-content_1fr]">
                    {orderedAppliedEntries(receipt.result.applied).map(([field, value]) => (
                      <div className="contents" key={field}>
                        <dt className="text-muted-foreground">{appliedFieldLabels[field] ?? field}</dt>
                        <dd className="break-words font-medium">{appliedValue(field, value, receipt.result?.applied_labels ?? {})}</dd>
                      </div>
                    ))}
                  </dl>
                )}
                <div className="flex flex-wrap gap-2">
                  <Button
                    onClick={() => {
                      const target = receiptTarget();
                      if (target) executeMutation.mutate(target);
                    }}
                    disabled={isPending}
                  >
                    Crear proyecto y tarea
                  </Button>
                  <Button variant="outline" onClick={resetCommand} disabled={isPending}>
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
                <p className="text-sm">
                  {networkUncertain
                    ? "No hemos recibido respuesta del reintento. Comprueba la misma petición antes de volver a enviarla."
                    : "Se enviará una petición nueva con el mismo texto."}
                </p>
                <div className="flex gap-2">
                  {!networkUncertain && <Button variant="outline" onClick={editCommand}>
                    Editar petición
                  </Button>}
                  <Button
                    onClick={retryFailedCommand}
                    disabled={isPending}
                  >
                    {networkUncertain ? "Comprobar el reintento" : "Reintentar"}
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
                {receipt.result.kind === "derivation" && receipt.raw_text && (
                  <blockquote className="rounded-md border border-border bg-background/70 px-3 py-2 text-sm text-muted-foreground">
                    {receipt.raw_text}
                  </blockquote>
                )}
                {receipt.result.applied && (
                  <dl className="grid gap-x-4 gap-y-1 rounded-md bg-background/70 p-3 text-sm sm:grid-cols-[max-content_1fr]">
                    {orderedAppliedEntries(receipt.result.applied).map(([field, value]) => (
                      <div className="contents" key={field}>
                        <dt className="text-muted-foreground">{appliedFieldLabels[field] ?? field}</dt>
                        <dd className="font-medium">{appliedValue(field, value, receipt.result?.applied_labels ?? {})}</dd>
                      </div>
                    ))}
                  </dl>
                )}
                {receipt.result.query ? (
                  <div className="space-y-2">
                    {receipt.result.query.kind === "decisions" && <p className="text-sm text-muted-foreground">Avisos activos que requieren atención. Los pospuestos quedan fuera hasta que vuelvan a activarse.</p>}
                    {receipt.result.query.items.map((entity) => (
                      <Link
                        className="block rounded-md border border-border bg-card px-3 py-2 text-sm hover:border-brand"
                        key={`${entity.type}-${entity.id}`}
                        to={entityHref(entity)}
                        onClick={() => onOpenChange(false)}
                      >
                        <span className="block font-medium">{entity.label}</span>
                        {entity.type === "incident" && entity.message && <span className="mt-1 block text-muted-foreground">{entity.message}</span>}
                        {entity.type === "incident" && entity.recipient_name && <span className="mt-1 block text-xs text-muted-foreground">Para {entity.recipient_name}</span>}
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
                          onClick={() => {
                            const target = receiptTarget();
                            if (target) queryPageMutation.mutate(target);
                          }}
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
                  {receipt.result.action?.kind === "open_project_form" && (
                    <Link
                      className="inline-flex h-10 items-center justify-center rounded-[10px] bg-brand px-5 py-2 text-sm font-semibold text-primary-foreground shadow hover:bg-brand/90"
                      to={receipt.result.action.href}
                      onClick={() => onOpenChange(false)}
                    >
                      Revisar proyecto
                    </Link>
                  )}
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
            {(canReadClients || canReadProjects) && <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {canReadClients && <Select
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
              </Select>}
              {canReadProjects && <Select
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
              </Select>}
            </div>}
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
