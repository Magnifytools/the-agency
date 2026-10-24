// Pantallazos de las sugerencias: los mismos límites que el servidor (api/routes/suggestions.py).
export const MAX_IMAGES = 5
export const MAX_IMAGE_BYTES = 5 * 1024 * 1024
export const IMAGE_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp"]

/** Qué imágenes caben y por qué se quedan fuera las demás. */
export function acceptImages(current: File[], incoming: File[]): { files: File[]; problem: string | null } {
  const files = [...current]
  let problem: string | null = null
  for (const file of incoming) {
    if (!IMAGE_TYPES.includes(file.type)) problem = "Sólo imágenes PNG, JPG, GIF o WebP"
    else if (file.size > MAX_IMAGE_BYTES) problem = `${file.name || "La imagen"} pasa de 5 MB`
    else if (files.length >= MAX_IMAGES) problem = `Como mucho ${MAX_IMAGES} imágenes`
    else files.push(file)
  }
  return { files, problem }
}
