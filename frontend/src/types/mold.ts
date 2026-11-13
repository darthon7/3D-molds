export type Vec3 = [number, number, number];

export type MoldType = 'direct_negative' | 'pouring_box';
export type ExportFormat = 'stl' | '3mf';

export interface AnalyzeResponse {
  model_id: string;
  filename: string;
  is_watertight: boolean;
  volume_mm3: number;
  vertex_count: number;
  face_count: number;
  bbox_min: Vec3;
  bbox_max: Vec3;
  dimensions: Vec3;
  suggested_parting_z: number;
  air_traps: Vec3[];
  spout_position: Vec3;
  key_positions: Vec3[];
  oriented_mesh_url: string;
}

export interface MoldParams {
  mold_type: MoldType;
  wall_thickness: number;
  parting_z_offset: number;
  key_radius: number;
  tolerance: number;
  spout_radius: number;
  auto_orient: boolean;
  auto_vents: boolean;
  export_format: ExportFormat;
  custom_spout_position: Vec3 | null;
  custom_vent_points: Vec3[] | null;
  custom_key_positions: Vec3[] | null;
}

export interface GenerateRequest {
  model_id: string;
  params: MoldParams;
}

export interface GeneratedPartInfo {
  name: string;
  filename: string;
  url: string;
  preview_url?: string;
  is_watertight: boolean;
  volume_mm3: number;
}

export interface GenerateResponse {
  job_id: string;
  model_id: string;
  mold_type: MoldType;
  parts: GeneratedPartInfo[];
  zip_url: string;
}

export type AppPhase = 'idle' | 'analyzing' | 'ready' | 'generating' | 'generated';

export type InteractiveMarkerKind = 'key' | 'spout' | 'vent';

export interface SelectedMarker {
  kind: InteractiveMarkerKind;
  index: number;
}
