import { describe, expect, it } from "vitest"
import { completeCivilDate, dateShortcuts, parseMinutes } from "./inline-edit"

describe("dateShortcuts", () => {
  it("ofrece hoy, mañana y el lunes que viene", () => {
    // 1 oct 2026 es jueves.
    expect(dateShortcuts("2026-10-01").map((item) => item.date)).toEqual(["2026-10-01", "2026-10-02", "2026-10-05"])
  })

  it("un lunes, 'El lunes' es el de la semana próxima; un domingo, mañana", () => {
    expect(dateShortcuts("2026-10-05")[2].date).toBe("2026-10-12")
    expect(dateShortcuts("2026-10-04")[2].date).toBe("2026-10-05")
  })
})

describe("completeCivilDate", () => {
  it("ignora el año a medio teclear del selector nativo", () => {
    expect(completeCivilDate("0202-10-31")).toBeNull()
    expect(completeCivilDate("")).toBeNull()
    expect(completeCivilDate("2026-10-31")).toBe("2026-10-31")
  })
})

describe("parseMinutes", () => {
  it.each([
    ["90", 90], ["1h", 60], ["1h 30m", 90], ["1,5h", 90], ["45m", 45], ["2 h", 120], ["30 min", 30],
  ])("%s → %i minutos", (text, minutes) => {
    expect(parseMinutes(text)).toBe(minutes)
  })

  it.each(["", "una hora", "h", "0"])("'%s' no es una duración", (text) => {
    expect(parseMinutes(text)).toBeNull()
  })
})
