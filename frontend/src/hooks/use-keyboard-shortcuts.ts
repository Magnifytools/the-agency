import { useEffect, useRef, useState, useCallback, useMemo } from "react"
import { useNavigate } from "react-router-dom"
import { isHidden } from "@/lib/hidden-modules"

export const DEFAULT_SHORTCUTS: Record<string, string> = {
  search: "Ctrl+K",
  capture: "Ctrl+J",
  goto_dashboard: "G+D",
  goto_inbox: "G+I",
  goto_timesheet: "G+T",
  goto_clients: "G+C",
  goto_projects: "G+P",
  goto_tasks: "G+A",
  goto_leads: "G+L",
  new_entry: "N",
  show_shortcuts: "?",
  undo: "Ctrl+Z",
}

export const SHORTCUT_LABELS: Record<string, string> = {
  search: "Buscar",
  capture: "Captura rápida",
  goto_dashboard: "Ir a Visión general",
  goto_inbox: "Ir a Por aclarar",
  goto_timesheet: "Ir a Horas",
  goto_clients: "Ir a Clientes",
  goto_projects: "Ir a Proyectos",
  goto_tasks: "Ir a Tareas",
  goto_leads: "Ir a Pipeline",
  new_entry: "Nueva entrada",
  show_shortcuts: "Mostrar atajos",
  undo: "Deshacer último cambio",
}

// Routes for chord navigation actions
const ACTION_ROUTES: Record<string, string> = {
  goto_dashboard: "/dashboard",
  goto_inbox: "/inbox",
  goto_timesheet: "/timesheet",
  goto_clients: "/clients",
  goto_projects: "/projects",
  goto_tasks: "/tasks?view=all",
  goto_leads: "/leads",
}

const ACTION_MODULES: Record<string, string> = {
  goto_dashboard: "dashboard",
  goto_inbox: "tasks",
  goto_timesheet: "timesheet",
  goto_clients: "clients",
  goto_projects: "projects",
  goto_tasks: "tasks",
  goto_leads: "leads",
}

export function isShortcutAvailable(action: string): boolean {
  const module = ACTION_MODULES[action]
  return !module || !isHidden(module)
}

/** Navigation uses two successive keys; actions use one keydown with optional modifiers. */
export function isValidShortcutBinding(action: string, binding: string): boolean {
  if (ACTION_ROUTES[action]) return /^G\+[A-Z]$/i.test(binding)
  return /^(?:(?:Ctrl|Cmd)\+)?(?:Shift\+)?(?:[A-Z0-9?])$/i.test(binding)
}

export function resolveShortcuts(overrides: Record<string, string> = {}): Record<string, string> {
  const resolved = { ...DEFAULT_SHORTCUTS }
  for (const action of Object.keys(DEFAULT_SHORTCUTS)) {
    const binding = overrides[action]
    if (typeof binding === "string" && isValidShortcutBinding(action, binding) && !shortcutConflict(action, binding, resolved)) {
      resolved[action] = binding.toUpperCase().replace("CTRL", "Ctrl").replace("SHIFT", "Shift").replace("CMD", "Cmd")
    }
  }
  return resolved
}

export function shortcutConflict(action: string, binding: string, bindings: Record<string, string>): string | null {
  if (!isShortcutAvailable(action)) return null
  const canonical = (value: string) => value.toUpperCase().replace(/^CMD\+/, "CTRL+")
  return Object.keys(DEFAULT_SHORTCUTS).find((other) =>
    other !== action && isShortcutAvailable(other) && canonical(bindings[other] ?? DEFAULT_SHORTCUTS[other]) === canonical(binding),
  ) ?? null
}

function isMac() {
  return typeof navigator !== "undefined" && /Mac/i.test(navigator.platform)
}

function isInputFocused(): boolean {
  const el = document.activeElement
  if (!el) return false
  const tag = el.tagName.toLowerCase()
  if (tag === "input" || tag === "textarea" || tag === "select") return true
  if ((el as HTMLElement).isContentEditable) return true
  return false
}

/** Parse a shortcut string into modifier flags + key */
function parseShortcut(shortcut: string): { ctrl: boolean; meta: boolean; shift: boolean; key: string } {
  const parts = shortcut.split("+")
  const key = parts[parts.length - 1].toLowerCase()
  const ctrl = parts.some((p) => p.toLowerCase() === "ctrl")
  const meta = parts.some((p) => p.toLowerCase() === "cmd" || p.toLowerCase() === "meta")
  const shift = parts.some((p) => p.toLowerCase() === "shift")
  return { ctrl, meta, shift, key }
}

