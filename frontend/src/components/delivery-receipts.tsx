import { useEffect, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { deliveriesApi } from "@/lib/api"
import type { DeliveryReceipt } from "@/lib/types"
import { getErrorMessage } from "@/lib/utils"
import { useAuth } from "@/context/auth-context"
import { Button } from "@/components/ui/button"

const labels: Record<string, string> = {
  pending: "En cola", sending: "Enviando", sent: "Confirmado", failed: "Fallido",
  uncertain: "Sin confirmación", cancelled: "Cancelado", expired: "Caducado",
}

// eslint-disable-next-line react-refresh/only-export-components
export function deliveryToast(receipt: DeliveryReceipt) {
  if (receipt.status === "sent") toast.success(receipt.message)
  else if (receipt.status === "pending" || receipt.status === "sending") toast.info(receipt.message)
  else if (receipt.status === "uncertain") toast.warning(receipt.message)
  else toast.error(receipt.message)
}

type ManualKind = "pm_briefing" | "weekly_report" | "daily_summary" | "custom" | "connection_test"

type ReceiptSource =
  | { sourceKind: "daily" | "digest"; sourceId: number; manualKind?: never; scope?: never }
  | { manualKind: ManualKind; scope?: "mine" | "team"; sourceKind?: never; sourceId?: never }

function ReceiptHistory(props: ReceiptSource) {
  const { user } = useAuth()
  const client = useQueryClient()
  const [review, setReview] = useState<{ receipt: DeliveryReceipt; key: string } | null>(null)
  const [acknowledged, setAcknowledged] = useState(false)
  const key = "manualKind" in props
    ? ["deliveries", "manual", user?.id, props.manualKind, props.scope]
    : ["deliveries", user?.id, props.sourceKind, props.sourceId]
  const query = useQuery({
    queryKey: key,
    queryFn: () => "manualKind" in props
      ? deliveriesApi.listManual(props.manualKind!, props.scope)
      : deliveriesApi.list(props.sourceKind!, props.sourceId!),
    enabled: !!user,
    refetchInterval: (q) => q.state.data?.some((r) => r.worker_enabled && (r.status === "pending" || r.status === "sending")) ? 3000 : false,
    refetchIntervalInBackground: false,
  })
  const mutation = useMutation({
    mutationFn: ({ action, id, reviewKey }: { action: "retry" | "cancel" | "resend"; id: string; reviewKey?: string }) =>
      action === "resend" ? deliveriesApi.resend(id, reviewKey!) : deliveriesApi[action](id),
    onSuccess: (receipt) => {
      deliveryToast(receipt)
      setReview(null)
      setAcknowledged(false)
      client.invalidateQueries({ queryKey: key })
      client.invalidateQueries({ queryKey: ["dailys"] })
      client.invalidateQueries({ queryKey: ["daily-today"] })
    },
    onError: (error) => toast.error(getErrorMessage(error, "No se pudo actualizar el envío")),
  })
  const terminalReceipts = (query.data || []).filter((r) => r.status === "sent").map((r) => r.delivery_id).join(",")
  useEffect(() => {
    if (terminalReceipts && props.sourceKind === "daily") {
      client.invalidateQueries({ queryKey: ["dailys"] })
      client.invalidateQueries({ queryKey: ["daily-today"] })
    }
  }, [terminalReceipts, props.sourceKind, client])

  if (query.isPending) return <p className="text-xs text-muted-foreground">Cargando recibos…</p>
  if (query.isError) return <div role="alert" className="text-sm">No se pudieron cargar los recibos. <Button size="sm" variant="outline" onClick={() => query.refetch()}>Reintentar consulta</Button></div>
  if (!query.data?.length) return <p className="text-xs text-muted-foreground">Sin recibos de envío registrados. Los envíos anteriores pueden no tener recibo.</p>

  return <section className="space-y-3 text-sm" aria-label="Recibos de Discord">
    <h3 className="font-medium">Envíos a Discord</h3>
    {query.data.map((receipt) => <div key={receipt.delivery_id} className="rounded-md border p-3 space-y-2">
      <p role="status"><strong>{labels[receipt.status]}</strong> · {receipt.message}</p>
      {(receipt.title || receipt.destination_label || receipt.period_start) && <p className="text-xs text-muted-foreground">
        {receipt.title}{receipt.destination_label ? ` · ${receipt.destination_label}` : ""}
        {receipt.period_start ? ` · ${receipt.period_start}${receipt.period_end && receipt.period_end !== receipt.period_start ? ` — ${receipt.period_end}` : ""}` : ""}
      </p>}
      {!receipt.worker_enabled && receipt.status === "pending" && <p>El procesamiento está pausado. El mensaje y el borrador están guardados.</p>}
      {receipt.source_changed && <p className="text-amber-600">Este recibo corresponde a una versión anterior. Tu borrador actual se conserva.</p>}
      <ul className="space-y-1 text-xs text-muted-foreground">
        {receipt.steps.map((step, index) => <li key={index}>
          {step.label}: {labels[step.status] || step.status}{step.message_id ? ` · ID Discord ${step.message_id}` : ""}{step.error ? ` · ${step.error}` : ""}
        </li>)}
      </ul>
      <details><summary className="cursor-pointer">Ver el texto de esta versión</summary><pre className="whitespace-pre-wrap break-words mt-2 text-xs max-h-64 overflow-auto">{receipt.content}</pre></details>
      <div className="flex flex-wrap gap-2">
        {receipt.can_retry && <Button size="sm" variant="outline" disabled={mutation.isPending} onClick={() => mutation.mutate({ action: "retry", id: receipt.delivery_id })}>Reintentar partes pendientes</Button>}
        {receipt.can_cancel && <Button size="sm" variant="outline" disabled={mutation.isPending} onClick={() => mutation.mutate({ action: "cancel", id: receipt.delivery_id })}>Cancelar envío</Button>}
        {receipt.can_resend && <Button size="sm" variant="outline" disabled={mutation.isPending} onClick={() => { setReview({ receipt, key: crypto.randomUUID() }); setAcknowledged(false) }}>Revisar posible reenvío</Button>}
      </div>
      {review?.receipt.delivery_id === receipt.delivery_id && <div className="rounded border border-amber-500 p-3 space-y-3" role="group" aria-label="Revisar reenvío incierto">
        <p>Comprueba Discord primero. El mensaje pudo llegar y este reenvío podría duplicarlo. Se reenviará exactamente este texto, aunque tu borrador haya cambiado:</p>
        <pre className="whitespace-pre-wrap break-words max-h-64 overflow-auto text-xs">{review.receipt.content}</pre>
        <label className="flex items-start gap-2"><input type="checkbox" checked={acknowledged} onChange={(e) => setAcknowledged(e.target.checked)} />He revisado Discord y acepto el posible duplicado.</label>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" disabled={!acknowledged || mutation.isPending} onClick={() => mutation.mutate({ action: "resend", id: review.receipt.delivery_id, reviewKey: review.key })}>Crear nuevo envío de este texto</Button>
          <Button size="sm" variant="ghost" disabled={mutation.isPending} onClick={() => setReview(null)}>Volver sin reenviar</Button>
        </div>
      </div>}
    </div>)}
  </section>
}

export function DeliveryReceipts(props: { sourceKind: "daily" | "digest"; sourceId: number }) {
  return <ReceiptHistory {...props} />
}

export function ManualDeliveryReceipts({ kind, scope }: { kind: ManualKind; scope?: "mine" | "team" }) {
  return <ReceiptHistory manualKind={kind} scope={scope} />
}
