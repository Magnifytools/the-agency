import { render, screen, fireEvent } from "@testing-library/react"
import { MemoryRouter, useLocation } from "react-router-dom"
import { expect, it } from "vitest"
import { useKeyboardShortcuts } from "./use-keyboard-shortcuts"

function Harness() {
  useKeyboardShortcuts({ userOverrides: { goto_leads: "G+L" } })
  const location = useLocation()
  return <output>{location.pathname}{location.search}</output>
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
