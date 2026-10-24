import type { ServiceType } from "@/lib/types"

export const serviceTypeLabels: Record<ServiceType, string> = {
    seo_sprint: "SEO Sprint",
    migration: "Migración Web",
    market_study: "Estudio de Mercado",
    consulting_retainer: "Consultoría SEO",
    partnership_retainer: "Partnership SEO",
    brand_audit: "Brand Audit",
    custom: "Personalizado",
}

export const projectTypeLabels: Record<string, string> = {
    seo_audit: "Auditoría SEO",
    content_strategy: "Estrategia de contenido",
    linkbuilding: "Link building",
    technical_seo: "SEO técnico",
    local_seo: "SEO local",
    custom: "Personalizado",
}

export function projectTypeLabel(type: string): string {
    return projectTypeLabels[type] ?? type
}
