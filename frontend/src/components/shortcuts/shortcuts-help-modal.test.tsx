import { render, screen } from "@testing-library/react"
import { expect, it } from "vitest"
import { ShortcutsHelpModal } from "./shortcuts-help-modal"

it("shows current navigation names and omits hidden Pipeline", () => {
  render(<ShortcutsHelpModal open onOpenChange={() => {}} shortcuts={{ goto_leads: "G+Y" }} />)
  expect(screen.getByText("Ir a Visión general")).toBeInTheDocument()
  expect(screen.getByText("Ir a Por aclarar")).toBeInTheDocument()
  expect(screen.getByText("Ir a Horas")).toBeInTheDocument()
  expect(screen.queryByText("Ir a Pipeline")).not.toBeInTheDocument()
})
