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
