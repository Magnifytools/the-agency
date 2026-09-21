import { render, screen, fireEvent } from "@testing-library/react"
import { MemoryRouter, useLocation } from "react-router-dom"
import { expect, it, vi } from "vitest"
import { useKeyboardShortcuts, resolveShortcuts, shortcutConflict } from "./use-keyboard-shortcuts"

function Harness() {
  useKeyboardShortcuts({ userOverrides: { goto_leads: "G+L" } })
  const location = useLocation()
  return <output>{location.pathname}{location.search}</output>
}

function OverrideHarness({ overrides }: { overrides: Record<string, string> }) {
  const { isHelpOpen } = useKeyboardShortcuts({ userOverrides: overrides })
  const location = useLocation()
  return <><output>{location.pathname}{location.search}</output><span data-testid="help-open">{String(isHelpOpen)}</span></>
}

it("opens shortcut help with the shifted question mark key", () => {
  render(<MemoryRouter><OverrideHarness overrides={{}} /></MemoryRouter>)
  fireEvent.keyDown(document, { key: "?", shiftKey: true })
  expect(screen.getByTestId("help-open")).toHaveTextContent("true")
})

it("executes a custom sequential navigation chord and rejects modified second keys", () => {
  render(<MemoryRouter initialEntries={["/settings"]}><OverrideHarness overrides={{ goto_dashboard: "G+H" }} /></MemoryRouter>)
  fireEvent.keyDown(document, { key: "h" })
  expect(screen.getByRole("status")).toHaveTextContent("/settings")
  fireEvent.keyDown(document, { key: "g" })
  fireEvent.keyDown(document, { key: "h", ctrlKey: true })
  expect(screen.getByRole("status")).toHaveTextContent("/settings")
  fireEvent.keyDown(document, { key: "g" })
  fireEvent.keyDown(document, { key: "h" })
  expect(screen.getByRole("status")).toHaveTextContent("/dashboard")
})

it("clears a pending chord when typing starts in an input", () => {
  render(<MemoryRouter initialEntries={["/settings"]}><OverrideHarness overrides={{ goto_dashboard: "G+H" }} /></MemoryRouter>)
  fireEvent.keyDown(document, { key: "g" })
  const input = document.createElement("input")
  document.body.appendChild(input)
  input.focus()
  fireEvent.keyDown(document, { key: "x" })
  input.blur()
  input.remove()
  fireEvent.keyDown(document, { key: "h" })
  expect(screen.getByRole("status")).toHaveTextContent("/settings")
})

it("normalizes invalid legacy bindings and detects active collisions", () => {
  expect(resolveShortcuts({ goto_dashboard: "H", search: "Alt+K" }).goto_dashboard).toBe("G+D")
  expect(resolveShortcuts({ goto_dashboard: "H", search: "Alt+K" }).search).toBe("Ctrl+K")
  expect(resolveShortcuts({ goto_dashboard: "G+A" }).goto_dashboard).toBe("G+D")
  expect(shortcutConflict("goto_dashboard", "G+A", { goto_tasks: "G+A" })).toBe("goto_tasks")
  expect(shortcutConflict("goto_dashboard", "G+L", { goto_leads: "G+L" })).toBeNull()
})

it("does not accept extra modifiers on regular shortcuts", () => {
  const onCapture = vi.fn()
  render(<MemoryRouter><NewEntryHarness onCapture={onCapture} userOverrides={{ new_entry: "Ctrl+N" }} /></MemoryRouter>)
  fireEvent.keyDown(document, { key: "n", ctrlKey: true, altKey: true })
  expect(onCapture).not.toHaveBeenCalled()
})

function NewEntryHarness({ onCapture, userOverrides = {} }: { onCapture: () => void; userOverrides?: Record<string, string> }) {
  useKeyboardShortcuts({ onCapture, userOverrides })
  return <input aria-label="Campo de prueba" />
}

it("ignores a legacy shortcut to hidden Pipeline and navigates to active Trabajo", () => {
  render(<MemoryRouter initialEntries={["/settings"]}><Harness /></MemoryRouter>)
  fireEvent.keyDown(document, { key: "g" })
  fireEvent.keyDown(document, { key: "l" })
  expect(screen.getByRole("status")).toHaveTextContent("/settings")
  fireEvent.keyDown(document, { key: "g" })
  fireEvent.keyDown(document, { key: "a" })
  expect(screen.getByRole("status")).toHaveTextContent("/tasks?view=all")
})

it("opens the global entry with N but does not interrupt typing", () => {
  const onCapture = vi.fn()
  render(<MemoryRouter><NewEntryHarness onCapture={onCapture} /></MemoryRouter>)

  fireEvent.keyDown(document, { key: "n" })
  expect(onCapture).toHaveBeenCalledTimes(1)

  screen.getByRole("textbox", { name: "Campo de prueba" }).focus()
  fireEvent.keyDown(document, { key: "n" })
  expect(onCapture).toHaveBeenCalledTimes(1)
})

it("uses the customized new-entry shortcut", () => {
  const onCapture = vi.fn()
  render(<MemoryRouter><NewEntryHarness onCapture={onCapture} userOverrides={{ new_entry: "Shift+N" }} /></MemoryRouter>)

  fireEvent.keyDown(document, { key: "n" })
  expect(onCapture).not.toHaveBeenCalled()
  fireEvent.keyDown(document, { key: "N", shiftKey: true })
  expect(onCapture).toHaveBeenCalledTimes(1)
})
