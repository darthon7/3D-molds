import { create } from 'zustand';
import { analyzeModel, generateMold } from '../api/moldApi';
import type {
  AnalyzeResponse,
  AppPhase,
  ExportFormat,
  GenerateResponse,
  MoldParams,
  MoldType,
  SelectedMarker,
  Vec3,
} from '../types/mold';

export type NumericMoldParamKey =
  | 'wall_thickness'
  | 'parting_z_offset'
  | 'key_radius'
  | 'tolerance'
  | 'spout_radius';

export interface ParamLimit {
  min: number;
  max: number;
  step: number;
}

export const MOLD_PARAM_LIMITS: Record<NumericMoldParamKey, ParamLimit> = {
  wall_thickness: { min: 3, max: 50, step: 0.5 },
  parting_z_offset: { min: -500, max: 500, step: 0.5 },
  key_radius: { min: 2, max: 15, step: 0.5 },
  tolerance: { min: 0.15, max: 0.35, step: 0.01 },
  spout_radius: { min: 2, max: 20, step: 0.5 },
};

const DEFAULT_PARAMS: MoldParams = {
  mold_type: 'direct_negative',
  wall_thickness: 10,
  parting_z_offset: 0,
  key_radius: 4,
  tolerance: 0.25,
  spout_radius: 5,
  auto_orient: true,
  auto_vents: true,
  export_format: 'stl',
  custom_spout_position: null,
  custom_vent_points: null,
  custom_key_positions: null,
};

export function isNumericMoldParamKey(
  key: keyof MoldParams
): key is NumericMoldParamKey {
  return key in MOLD_PARAM_LIMITS;
}

export function clampMoldParam(key: NumericMoldParamKey, value: number): number {
  if (!Number.isFinite(value)) {
    return DEFAULT_PARAMS[key];
  }
  const { min, max } = MOLD_PARAM_LIMITS[key];
  return Math.max(min, Math.min(max, value));
}

export function sanitizeMoldParams(params: MoldParams): MoldParams {
  return {
    ...params,
    wall_thickness: clampMoldParam('wall_thickness', params.wall_thickness),
    parting_z_offset: clampMoldParam('parting_z_offset', params.parting_z_offset),
    key_radius: clampMoldParam('key_radius', params.key_radius),
    tolerance: clampMoldParam('tolerance', params.tolerance),
    spout_radius: clampMoldParam('spout_radius', params.spout_radius),
    custom_vent_points: params.auto_vents ? params.custom_vent_points : null,
  };
}

let currentAbortController: AbortController | null = null;

function replaceAbortController(): AbortController {
  if (currentAbortController) {
    currentAbortController.abort();
  }
  currentAbortController = new AbortController();
  return currentAbortController;
}

function isAbortError(err: unknown): boolean {
  return (
    (err instanceof DOMException && err.name === 'AbortError') ||
    (err instanceof Error && err.name === 'AbortError')
  );
}

function isTimeoutError(err: unknown): boolean {
  return (
    (err instanceof DOMException && err.name === 'TimeoutError') ||
    (err instanceof Error && err.name === 'TimeoutError')
  );
}

function formatRequestError(err: unknown, fallback: string): string {
  if (isTimeoutError(err)) {
    return 'La operación superó el tiempo de espera. Inténtalo de nuevo.';
  }
  return err instanceof Error ? err.message : fallback;
}

export function getBboxCenterZ(analysis: AnalyzeResponse | null): number {
  if (!analysis) return 0;
  return (analysis.bbox_min[2] + analysis.bbox_max[2]) / 2;
}

export function getEffectivePartingZ(
  analysis: AnalyzeResponse | null,
  partingZOffset: number
): number {
  return getBboxCenterZ(analysis) + partingZOffset;
}

type LastActionKind = 'analyze' | 'generate' | null;

interface MoldState {
  phase: AppPhase;
  selectedFile: File | null;
  analysis: AnalyzeResponse | null;
  generated: GenerateResponse | null;
  params: MoldParams;
  explosionDistance: number;
  showOriginalMesh: boolean;
  showMoldParts: boolean;
  isDraggingGizmo: boolean;
  selectedMarker: SelectedMarker | null;
  lastAction: LastActionKind;
  lastAnalyzeAutoOrient: boolean | null;
  error: string | null;
  successMessage: string | null;

  // Actions
  uploadAndAnalyze: (file: File, autoOrientOverride?: boolean) => Promise<void>;
  reanalyzeWithAutoOrient: (autoOrient: boolean) => Promise<void>;
  retryLastAction: () => Promise<void>;
  triggerGenerate: () => Promise<void>;
  cancelActiveRequest: () => void;
  resetProject: () => void;

