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

it("la política cuenta el detalle por consulta y página de Search Console y su retención", () => {
  renderPage(<PrivacyPage />)
  const text = (document.body.textContent ?? "").replace(/\s+/g, " ")
  expect(text).toContain("Actualizada el 22 de octubre de 2026")
  expect(text).toContain("durante 120 días, guardamos esas mismas cifras por día para cada búsqueda (consulta) y cada página")
  expect(text).toContain("agregadas y anonimizadas en Search Console: no identifican a ninguna persona")
  expect(text).toContain("No guardamos países ni dispositivos")
  expect(text).toContain("qué búsquedas, páginas y secciones ganan o pierden tráfico y cuánto viene de la marca")
  expect(text).toContain("El detalle por búsqueda y página se borra a los 120 días, y también cuando la web deja de estar asociada a un cliente activo")
  expect(text).toContain("incluye el detalle por búsqueda y página")
  expect(text).toContain("for 120 days the same daily figures per search query and per page, as aggregated and anonymised by Google")
  expect(text).toContain("Query and page detail is deleted after 120 days or when the site is no longer linked to an active client")
  // Sigue prometiendo que las cifras de Google no van a la IA (lo vigila test_gsc_detail.py).
  expect(text).toContain("no se envían a ningún servicio de IA")
  expect(text).toContain("not sent to any AI service")
  // Ya no dice lo contrario.
  expect(text).not.toContain("No guardamos consultas, páginas")
  expect(text).not.toContain("No queries, pages")
})

it("la página de inicio menciona el detalle por búsqueda y página", () => {
  renderPage(<AboutPage />)
  const text = (document.body.textContent ?? "").replace(/\s+/g, " ")
  expect(text).toContain("y el detalle por búsqueda y página de los últimos 120 días")
  expect(text).toContain("per-query and per-page detail for the last 120 days")
})
