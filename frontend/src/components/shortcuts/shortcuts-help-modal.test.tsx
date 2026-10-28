import { render, screen } from "@testing-library/react"
import { afterEach, expect, it } from "vitest"
import { HIDDEN_MODULES, setRuntimeHiddenModules } from "@/lib/hidden-modules"
import { ShortcutsHelpModal } from "./shortcuts-help-modal"

afterEach(() => setRuntimeHiddenModules([...HIDDEN_MODULES]))

it("shows current navigation names and omits a hidden module", () => {
  // El Pipeline está activo desde el 28 oct 2026: se oculta a mano para probarlo.
  setRuntimeHiddenModules([...HIDDEN_MODULES, "leads"])
  render(<ShortcutsHelpModal open onOpenChange={() => {}} shortcuts={{ goto_leads: "G+Y" }} />)
  expect(screen.getByText("Ir a Visión general")).toBeInTheDocument()
  expect(screen.getByText("Ir a Por aclarar")).toBeInTheDocument()
  expect(screen.getByText("Ir a Horas")).toBeInTheDocument()
  expect(screen.queryByText("Ir a Pipeline")).not.toBeInTheDocument()
  expect(screen.getByText("Pulsa G y después la letra.")).toBeInTheDocument()
})

it("lists the Pipeline shortcut now that the Pipeline is active", () => {
  render(<ShortcutsHelpModal open onOpenChange={() => {}} shortcuts={{ goto_leads: "G+Y" }} />)
  expect(screen.getByText("Ir a Pipeline")).toBeInTheDocument()
})
