import { parseApiInstant } from "@/lib/dates"

export function elapsedSeconds(
  startedAt: string,
  accumulatedSeconds = 0,
  paused: boolean | string | null = false,
  nowMs = Date.now(),
) {
  if (paused) return Math.max(0, accumulatedSeconds)
  const currentSegment = Math.floor((nowMs - parseApiInstant(startedAt).getTime()) / 1000)
  return Math.max(0, accumulatedSeconds + currentSegment)
}

export function formatElapsedSeconds(total: number) {
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
}
