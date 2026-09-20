import type { QueryClient } from "@tanstack/react-query"
import { myWeekKeys } from "@/lib/query-keys"

export const calendarKeys = {
  nextMeetings: () => ["calendar-next-meeting"] as const,
  nextMeeting: (userId: number | undefined) => ["calendar-next-meeting", userId] as const,
}

export function invalidateCalendarViews(queryClient: QueryClient) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: ["calendar-status"] }),
    queryClient.invalidateQueries({ queryKey: calendarKeys.nextMeetings() }),
    queryClient.invalidateQueries({ queryKey: myWeekKeys.all() }),
  ])
}
