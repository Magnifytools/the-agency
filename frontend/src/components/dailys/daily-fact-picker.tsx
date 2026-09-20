import { Link } from "react-router-dom"
import { Clock3, ListChecks } from "lucide-react"
import type { DailyFact } from "@/lib/types"

const labels: Record<DailyFact["kind"], string> = {
  task_completed: "Completada",
  time_logged: "Tiempo registrado",
  task_advanced: "Avanzada",
  task_waiting: "En espera",
  next_step: "Próximo paso",
}

function factMeta(fact: DailyFact) {
  const parts = [labels[fact.kind]]
  if (fact.minutes != null) parts.push(`${Math.round(fact.minutes)} min reales`)
  if (fact.client_name) parts.push(fact.client_name)
  if (fact.project_name) parts.push(fact.project_name)
  return parts.join(" · ")
}

export function DailyFactPicker({ facts, selected, onSelectedChange, maxSelected = 500, canOpenSources = false, readOnly = false }: {
  facts: DailyFact[]
  selected: string[]
  onSelectedChange: (keys: string[]) => void
  maxSelected?: number
  canOpenSources?: boolean
  readOnly?: boolean
}) {
  if (!facts.length) return <p className="text-sm text-muted-foreground">No hay hechos registrados para esta fecha. Puedes escribir notas libres.</p>
  return <ul className="divide-y rounded-lg border" aria-label="Hechos del día">
    {facts.map((fact) => {
      const checked = selected.includes(fact.key)
      return <li key={fact.key} className="flex gap-3 p-3">
        <input
          id={`daily-fact-${fact.key}`}
          type="checkbox"
          className="mt-1 size-4"
          checked={checked}
          disabled={readOnly || (!checked && selected.length >= maxSelected)}
          onChange={() => onSelectedChange(checked ? selected.filter((key) => key !== fact.key) : [...selected, fact.key])}
        />
        <div className="min-w-0 flex-1">
          <label htmlFor={`daily-fact-${fact.key}`} className="cursor-pointer text-sm font-medium">{fact.title}</label>
          <p className="mt-0.5 text-xs text-muted-foreground">{factMeta(fact)}{fact.detail ? ` · ${fact.detail}` : ""}</p>
          {fact.href && canOpenSources && <Link to={fact.href} className="mt-1 inline-flex text-xs text-primary underline underline-offset-2">Abrir fuente</Link>}
        </div>
        {fact.kind === "time_logged" ? <Clock3 aria-hidden className="mt-0.5 size-4 text-muted-foreground" /> : <ListChecks aria-hidden className="mt-0.5 size-4 text-muted-foreground" />}
      </li>
    })}
  </ul>
}
