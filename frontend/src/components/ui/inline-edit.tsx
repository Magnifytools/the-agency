import { useRef, useState, type KeyboardEvent, type ReactNode } from "react"
import { Check } from "lucide-react"
import { Popover } from "@/components/ui/popover"
import { cn } from "@/lib/utils"
import { formatCivilDate } from "@/lib/dates"
import { completeCivilDate, dateShortcuts, formatMinutes, parseMinutes } from "@/lib/inline-edit"

const triggerClass = "-mx-1.5 inline-flex max-w-full items-center gap-1 rounded-md px-1.5 py-0.5 text-left transition-colors duration-150 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand aria-expanded:bg-muted"
const optionClass = "flex w-full items-center justify-between gap-3 rounded-md px-3 py-2 text-left text-sm transition-colors duration-150 hover:bg-muted focus-visible:bg-muted focus-visible:outline-none"

interface TriggerProps {
  /** Qué se cambia, p. ej. "Prioridad de Preparar informe". */
  label: string
  /** Valor actual en texto, para lectores de pantalla. */
  valueText: string
  /** Sin permiso de escritura se enseña el valor tal cual, sin botón. */
  disabled?: boolean
  children: ReactNode
  className?: string
}

function InlineTrigger({ label, valueText, disabled, children, className, panel }: TriggerProps & { panel: (close: () => void) => ReactNode }) {
  if (disabled) return <>{children}</>
  return (
    <Popover
      label={label}
      trigger={({ ref, props }) => (
        <button ref={ref} type="button" aria-label={`${label}: ${valueText}`} title={label} className={cn(triggerClass, className)} {...props}>
          {children}
        </button>
      )}
    >
      {panel}
    </Popover>
  )
}

/** Flechas arriba/abajo entre las opciones de un panel. */
function moveFocus(event: KeyboardEvent<HTMLElement>) {
  if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return
  const options = Array.from(event.currentTarget.querySelectorAll<HTMLElement>("[data-inline-option]"))
  if (!options.length) return
  event.preventDefault()
  const index = options.indexOf(document.activeElement as HTMLElement)
  const next = event.key === "ArrowDown" ? index + 1 : index - 1
  options[(next + options.length) % options.length].focus()
}

function Option({ selected, onSelect, children, hint }: { selected: boolean; onSelect: () => void; children: ReactNode; hint?: ReactNode }) {
  return (
    <button type="button" role="option" aria-selected={selected} data-inline-option onClick={onSelect} className={cn(optionClass, selected && "font-semibold")}>
      <span className="inline-flex min-w-0 items-center gap-2">{children}</span>
      <span className="inline-flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
        {hint}
        {selected && <Check className="h-3.5 w-3.5 text-foreground" aria-hidden />}
      </span>
    </button>
  )
}

export interface InlineSelectOption<T> {
  value: T
  label: string
  content?: ReactNode
}

interface InlineSelectProps<T> extends TriggerProps {
  value: T
  options: InlineSelectOption<T>[]
  onChange: (value: T) => void
}

/** Elegir entre unas pocas opciones; con más de 8 aparece un buscador. */
export function InlineSelect<T extends string | number | null>({ value, options, onChange, ...trigger }: InlineSelectProps<T>) {
  return (
    <InlineTrigger {...trigger} panel={(close) => (
      <OptionList options={options} value={value} label={trigger.label} onPick={(next) => { close(); if (next !== value) onChange(next) }} />
    )} />
  )
}

function OptionList<T>({ options, value, label, onPick }: { options: InlineSelectOption<T>[]; value: T; label: string; onPick: (value: T) => void }) {
  const [query, setQuery] = useState("")
  const searchable = options.length > 8
  const visible = query
    ? options.filter((option) => option.label.toLocaleLowerCase("es").includes(query.toLocaleLowerCase("es")))
    : options
  return (
    <div onKeyDown={moveFocus}>
      {searchable && (
        <input
          type="search"
          autoFocus
          aria-label="Buscar"
          placeholder="Buscar…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => { if (event.key === "Enter" && visible.length) { event.preventDefault(); onPick(visible[0].value) } }}
          className="mb-1 h-8 w-full rounded-md border border-border bg-background px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
        />
      )}
      <div role="listbox" aria-label={label}>
        {visible.map((option) => (
          <Option key={String(option.value)} selected={!query && option.value === value} onSelect={() => onPick(option.value)}>
            {option.content ?? option.label}
          </Option>
        ))}
        {!visible.length && <p className="px-3 py-2 text-sm text-muted-foreground">Nada coincide</p>}
      </div>
    </div>
  )
}

interface InlineDateProps extends TriggerProps {
  value: string | null
  /** Día de hoy de la agencia (hora civil de Madrid). */
  today: string
  onChange: (value: string | null) => void
  /** Texto de la opción que quita la fecha; sin él no se puede quitar. */
  clearLabel?: string
  /** Ofrecer quitarla aunque ahora no haya fecha (varias tareas a la vez). */
  alwaysClearable?: boolean
}