  setParam: <K extends keyof MoldParams>(key: K, value: MoldParams[K]) => void;
  setMoldType: (moldType: MoldType) => void;
  setExportFormat: (format: ExportFormat) => void;
  setPartingZFromWorld: (worldZ: number) => void;

  updateKeyPosition: (index: number, pos: Vec3) => void;
  updateSpoutPosition: (pos: Vec3) => void;
  updateVentPosition: (index: number, pos: Vec3) => void;
  resetCustomMarkers: () => void;

  setExplosionDistance: (distance: number) => void;
  setShowOriginalMesh: (show: boolean) => void;
  setShowMoldParts: (show: boolean) => void;
  setIsDraggingGizmo: (dragging: boolean) => void;
  setSelectedMarker: (marker: SelectedMarker | null) => void;
  setError: (error: string | null) => void;
  dismissError: () => void;
  dismissSuccess: () => void;
}

export const useMoldStore = create<MoldState>((set, get) => ({
  phase: 'idle',
  selectedFile: null,
  analysis: null,
  generated: null,
  params: { ...DEFAULT_PARAMS },
  explosionDistance: 0,
  showOriginalMesh: true,
  showMoldParts: true,
  isDraggingGizmo: false,
  selectedMarker: null,
  lastAction: null,
  lastAnalyzeAutoOrient: null,
  error: null,
  successMessage: null,

  uploadAndAnalyze: async (file: File, autoOrientOverride?: boolean) => {
    const controller = replaceAbortController();
    const { params } = get();
    const effectiveAutoOrient = autoOrientOverride ?? params.auto_orient;

    set({
      phase: 'analyzing',
      selectedFile: file,
      lastAction: 'analyze',
      lastAnalyzeAutoOrient: effectiveAutoOrient,
      error: null,
      successMessage: null,
      generated: null,
      explosionDistance: 0,
      selectedMarker: null,
    });

    try {
      const data = await analyzeModel(file, effectiveAutoOrient, controller.signal);
      if (controller.signal.aborted) return;

      const centerZ = (data.bbox_min[2] + data.bbox_max[2]) / 2;
      const initialOffset = clampMoldParam(
        'parting_z_offset',
        Number((data.suggested_parting_z - centerZ).toFixed(2))
      );

      set((state) => ({
        phase: 'ready',
        analysis: data,
        generated: null,
        showOriginalMesh: true,
        showMoldParts: true,
        params: {
          ...state.params,
          auto_orient: effectiveAutoOrient,
          parting_z_offset: initialOffset,
          custom_key_positions: null,
          custom_spout_position: null,
          custom_vent_points: null,
        },
        successMessage: `Modelo "${data.filename}" analizado correctamente.`,
      }));
    } catch (err) {
      if (isAbortError(err)) return;
      const message = formatRequestError(err, 'No se pudo analizar el modelo 3D.');
      set((state) => ({
        phase: state.analysis ? 'ready' : 'idle',
        error: message,
      }));
    }
  },

  reanalyzeWithAutoOrient: async (autoOrient: boolean) => {
    const { selectedFile, uploadAndAnalyze } = get();
    if (selectedFile) {
      await uploadAndAnalyze(selectedFile, autoOrient);
    } else {
      set((state) => ({
        params: { ...state.params, auto_orient: autoOrient },
      }));
    }
  },

  retryLastAction: async () => {
    const {
      lastAction,
      lastAnalyzeAutoOrient,
      selectedFile,
      analysis,
      uploadAndAnalyze,
      triggerGenerate,
    } = get();

    if (lastAction === 'analyze' && selectedFile) {
      await uploadAndAnalyze(selectedFile, lastAnalyzeAutoOrient ?? undefined);
      return;
    }
    if (lastAction === 'generate' && analysis) {
      await triggerGenerate();
      return;
    }
    if (selectedFile && !analysis) {
      await uploadAndAnalyze(selectedFile, lastAnalyzeAutoOrient ?? undefined);
    } else if (analysis) {
      await triggerGenerate();
    }
  },

  triggerGenerate: async () => {
    const { analysis, params } = get();
    if (!analysis) {
      set({ error: 'Primero debes cargar y analizar un modelo 3D.' });
      return;
    }

    const sanitizedParams = sanitizeMoldParams(params);
    const controller = replaceAbortController();

    set({
      phase: 'generating',
      lastAction: 'generate',
      params: sanitizedParams,
      error: null,
      successMessage: null,
    });

    try {
      const result = await generateMold(
        {
          model_id: analysis.model_id,
          params: sanitizedParams,
        },
        controller.signal
      );
      if (controller.signal.aborted) return;

      set({
        phase: 'generated',
        generated: result,
        explosionDistance: 12,
        showMoldParts: true,
        successMessage: `Molde generado (${result.parts.length} piezas listas para descargar).`,
      });
    } catch (err) {
      if (isAbortError(err)) return;
      const message = formatRequestError(err, 'Error al generar las piezas del molde.');
      set((state) => ({
        phase: state.generated ? 'generated' : 'ready',
        error: message,
      }));
    }
  },

  cancelActiveRequest: () => {
    if (currentAbortController) {
      currentAbortController.abort();
      currentAbortController = null;
    }
    set((state) => ({
      phase: state.generated ? 'generated' : state.analysis ? 'ready' : 'idle',
      error: null,
    }));
  },

  resetProject: () => {
    if (currentAbortController) {
      currentAbortController.abort();
      currentAbortController = null;
    }
    set({
      phase: 'idle',
      selectedFile: null,
      analysis: null,
      generated: null,
      params: { ...DEFAULT_PARAMS },
      explosionDistance: 0,
      showOriginalMesh: true,
      showMoldParts: true,
      isDraggingGizmo: false,
      selectedMarker: null,
      lastAction: null,
      lastAnalyzeAutoOrient: null,
      error: null,
      successMessage: null,
    });
  },

  setParam: (key, value) => {
    set((state) => {
      const nextValue =
        isNumericMoldParamKey(key) && typeof value === 'number'
          ? (clampMoldParam(key, value) as MoldParams[typeof key])
          : value;
      const clearVentSelection =
        key === 'auto_vents' &&
        value === false &&
        state.selectedMarker?.kind === 'vent';

      return {
        selectedMarker: clearVentSelection ? null : state.selectedMarker,
        params: { ...state.params, [key]: nextValue },
      };
    });
  },

  setMoldType: (moldType) => {
    set((state) => ({
      params: { ...state.params, mold_type: moldType },
    }));
  },

  setExportFormat: (format) => {
    set((state) => ({
      params: { ...state.params, export_format: format },
    }));
  },

  setPartingZFromWorld: (worldZ) => {
    const { analysis } = get();
    if (!analysis) return;
    const centerZ = getBboxCenterZ(analysis);
    const minZ = analysis.bbox_min[2];
    const maxZ = analysis.bbox_max[2];
    const clampedZ = Math.max(minZ, Math.min(maxZ, worldZ));
    const offset = clampMoldParam(
      'parting_z_offset',
      Number((clampedZ - centerZ).toFixed(2))
    );

    set((state) => ({
      params: {
        ...state.params,
        parting_z_offset: offset,
        custom_key_positions: state.params.custom_key_positions
          ? state.params.custom_key_positions.map((k) => [k[0], k[1], clampedZ] as Vec3)
          : null,
      },
    }));
  },

  updateKeyPosition: (index, pos) => {
    set((state) => {
      const base =
        state.params.custom_key_positions ?? state.analysis?.key_positions ?? [];
      if (index < 0 || index >= base.length) return state;
      const next = base.map((item, i) =>
        i === index
          ? ([
              Number(pos[0].toFixed(2)),
              Number(pos[1].toFixed(2)),
              Number(pos[2].toFixed(2)),
            ] as Vec3)
          : item
      );
      return {
        params: { ...state.params, custom_key_positions: next },
      };
    });
  },

  updateSpoutPosition: (pos) => {
    set((state) => ({
      params: {
        ...state.params,
        custom_spout_position: [
          Number(pos[0].toFixed(2)),
          Number(pos[1].toFixed(2)),
          Number(pos[2].toFixed(2)),
        ],
      },
    }));
  },

  updateVentPosition: (index, pos) => {
    set((state) => {
      const base = state.params.custom_vent_points ?? state.analysis?.air_traps ?? [];
      if (index < 0 || index >= base.length) return state;
      const next = base.map((item, i) =>
        i === index
          ? ([
              Number(pos[0].toFixed(2)),
              Number(pos[1].toFixed(2)),
              Number(pos[2].toFixed(2)),
            ] as Vec3)
          : item
      );
      return {
        params: { ...state.params, custom_vent_points: next },
      };
    });
  },

  resetCustomMarkers: () => {
    set((state) => ({
      selectedMarker: null,
      params: {
        ...state.params,
        custom_key_positions: null,
        custom_spout_position: null,
        custom_vent_points: null,
      },
    }));
  },

  setExplosionDistance: (distance) => set({ explosionDistance: distance }),
  setShowOriginalMesh: (show) => set({ showOriginalMesh: show }),
  setShowMoldParts: (show) => set({ showMoldParts: show }),
  setIsDraggingGizmo: (dragging) => set({ isDraggingGizmo: dragging }),
  setSelectedMarker: (marker) => set({ selectedMarker: marker }),
  setError: (error) => set({ error }),
  dismissError: () => set({ error: null }),
  dismissSuccess: () => set({ successMessage: null }),
}));
