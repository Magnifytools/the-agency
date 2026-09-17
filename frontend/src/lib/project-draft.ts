import type { ProjectCreate, ProjectDraft } from "@/lib/types"

/** Preserve reviewed document values without deriving or inventing prices. */
export function projectCreateFromDraft(
  draft: Partial<ProjectDraft>,
  clientId: number,
): ProjectCreate {
  return {
    name: draft.name ?? "",
    client_id: clientId,
    description: draft.description ?? undefined,
    project_type: draft.project_type ?? undefined,
    is_recurring: draft.is_recurring ?? false,
    budget_amount: draft.budget_amount ?? undefined,
    monthly_fee: draft.monthly_fee ?? undefined,
    start_date: draft.start_date ?? undefined,
    target_end_date: draft.target_end_date ?? undefined,
    pricing_model: draft.pricing_model ?? undefined,
    unit_price: draft.unit_price ?? undefined,
    unit_label: draft.unit_label ?? undefined,
    scope: draft.scope ?? undefined,
  }
}
