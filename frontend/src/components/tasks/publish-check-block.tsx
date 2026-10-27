import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { CheckCircle2, RefreshCw, XCircle } from "lucide-react"
import { tasksApi } from "@/lib/api"
import type { TaskPublishCheck } from "@/lib/types"
import { getErrorMessage } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { formatInstant } from "@/components/web/uptime-status"

export const publishCheckKey = (taskId: number) => ["task-publish-check", taskId] as const

const WAITING: TaskPublishCheck["status"][] = ["waiting", "pending"]

/**
 * Revisión tras publicar: al completar una tarea con enlace a la web del
 * cliente, el servidor comprueba esa página (responde, indexable, canonical,
 * title y description). No bloquea el cierre: se mira en segundo plano.
 */
export function PublishCheckBlock({ taskId, canWrite }: { taskId: number; canWrite: boolean }) {
  const qc = useQueryClient()
  const query = useQuery({
    queryKey: publishCheckKey(taskId),
    queryFn: () => tasksApi.publishCheck.get(taskId),
    refetchInterval: (q) => (q.state.data && WAITING.includes(q.state.data.status) ? 15_000 : false),
  })
  const retry = useMutation({
    mutationFn: () => tasksApi.publishCheck.retry(taskId),
    onSuccess: (data) => {
      qc.setQueryData(publishCheckKey(taskId), data)
      toast.success("Se volverá a comprobar en menos de un minuto")
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })
  const data = query.data
  if (!data || data.status === "none") return null

  const retryButton = canWrite && data.enabled && (
    <Button type="button" size="sm" variant="outline" disabled={retry.isPending} onClick={() => retry.mutate()}>
      <RefreshCw className="h-3.5 w-3.5 mr-1" /> {retry.isPending ? "Poniendo en cola…" : "Volver a comprobar"}
    </Button>
  )

  let body: React.ReactNode
  switch (data.status) {
    case "disabled":
      body = <p className="text-muted-foreground">La revisión de la página publicada está apagada en el servidor.</p>
      break
    case "waiting":
      body = <p className="text-muted-foreground">Comprobando la página publicada… (tarda menos de un minuto).</p>
      break
    case "pending":
      body = (
        <p className="text-muted-foreground">
          {data.attempts
            ? `La página no respondió bien; se vuelve a intentar ${data.next_attempt_at ? `el ${formatInstant(data.next_attempt_at)}` : "en breve"}.`
            : "En cola: se comprobará en menos de un minuto."}
        </p>
      )
      break
    case "skipped":
      body = <p className="text-muted-foreground">No se revisa: {data.error ?? "el enlace no es de la web del cliente."}</p>
      break
    case "unreachable":
      body = (
        <div className="space-y-2">
          <p className="text-red-600">No se pudo abrir la página ({data.error ?? "sin respuesta"}) tras {data.attempts} intentos.</p>
          {retryButton}
        </div>
      )
      break
    default:
      body = (
        <div className="space-y-2">
          <ul className="space-y-1">
            {(data.results ?? []).map((item) => (
              <li key={item.code} className="flex items-start gap-2">
                {item.ok
                  ? <CheckCircle2 aria-label="Correcto" className="mt-0.5 h-4 w-4 shrink-0 text-green-500" />
                  : <XCircle aria-label="Falla" className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />}
                <span><span className="font-medium">{item.label}.</span> <span className="text-muted-foreground break-all">{item.detail}</span></span>
              </li>
            ))}
          </ul>
          {data.status === "problems" && retryButton}
        </div>
      )
  }

  const title = data.status === "ok" ? "Página publicada: todo correcto"
    : data.status === "problems" ? "Página publicada: hay que revisar algo"
    : "Revisión de la página publicada"
  return (
    <section aria-label="Revisión de la página publicada" className="space-y-2 rounded-md border border-border p-3 text-sm">
      <p className="font-medium">{title}</p>
      {body}
      {data.checked_at && data.status !== "skipped" && (
        <p className="text-xs text-muted-foreground">Comprobado el {formatInstant(data.checked_at)}.</p>
      )}
    </section>
  )
}
