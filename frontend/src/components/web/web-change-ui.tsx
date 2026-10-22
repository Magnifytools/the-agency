import { useEffect, useId, useRef, type ReactNode } from "react"
import { createPortal } from "react-dom"
import { X } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import type { WebSeverity, WebWatch } from "@/lib/types"
import { SEVERITY_LABEL, watchHealth, type WatchHealth } from "@/components/web/change-format"

const HEALTH: Record<WatchHealth, { label: string; variant: "default" | "success" | "destructive" | "warning" | "secondary" | "outline"; hint: string }> = {
  stable: { label: "Estable", variant: "success", hint: "La última comprobación fue bien." },
  error: { label: "Error", variant: "destructive", hint: "La última comprobación falló." },
  review: { label: "Revisar configuración", variant: "warning", hint: "La sección acotada ya no existe o la página necesita JavaScript." },
  checking: { label: "Comprobando…", variant: "default", hint: "El barrido la está mirando ahora." },
  unchecked: { label: "Sin comprobar", variant: "secondary", hint: "Todavía no se ha mirado." },
  paused: { label: "Pausada", variant: "outline", hint: "No entra en el barrido." },
  archived: { label: "Archivada", variant: "outline", hint: "Fuera de la lista y del barrido, con su historial." },
}

export function WatchHealthBadge({ watch }: { watch: WebWatch }) {
  const { label, variant, hint } = HEALTH[watchHealth(watch)]
  return <Badge variant={variant} title={hint}>{label}</Badge>
}

const SEVERITY_VARIANT: Record<WebSeverity, "destructive" | "warning" | "secondary"> = {
  critical: "destructive",
  warning: "warning",
  info: "secondary",
}

export function SeverityBadge({ severity }: { severity: WebSeverity }) {
  return <Badge variant={SEVERITY_VARIANT[severity]}>{SEVERITY_LABEL[severity]}</Badge>
}

/** Borde izquierdo por severidad para filas sin revisar. */
export const SEVERITY_EDGE: Record<WebSeverity, string> = {
  critical: "border-l-2 border-l-red-500",
  warning: "border-l-2 border-l-amber-500",
  info: "border-l-2 border-l-slate-500",
}

export interface SegmentOption<T extends string> {
  id: T
  label: string
  count?: number
}

/**
 * Control segmentado: un filtro tiene que PARECER un control (lección 0decies
 * de Vigil: los filtros funcionaban, pero eran botones fantasma y nadie los
 * usaba). Cada opción lleva su recuento; quien lo pinta decide que ignore el
 * filtro activo, o al pulsar uno los demás dirían 0.
 */
export function Segmented<T extends string>({ label, options, value, onChange }: {
  label: string
  options: SegmentOption<T>[]
  value: T
  onChange: (value: T) => void
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex flex-wrap rounded-[10px] border border-border bg-background p-0.5">
      {options.map((option) => {
        const active = option.id === value
        return (
          <button
            key={option.id}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(option.id)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-[8px] px-3 h-8 text-xs font-semibold transition-colors duration-150",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand",
              active ? "bg-card text-foreground shadow-sm ring-1 ring-border" : "text-muted-foreground hover:text-foreground",
              option.count === 0 && !active && "opacity-60",
            )}
          >
            {option.label}
            {option.count !== undefined && (
              <span className={cn("mono rounded px-1.5 text-[11px]", active ? "bg-brand/15 text-brand" : "bg-muted/40")}>
                {option.count}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}

/** Panel lateral (a pantalla completa en móvil). Escape y el fondo lo cierran. */
export function WebDrawer({ open, onClose, title, children }: {
  open: boolean
  onClose: () => void
  title: ReactNode
  children: ReactNode
}) {
  const titleId = useId()
  const panelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const previous = document.activeElement as HTMLElement | null
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation()
        onClose()
      }
    }
    document.addEventListener("keydown", onKey)
    document.body.style.overflow = "hidden"
    panelRef.current?.focus()
    return () => {
      document.removeEventListener("keydown", onKey)
      document.body.style.overflow = ""
      previous?.focus?.()
    }
  }, [open, onClose])

  if (!open) return null
  return createPortal(
    <div className="fixed inset-0 z-[60] flex justify-end">
      <div className="fixed inset-0 bg-black/60" onClick={onClose} aria-hidden="true" />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="relative z-10 h-full w-full sm:max-w-2xl overflow-y-auto border-l border-border bg-card p-4 sm:p-6 shadow-2xl focus:outline-none"
      >
        <div className="flex items-start justify-between gap-3 mb-4">
          <h2 id={titleId} className="min-w-0 text-lg font-semibold break-all">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Cerrar"
            className="shrink-0 rounded-sm text-muted-foreground hover:text-foreground transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  )
}

/** Una línea de diff (.mono): verde lo que entra, rojo lo que sale. */
export function DiffLine({ op, children, pre = false }: { op: "+" | "-" | " " | "…"; children: ReactNode; pre?: boolean }) {
  return (
    <div
      className={cn(
        "px-3 py-0.5",
        pre ? "whitespace-pre" : "break-words",
        op === "+" && "bg-green-500/10 text-green-300",
        op === "-" && "bg-red-500/10 text-red-300",
        (op === " " || op === "…") && "text-muted-foreground",
      )}
    >
      <span className="select-none opacity-60 mr-2" aria-hidden="true">{op === "…" ? "⋯" : op}</span>
      <span className="sr-only">{op === "+" ? "Añadido: " : op === "-" ? "Quitado: " : ""}</span>
      {children}
    </div>
  )
}
