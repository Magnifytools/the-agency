import { useEffect, useRef, useState, useCallback, useMemo } from "react"
import { useNavigate } from "react-router-dom"

export const DEFAULT_SHORTCUTS: Record<string, string> = {
  search: "Ctrl+K",
  capture: "Ctrl+J",
  goto_dashboard: "G+D",
  goto_inbox: "G+I",
  goto_timesheet: "G+T",
  goto_clients: "G+C",
  new_entry: "N",
  show_shortcuts: "?",
}

export const SHORTCUT_LABELS: Record<string, string> = {
  search: "Buscar",
  capture: "Captura rápida",
  goto_dashboard: "Ir a Dashboard",
  goto_inbox: "Ir a Inbox",
  goto_timesheet: "Ir a Timesheet",
  goto_clients: "Ir a Clientes",
  new_entry: "Nueva entrada",
  show_shortcuts: "Mostrar atajos",
}

// Routes for chord navigation actions
const ACTION_ROUTES: Record<string, string> = {
  goto_dashboard: "/dashboard",
  goto_inbox: "/inbox",
  goto_timesheet: "/timesheet",
  goto_clients: "/clients",
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
  if (shift && !e.shiftKey) return false
  if (!shift && e.shiftKey) return false

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
}

export function useKeyboardShortcuts({ userOverrides = {}, onSearch, onCapture }: UseKeyboardShortcutsOptions) {
  const navigate = useNavigate()
  const [isHelpOpen, setIsHelpOpen] = useState(false)
  const chordPendingRef = useRef(false)
  const chordTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Memoize so the effect only re-runs when shortcuts actually change
  const shortcuts = useMemo(() => ({ ...DEFAULT_SHORTCUTS, ...userOverrides }), [userOverrides])

  const clearChord = useCallback(() => {
    chordPendingRef.current = false
    if (chordTimerRef.current) {
      clearTimeout(chordTimerRef.current)
      chordTimerRef.current = null
    }
  }, [])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (isInputFocused()) return

      // --- Chord resolution (G+X) ---
      if (chordPendingRef.current) {
        clearChord()
        const key = e.key.toLowerCase()
        // Build dynamic map: letter → route, respecting user-customized bindings
        const resolvedMap: Record<string, string> = {}
        for (const [action, binding] of Object.entries(shortcuts)) {
          if (binding.includes("+") && binding.split("+")[0].toLowerCase() === "g" && ACTION_ROUTES[action]) {
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
      const hasGChord = Object.values(shortcuts).some(
        (b) => b.split("+")[0].toLowerCase() === "g" && b.includes("+"),
      )
      if (hasGChord && e.key.toLowerCase() === "g" && !e.metaKey && !e.ctrlKey && !e.altKey) {
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
      if (matchesShortcut(e, shortcuts.show_shortcuts)) {
        e.preventDefault()
        setIsHelpOpen((o) => !o)
        return
      }
    }

    document.addEventListener("keydown", handler)
    return () => {
      document.removeEventListener("keydown", handler)
      clearChord()
    }
  }, [shortcuts, navigate, onSearch, onCapture, clearChord])

  return { shortcuts, isHelpOpen, setIsHelpOpen }
}
