import { render, screen, fireEvent } from "@testing-library/react"
import { MemoryRouter, useLocation } from "react-router-dom"
import { expect, it, vi } from "vitest"
import { useKeyboardShortcuts } from "./use-keyboard-shortcuts"

function Harness() {
  useKeyboardShortcuts({ userOverrides: { goto_leads: "G+L" } })
  const location = useLocation()
  return <output>{location.pathname}{location.search}</output>
}

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