/** Fecha con atajos (Hoy, Mañana, El lunes), quitar y cualquier otro día. */
export function InlineDate({ value, today, onChange, clearLabel, alwaysClearable, ...trigger }: InlineDateProps) {
  return (
    <InlineTrigger {...trigger} panel={(close) => {
      const pick = (next: string | null) => { close(); if (next !== value || alwaysClearable) onChange(next) }
      return (
        <div onKeyDown={moveFocus} className="w-60">
          <div role="listbox" aria-label={trigger.label}>
            {dateShortcuts(today).map((shortcut) => (
              <Option key={shortcut.label} selected={value === shortcut.date} onSelect={() => pick(shortcut.date)}
                hint={formatCivilDate(shortcut.date, { weekday: "short", day: "numeric", month: "short" })}>
                {shortcut.label}
              </Option>
            ))}
            {clearLabel && (value || alwaysClearable) && <Option selected={false} onSelect={() => pick(null)}>{clearLabel}</Option>}
          </div>
          <label className="mt-1 block border-t border-border px-3 pb-2 pt-2 text-xs text-muted-foreground">
            Otro día
            <input
              type="date"
              defaultValue={value ?? ""}
              onChange={(event) => { const date = completeCivilDate(event.target.value); if (date) pick(date) }}
              className="mt-1 block h-8 w-full rounded-md border border-border bg-background px-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
            />
          </label>
        </div>
      )
    }} />
  )
}

const MINUTE_PRESETS = [15, 30, 60, 120, 240, 480]

interface InlineMinutesProps extends TriggerProps {
  value: number | null
  onChange: (value: number | null) => void
}

/** Estimación: duraciones habituales, otra escrita ("1h 30m") o sin estimar. */
export function InlineMinutes({ value, onChange, ...trigger }: InlineMinutesProps) {
  return (
    <InlineTrigger {...trigger} panel={(close) => (
      <MinutesPanel value={value} label={trigger.label} onPick={(next) => { close(); if (next !== value) onChange(next) }} />
    )} />
  )
}

function MinutesPanel({ value, label, onPick }: { value: number | null; label: string; onPick: (value: number | null) => void }) {
  const [text, setText] = useState(value && !MINUTE_PRESETS.includes(value) ? formatMinutes(value) : "")
  const parsed = parseMinutes(text)
  return (
    <div onKeyDown={moveFocus} className="w-52">
      <div role="listbox" aria-label={label}>
        {MINUTE_PRESETS.map((minutes) => (
          <Option key={minutes} selected={value === minutes} onSelect={() => onPick(minutes)}>{formatMinutes(minutes)}</Option>
        ))}
        {value !== null && <Option selected={false} onSelect={() => onPick(null)}>Sin estimar</Option>}
      </div>
      <form
        className="mt-1 flex items-end gap-1 border-t border-border px-3 pb-2 pt-2"
        onSubmit={(event) => { event.preventDefault(); if (parsed !== null) onPick(parsed) }}
      >
        <label className="flex-1 text-xs text-muted-foreground">
          Otra
          <input
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder="1h 30m"
            aria-invalid={text.trim() !== "" && parsed === null}
            className="mt-1 block h-8 w-full rounded-md border border-border bg-background px-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand aria-[invalid=true]:border-destructive"
          />
        </label>
        <button type="submit" disabled={parsed === null} className="h-8 rounded-md border border-border px-2 text-xs font-medium hover:bg-muted disabled:opacity-50">
          Poner
        </button>
      </form>
    </div>
  )
}

interface InlineTextInputProps {
  label: string
  value: string
  maxLength?: number
  onSubmit: (value: string) => void
  onCancel: () => void
  className?: string
}

/** Texto editado en su sitio: Enter o salir del campo guarda, Escape lo deja como estaba. */
export function InlineTextInput({ label, value, maxLength, onSubmit, onCancel, className }: InlineTextInputProps) {
  const [text, setText] = useState(value)
  const done = useRef(false)
  const finish = (save: boolean) => {
    if (done.current) return
    done.current = true
    const next = text.trim()
    if (save && next && next !== value) onSubmit(next)
    else onCancel()
  }
  return (
    <input
      autoFocus
      aria-label={label}
      value={text}
      maxLength={maxLength}
      onFocus={(event) => event.currentTarget.select()}
      onChange={(event) => setText(event.target.value)}
      onClick={(event) => event.stopPropagation()}
      onKeyDown={(event) => {
        if (event.key === "Enter") { event.preventDefault(); finish(true) }
        if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); finish(false) }
      }}
      onBlur={() => finish(true)}
      className={cn("h-8 w-full min-w-48 rounded-md border border-border bg-background px-2 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand", className)}
    />
  )
}
