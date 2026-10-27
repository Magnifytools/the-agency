import { describe, expect, it } from "vitest"
import { layoutDay, minutesOf, newBlockMinutes, placeBlock, snap, stampAt, workWeek, PX_PER_MINUTE } from "./time-grid"

describe("time-grid", () => {
  it("convierte entre hora civil y minutos, también la medianoche", () => {
    expect(minutesOf("2026-10-28T10:30")).toBe(630)
    expect(minutesOf("2026-10-28T10:30:00")).toBe(630)
    expect(stampAt("2026-10-28", 630)).toBe("2026-10-28T10:30")
    expect(stampAt("2026-10-28", 1440)).toBe("2026-10-29T00:00")
  })

  it("ajusta a cuartos de hora y mete el bloque en 8-20", () => {
    expect(snap(637)).toBe(630)
    expect(snap(638)).toBe(645)
    expect(placeBlock(400, 60)).toEqual({ start: 480, end: 540 })
    expect(placeBlock(1170, 90)).toEqual({ start: 1110, end: 1200 })
    expect(placeBlock(600, 5)).toEqual({ start: 600, end: 615 })
  })

  it("un bloque nuevo dura lo estimado (entre 15 min y 4 h) o una hora", () => {
    expect(newBlockMinutes(null)).toBe(60)
    expect(newBlockMinutes(50)).toBe(45)
    expect(newBlockMinutes(5)).toBe(15)
    expect(newBlockMinutes(600)).toBe(240)
  })

  it("la semana es de lunes a viernes", () => {
    expect(workWeek("2026-10-29")).toEqual(["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30"])
    expect(workWeek("2026-11-01")[0]).toBe("2026-10-26")
  })

  it("reparte en carriles lo que se solapa y recorta lo que se sale", () => {
    const items = [
      { id: "a", start: 600, end: 660 }, { id: "b", start: 630, end: 690 },
      { id: "c", start: 700, end: 720 }, { id: "d", start: 420, end: 510 },
    ]
    const placed = Object.fromEntries(layoutDay(items, (item) => item).map((entry) => [entry.item.id, entry]))
    expect([placed.a.lane, placed.a.lanes, placed.b.lane, placed.b.lanes]).toEqual([0, 2, 1, 2])
    expect([placed.c.lane, placed.c.lanes]).toEqual([0, 1])
    expect(placed.d.top).toBe(0)
    expect(placed.d.height).toBe(30 * PX_PER_MINUTE)
    expect(layoutDay([{ start: 1260, end: 1300 }], (item) => item)).toEqual([])
  })
})
