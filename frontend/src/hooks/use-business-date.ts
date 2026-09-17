import { useEffect, useState } from "react"

import { businessDateString, millisecondsUntilNextBusinessDay } from "@/lib/dates"

export function useBusinessDate() {
  const [today, setToday] = useState(() => businessDateString())

  useEffect(() => {
    let timeout: ReturnType<typeof setTimeout>
    const schedule = () => {
      timeout = setTimeout(() => {
        setToday(businessDateString())
        schedule()
      }, millisecondsUntilNextBusinessDay() + 50)
    }
    schedule()
    return () => clearTimeout(timeout)
  }, [])

  return today
}
