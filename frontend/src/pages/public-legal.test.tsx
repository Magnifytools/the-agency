import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { expect, it } from "vitest"
import { AboutPage, PrivacyPage } from "./public-legal"

function renderPage(page: React.ReactNode) {
  return render(<MemoryRouter>{page}</MemoryRouter>)
}

it("la página de inicio describe la app, enlaza a la privacidad y no se indexa", () => {
  renderPage(<AboutPage />)
  expect(screen.getByRole("heading", { level: 1, name: "The Agency" })).toBeInTheDocument()
  expect(screen.getAllByRole("link", { name: /política de privacidad|privacy policy/i })[0]).toHaveAttribute("href", "/privacidad")
  expect(document.querySelector('meta[name="robots"]')?.getAttribute("content")).toContain("noindex")
})

it("la política declara los permisos de Google y el uso limitado", () => {
  renderPage(<PrivacyPage />)
  for (const scope of ["webmasters.readonly", "analytics.readonly", "calendar.readonly"]) {
    expect(screen.getAllByText(new RegExp(scope)).length).toBeGreaterThan(0)
  }
  expect(screen.getByRole("link", { name: "Google API Services User Data Policy" }))
    .toHaveAttribute("href", "https://developers.google.com/terms/api-services-user-data-policy")
  expect(document.querySelector('meta[name="robots"]')?.getAttribute("content")).toContain("noindex")
})

it("la política cuenta lo que hace desconectar y la retención del calendario", () => {
  renderPage(<PrivacyPage />)
  const text = (document.body.textContent ?? "").replace(/\s+/g, " ")
  expect(text).toContain("pide a Google que revoque su acceso")
  expect(text).toContain("puede elegir borrar también las cifras importadas")
  expect(text).toContain("Al desconectar Google Calendar se borran todos los eventos importados")
  expect(text).toContain("30 días después de terminar")
  expect(text).toContain("deleted 30 days after it ends")
  // Ya no dice lo contrario.
  expect(text).not.toContain("se conservan en la app aunque pasen")
  expect(text).not.toContain("no se borran solas")
  expect(text).not.toContain("imported calendar events are kept")
})
