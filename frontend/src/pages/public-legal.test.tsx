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
  expect(text).toContain("Actualizada el 28 de octubre de 2026")
  expect(text).toContain("durante 120 días, guardamos esas mismas cifras por día para cada búsqueda (consulta) y cada página")
  expect(text).toContain("agregadas y anonimizadas en Search Console: no identifican a ninguna persona")
  expect(text).toContain("No guardamos países ni dispositivos")
  expect(text).toContain("qué búsquedas, páginas y secciones ganan o pierden tráfico y cuánto viene de la marca")
  expect(text).toContain("El detalle por búsqueda y página se borra a los 120 días, y también cuando la web deja de estar asociada a un cliente activo")
  expect(text).toContain("incluye el detalle por búsqueda y página")
  expect(text).toContain("for 120 days the same daily figures per search query and per page, as aggregated and anonymised by Google")
  expect(text).toContain("Query and page detail is deleted after 120 days or when the site is no longer linked to an active client")
  // El detalle guardado sigue sin ir a la IA (lo vigila test_gsc_detail.py).
  expect(text).toContain("Ni Analytics ni el detalle guardado por búsqueda y página se envían a ningún servicio de IA")
  expect(text).toContain("the stored per-query and per-page detail are never sent to any AI service")
  // Ya no dice lo contrario.
  expect(text).not.toContain("No guardamos consultas, páginas")
  expect(text).not.toContain("No queries, pages")
})

it("la política cuenta el total mensual por búsqueda (historial de posiciones) y su retención", () => {
  renderPage(<PrivacyPage />)
  const text = (document.body.textContent ?? "").replace(/\s+/g, " ")
  expect(text).toContain("Actualizada el 28 de octubre de 2026")
  expect(text).toContain("Pasados esos 120 días, de cada búsqueda sólo conservamos un total por mes (clics, impresiones y posición media), durante un máximo de 16 meses y mientras la web esté asociada a un cliente activo")
  expect(text).toContain("El total mensual por búsqueda se conserva como mucho 16 meses y se borra antes si la web deja de estar asociada a un cliente activo")
  expect(text).toContain("el borrado incluye el detalle por búsqueda y página, el total mensual por búsqueda")
  expect(text).toContain("Beyond those 120 days, we keep only a monthly total per search query (clicks, impressions and average position) for up to 16 months while the site is linked to an active client")
  expect(text).toContain("Monthly per-query totals are kept for up to 16 months and deleted earlier when the site is no longer linked to an active client")
  expect(text).toContain("including query and page detail, monthly per-query totals")
})

it("la política cuenta los leads por página de entrada y el historial importado de la herramienta anterior", () => {
  renderPage(<PrivacyPage />)
  const text = (document.body.textContent ?? "").replace(/\s+/g, " ")
  // Leads por landing (GA4): qué se guarda, sin datos personales, y cuánto tiempo.
  expect(text).toContain("por día, página de entrada y canal (búsqueda orgánica, de pago, redes sociales…), guardamos el número de eventos que cuentan como lead para ese cliente")
  expect(text).toContain("ya agregados por Google, durante un máximo de 16 meses")
  expect(text).toContain("Ver qué páginas de entrada y qué canales traen leads a cada cliente")
  expect(text).toContain("Los leads por página de entrada y canal se conservan como mucho 16 meses y se borran antes si la propiedad de Analytics deja de estar asociada a un cliente activo")
  expect(text).toContain("y los leads por página de entrada. Si no lo elige, se conservan")
  expect(text).toContain("per day, landing page and channel (organic search, paid search, social…), the number of events that count as a lead for that client")
  expect(text).toContain("Lead events per landing page and channel are kept for up to 16 months and deleted earlier when the Analytics property is no longer linked to an active client")
  expect(text).toContain("and lead events per landing page; otherwise they are kept")
  // Historial de posiciones traído una vez de la herramienta anterior: no caduca a los 16 meses.
  expect(text).toContain("totales mensuales por búsqueda anteriores a esos 16 meses, con los mismos datos de Search Console, que importamos una sola vez de nuestra herramienta anterior; se guardan mientras la web esté asociada a un cliente activo")
  expect(text).toContain("el importado de nuestra herramienta anterior se conserva mientras la web esté asociada a un cliente activo")
  expect(text).toContain("monthly per-query totals older than those 16 months, with the same Search Console data, imported once from our previous tool; they are kept while the site is linked to an active client")
  expect(text).toContain("those imported from our previous tool are kept while the site is linked to an active client")
  // Siguen sin ir a la IA.
  expect(text).toContain("Ni Analytics ni el detalle guardado por búsqueda y página se envían a ningún servicio de IA")
})

it("la política cuenta las consultas en vivo a Search Console desde Claude (gsc_live)", () => {
  renderPage(<PrivacyPage />)
  const text = (document.body.textContent ?? "").replace(/\s+/g, " ")
  expect(text).toContain("The Agency consulta Search Console en ese momento")
  expect(text).toContain("pasa la respuesta de Google a Claude. Esas consultas no se guardan en The Agency")
  expect(text).toContain("y con Anthropic, proveedor de Claude")
  expect(text).toContain("passes Google's response to Claude. Those queries are not stored in The Agency")
  expect(text).toContain("and with Anthropic, Claude's provider")
  // Ya no promete lo que dejó de ser verdad.
  expect(text).not.toContain("Las cifras de Google se pintan con código: no se envían a ningún servicio de IA")
  expect(text).not.toContain("Google figures are rendered by code and are not sent to any AI service")
})

it("la página de inicio menciona el detalle por búsqueda y página", () => {
  renderPage(<AboutPage />)
  const text = (document.body.textContent ?? "").replace(/\s+/g, " ")
  expect(text).toContain("y el detalle por búsqueda y página de los últimos 120 días")
  expect(text).toContain("per-query and per-page detail for the last 120 days")
  expect(text).toContain("y los leads por página de entrada y canal")
  expect(text).toContain("including daily lead events per landing page and channel")
})

it("la política cuenta el calendario «The Agency» de los bloques de trabajo", () => {
  renderPage(<PrivacyPage />)
  const text = (document.body.textContent ?? "").replace(/\s+/g, " ")
  expect(text).toContain("Calendario «The Agency» (permiso calendar.app.created)")
  expect(text).toContain("sólo puede ver y tocar ese calendario, nunca los demás")
  expect(text).toContain("el título de la tarea, el nombre del cliente, un enlace a la tarea en la app y la hora de inicio y fin")
  expect(text).toContain("Borrar un evento en Google borra el bloque, nunca la tarea")
  expect(text).toContain("puede elegir borrar también el calendario «The Agency» de su Google")
  expect(text).toContain("can only see and change that calendar, never the others")
})

it("la página de inicio ya no dice que la app nunca escribe en Google", () => {
  renderPage(<AboutPage />)
  const text = (document.body.textContent ?? "").replace(/\s+/g, " ")
  expect(text).toContain("sólo escribe en Google en ese calendario «The Agency», y sólo si la persona lo activa")
  expect(text).not.toContain("nunca escribe, modifica ni borra nada en las cuentas de Google")
  expect(text).not.toContain("The app never writes to")
})
