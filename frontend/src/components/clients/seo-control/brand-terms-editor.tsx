import { useState, type KeyboardEvent } from "react"
import { Plus, Sparkles, Tag, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { MAX_BRAND_TERMS, brandTermProblem, suggestBrandTerms } from "@/lib/seo-control"

interface Props {
  value: string[]
  onChange: (terms: string[]) => void
  disabled?: boolean
  client: { name: string; website?: string | null; gsc_url?: string | null }
  /** URL que se está escribiendo (aún sin guardar): también sirve para sugerir. */
  gscDraft?: string
}

/**
 * Términos de marca del cliente (Control SEO). Chips + "Sugerir": la
 * sugerencia sólo propone; nada se guarda hasta aceptarla y pulsar Guardar.
 */
export function BrandTermsEditor({ value, onChange, disabled, client, gscDraft }: Props) {
  const [draft, setDraft] = useState("")
  const [problem, setProblem] = useState<string | null>(null)
  const [suggestions, setSuggestions] = useState<string[] | null>(null)

  const add = (raw: string) => {
    const term = raw.split(/\s+/).filter(Boolean).join(" ")
    if (!term) return
    const issue = brandTermProblem(term, value)
    setProblem(issue)
    if (issue) return
    onChange([...value, term])
    setDraft("")
    setSuggestions((current) => current?.filter((s) => s !== term) ?? null)
  }

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault()
      add(draft)
    } else if (event.key === "Backspace" && !draft && value.length > 0) {
      onChange(value.slice(0, -1))
    }
  }

  const suggest = () => {
    setProblem(null)
    setSuggestions(suggestBrandTerms({ ...client, gsc_url: gscDraft?.trim() || client.gsc_url }, value))
  }

  return (
    <div>
      <Label htmlFor="brand-terms-input" className="flex items-center gap-1.5">
        <Tag className="h-3.5 w-3.5 text-muted-foreground" />
        Términos de marca
      </Label>
      <div className="mt-1 flex flex-wrap items-center gap-1.5 rounded-[10px] border border-border bg-background px-2 py-1.5">
        {value.map((term) => (
          <span key={term} className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs">
            {term}
            {!disabled && (
              <button type="button" aria-label={`Quitar ${term}`} onClick={() => onChange(value.filter((t) => t !== term))}>
                <X className="h-3 w-3" />
              </button>
            )}
          </span>
        ))}
        {!disabled && value.length < MAX_BRAND_TERMS && (
          <Input
            id="brand-terms-input"
            value={draft}
            onChange={(e) => { setDraft(e.target.value); setProblem(null) }}
            onKeyDown={onKeyDown}
            onBlur={() => draft.trim() && add(draft)}
            placeholder={value.length ? "Añadir otro…" : "nombre de la marca, dominio…"}
            className="h-7 flex-1 min-w-[140px] border-0 px-1 text-sm focus-visible:ring-0"
          />
        )}
      </div>
      {problem && <p role="alert" className="text-[11px] text-red-500 mt-1">{problem}</p>}
      {!disabled && (
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          <Button type="button" size="sm" variant="ghost" className="h-7 text-xs" onClick={suggest}>
            <Sparkles className="h-3.5 w-3.5 mr-1" /> Sugerir
          </Button>
          {suggestions?.length === 0 && <span className="text-[11px] text-muted-foreground">Nada nuevo que sugerir.</span>}
          {suggestions?.map((term) => (
            <button
              key={term}
              type="button"
              onClick={() => add(term)}
              aria-label={`Añadir ${term}`}
              className="inline-flex items-center gap-1 rounded-full border border-dashed border-border px-2 py-0.5 text-xs hover:bg-muted"
            >
              <Plus className="h-3 w-3" /> {term}
            </button>
          ))}
        </div>
      )}
      <p className="text-[11px] text-muted-foreground mt-1">
        Una búsqueda es de marca si contiene alguno (sin acentos ni mayúsculas, con o sin espacios). Mínimo 3 caracteres, hasta {MAX_BRAND_TERMS}.
      </p>
    </div>
  )
}