/** Returns true if the event matches the shortcut string, handling Ctrl/Cmd cross-platform */
function matchesShortcut(e: KeyboardEvent, shortcut: string): boolean {
  const { ctrl, meta, shift, key } = parseShortcut(shortcut)
  const mac = isMac()

  // Ctrl in storage means: Cmd on Mac, Ctrl on Windows/Linux
  const modifierMatches = ctrl
    ? mac
      ? e.metaKey && !e.ctrlKey
      : e.ctrlKey && !e.metaKey
    : meta
      ? e.metaKey
      : true

  if (!modifierMatches) return false
  if (e.altKey || (meta && e.ctrlKey) || (ctrl && e.altKey)) return false
  if (shift && !e.shiftKey) return false
  // Producing "?" requires Shift on common keyboard layouts.
  if (!shift && e.shiftKey && key !== "?") return false

  // For plain single-key shortcuts (no modifiers), reject if any modifier is held
  if (!ctrl && !meta && !shift) {
    if (e.metaKey || e.ctrlKey || e.altKey) return false
  }

  return e.key.toLowerCase() === key
}

export interface UseKeyboardShortcutsOptions {
  userOverrides?: Record<string, string>
  onSearch?: () => void
  onCapture?: () => void
  onUndo?: () => void
}

export function useKeyboardShortcuts({ userOverrides = {}, onSearch, onCapture, onUndo }: UseKeyboardShortcutsOptions) {
  const navigate = useNavigate()
  const [isHelpOpen, setIsHelpOpen] = useState(false)
  const chordPendingRef = useRef(false)
  const chordTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Memoize so the effect only re-runs when shortcuts actually change
  const shortcuts = useMemo(() => resolveShortcuts(userOverrides), [userOverrides])

  const clearChord = useCallback(() => {
    chordPendingRef.current = false
    if (chordTimerRef.current) {
      clearTimeout(chordTimerRef.current)
      chordTimerRef.current = null
    }
  }, [])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (isInputFocused()) {
        clearChord()
        return
      }

      // --- Chord resolution (G+X) ---
      if (chordPendingRef.current) {
        clearChord()
        if (e.metaKey || e.ctrlKey || e.altKey || e.shiftKey) return
        const key = e.key.toLowerCase()
        // Build dynamic map: letter → route, respecting user-customized bindings
        const resolvedMap: Record<string, string> = {}
        for (const [action, binding] of Object.entries(shortcuts)) {
          if (isShortcutAvailable(action) && binding.includes("+") && binding.split("+")[0].toLowerCase() === "g" && ACTION_ROUTES[action]) {
            resolvedMap[binding.split("+")[1].toLowerCase()] = ACTION_ROUTES[action]
          }
        }
        if (resolvedMap[key]) {
          e.preventDefault()
          navigate(resolvedMap[key])
        }
        return
      }

      // --- Chord initiator (G key) ---
      const hasGChord = Object.entries(shortcuts).some(
        ([action, b]) => isShortcutAvailable(action) && !!ACTION_ROUTES[action] && b.split("+")[0].toLowerCase() === "g" && b.includes("+"),
      )
      if (hasGChord && e.key.toLowerCase() === "g" && !e.metaKey && !e.ctrlKey && !e.altKey && !e.shiftKey) {
        e.preventDefault()
        chordPendingRef.current = true
        chordTimerRef.current = setTimeout(clearChord, 1500)
        return
      }

      // --- Regular shortcuts ---
      if (matchesShortcut(e, shortcuts.search)) {
        e.preventDefault()
        onSearch?.()
        return
      }
      if (matchesShortcut(e, shortcuts.capture)) {
        e.preventDefault()
        onCapture?.()
        return
      }
      if (matchesShortcut(e, shortcuts.new_entry)) {
        e.preventDefault()
        onCapture?.()
        return
      }
      if (matchesShortcut(e, shortcuts.show_shortcuts)) {
        e.preventDefault()
        setIsHelpOpen((o) => !o)
        return
      }
      // Cmd/Ctrl+Z. El guard isInputFocused() de arriba deja intacto el deshacer
      // nativo mientras se escribe: esto sólo actúa sobre el documento.
      if (matchesShortcut(e, shortcuts.undo)) {
        e.preventDefault()
        onUndo?.()
        return
      }
    }

    document.addEventListener("keydown", handler)
    return () => {
      document.removeEventListener("keydown", handler)
      clearChord()
    }
  }, [shortcuts, navigate, onSearch, onCapture, onUndo, clearChord])

  return { shortcuts, isHelpOpen, setIsHelpOpen }
}
