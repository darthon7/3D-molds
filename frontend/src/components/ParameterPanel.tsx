import { useEffect, useRef, useState } from 'react';
import {
  AlertTriangle,
  Box,
  CheckCircle2,
  Download,
  FileUp,
  Layers,
  RefreshCw,
  RotateCcw,
  Sliders,
  Sparkles,
} from 'lucide-react';
import {
  clampMoldParam,
  getEffectivePartingZ,
  MOLD_PARAM_LIMITS,
  type NumericMoldParamKey,
  useMoldStore,
} from '../store/useMoldStore';
import type { ExportFormat, MoldType } from '../types/mold';
import { isSupportedMeshFile } from '../utils/meshFile';

export function ParameterPanel() {
  const phase = useMoldStore((s) => s.phase);
  const analysis = useMoldStore((s) => s.analysis);
  const generated = useMoldStore((s) => s.generated);
  const params = useMoldStore((s) => s.params);

  const setParam = useMoldStore((s) => s.setParam);
  const setMoldType = useMoldStore((s) => s.setMoldType);
  const setExportFormat = useMoldStore((s) => s.setExportFormat);
  const reanalyzeWithAutoOrient = useMoldStore((s) => s.reanalyzeWithAutoOrient);
  const triggerGenerate = useMoldStore((s) => s.triggerGenerate);
  const uploadAndAnalyze = useMoldStore((s) => s.uploadAndAnalyze);
  const resetCustomMarkers = useMoldStore((s) => s.resetCustomMarkers);
  const resetProject = useMoldStore((s) => s.resetProject);
  const setError = useMoldStore((s) => s.setError);

  const replaceInputRef = useRef<HTMLInputElement | null>(null);
  const [draftValues, setDraftValues] = useState<
    Partial<Record<NumericMoldParamKey, string>>
  >({});

  useEffect(() => {
    setDraftValues({});
  }, [analysis?.model_id]);

  const isBusy = phase === 'analyzing' || phase === 'generating';
  const hasCustomMarkers = Boolean(
    params.custom_key_positions ||
      params.custom_spout_position ||
      params.custom_vent_points
  );

  const effectivePartingZ = getEffectivePartingZ(analysis, params.parting_z_offset);

  const handleNumberChange = (key: NumericMoldParamKey, rawValue: string) => {
    setDraftValues((prev) => ({ ...prev, [key]: rawValue }));
    const parsed = Number.parseFloat(rawValue);
    if (Number.isFinite(parsed)) {
      setParam(key, parsed);
    }
  };

  const handleNumberBlur = (key: NumericMoldParamKey) => {
    const rawValue = draftValues[key];
    setDraftValues((prev) => {
      if (!(key in prev)) return prev;
      const next = { ...prev };
      delete next[key];
      return next;
    });
    if (rawValue !== undefined) {
      const parsed = Number.parseFloat(rawValue);
      setParam(
        key,
        Number.isFinite(parsed)
          ? clampMoldParam(key, parsed)
          : clampMoldParam(key, params[key])
      );
    }
  };

  return (
    <aside
      aria-label="Panel de parámetros del molde"
      className="flex h-full w-full flex-col border-l border-slate-800/90 bg-slate-900/95 text-slate-100 md:w-[380px] lg:w-[400px]"
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-800 px-5 py-3.5">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-cyan-500/15 text-cyan-400 ring-1 ring-cyan-500/30">
            <Sliders className="h-4 w-4" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-white">Parámetros del Molde</h2>
            <p className="text-[11px] text-slate-400">
              Configuración CAD y exportación
            </p>
          </div>
        </div>

        {analysis && (
          <div className="flex items-center gap-1.5">
            <input
              ref={replaceInputRef}
              data-testid="replace-file-input"
              type="file"
              accept=".stl,.obj,.3mf"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) {
                  if (!isSupportedMeshFile(file)) {
                    setError(
                      `Formato no compatible ("${file.name}"). Sube un archivo .stl, .obj o .3mf.`
                    );
                  } else {
                    void uploadAndAnalyze(file);
                  }
                }
                e.target.value = '';
              }}
            />
            <button
              type="button"
              data-testid="replace-file-button"
              aria-label="Cargar otro archivo 3D"
              onClick={() => replaceInputRef.current?.click()}
              disabled={isBusy}
              className="inline-flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-800/80 px-2 py-1 text-[11px] font-medium text-slate-200 transition hover:border-cyan-500/50 hover:text-white disabled:opacity-50"
              title="Cargar otro archivo 3D"
            >
              <FileUp className="h-3.5 w-3.5 text-cyan-400" />
              Otro
            </button>
            <button
              type="button"
              data-testid="reset-project-button"
              aria-label="Reiniciar proyecto"
              onClick={resetProject}
              disabled={isBusy}
              className="rounded-lg border border-slate-700 bg-slate-800/80 p-1.5 text-slate-300 transition hover:border-rose-500/50 hover:text-rose-300 disabled:opacity-50"
              title="Reiniciar proyecto"
            >
              <RotateCcw className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
      </div>

      {/* Scrollable Body */}
      <div className="flex-1 space-y-5 overflow-y-auto px-5 py-4">
        {/* Model Metrics Summary */}
        {analysis ? (
          <section
            data-testid="model-metrics"
            className="rounded-xl border border-slate-800 bg-slate-950/70 p-3.5"
          >
            <div className="mb-2.5 flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="truncate text-xs font-semibold text-white" title={analysis.filename}>
                  {analysis.filename}
                </p>
                <p className="font-mono text-[10px] text-slate-400">
                  ID: {analysis.model_id}
                </p>
              </div>
              {analysis.is_watertight ? (
                <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-medium text-emerald-300 ring-1 ring-emerald-500/30">
                  <CheckCircle2 className="h-3 w-3" />
                  Watertight
                </span>
              ) : (
                <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-medium text-amber-300 ring-1 ring-amber-500/30">
                  <AlertTriangle className="h-3 w-3" />
                  No cerrada
                </span>
              )}
            </div>

            <div className="grid grid-cols-2 gap-2 text-[11px]">
              <div className="rounded-lg bg-slate-900/90 px-2.5 py-1.5">
                <span className="block text-[10px] text-slate-400">Dimensiones (mm)</span>
                <span className="font-mono font-medium text-slate-100">
                  {analysis.dimensions[0].toFixed(1)} × {analysis.dimensions[1].toFixed(1)} ×{' '}
                  {analysis.dimensions[2].toFixed(1)}
                </span>
              </div>
              <div className="rounded-lg bg-slate-900/90 px-2.5 py-1.5">
                <span className="block text-[10px] text-slate-400">Volumen</span>
                <span className="font-mono font-medium text-slate-100">
                  {(analysis.volume_mm3 / 1000).toFixed(2)} cm³
                </span>
              </div>
              <div className="rounded-lg bg-slate-900/90 px-2.5 py-1.5">
                <span className="block text-[10px] text-slate-400">Vértices / Caras</span>
                <span className="font-mono font-medium text-slate-100">
                  {analysis.vertex_count.toLocaleString()} / {analysis.face_count.toLocaleString()}
                </span>
              </div>
              <div className="rounded-lg bg-slate-900/90 px-2.5 py-1.5">
                <span className="block text-[10px] text-slate-400">Trampas de aire</span>
                <span className="font-mono font-medium text-cyan-300">
                  {analysis.air_traps.length} detectadas
                </span>
              </div>
            </div>
          </section>
        ) : (
          <div className="rounded-xl border border-dashed border-slate-700/80 bg-slate-950/40 p-4 text-center">
            <Box className="mx-auto mb-2 h-6 w-6 text-slate-500" />
            <p className="text-xs font-medium text-slate-300">
              Ningún modelo cargado
            </p>
            <p className="mt-1 text-[11px] text-slate-500">
              Sube un archivo .stl, .obj o .3mf para ajustar los parámetros del molde.
            </p>
          </div>
        )}

        {/* Mold Type */}
        <div className="space-y-1.5">
          <label
            htmlFor="select-mold-type"
            className="block text-xs font-medium text-slate-300"
          >
            Modalidad de Molde
          </label>
          <select
            id="select-mold-type"
            data-testid="select-mold-type"
            value={params.mold_type}
            disabled={isBusy}
            onChange={(e) => setMoldType(e.target.value as MoldType)}
            className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 outline-none transition focus:border-cyan-500 disabled:opacity-60"
          >
            <option value="direct_negative">
              Molde Negativo Bivalvo (Cavidad directa)
            </option>
            <option value="pouring_box">
              Caja de Moldeo / Metamolde (Silicona líquida)
            </option>
          </select>
        </div>

        {/* Numeric Parameters Grid */}
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1">
            <label
              htmlFor="input-wall-thickness"
              className="block text-[11px] font-medium text-slate-300"
            >
              Grosor pared (mm)
            </label>
            <input
              id="input-wall-thickness"
              data-testid="input-wall-thickness"
              type="number"
              min={MOLD_PARAM_LIMITS.wall_thickness.min}
              max={MOLD_PARAM_LIMITS.wall_thickness.max}
              step={MOLD_PARAM_LIMITS.wall_thickness.step}
              value={draftValues.wall_thickness ?? params.wall_thickness}
              disabled={isBusy}
              onFocus={() =>
                setDraftValues((prev) => ({
                  ...prev,
                  wall_thickness: String(params.wall_thickness),
                }))
              }
              onChange={(e) => handleNumberChange('wall_thickness', e.target.value)}
              onBlur={() => handleNumberBlur('wall_thickness')}
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1.5 font-mono text-xs text-slate-100 outline-none focus:border-cyan-500 disabled:opacity-60"
            />
          </div>

          <div className="space-y-1">
            <label
              htmlFor="input-parting-z"
              className="block text-[11px] font-medium text-slate-300"
            >
              Offset corte Z (mm)
            </label>
            <input
              id="input-parting-z"
              data-testid="input-parting-z"
              type="number"
              min={MOLD_PARAM_LIMITS.parting_z_offset.min}
              max={MOLD_PARAM_LIMITS.parting_z_offset.max}
              step={MOLD_PARAM_LIMITS.parting_z_offset.step}
              value={draftValues.parting_z_offset ?? params.parting_z_offset}
              disabled={isBusy}
              onFocus={() =>
                setDraftValues((prev) => ({
                  ...prev,
                  parting_z_offset: String(params.parting_z_offset),
                }))
              }
              onChange={(e) => handleNumberChange('parting_z_offset', e.target.value)}
              onBlur={() => handleNumberBlur('parting_z_offset')}
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1.5 font-mono text-xs text-cyan-300 outline-none focus:border-cyan-500 disabled:opacity-60"
            />
            {analysis && (
              <span className="block font-mono text-[10px] text-slate-500">
                Plano Z: {effectivePartingZ.toFixed(2)} mm
              </span>
            )}
          </div>

          <div className="space-y-1">
            <label
              htmlFor="input-key-radius"
              className="block text-[11px] font-medium text-slate-300"
            >
              Radio llaves (mm)
            </label>
            <input
              id="input-key-radius"
              data-testid="input-key-radius"
              type="number"
              min={MOLD_PARAM_LIMITS.key_radius.min}
              max={MOLD_PARAM_LIMITS.key_radius.max}
              step={MOLD_PARAM_LIMITS.key_radius.step}
              value={draftValues.key_radius ?? params.key_radius}
              disabled={isBusy}
              onFocus={() =>
                setDraftValues((prev) => ({
                  ...prev,
                  key_radius: String(params.key_radius),
                }))
              }
              onChange={(e) => handleNumberChange('key_radius', e.target.value)}
              onBlur={() => handleNumberBlur('key_radius')}
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1.5 font-mono text-xs text-slate-100 outline-none focus:border-cyan-500 disabled:opacity-60"
            />
          </div>

          <div className="space-y-1">
            <label
              htmlFor="input-tolerance"
              className="block text-[11px] font-medium text-slate-300"
            >
              Tolerancia encaje (mm)
            </label>
            <input
              id="input-tolerance"
              data-testid="input-tolerance"
              type="number"
              min={MOLD_PARAM_LIMITS.tolerance.min}
              max={MOLD_PARAM_LIMITS.tolerance.max}
              step={MOLD_PARAM_LIMITS.tolerance.step}
              value={draftValues.tolerance ?? params.tolerance}
              disabled={isBusy}
              onFocus={() =>
                setDraftValues((prev) => ({
                  ...prev,
                  tolerance: String(params.tolerance),
                }))
              }
              onChange={(e) => handleNumberChange('tolerance', e.target.value)}
              onBlur={() => handleNumberBlur('tolerance')}
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1.5 font-mono text-xs text-slate-100 outline-none focus:border-cyan-500 disabled:opacity-60"
            />
          </div>

          <div className="space-y-1">
            <label
              htmlFor="input-spout-radius"
              className="block text-[11px] font-medium text-slate-300"
            >
              Radio bebedero (mm)
            </label>
            <input
              id="input-spout-radius"
              data-testid="input-spout-radius"
              type="number"
              min={MOLD_PARAM_LIMITS.spout_radius.min}
              max={MOLD_PARAM_LIMITS.spout_radius.max}
              step={MOLD_PARAM_LIMITS.spout_radius.step}
              value={draftValues.spout_radius ?? params.spout_radius}
              disabled={isBusy}
              onFocus={() =>
                setDraftValues((prev) => ({
                  ...prev,
                  spout_radius: String(params.spout_radius),
                }))
              }
              onChange={(e) => handleNumberChange('spout_radius', e.target.value)}
              onBlur={() => handleNumberBlur('spout_radius')}
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1.5 font-mono text-xs text-slate-100 outline-none focus:border-cyan-500 disabled:opacity-60"
            />
          </div>

          <div className="space-y-1">
            <label
              htmlFor="select-export-format"
              className="block text-[11px] font-medium text-slate-300"
            >
              Formato exportación
            </label>
            <select
              id="select-export-format"
              data-testid="select-export-format"
              value={params.export_format}
              disabled={isBusy}
              onChange={(e) => setExportFormat(e.target.value as ExportFormat)}
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1.5 font-mono text-xs uppercase text-slate-100 outline-none focus:border-cyan-500 disabled:opacity-60"
            >
              <option value="stl">STL (.stl)</option>
              <option value="3mf">3MF (.3mf)</option>
            </select>
          </div>
        </div>

        {/* Toggles */}
        <div className="space-y-2.5 rounded-xl border border-slate-800 bg-slate-950/60 p-3">
          <label className="flex cursor-pointer items-center justify-between gap-3">
            <div>
              <span className="block text-xs font-medium text-slate-200">
                Auto-orientación óptima
              </span>
              <span className="block text-[10px] text-slate-400">
                Minimiza contrasalidas en eje Z
              </span>
            </div>
            <input
              type="checkbox"
              data-testid="toggle-auto-orient"
              checked={params.auto_orient}
              disabled={isBusy}
              onChange={(e) => {
                void reanalyzeWithAutoOrient(e.target.checked);
              }}
              className="h-4 w-4 rounded border-slate-600 bg-slate-800 text-cyan-500 focus:ring-cyan-500"
            />
          </label>

          <div className="h-px bg-slate-800" />

          <label className="flex cursor-pointer items-center justify-between gap-3">
            <div>
              <span className="block text-xs font-medium text-slate-200">
                Respiraderos automáticos
              </span>
              <span className="block text-[10px] text-slate-400">
                Canales en puntos altos para evitar burbujas
              </span>
            </div>
            <input
              type="checkbox"
              data-testid="toggle-auto-vents"
              checked={params.auto_vents}
              disabled={isBusy}
              onChange={(e) => setParam('auto_vents', e.target.checked)}
              className="h-4 w-4 rounded border-slate-600 bg-slate-800 text-cyan-500 focus:ring-cyan-500"
            />
          </label>
        </div>

        {/* Reset Custom 3D Markers */}
        {hasCustomMarkers && (
          <button
            type="button"
            data-testid="reset-markers-button"
            onClick={resetCustomMarkers}
            className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-1.5 text-xs font-medium text-slate-200 transition hover:border-cyan-500/50 hover:text-white"
          >
            <RefreshCw className="h-3.5 w-3.5 text-cyan-400" />
            Restablecer marcadores 3D sugeridos
          </button>
        )}

        {/* Generated Parts List */}
        {generated && (
          <section
            data-testid="generated-parts-list"
            className="space-y-2 rounded-xl border border-emerald-500/30 bg-emerald-950/20 p-3.5"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5 text-xs font-semibold text-emerald-300">
                <Layers className="h-4 w-4" />
                Piezas Generadas ({generated.parts.length})
              </div>
              <span className="font-mono text-[10px] text-emerald-400/80">
                Job {generated.job_id}
              </span>
            </div>

            <ul className="space-y-1.5">
              {generated.parts.map((part) => (
                <li
                  key={part.name}
                  className="flex items-center justify-between gap-2 rounded-lg border border-slate-800 bg-slate-900/90 px-2.5 py-2 text-xs"
                >
                  <div className="min-w-0">
                    <p className="truncate font-medium text-slate-100">
                      {part.filename}
                    </p>
                    <p className="font-mono text-[10px] text-slate-400">
                      {(part.volume_mm3 / 1000).toFixed(2)} cm³ ·{' '}
                      <span
                        className={
                          part.is_watertight ? 'text-emerald-400' : 'text-amber-400'
                        }
                      >
                        {part.is_watertight ? 'Watertight' : 'Revisar malla'}
                      </span>
                    </p>
                  </div>
                  <a
                    data-testid={`download-part-${part.name}`}
                    aria-label={`Descargar ${part.filename}`}
                    href={part.url}
                    download={part.filename}
                    className="shrink-0 rounded-md border border-slate-700 bg-slate-800 p-1.5 text-slate-300 transition hover:border-cyan-500/50 hover:text-cyan-300"
                    title={`Descargar ${part.filename}`}
                  >
                    <Download className="h-3.5 w-3.5" />
                  </a>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>

      {/* Footer Actions */}
      <div className="space-y-2.5 border-t border-slate-800 bg-slate-900/95 px-5 py-4">
        <button
          type="button"
          data-testid="generate-mold-button"
          disabled={!analysis || isBusy}
          onClick={() => void triggerGenerate()}
          className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-cyan-500 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-cyan-500/20 transition hover:from-cyan-400 hover:to-blue-500 disabled:cursor-not-allowed disabled:opacity-45 disabled:shadow-none"
        >
          <Sparkles className="h-4 w-4" />
          {phase === 'generating' ? 'Generando Molde...' : 'Generar Molde'}
        </button>

        {generated && (
          <a
            data-testid="download-zip-button"
            href={generated.zip_url}
            download={`molde_${generated.job_id}.zip`}
            className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-emerald-500/50 bg-emerald-600/20 px-4 py-2.5 text-sm font-semibold text-emerald-200 transition hover:bg-emerald-600/30 hover:text-white"
          >
            <Download className="h-4 w-4 text-emerald-400" />
            Descargar ZIP Completo
          </a>
        )}
      </div>
    </aside>
  );
}
