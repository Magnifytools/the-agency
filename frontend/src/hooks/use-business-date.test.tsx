import { act, renderHook } from "@testing-library/react"
import { afterEach, expect, it, vi } from "vitest"
import { useBusinessDate } from "./use-business-date"
import { setAgencyTimezone } from "@/lib/dates"

afterEach(() => vi.useRealTimers())

it("rerenders the operational date at Madrid midnight without a user interaction", () => {
  vi.useFakeTimers()
  setAgencyTimezone("Europe/Madrid")
  vi.setSystemTime(new Date("2026-09-17T21:59:59Z"))
  const { result, unmount } = renderHook(useBusinessDate)
  expect(result.current).toBe("2026-09-17")
  act(() => vi.advanceTimersByTime(2100))
  expect(result.current).toBe("2026-09-18")
  unmount()
  expect(vi.getTimerCount()).toBe(0)
})
