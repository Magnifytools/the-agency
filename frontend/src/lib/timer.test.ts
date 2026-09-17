import { describe, expect, it } from "vitest"

import { elapsedSeconds, formatElapsedSeconds } from "./timer"

describe("timer elapsed contract", () => {
  it("adds previous segments after resume", () => {
    expect(elapsedSeconds("2026-09-17T10:00:00Z", 120, false, Date.parse("2026-09-17T10:01:00Z"))).toBe(180)
  })

  it("freezes a paused timer at accumulated seconds", () => {
    expect(elapsedSeconds("2026-09-17T10:00:00", 125, "2026-09-17T10:02:05", Date.parse("2026-09-18T10:00:00Z"))).toBe(125)
    expect(formatElapsedSeconds(125)).toBe("00:02:05")
  })
})
