import { Loader2 } from "lucide-react"
import type { UploadState } from "@/hooks/use-file-upload"

/** Línea "Subiendo archivo… 40 %" con barra; nada si no hay subida en curso. */
export function UploadProgress({ state }: { state: UploadState | null }) {
  if (!state) return null
  const done = state.percent === 100
  return (
    <div className="space-y-1 text-xs text-muted-foreground" role="status" aria-live="polite">
      <div className="flex items-center gap-2">
        <Loader2 className="h-3 w-3 animate-spin shrink-0" />
        <span className="truncate flex-1">
          {done ? "Guardando" : "Subiendo"} {state.name}…
        </span>
        {state.percent !== null && <span className="mono">{state.percent} %</span>}
      </div>
      <div
        className="h-1 w-full overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-label={`Subida de ${state.name}`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={state.percent ?? undefined}
      >
        <div
          className={state.percent === null ? "h-full w-1/3 animate-pulse bg-brand" : "h-full bg-brand transition-[width] duration-150"}
          style={state.percent === null ? undefined : { width: `${state.percent}%` }}
        />
      </div>
    </div>
  )
}
