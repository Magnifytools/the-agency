import { useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "react-router-dom"
import { AlertTriangle, CheckCircle2, RotateCcw, XCircle } from "lucide-react"
import { toast } from "sonner"
import { projectsApi } from "@/lib/api"
import type { Project, ProjectClosePreview, ProjectReopenPreview } from "@/lib/types"
import { invalidateProjectChange, projectKeys } from "@/lib/query-keys"
import { getErrorMessage } from "@/lib/utils"
import { useAuth } from "@/context/auth-context"
import { Button } from "@/components/ui/button"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"

type LifecycleAction = "completed" | "cancelled" | "reopen"
type LifecyclePreview = ProjectClosePreview | ProjectReopenPreview

function lifecycleError(error: unknown) {
  return (error as { response?: { status?: number; data?: { detail?: { code?: string; current_preview?: LifecyclePreview } } } })?.response?.data?.detail
}

function actionCopy(action: LifecycleAction) {
  if (action === "completed") {
    return {
      title: "Cerrar como terminado",
      description: "Revisa que no queda trabajo operativo antes de archivar el proyecto.",
      confirm: "Cerrar proyecto",
      success: "Proyecto archivado como terminado",
      icon: CheckCircle2,
    }
  }
  if (action === "cancelled") {
    return {
      title: "Cancelar y archivar",
      description: "Cancelar no elimina tareas, horas ni deuda pendiente. Revisa el trabajo abierto antes de continuar.",
      confirm: "Cancelar proyecto",
      success: "Proyecto cancelado y archivado",
      icon: XCircle,
    }
  }
  return {
    title: "Reabrir proyecto",
    description: "El proyecto volverá a estar activo. Las plantillas pausadas manualmente seguirán pausadas.",
    confirm: "Reabrir proyecto",
    success: "Proyecto reabierto",
    icon: RotateCcw,
  }
}

function recurrenceMessage(recurrence: LifecyclePreview["recurrence"], reopening: boolean) {
  if (recurrence.templates === 0) return null
  if (reopening) {
    return `${recurrence.templates} plantilla${recurrence.templates === 1 ? "" : "s"}: ${recurrence.suppressed_after_close} no pausada${recurrence.suppressed_after_close === 1 ? "" : "s"} volverá${recurrence.suppressed_after_close === 1 ? "" : "n"} a crear tareas desde hoy. ${recurrence.paused} pausa${recurrence.paused === 1 ? "" : "s"} manual${recurrence.paused === 1 ? "" : "es"} se conserva${recurrence.paused === 1 ? "" : "n"}.`
  }
  return `${recurrence.templates} plantilla${recurrence.templates === 1 ? "" : "s"} recurrente${recurrence.templates === 1 ? "" : "s"}; ${recurrence.suppressed_after_close} no pausada${recurrence.suppressed_after_close === 1 ? "" : "s"} dejará${recurrence.suppressed_after_close === 1 ? "" : "n"} de crear tareas mientras el proyecto esté archivado. No se modifican sus pausas manuales.`
}

function isReopenPreview(preview: LifecyclePreview): preview is ProjectReopenPreview {
  return "can_reopen" in preview
}

export function ProjectLifecycleDialog({
  project,
  action,
  open,
  onOpenChange,
}: {
  project: Project
  action: LifecycleAction
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const { user, hasPermission } = useAuth()
  const [conflict, setConflict] = useState<{ scope: string; message: string } | null>(null)
  const [accessDenied, setAccessDenied] = useState<{ scope: string; at: number } | null>(null)
  const reopening = action === "reopen"
  const copy = actionCopy(action)
  const permissionSignature = useMemo(() => (user?.permissions ?? [])
    .map((permission) => `${permission.module}:${permission.can_read ? 1 : 0}:${permission.can_write ? 1 : 0}`)
    .sort()
    .join("|"), [user?.permissions])
  const scope = `${user?.id ?? "anonymous"}:${permissionSignature}:${project.id}:${action}:${project.updated_at}`
  const previewKey = ["projects", "lifecycle-preview", user?.id ?? "anonymous", permissionSignature, project.id, action, project.updated_at] as const
  const previewQuery = useQuery<LifecyclePreview>({
    queryKey: previewKey,
    queryFn: () => reopening ? projectsApi.reopenPreview(project.id) : projectsApi.closePreview(project.id, action),
    enabled: open && hasPermission("projects", true),
    retry: false,
  })

  const canWriteProjects = hasPermission("projects", true)
  const accessDeniedAt = accessDenied?.scope === scope ? accessDenied.at : null
  const accessStillDenied = !!accessDeniedAt && !(previewQuery.isSuccess && !previewQuery.isFetching && previewQuery.dataUpdatedAt > accessDeniedAt)
  const conflictMessage = conflict?.scope === scope ? conflict.message : null
  const preview = !canWriteProjects || accessStillDenied || previewQuery.isError || previewQuery.isFetching ? null : previewQuery.data
  const canConfirm = preview && (isReopenPreview(preview) ? preview.can_reopen : preview.can_close)
  const mutation = useMutation({
    mutationFn: () => {
      if (!preview) throw new Error("La revisión aún no está disponible")
      const request = {
        expected_updated_at: preview.expected_updated_at,
        preview_revision: preview.preview_revision,
      }
      return reopening
        ? projectsApi.reopen(project.id, request)
        : projectsApi.close(project.id, { ...request, target: action })
    },
    onSuccess: async (updated) => {
      await invalidateProjectChange(queryClient, { clientId: updated.client_id, projectId: updated.id })
      queryClient.setQueryData(projectKeys.detail(updated.id), updated)
      toast.success(copy.success)
      onOpenChange(false)
    },
    onError: (error) => {
      const detail = lifecycleError(error)
      const status = (error as { response?: { status?: number } })?.response?.status
      if (status === 401 || status === 403) {
        setAccessDenied({ scope, at: Date.now() })
        setConflict({ scope, message: "Tus permisos cambiaron. Vuelve a comprobar el estado antes de continuar." })
        queryClient.removeQueries({ queryKey: previewKey, exact: true })
        void previewQuery.refetch()
        return
      }
      if (detail?.current_preview) {
        setConflict({ scope, message: "El proyecto cambió mientras revisabas la decisión. Se ha actualizado la revisión; confirma de nuevo si sigue siendo válida." })
        void previewQuery.refetch()
        return
      }
      if (status === 409) {
        void invalidateProjectChange(queryClient, { clientId: project.client_id, projectId: project.id })
        toast.error(getErrorMessage(error, "El proyecto cambió antes de confirmar la decisión. Vuelve a revisar su estado."))
        onOpenChange(false)
        return
      }
      toast.error(getErrorMessage(error, "No se pudo aplicar el cambio de proyecto"))
    },
  })

  const Icon = copy.icon
  const blockers = !reopening && preview && "blockers" in preview ? preview.blockers : null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader>
        <DialogTitle>{copy.title}</DialogTitle>
      </DialogHeader>
      <div className="space-y-4">
        <p className="text-sm text-muted-foreground">{copy.description}</p>
        {(previewQuery.isLoading || previewQuery.isFetching) && !preview && <p role="status" className="text-sm text-muted-foreground">Comprobando el estado actual del proyecto…</p>}
        {previewQuery.isError && !preview && (
          <div role="alert" className="space-y-2 rounded-lg border border-destructive/40 p-3 text-sm">
            <p>No se pudo comprobar si el proyecto se puede cerrar o reabrir.</p>
            <Button type="button" variant="outline" size="sm" onClick={() => void previewQuery.refetch()} disabled={previewQuery.isFetching || !canWriteProjects}>Reintentar</Button>
          </div>
        )}
        {conflictMessage && <p role="alert" className="rounded-lg border border-amber-400/50 p-3 text-sm">{conflictMessage}</p>}
        {preview && (
          <>
            {blockers && !isReopenPreview(preview) && !preview.can_close && (
              <div role="alert" className="space-y-3 rounded-lg border border-amber-400/50 p-3 text-sm">
                <div className="flex gap-2"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" /><p>Queda trabajo operativo. Resuélvelo con las acciones habituales antes de archivar.</p></div>
                {blockers.active_tasks.total > 0 && <BlockerList label={`${blockers.active_tasks.total} tarea${blockers.active_tasks.total === 1 ? " activa" : "s activas"}`} rows={blockers.active_tasks.sample} />}
                {blockers.active_timers.total > 0 && <BlockerList label={`${blockers.active_timers.total} temporizador${blockers.active_timers.total === 1 ? " activo" : "es activos"}`} rows={blockers.active_timers.sample} />}
                {(blockers.waiting_count > 0 || blockers.in_review_count > 0) && <p className="text-muted-foreground">Incluye {blockers.waiting_count} en espera y {blockers.in_review_count} en revisión.</p>}
              </div>
            )}
            {reopening && <p className="rounded-lg border border-border p-3 text-sm">{(preview as ProjectReopenPreview).message}</p>}
            {recurrenceMessage(preview.recurrence, reopening) && <p className="rounded-lg border border-border p-3 text-sm text-muted-foreground">{recurrenceMessage(preview.recurrence, reopening)}</p>}
          </>
        )}
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancelar</Button>
          <Button type="button" variant={action === "cancelled" ? "destructive" : "default"} onClick={() => mutation.mutate()} disabled={!canConfirm || mutation.isPending}>
            <Icon className="mr-2 h-4 w-4" />{mutation.isPending ? "Guardando…" : copy.confirm}
          </Button>
        </div>
      </div>
    </Dialog>
  )
}

function BlockerList({ label, rows }: { label: string; rows: Array<{ id: number; href: string | null; title?: string }> }) {
  return (
    <div className="space-y-1">
      <p className="font-medium">{label}</p>
      {rows.length > 0 && <ul className="list-inside list-disc text-muted-foreground">
        {rows.map((row) => <li key={row.id}>{row.href ? <Link className="underline hover:text-foreground" to={row.href}>{row.title || `Temporizador #${row.id}`}</Link> : (row.title || "Detalle no disponible con tus permisos")}</li>)}
      </ul>}
    </div>
  )
}
