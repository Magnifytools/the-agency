import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { expect, it } from "vitest"
import { InfoTooltip } from "./tooltip"

it("makes contextual help available by keyboard and touch", async () => {
  const user = userEvent.setup()
  render(<InfoTooltip content="Tiempo registrado con el cronómetro" />)

  const help = screen.getByRole("button", { name: /Ayuda: Tiempo registrado/ })
  await user.tab()
  expect(help).toHaveFocus()
  expect(screen.getByRole("tooltip")).toHaveTextContent("Tiempo registrado con el cronómetro")

  await user.keyboard("{Escape}")
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument()

  await user.click(help)
  expect(screen.getByRole("tooltip")).toBeInTheDocument()
  await user.pointer({ keys: "[MouseLeft]", target: document.body })
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument()
})
