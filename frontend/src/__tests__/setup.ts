import "@testing-library/jest-dom/vitest"
import { configure } from "@testing-library/react"

// `findBy*` / `waitFor` esperan 1 s por defecto. Con la máquina cargada, un
// render de página con datos simulados ya resueltos tardaba más que eso y el
// test fallaba con "Unable to find role=…" aunque el elemento acababa saliendo.
// Esperar más no oculta nada: lo que no debe aparecer se comprueba con
// `queryBy*`, que no espera.
configure({ asyncUtilTimeout: 5_000 })

// jsdom no implementa scrollIntoView (el panel de tarea lleva la fila a la vista).
Element.prototype.scrollIntoView ??= () => {}
