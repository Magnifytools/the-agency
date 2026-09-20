import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Clock,
  Download,
  Paperclip,
  Pause,
  Play,
  Plus,
  RotateCcw,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import {
  categoriesApi,
  clientsApi,
  projectsApi,
  tasksApi,
  usersApi,
} from "@/lib/api";
import type { RecurrenceSummary, Task, TaskCreate, TaskPriority, TaskStatus } from "@/lib/types";
import { invalidateTaskChange, projectKeys, taskKeys } from "@/lib/query-keys";
import { getErrorMessage } from "@/lib/utils";
import { useAuth } from "@/context/auth-context";
import { Button } from "@/components/ui/button";
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useBusinessDate } from "@/hooks/use-business-date";

type Defaults = {
  clientId?: number | null;
  projectId?: number | null;
  phaseId?: number | null;
};
type RecurrencePreview = { key: string; summary: RecurrenceSummary };
type LegacyComparison = { key: string; sourceKey: string; current: RecurrenceSummary; proposed: RecurrenceSummary; anchor: string };

export interface TaskPanelProps {
  open: boolean;
  taskId?: number | null;
  defaults?: Defaults;
  onOpenChange: (open: boolean) => void;
  onSaved?: (task: Task) => void;
  onOpenTime?: (task: Task) => void;
}

const EMPTY: TaskCreate = {
  title: "",
  description: null,
  status: "pending",
  priority: "medium",
  estimated_minutes: null,
  due_date: null,
  scheduled_date: null,
  client_id: null,
  project_id: null,
  phase_id: null,
  category_id: null,
  assigned_to: null,
  depends_on: null,
  waiting_for: null,
  follow_up_date: null,
  is_recurring: false,
  recurrence_pattern: null,
  recurrence_day: null,
  recurrence_end_date: null,
  recurrence_anchor_date: null,
};

function fromTask(task?: Task, defaults?: Defaults): TaskCreate {
  if (!task)
    return {
      ...EMPTY,
      client_id: defaults?.clientId ?? null,
      project_id: defaults?.projectId ?? null,
      phase_id: defaults?.phaseId ?? null,
    };
  return {
    title: task.title,
    description: task.description,
    status: task.status,
    priority: task.priority,
    estimated_minutes: task.estimated_minutes,
    due_date: task.due_date?.slice(0, 10) ?? null,
    scheduled_date: task.scheduled_date,
    client_id: task.client_id,
    project_id: task.project_id,
    phase_id: task.phase_id,
    category_id: task.category_id,
    assigned_to: task.assigned_to,
    waiting_for: task.waiting_for,
    follow_up_date: task.follow_up_date,
    depends_on: task.depends_on,
    is_recurring: task.is_recurring,
    recurrence_pattern: task.recurrence_pattern,
    recurrence_day: task.recurrence_day,
    recurrence_end_date: task.recurrence_end_date,
    recurrence_anchor_date: task.recurrence_anchor_date,
  };
}

function LoadError({
  label,
  onRetry,
}: {
  label: string;
  onRetry: () => unknown;
}) {
  return (
    <div
      role="alert"
      className="flex items-center justify-between gap-2 text-sm text-destructive"
    >
      <span>No se pudieron cargar {label}.</span>
      <Button type="button" size="sm" variant="outline" onClick={onRetry}>
        Reintentar
      </Button>
    </div>
  );
}

