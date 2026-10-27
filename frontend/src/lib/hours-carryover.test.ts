import { expect, it } from "vitest"
import { carryoverNote } from "./hours-carryover"

it("explains where this month's ceiling comes from", () => {
  expect(carryoverNote(2, 10)).toBe("10h del mes + 2h que sobraron el mes anterior. Aviso temprano al 75 %.")
  expect(carryoverNote(-3.5, 10)).toBe("10h del mes − 3,5h de exceso el mes anterior. Aviso temprano al 75 %.")
  expect(carryoverNote(0, 24)).toBe("24h del mes + 0h que sobraron el mes anterior. Aviso temprano al 75 %.")
})

it("says nothing when the project does not carry hours", () => {
  expect(carryoverNote(null, 10)).toBeNull()
  expect(carryoverNote(undefined, 10)).toBeNull()
  expect(carryoverNote(2, null)).toBeNull()
})
