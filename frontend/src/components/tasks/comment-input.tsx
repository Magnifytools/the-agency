import { useId, useRef, useState } from "react"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { activeMention, insertMention, mentionedIds, type MentionCandidate } from "@/lib/mentions"

interface Props {
  value: string
  onChange: (value: string) => void
  candidates: MentionCandidate[]
  onSubmit: (text: string, mentionIds: number[]) => void
  pending?: boolean
}

/**
 * Caja de comentario con @menciones: al escribir @ sale la lista de personas;
 * ↑/↓ para elegir, Enter o Tab para ponerla, Escape para cerrarla. Fuera de la
 * lista, Enter publica (y no guarda el formulario de la tarea que la envuelve).
 */
export function CommentInput({ value, onChange, candidates, onSubmit, pending = false }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const listId = useId()
  const [caret, setCaret] = useState(0)
  const [highlight, setHighlight] = useState(0)
  const [dismissedAt, setDismissedAt] = useState<number | null>(null)
  const [picked, setPicked] = useState<MentionCandidate[]>([])

  const mention = activeMention(value, caret)
  const matches = mention
    ? candidates.filter((candidate) => {
      const query = mention.query.toLocaleLowerCase("es")
      return candidate.name.toLocaleLowerCase("es").startsWith(query)
        || candidate.fullName.toLocaleLowerCase("es").includes(query)
    }).slice(0, 6)
    : []
  const open = !!mention && matches.length > 0 && dismissedAt !== mention.start
  const active = Math.min(highlight, matches.length - 1)

  const choose = (candidate: MentionCandidate) => {
    if (!mention) return
    const next = insertMention(value, mention.start, caret, candidate.name)
    onChange(next.text)
    setPicked((current) => [...current.filter((item) => item.id !== candidate.id), candidate])
    setCaret(next.caret)
    requestAnimationFrame(() => {
      inputRef.current?.focus()
      inputRef.current?.setSelectionRange(next.caret, next.caret)
    })
  }
  const submit = () => {
    if (!value.trim() || pending) return
    onSubmit(value.trim(), mentionedIds(value, picked))
  }

  return (
    <div className="flex gap-2">
      <div className="relative flex-1">
        <Input
          ref={inputRef}
          aria-label="Nuevo comentario"
          placeholder="Escribe un comentario; @ para mencionar"
          value={value}
          role="combobox"
          aria-expanded={open}
          aria-controls={open ? listId : undefined}
          aria-autocomplete="list"
          aria-activedescendant={open ? `${listId}-${matches[active].id}` : undefined}
          onChange={(event) => {
            onChange(event.target.value)
            setCaret(event.target.selectionStart ?? event.target.value.length)
            setHighlight(0)
            setDismissedAt(null)
          }}
          onSelect={(event) => setCaret(event.currentTarget.selectionStart ?? 0)}
          onKeyDown={(event) => {
            if (open && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
              event.preventDefault()
              const step = event.key === "ArrowDown" ? 1 : -1
              setHighlight((active + step + matches.length) % matches.length)
            } else if (open && (event.key === "Enter" || event.key === "Tab")) {
              event.preventDefault()
              choose(matches[active])
            } else if (open && event.key === "Escape") {
              // Cierra la lista, no el panel.
              event.preventDefault()
              event.stopPropagation()
              setDismissedAt(mention!.start)
            } else if (event.key === "Enter") {
              event.preventDefault()
              submit()
            }
          }}
        />
        {open && (
          <ul id={listId} role="listbox" aria-label="Mencionar a" className="absolute bottom-full left-0 z-10 mb-1 w-60 rounded-lg border border-border bg-card p-1 shadow-xl">
            {matches.map((candidate, index) => (
              <li
                key={candidate.id}
                id={`${listId}-${candidate.id}`}
                role="option"
                aria-selected={index === active}
                onMouseDown={(event) => { event.preventDefault(); choose(candidate) }}
                className={cn("cursor-pointer rounded-md px-3 py-2 text-sm", index === active && "bg-muted")}
              >
                <span className="font-medium">@{candidate.name}</span>
                {candidate.fullName !== candidate.name && <span className="ml-2 text-xs text-muted-foreground">{candidate.fullName}</span>}
              </li>
            ))}
          </ul>
        )}
      </div>
      <Button type="button" variant="outline" disabled={pending || !value.trim()} onClick={submit}>
        Comentar
      </Button>
    </div>
  )
}