export function TaskPanel({
  open,
  taskId,
  defaults,
  onOpenChange,
  onSaved,
  onOpenTime,
}: TaskPanelProps) {
  const queryClient = useQueryClient();
  const { hasPermission } = useAuth();
  const canWrite = hasPermission?.("tasks", true) ?? false;
  const canReadTime = hasPermission?.("timesheet") ?? false;
  const businessToday = useBusinessDate();
  const [draft, setDraft] = useState<TaskCreate>(() =>
    fromTask(undefined, defaults),
  );
  const [secondaryOpen, setSecondaryOpen] = useState(false);
  const [newChecklist, setNewChecklist] = useState("");
  const [newComment, setNewComment] = useState("");
  const [recurrencePreview, setRecurrencePreview] = useState<RecurrencePreview | null>(null);
  const [legacyComparison, setLegacyComparison] = useState<LegacyComparison | null>(null);
  const initializedFor = useRef<string | null>(null);
  const contextKey = `${taskId ?? "new"}:${defaults?.clientId ?? ""}:${defaults?.projectId ?? ""}:${defaults?.phaseId ?? ""}`;

  const taskQuery = useQuery({
    queryKey: taskKeys.detail(taskId ?? 0),
    queryFn: () => tasksApi.get(taskId!),
    enabled: open && !!taskId,
    retry: false,
  });
  const { data: clients = [] } = useQuery({
    queryKey: ["clients-all"],
    queryFn: () => clientsApi.listAll(),
    enabled: open,
  });
  const { data: projects = [] } = useQuery({
    queryKey: projectKeys.list(["all"]),
    queryFn: () => projectsApi.listAll(),
    enabled: open,
  });
  const { data: users = [] } = useQuery({
    queryKey: ["users-all"],
    queryFn: () => usersApi.listAll(),
    enabled: open,
  });
  const { data: categories = [] } = useQuery({
    queryKey: ["categories"],
    queryFn: () => categoriesApi.list(),
    enabled: open,
  });
  const { data: dependencyTasks = [] } = useQuery({
    queryKey: taskKeys.list(["panel-dependencies"]),
    queryFn: () => tasksApi.listAll(),
    enabled: open && canWrite,
  });
  const projectQuery = useQuery({
    queryKey: projectKeys.detail(draft.project_id ?? 0),
    queryFn: () => projectsApi.get(draft.project_id!),
    enabled: open && !!draft.project_id,
  });
  const checklistQuery = useQuery({
    queryKey: ["task-checklist", taskId],
    queryFn: () => tasksApi.checklist.list(taskId!),
    enabled: open && !!taskId && secondaryOpen,
  });
  const attachmentsQuery = useQuery({
    queryKey: ["task-attachments", taskId],
    queryFn: () => tasksApi.attachments.list(taskId!),
    enabled: open && !!taskId && secondaryOpen,
  });
  const commentsQuery = useQuery({
    queryKey: ["task-comments", taskId],
    queryFn: () => tasksApi.comments.list(taskId!),
    enabled: open && !!taskId && secondaryOpen,
  });

  useEffect(() => {
    if (!open) {
      initializedFor.current = null;
      return;
    }
    if (taskId && !taskQuery.data) return;
    if (initializedFor.current === contextKey) return;
    // Opening a different entity deliberately starts a fresh draft; retries keep it intact.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDraft(fromTask(taskQuery.data, defaults));
    setSecondaryOpen(false);
    initializedFor.current = contextKey;
  }, [open, taskId, taskQuery.data, defaults, contextKey]);

  const availableProjects = useMemo(
    () =>
      draft.client_id
        ? projects.filter((project) => project.client_id === draft.client_id)
        : projects,
    [draft.client_id, projects],
  );
  const change = <K extends keyof TaskCreate>(key: K, value: TaskCreate[K]) => {
    setDraft((current) => ({ ...current, [key]: value }));
  };
  const recurrencePaused = !!taskQuery.data?.recurrence_paused_at;
  const recurrenceDraftKey = JSON.stringify({
    contextKey,
    open,
    is_recurring: draft.is_recurring,
    recurrence_pattern: draft.recurrence_pattern,
    recurrence_day: draft.recurrence_day,
    recurrence_anchor_date: draft.recurrence_anchor_date,
    recurrence_end_date: draft.recurrence_end_date,
    client_id: draft.client_id,
    project_id: draft.project_id,
    phase_id: draft.phase_id,
    recurrencePaused,
  });
  const recurrenceSummary = recurrencePreview?.key === recurrenceDraftKey
    ? recurrencePreview.summary
    : taskQuery.data?.recurrence_summary;
  const legacyAnchorChange = !!taskId && taskQuery.data?.recurrence_pattern === "biweekly"
    && !taskQuery.data.recurrence_anchor_date && !!draft.recurrence_anchor_date;
  const comparisonReady = legacyComparison?.key === recurrenceDraftKey;
  const legacySourceKey = JSON.stringify({ contextKey, open, recurrenceDraftKey, anchor: null });

  const save = useMutation({
    mutationFn: () =>
      taskId ? tasksApi.update(taskId, draft) : tasksApi.create(draft),
    onSuccess: (task) => {
      invalidateTaskChange(queryClient, {
        projectId: task.project_id,
        previousProjectId: taskQuery.data?.project_id,
        clientId: task.client_id,
        previousClientId: taskQuery.data?.client_id,
      });
      queryClient.setQueryData(taskKeys.detail(task.id), task);
      toast.success(taskId ? "Tarea actualizada" : "Tarea creada");
      onSaved?.(task);
      onOpenChange(false);
    },
    onError: (error) =>
      toast.error(
        getErrorMessage(error, "No se pudo guardar. El borrador sigue aquí."),
      ),
  });
  const previewRecurrence = useMutation({
    mutationFn: () => {
      const request = {
        is_recurring: !!draft.is_recurring,
        recurrence_pattern: draft.recurrence_pattern,
        recurrence_day: draft.recurrence_day,
        recurrence_end_date: draft.recurrence_end_date,
        recurrence_paused: recurrencePaused,
        client_id: draft.client_id,
        project_id: draft.project_id,
        phase_id: draft.phase_id,
      } as Parameters<typeof tasksApi.recurrencePreview>[0];
      if (taskId || draft.recurrence_anchor_date) {
        request.recurrence_anchor_date = draft.recurrence_anchor_date;
      }
      return tasksApi.recurrencePreview(request);
    },
    onMutate: () => ({ recurrenceDraftKey, legacySourceKey }),
    onSuccess: (summary, _variables, submitted) => {
      if (submitted.recurrenceDraftKey === recurrenceDraftKey) setRecurrencePreview({ key: submitted.recurrenceDraftKey, summary });
    },
    onError: (error) =>
      toast.error(getErrorMessage(error, "No se pudo calcular la recurrencia")),
  });
  const compareLegacyCalendar = useMutation({
    mutationFn: async () => {
      const proposedAnchor = draft.recurrence_anchor_date ?? businessToday;
      const saved = taskQuery.data;
      const legacy = {
        is_recurring: true,
        recurrence_pattern: "biweekly",
        recurrence_day: saved?.recurrence_day ?? draft.recurrence_day,
        recurrence_anchor_date: null,
        recurrence_end_date: saved?.recurrence_end_date ?? draft.recurrence_end_date,
        recurrence_paused: false,
        client_id: saved?.client_id ?? draft.client_id,
        project_id: saved?.project_id ?? draft.project_id,
        phase_id: saved?.phase_id ?? draft.phase_id,
      } as Parameters<typeof tasksApi.recurrencePreview>[0];
      const proposed = {
        is_recurring: !!draft.is_recurring,
        recurrence_pattern: draft.recurrence_pattern,
        recurrence_day: draft.recurrence_day,
        recurrence_anchor_date: proposedAnchor,
        recurrence_end_date: draft.recurrence_end_date,
        recurrence_paused: false,
        client_id: draft.client_id,
        project_id: draft.project_id,
        phase_id: draft.phase_id,
      } as Parameters<typeof tasksApi.recurrencePreview>[0];
      const [current, next] = await Promise.all([
        tasksApi.recurrencePreview(legacy),
        tasksApi.recurrencePreview(proposed),
      ]);
      return { current, proposed: next };
    },
    onMutate: () => legacySourceKey,
    onSuccess: ({ current, proposed }, _variables, sourceKey) => {
      const proposedKey = JSON.stringify({
        contextKey,
        open,
        is_recurring: draft.is_recurring,
        recurrence_pattern: draft.recurrence_pattern,
        recurrence_day: draft.recurrence_day,
        recurrence_anchor_date: draft.recurrence_anchor_date ?? businessToday,
        recurrence_end_date: draft.recurrence_end_date,
        client_id: draft.client_id,
        project_id: draft.project_id,
        phase_id: draft.phase_id,
        recurrencePaused,
      });
      if (sourceKey === legacySourceKey) setLegacyComparison({ key: proposedKey, sourceKey, current, proposed, anchor: draft.recurrence_anchor_date ?? businessToday });
    },
    onError: (error) => toast.error(getErrorMessage(error, "No se pudo comparar los calendarios")),
  });
  const toggleRecurrencePause = useMutation({
    mutationFn: ({ id, paused }: { id: number; paused: boolean }) =>
      tasksApi.update(id, { recurrence_paused: paused }),
    onSuccess: (task) => {
      queryClient.setQueryData(taskKeys.detail(task.id), task);
      void queryClient.invalidateQueries({ queryKey: taskKeys.recurring() });
      toast.success(task.recurrence_paused_at ? "Recurrencia pausada" : "Recurrencia activa. Si corresponde hoy, la tarea se generará en unos minutos.");
    },
    onError: (error) =>
      toast.error(getErrorMessage(error, "No se pudo cambiar la recurrencia")),
  });
  const addChecklist = useMutation({
    mutationFn: () => tasksApi.checklist.create(taskId!, newChecklist.trim()),
    onSuccess: () => {
      setNewChecklist("");
      void checklistQuery.refetch();
    },
    onError: (error) =>
      toast.error(getErrorMessage(error, "No se pudo añadir al checklist")),
  });
  const upload = useMutation({
    mutationFn: (file: File) => tasksApi.attachments.upload(taskId!, file),
    onSuccess: () => void attachmentsQuery.refetch(),
    onError: (error) =>
      toast.error(getErrorMessage(error, "No se pudo adjuntar el archivo")),
  });
  const addComment = useMutation({
    mutationFn: () => tasksApi.comments.create(taskId!, newComment.trim()),
    onSuccess: () => {
      setNewComment("");
      void commentsQuery.refetch();
    },
    onError: (error) =>
      toast.error(getErrorMessage(error, "No se pudo publicar el comentario")),
  });
  const updateChecklist = useMutation({
    mutationFn: ({
      itemId,
      data,
    }: {
      itemId: number;
      data: Partial<{
        text: string;
        description: string | null;
        is_done: boolean;
        assigned_to: number | null;
        due_date: string | null;
      }>;
    }) => tasksApi.checklist.update(taskId!, itemId, data),
    onSuccess: () => void checklistQuery.refetch(),
    onError: (error) =>
      toast.error(getErrorMessage(error, "No se pudo actualizar el checklist")),
  });
  const deleteChecklist = useMutation({
    mutationFn: (itemId: number) => tasksApi.checklist.delete(taskId!, itemId),
    onSuccess: () => void checklistQuery.refetch(),
    onError: (error) =>
      toast.error(getErrorMessage(error, "No se pudo eliminar del checklist")),
  });
  const deleteAttachment = useMutation({
    mutationFn: (attachmentId: number) =>
      tasksApi.attachments.delete(taskId!, attachmentId),
    onSuccess: () => void attachmentsQuery.refetch(),
    onError: (error) =>
      toast.error(getErrorMessage(error, "No se pudo eliminar el archivo")),
  });
  const deleteComment = useMutation({
    mutationFn: (commentId: number) =>
      tasksApi.comments.delete(taskId!, commentId),
    onSuccess: () => void commentsQuery.refetch(),
    onError: (error) =>
      toast.error(getErrorMessage(error, "No se pudo eliminar el comentario")),
  });
  const downloadAttachment = async (attachmentId: number, filename: string) => {
    try {
      const blob = await tasksApi.attachments.download(taskId!, attachmentId);
      const url = URL.createObjectURL(blob as Blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      toast.error(getErrorMessage(error, "No se pudo descargar el archivo"));
    }
  };

  const loadedTask = taskQuery.data;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader>
        <DialogTitle>{taskId ? "Detalle de tarea" : "Nueva tarea"}</DialogTitle>
      </DialogHeader>
      {taskQuery.isError && (
        <div role="alert" className="space-y-2 text-sm">
          <p>
            {getErrorMessage(taskQuery.error, "No se pudo cargar la tarea")}
          </p>
          <Button variant="outline" onClick={() => taskQuery.refetch()}>
            <RotateCcw className="h-4 w-4 mr-1" />
            Reintentar
          </Button>
        </div>
      )}
      {taskId && taskQuery.isLoading ? (
        <p className="py-8 text-center text-sm text-muted-foreground">
          Cargando…
        </p>
      ) : (
        (!taskId || loadedTask) && (
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              if (canWrite && draft.title.trim() && !(legacyAnchorChange && !comparisonReady)) save.mutate();
            }}
          >
            {!canWrite && (
              <p role="status" className="rounded-md bg-muted p-3 text-sm">
                Puedes consultar esta tarea, pero no editarla.
              </p>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="task-panel-title">Título</Label>
              <Input
                id="task-panel-title"
                autoFocus
                value={draft.title}
                onChange={(e) => change("title", e.target.value)}
                disabled={!canWrite}
                required
              />
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <Label htmlFor="task-panel-status">Estado</Label>
                <Select
                  id="task-panel-status"
                  value={draft.status}
                  onChange={(e) =>
                    change("status", e.target.value as TaskStatus)
                  }
                  disabled={!canWrite}
                >
                  <option value="backlog">Backlog</option>
                  <option value="pending">Pendiente</option>
                  <option value="in_progress">En curso</option>
                  <option value="waiting">En espera</option>
                  <option value="in_review">En revisión</option>
                  <option value="advanced">Avanzada</option>
                  <option value="completed">Completada</option>
                </Select>
              </div>
              <div>
                <Label htmlFor="task-panel-priority">Prioridad</Label>
                <Select
                  id="task-panel-priority"
                  value={draft.priority}
                  onChange={(e) =>
                    change("priority", e.target.value as TaskPriority)
                  }
                  disabled={!canWrite}
                >
                  <option value="urgent">Urgente</option>
                  <option value="high">Alta</option>
                  <option value="medium">Media</option>
                  <option value="low">Baja</option>
                </Select>
              </div>
              <div>
                <Label htmlFor="task-panel-client">Cliente</Label>
                <Select
                  id="task-panel-client"
                  value={draft.client_id ?? ""}
                  onChange={(e) => {
                    const clientId = e.target.value
                      ? Number(e.target.value)
                      : null;
                    setDraft((current) => {
                      const keepsProject =
                        current.project_id &&
                        projects.some(
                          (project) =>
                            project.id === current.project_id &&
                            project.client_id === clientId,
                        );
                      return {
                        ...current,
                        client_id: clientId,
                        project_id: keepsProject ? current.project_id : null,
                        phase_id: keepsProject ? current.phase_id : null,
                      };
                    });
                  }}
                  disabled={!canWrite || defaults?.clientId != null}
                >
                  <option value="">Sin cliente</option>
                  {clients.map((client) => (
                    <option key={client.id} value={client.id}>
                      {client.name}
                    </option>
                  ))}
                </Select>
              </div>
              <div>
                <Label htmlFor="task-panel-project">Proyecto</Label>
                <Select
                  id="task-panel-project"
                  value={draft.project_id ?? ""}
                  onChange={(e) => {
                    const projectId = e.target.value
                      ? Number(e.target.value)
                      : null;
                    const project = projects.find(
                      (item) => item.id === projectId,
                    );
                    setDraft((current) => ({
                      ...current,
                      project_id: projectId,
                      phase_id: null,
                      client_id: project?.client_id ?? current.client_id,
                    }));
                  }}
                  disabled={!canWrite || defaults?.projectId != null}
                >
                  <option value="">Sin proyecto</option>
                  {availableProjects.map((project) => (
                    <option key={project.id} value={project.id}>
                      {project.name}
                    </option>
                  ))}
                </Select>
              </div>
              <div>
                <Label htmlFor="task-panel-owner">Responsable</Label>
                <Select
                  id="task-panel-owner"
                  value={draft.assigned_to ?? ""}
                  onChange={(e) =>
                    change(
                      "assigned_to",
                      e.target.value ? Number(e.target.value) : null,
                    )
                  }
                  disabled={!canWrite}
                >
                  <option value="">Sin asignar</option>
                  {users.map((user) => (
                    <option key={user.id} value={user.id}>
                      {user.full_name}
                    </option>
                  ))}
                </Select>
              </div>
              <div>
                <Label htmlFor="task-panel-category">Categoría</Label>
                <Select
                  id="task-panel-category"
                  value={draft.category_id ?? ""}
                  onChange={(e) =>
                    change(
                      "category_id",
                      e.target.value ? Number(e.target.value) : null,
                    )
                  }
                  disabled={!canWrite}
                >
                  <option value="">Sin categoría</option>
                  {categories.map((category) => (
                    <option key={category.id} value={category.id}>
                      {category.name}
                    </option>
                  ))}
                </Select>
              </div>
              <div>
                <Label htmlFor="task-panel-phase">Fase</Label>
                <Select
                  id="task-panel-phase"
                  value={draft.phase_id ?? ""}
                  onChange={(e) =>
                    change(
                      "phase_id",
                      e.target.value ? Number(e.target.value) : null,
                    )
                  }
                  disabled={!canWrite || !draft.project_id}
                >
                  <option value="">Sin fase</option>
                  {projectQuery.data?.phases?.map((phase) => (
                    <option key={phase.id} value={phase.id}>
                      {phase.name}
                    </option>
                  ))}
                </Select>
              </div>
              <div>
                <Label htmlFor="task-panel-due">Fecha límite</Label>
                <Input
                  id="task-panel-due"
                  type="date"
                  value={draft.due_date ?? ""}
                  onChange={(e) => change("due_date", e.target.value || null)}
                  disabled={!canWrite}
                />
              </div>
              <div>
                <Label htmlFor="task-panel-scheduled">Planificada</Label>
                <Input
                  id="task-panel-scheduled"
                  type="date"
                  value={draft.scheduled_date ?? ""}
                  onChange={(e) =>
                    change("scheduled_date", e.target.value || null)
                  }
                  disabled={!canWrite}
                />
              </div>
              <div>
                <Label htmlFor="task-panel-estimate">Estimación (min)</Label>
                <Input
                  id="task-panel-estimate"
                  type="number"
                  min="0"
                  value={draft.estimated_minutes ?? ""}
                  onChange={(e) =>
                    change(
                      "estimated_minutes",
                      e.target.value ? Number(e.target.value) : null,
                    )
                  }
                  disabled={!canWrite}
                />
              </div>
            </div>
            <details>
              <summary className="cursor-pointer text-sm font-medium">
                Descripción
              </summary>
              <Textarea
                className="mt-2"
                value={draft.description ?? ""}
                onChange={(e) => change("description", e.target.value || null)}
                disabled={!canWrite}
                rows={4}
              />
            </details>
            <details>
              <summary className="cursor-pointer text-sm font-medium">
                Seguimiento
              </summary>
              <div className="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <Label htmlFor="task-panel-waiting">Esperando a</Label>
                  <Input
                    id="task-panel-waiting"
                    value={draft.waiting_for ?? ""}
                    onChange={(e) =>
                      change("waiting_for", e.target.value || null)
                    }
                    disabled={!canWrite}
                  />
                </div>
                <div>
                  <Label htmlFor="task-panel-followup">Revisar el</Label>
                  <Input
                    id="task-panel-followup"
                    type="date"
                    value={draft.follow_up_date ?? ""}
                    onChange={(e) =>
                      change("follow_up_date", e.target.value || null)
                    }
                    disabled={!canWrite}
                  />
                </div>
              </div>
            </details>
            <details>
              <summary className="cursor-pointer text-sm font-medium">
                Dependencias y recurrencia
              </summary>
                <div className="mt-2 space-y-3">
                {taskQuery.data?.recurring_parent_title && taskQuery.data.recurrence_occurrence_date && (
                  <p className="text-sm text-muted-foreground">
                    Prevista por {taskQuery.data.recurring_parent_title} para {taskQuery.data.recurrence_occurrence_date}. La fecha programada se puede ajustar sin cambiar esta referencia.
                  </p>
                )}
                <div>
                  <Label htmlFor="task-panel-dependency">Depende de</Label>
                  <Select
                    id="task-panel-dependency"
                    value={draft.depends_on ?? ""}
                    onChange={(e) =>
                      change(
                        "depends_on",
                        e.target.value ? Number(e.target.value) : null,
                      )
                    }
                    disabled={!canWrite}
                  >
                    <option value="">Sin dependencia</option>
                    {dependencyTasks
                      .filter((candidate) => candidate.id !== taskId)
                      .map((candidate) => (
                        <option key={candidate.id} value={candidate.id}>
                          {candidate.title}
                        </option>
                      ))}
                  </Select>
                </div>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={draft.is_recurring ?? false}
                    onChange={(event) =>
                      { setRecurrencePreview(null); setDraft((current) => ({
                        ...current,
                        is_recurring: event.target.checked,
                        recurrence_pattern: event.target.checked
                          ? (current.recurrence_pattern ?? "weekly")
                          : null,
                        recurrence_day: event.target.checked
                          ? (current.recurrence_pattern === "monthly"
                            ? Math.min(Math.max(current.recurrence_day ?? 1, 1), 28)
                            : Math.min(Math.max(current.recurrence_day ?? 0, 0), 4))
                          : null,
                        recurrence_end_date: event.target.checked
                          ? current.recurrence_end_date
                          : null,
                        recurrence_anchor_date: event.target.checked
                          ? current.recurrence_anchor_date
                          : null,
                      })); }
                    }
                    disabled={!canWrite}
                  />
                  Repetir tarea
                </label>
                {draft.is_recurring && (
                  <>
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    <div>
                      <Label htmlFor="task-panel-pattern">Patrón</Label>
                      <Select
                        id="task-panel-pattern"
                        value={draft.recurrence_pattern ?? "weekly"}
                        onChange={(e) => {
                          const pattern = e.target.value;
                          setDraft((current) => ({
                            ...current,
                            recurrence_pattern: pattern,
                            recurrence_day: pattern === "monthly"
                              ? Math.min(Math.max(current.recurrence_day ?? 1, 1), 28)
                              : Math.min(Math.max(current.recurrence_day ?? 0, 0), 4),
                            recurrence_anchor_date: pattern === "biweekly" && !(taskQuery.data?.is_recurring && taskQuery.data.recurrence_pattern === "biweekly" && !taskQuery.data.recurrence_anchor_date) && !current.recurrence_anchor_date
                              ? businessToday
                              : current.recurrence_anchor_date,
                          }));
                        }}
                        disabled={!canWrite}
                      >
                        <option value="daily">Diaria</option>
                        <option value="weekly">Semanal</option>
                        <option value="biweekly">Cada dos semanas</option>
                        <option value="monthly">Mensual</option>
                      </Select>
                    </div>
                    <div>
                      <Label htmlFor="task-panel-recurrence-day">Día</Label>
                      {draft.recurrence_pattern === "monthly" ? <Input
                        id="task-panel-recurrence-day"
                        type="number"
                        min="1"
                        max="28"
                        value={draft.recurrence_day ?? 1}
                        onChange={(e) => change("recurrence_day", Number(e.target.value))}
                        disabled={!canWrite}
                      /> : <Select
                        id="task-panel-recurrence-day"
                        value={String(draft.recurrence_day ?? 0)}
                        onChange={(e) => change("recurrence_day", Number(e.target.value))}
                        disabled={!canWrite || draft.recurrence_pattern === "daily"}
                      >
                        <option value="0">Lunes</option><option value="1">Martes</option><option value="2">Miércoles</option><option value="3">Jueves</option><option value="4">Viernes</option>
                      </Select>}
                    </div>
                    <div>
                      <Label htmlFor="task-panel-recurrence-end">
                        Finaliza
                      </Label>
                      <Input
                        id="task-panel-recurrence-end"
                        type="date"
                        value={draft.recurrence_end_date ?? ""}
                        onChange={(e) =>
                          change("recurrence_end_date", e.target.value || null)
                        }
                        disabled={!canWrite}
                      />
                    </div>
                  </div>
                  {draft.recurrence_pattern === "biweekly" && (
                    <div>
                      <Label htmlFor="task-panel-recurrence-anchor">
                        Repetir cada dos semanas desde
                      </Label>
                      <Input
                        id="task-panel-recurrence-anchor"
                        type="date"
                        value={draft.recurrence_anchor_date ?? ""}
                        onChange={(e) =>
                          change("recurrence_anchor_date", e.target.value || null)
                        }
                        disabled={!canWrite}
                      />
                      {!draft.recurrence_anchor_date && taskId && (
                        <p className="mt-1 text-xs text-muted-foreground">
                          Plantilla antigua: mantiene el calendario actual. Compara las próximas fechas antes de cambiarlo.
                        </p>
                      )}
                    </div>
                  )}
                  <div className="flex flex-wrap items-center gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => previewRecurrence.mutate()}
                      disabled={!canWrite || previewRecurrence.isPending}
                    >
                      Ver próximas fechas
                    </Button>
                    {draft.recurrence_pattern === "biweekly" && taskId && (!draft.recurrence_anchor_date || legacyAnchorChange) && (
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => compareLegacyCalendar.mutate()}
                        disabled={!canWrite || compareLegacyCalendar.isPending}
                      >
                        Comparar calendario actual
                      </Button>
                    )}
                    {taskId && taskQuery.data?.is_recurring && (
                      <Button
                        type="button"
                        size="sm"
                        onClick={() => toggleRecurrencePause.mutate({ id: taskId, paused: !recurrencePaused })}
                        disabled={!canWrite || toggleRecurrencePause.isPending}
                      >
                        {recurrencePaused ? <Play className="mr-1 size-4" /> : <Pause className="mr-1 size-4" />}
                        {recurrencePaused ? "Reanudar recurrencia" : "Pausar recurrencia"}
                      </Button>
                    )}
                  </div>
                  {recurrenceSummary && (
                    <div className="rounded-md border border-border p-3 text-sm">
                      <p className="font-medium">{recurrenceSummary.label}</p>
                      {recurrenceSummary.reason && <p className="mt-1 text-muted-foreground">{recurrenceSummary.reason}</p>}
                      {recurrenceSummary.next_dates.length > 0 && <p className="mt-1 text-muted-foreground">Próximas: {recurrenceSummary.next_dates.join(" · ")}</p>}
                    </div>
                  )}
                  {legacyComparison && (legacyComparison.sourceKey === legacySourceKey || comparisonReady) && (
                    <div className="space-y-3 rounded-md border border-border p-3 text-sm">
                      <p className="font-medium">{recurrencePaused ? "Fechas al reanudar" : "Antes de cambiar la recurrencia"}</p>
                      <div className="grid gap-3 sm:grid-cols-2">
                        <div><p className="font-medium">Calendario actual</p><p className="text-muted-foreground">{legacyComparison.current.next_dates.join(" · ") || "Sin próximas fechas"}</p></div>
                        <div><p className="font-medium">Con este cambio</p><p className="text-muted-foreground">{legacyComparison.proposed.next_dates.join(" · ") || "Sin próximas fechas"}</p></div>
                      </div>
                      {!draft.recurrence_anchor_date && <Button type="button" size="sm" onClick={() => change("recurrence_anchor_date", legacyComparison.anchor)} disabled={!canWrite}>Aplicar este cambio</Button>}
                    </div>
                  )}
                  {legacyAnchorChange && !comparisonReady && <p role="alert" className="text-sm text-muted-foreground">Compara el calendario actual y el nuevo antes de guardar este cambio.</p>}
                  </>
                )}
              </div>
            </details>
            {taskId && (
              <details
                open={secondaryOpen}
                onToggle={(event) => setSecondaryOpen(event.currentTarget.open)}
              >
                <summary className="cursor-pointer text-sm font-medium">
                  Checklist, comentarios y archivos
                </summary>
                <div className="mt-3 space-y-5">
                  <section className="space-y-2">
                    <h3 className="text-sm font-medium">Checklist</h3>
                    {checklistQuery.isError && (
                      <LoadError
                        label="checklist"
                        onRetry={() => checklistQuery.refetch()}
                      />
                    )}
                    {checklistQuery.isLoading && (
                      <p className="text-sm text-muted-foreground">
                        Cargando checklist…
                      </p>
                    )}
                    {checklistQuery.data?.map((item) => (
                      <div
                        key={item.id}
                        className="space-y-2 rounded-md border p-2"
                      >
                        <div className="flex items-center gap-2">
                          <input
                            aria-label={`Completar ${item.text}`}
                            type="checkbox"
                            checked={item.is_done}
                            disabled={!canWrite || updateChecklist.isPending}
                            onChange={(event) =>
                              updateChecklist.mutate({
                                itemId: item.id,
                                data: { is_done: event.target.checked },
                              })
                            }
                          />
                          <span
                            className={`flex-1 text-sm ${item.is_done ? "line-through text-muted-foreground" : ""}`}
                          >
                            {item.text}
                          </span>
                          {canWrite && (
                            <Button
                              type="button"
                              size="icon"
                              variant="ghost"
                              aria-label={`Eliminar ${item.text}`}
                              disabled={deleteChecklist.isPending}
                              onClick={() => deleteChecklist.mutate(item.id)}
                            >
                              <Trash2 className="h-3 w-3" />
                            </Button>
                          )}
                        </div>
                        <div className="grid gap-2 sm:grid-cols-2">
                          <Textarea
                            aria-label={`Descripción de ${item.text}`}
                            defaultValue={item.description ?? ""}
                            disabled={!canWrite || updateChecklist.isPending}
                            onBlur={(event) =>
                              updateChecklist.mutate({
                                itemId: item.id,
                                data: {
                                  description: event.target.value || null,
                                },
                              })
                            }
                          />
                          <div className="space-y-2">
                            <Select
                              aria-label={`Responsable de ${item.text}`}
                              defaultValue={item.assigned_to ?? ""}
                              disabled={!canWrite || updateChecklist.isPending}
                              onChange={(event) =>
                                updateChecklist.mutate({
                                  itemId: item.id,
                                  data: {
                                    assigned_to: event.target.value
                                      ? Number(event.target.value)
                                      : null,
                                  },
                                })
                              }
                            >
                              <option value="">Sin responsable</option>
                              {users.map((user) => (
                                <option key={user.id} value={user.id}>
                                  {user.full_name}
                                </option>
                              ))}
                            </Select>
                            <Input
                              aria-label={`Fecha de ${item.text}`}
                              type="date"
                              defaultValue={item.due_date?.slice(0, 10) ?? ""}
                              disabled={!canWrite || updateChecklist.isPending}
                              onChange={(event) =>
                                updateChecklist.mutate({
                                  itemId: item.id,
                                  data: {
                                    due_date: event.target.value || null,
                                  },
                                })
                              }
                            />
                          </div>
                        </div>
                      </div>
                    ))}
                    {canWrite && (
                      <div className="flex gap-2">
                        <Input
                          aria-label="Nueva entrada de checklist"
                          value={newChecklist}
                          onChange={(event) =>
                            setNewChecklist(event.target.value)
                          }
                        />
                        <Button
                          type="button"
                          aria-label="Añadir al checklist"
                          variant="outline"
                          disabled={
                            addChecklist.isPending || !newChecklist.trim()
                          }
                          onClick={() => addChecklist.mutate()}
                        >
                          <Plus className="h-4 w-4" />
                        </Button>
                      </div>
                    )}
                  </section>
                  <section className="space-y-2">
                    <h3 className="text-sm font-medium">Comentarios</h3>
                    {commentsQuery.isError && (
                      <LoadError
                        label="comentarios"
                        onRetry={() => commentsQuery.refetch()}
                      />
                    )}
                    {commentsQuery.isLoading && (
                      <p className="text-sm text-muted-foreground">
                        Cargando comentarios…
                      </p>
                    )}
                    {commentsQuery.data?.map((item) => (
                      <div
                        key={item.id}
                        className="flex items-start gap-2 rounded bg-muted p-2 text-sm"
                      >
                        <p className="flex-1">
                          <strong>{item.user_name ?? "Usuario"}:</strong>{" "}
                          {item.text}
                        </p>
                        {canWrite && (
                          <Button
                            type="button"
                            size="icon"
                            variant="ghost"
                            aria-label={`Eliminar comentario de ${item.user_name ?? "Usuario"}`}
                            disabled={deleteComment.isPending}
                            onClick={() => deleteComment.mutate(item.id)}
                          >
                            <Trash2 className="h-3 w-3" />
                          </Button>
                        )}
                      </div>
                    ))}
                    {canWrite && (
                      <div className="flex gap-2">
                        <Input
                          aria-label="Nuevo comentario"
                          value={newComment}
                          onChange={(event) =>
                            setNewComment(event.target.value)
                          }
                        />
                        <Button
                          type="button"
                          variant="outline"
                          disabled={addComment.isPending || !newComment.trim()}
                          onClick={() => addComment.mutate()}
                        >
                          Comentar
                        </Button>
                      </div>
                    )}
                  </section>
                  <section className="space-y-2">
                    <h3 className="text-sm font-medium">Archivos</h3>
                    {attachmentsQuery.isError && (
                      <LoadError
                        label="archivos"
                        onRetry={() => attachmentsQuery.refetch()}
                      />
                    )}
                    {attachmentsQuery.isLoading && (
                      <p className="text-sm text-muted-foreground">
                        Cargando archivos…
                      </p>
                    )}
                    {attachmentsQuery.data?.map((item) => (
                      <div
                        key={item.id}
                        className="flex items-center gap-2 text-sm"
                      >
                        <Paperclip className="h-3 w-3" />
                        <span className="flex-1 truncate">{item.name}</span>
                        <Button
                          type="button"
                          size="icon"
                          variant="ghost"
                          aria-label={`Descargar ${item.name}`}
                          onClick={() =>
                            void downloadAttachment(item.id, item.name)
                          }
                        >
                          <Download className="h-3 w-3" />
                        </Button>
                        {canWrite && (
                          <Button
                            type="button"
                            size="icon"
                            variant="ghost"
                            aria-label={`Eliminar archivo ${item.name}`}
                            disabled={deleteAttachment.isPending}
                            onClick={() => deleteAttachment.mutate(item.id)}
                          >
                            <Trash2 className="h-3 w-3" />
                          </Button>
                        )}
                      </div>
                    ))}
                    {canWrite && (
                      <Input
                        aria-label="Adjuntar archivo"
                        type="file"
                        disabled={upload.isPending}
                        onChange={(event) =>
                          event.target.files?.[0] &&
                          upload.mutate(event.target.files[0])
                        }
                      />
                    )}
                  </section>
                </div>
              </details>
            )}
            <div className="flex flex-wrap justify-end gap-2 border-t pt-4">
              {taskId && loadedTask && onOpenTime && canReadTime && (
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => onOpenTime(loadedTask)}
                >
                  <Clock className="h-4 w-4 mr-1" />
                  Ver horas y registrar tiempo
                </Button>
              )}
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
              >
                Cerrar
              </Button>
              {canWrite && (
                <Button
                  type="submit"
                  disabled={save.isPending || !draft.title.trim() || (legacyAnchorChange && !comparisonReady)}
                >
                  {save.isPending ? "Guardando…" : "Guardar"}
                </Button>
              )}
            </div>
          </form>
        )
      )}
    </Dialog>
  );
}
