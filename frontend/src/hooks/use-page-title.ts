import { useEffect, useLayoutEffect } from "react"

const APP_NAME = "The Agency"

export function pageTitle(title?: string | null) {
  return title ? `${title} · ${APP_NAME}` : APP_NAME
}

/** Título de la pestaña del navegador para esta pantalla. */
export function usePageTitle(title?: string | null) {
  // Efecto normal: corre después del useLayoutEffect del layout, así que el
  // título concreto de una ficha (p. ej. el nombre del cliente) gana al genérico.
  useEffect(() => {
    if (title) document.title = pageTitle(title)
  }, [title])
}

/** Título genérico por sección, puesto por el layout antes que el de la página. */
export function useSectionTitle(title?: string | null) {
  useLayoutEffect(() => {
    document.title = pageTitle(title)
  }, [title])
}
