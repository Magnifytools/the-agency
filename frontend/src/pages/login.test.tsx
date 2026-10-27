import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom"
import { describe, expect, it, vi } from "vitest"

import LoginPage from "./login"

const login = vi.hoisted(() => vi.fn())
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ login }) }))

function Where() {
  const location = useLocation()
  return <p>en {location.pathname}{location.search}</p>
}

function show(state?: unknown) {
  render(
    <MemoryRouter initialEntries={[{ pathname: "/login", state }]}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>,
  )
}

async function submit() {
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "a@b.c" } })
  fireEvent.change(screen.getByLabelText("Contraseña"), { target: { value: "x" } })
  fireEvent.click(screen.getByRole("button", { name: "Entrar" }))
}

describe("LoginPage", () => {
  it("vuelve a la pantalla de la que venía y avisa de que la sesión caducó", async () => {
    login.mockResolvedValue(undefined)
    show({ from: "/web/cambios/abc?cliente=3", expired: true })
    expect(screen.getByText(/Tu sesión ha caducado/)).toBeInTheDocument()
    await submit()
    expect(await screen.findByText("en /web/cambios/abc?cliente=3")).toBeInTheDocument()
  })

  it("sin origen, o con uno que no es de la app, va a la portada", async () => {
    login.mockResolvedValue(undefined)
    show({ from: "//otro-sitio.com/x" })
    expect(screen.queryByText(/Tu sesión ha caducado/)).not.toBeInTheDocument()
    await submit()
    await waitFor(() => expect(screen.getByText("en /")).toBeInTheDocument())
  })
})
