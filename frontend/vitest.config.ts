import { defineConfig } from "vitest/config"
import path from "path"

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/__tests__/setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    css: false,
    // Los tests de página (clientes, tareas, captura, proyectos...) montan la
    // página entera en jsdom y consultan por rol: ~40 % del CPU se va en
    // `getComputedStyle` de jsdom. Solos tardan como mucho ~1,6 s, pero con la
    // máquina cargada (todos los workers + la suite de backend) llegaban a 7 s
    // y caían por los 5 s por defecto, sin ningún fallo real. El plazo sólo
    // sirve para detectar un test colgado, así que se da margen de sobra.
    // Ojo: un test que agota el plazo NO se detiene y sigue pulsando sobre el
    // DOM del siguiente test, así que un timeout también rompía al vecino.
    testTimeout: 30_000,
  },
})
