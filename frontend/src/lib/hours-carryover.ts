/**
 * Arrastre de horas entre meses (opción `hours_carryover` del proyecto): el
 * techo de este mes = techo base + lo que sobró (o − el exceso) el mes
 * anterior. El cálculo es del servidor (`services/hours_carryover.py`); aquí
 * sólo se explica.
 */

function hours(value: number): string {
  return `${Number(value.toFixed(1))}h`.replace(".", ",")
}

/** "10h del mes + 2h que sobraron el mes anterior. Aviso temprano al 75 %." */
export function carryoverNote(carried: number | null | undefined, base: number | null | undefined): string | null {
  if (carried == null || base == null) return null
  const what = carried >= 0 ? `+ ${hours(carried)} que sobraron` : `− ${hours(Math.abs(carried))} de exceso`
  return `${hours(base)} del mes ${what} el mes anterior. Aviso temprano al 75 %.`
}
