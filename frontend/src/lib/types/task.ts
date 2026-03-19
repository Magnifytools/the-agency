import type { TaskStatus, TaskPriority } from "./common"

export interface TaskCategory {
  id: number
  name: string
  default_minutes: number
  created_at: string
  updated_at: string
}

export interface Task {
  id: number
  title: string
  description: string | null
  status: TaskStatus
  priority: TaskPriority
  estimated_minutes: number | null
  actual_minutes: number | null
  start_date: string | null
  due_date: string | null
  client_id: number | null
  category_id: number | null
  assigned_to: number | null
  project_id: number | null
  phase_id: number | null
  is_inbox: boolean
  depends_on: number | null
  created_by: number | null
  scheduled_date: string | null
  waiting_for: string | null
  follow_up_date: string | null
  is_recurring: boolean
  recurrence_pattern: string | null
  recurrence_day: number | null
  recurrence_end_date: string | null
  recurring_parent_id: number | null
  unit_cost: number | null
  invoiced_at: string | null
  created_at: string
  updated_at: string
  client_name: string | null
  category_name: string | null
  assigned_user_name: string | null
  project_name: string | null
  phase_name: string | null
  dependency_title: string | null
  created_by_name: string | null
  recurring_parent_title: string | null
  checklist_count: number
}

export interface ChecklistItem {
  id: number
  task_id: number
  text: string
  description: string | null
  is_done: boolean
  order_index: number
  assigned_to: number | null
  due_date: string | null
  assigned_user_name: string | null
  created_at: string
  updated_at: string
}

export interface TaskCreate {
  title: string
  description?: string | null
  status?: TaskStatus
  priority?: TaskPriority
  estimated_minutes?: number | null
  actual_minutes?: number | null
  start_date?: string | null
  due_date?: string | null
  client_id?: number | null
  category_id?: number | null
  assigned_to?: number | null
  project_id?: number | null
  phase_id?: number | null
  depends_on?: number | null
  is_inbox?: boolean
  scheduled_date?: string | null
  waiting_for?: string | null
  follow_up_date?: string | null
  is_recurring?: boolean
  recurrence_pattern?: string | null
  recurrence_day?: number | null
  recurrence_end_date?: string | null
  recurring_parent_id?: number | null
  unit_cost?: number | null
}

export interface TaskComment {
  id: number
  task_id: number
  user_id: number
  text: string
  user_name: string | null
  created_at: string
  updated_at: string
}

export interface TaskAttachment {
  id: number
  task_id: number
  name: string
  description: string | null
  mime_type: string
  size_bytes: number
  uploaded_by: number | null
  uploaded_by_name: string | null
  created_at: string
  updated_at: string
}

// Time Entries
export interface TimeEntry {
  id: number
  minutes: number | null
  started_at: string | null
  date: string
  notes: string | null
  task_id: number | null
  user_id: number
  created_at: string
  updated_at: string
  task_title: string | null
  client_name: string | null
}

export interface TimeEntryCreate {
  minutes: number
  task_id: number | null
  notes?: string | null
  date?: string | null
}

export interface ActiveTimer {
  id: number
  task_id: number | null
  task_title: string | null
  client_name: string | null
  started_at: string
}
