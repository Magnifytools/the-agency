// Mismos casos que backend/tests/test_task_rank.py: el front predice al servidor.
import { describe, expect, it } from "vitest"
import { byManualRank, orderAfterDrop, rankBetween, ranksForMove, spreadRanks } from "./task-rank"

describe("task-rank", () => {
  it.each([
    [null, null, "V"], ["V", null, "k"], [null, "V", "F"], ["V", "W", "VV"], ["a", "a1", "a0V"],
  ])("entre %s y %s → %s", (low, high, expected) => {
    expect(rankBetween(low, high)).toBe(expected)
  })

  it("no acepta un par al revés", () => {
    expect(() => rankBetween("k", "V")).toThrow()
  })

  it("reparte rangos ordenados que no acaban en 0", () => {
    expect(spreadRanks(3)).toEqual(["FV", "V", "kV"])
    const many = spreadRanks(500)
    expect([...many].sort()).toEqual(many)
    expect(new Set(many).size).toBe(500)
    expect(many.some((rank) => rank.endsWith("0"))).toBe(false)
  })

  it("entre vecinas con rango sólo cambia la que se mueve", () => {
    expect(ranksForMove([1, 2, 3], 3, new Map([[1, "F"], [2, "V"], [3, null]]))).toEqual(new Map([[3, "k"]]))
    expect(ranksForMove([1, 3, 2], 3, new Map([[1, "F"], [2, "V"], [3, "k"]]))).toEqual(new Map([[3, "N"]]))
  })

  it("sólo dan rango nuevo las que no tenían o rompían el orden", () => {
    expect(ranksForMove([1, 2, 3], 2, new Map())).toEqual(new Map([[1, "F"], [2, "V"], [3, "k"]]))
    expect(ranksForMove([1, 2, 3], 2, new Map([[1, "V"], [2, "k"], [3, "F"]]))).toEqual(new Map([[3, "s"]]))
    expect(ranksForMove([1, 2, 3], 1, new Map([[2, "V"]]))).toEqual(new Map([[1, "F"], [3, "k"]]))
    expect(ranksForMove([1, 2, 3], 2, new Map([[2, "V"]]))).toEqual(new Map([[1, "F"], [3, "k"]]))
  })

  it("ordenar una columna conserva lo que ya estaba ordenado", () => {
    expect(ranksForMove([21, 13, 17, 19], 13, new Map([[21, "P"]]))).toEqual(new Map([[13, "Y"], [17, "h"], [19, "q"]]))
  })

  it("si un rango se haría demasiado largo, reparte de nuevo", () => {
    const low = `a${"0".repeat(62)}1`
    const high = `a${"0".repeat(62)}2`
    expect(ranksForMove([1, 2, 3], 2, new Map([[1, low], [3, high]]))).toEqual(new Map([[1, "FV"], [2, "V"], [3, "kV"]]))
  })

  it("ordena primero lo que tiene orden manual, comparando como el servidor (COLLATE \"C\")", () => {
    const items = [{ id: 1, sort_rank: null }, { id: 2, sort_rank: "a" }, { id: 3, sort_rank: "B" }]
    expect(byManualRank(items).map((item) => item.id)).toEqual([3, 2, 1])
  })
})

describe("orderAfterDrop", () => {
  it("en la misma lista ocupa el sitio de la tarea sobre la que se suelta", () => {
    expect(orderAfterDrop([1, 2, 3, 4], 1, 3)).toEqual([2, 3, 1, 4])
    expect(orderAfterDrop([1, 2, 3, 4], 4, 2)).toEqual([1, 4, 2, 3])
    expect(orderAfterDrop([1, 2, 3], 2, 2)).toEqual([1, 2, 3])
  })

  it("desde otra lista entra delante de la tarea, o al final si no hay", () => {
    expect(orderAfterDrop([1, 2, 3], 9, 2)).toEqual([1, 9, 2, 3])
    expect(orderAfterDrop([1, 2, 3], 9, null)).toEqual([1, 2, 3, 9])
    expect(orderAfterDrop([], 9, null)).toEqual([9])
  })
})
