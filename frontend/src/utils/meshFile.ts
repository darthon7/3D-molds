export const ALLOWED_MESH_EXTENSIONS = ['.stl', '.obj', '.3mf'] as const;

export function isSupportedMeshFile(file: File): boolean {
  const lower = file.name.toLowerCase();
  return ALLOWED_MESH_EXTENSIONS.some((ext) => lower.endsWith(ext));
}
