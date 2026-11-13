import { useCallback, useRef, useState } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  Cuboid,
  Loader2,
  RefreshCw,
  UploadCloud,
  X,
} from 'lucide-react';
import { Canvas3D } from './components/Canvas3D';
import { ExplosionSlider } from './components/ExplosionSlider';
import { ParameterPanel } from './components/ParameterPanel';
import { useMoldStore } from './store/useMoldStore';
import { isSupportedMeshFile } from './utils/meshFile';

export default function App() {
  const phase = useMoldStore((s) => s.phase);
  const analysis = useMoldStore((s) => s.analysis);
  const error = useMoldStore((s) => s.error);
  const successMessage = useMoldStore((s) => s.successMessage);

  const uploadAndAnalyze = useMoldStore((s) => s.uploadAndAnalyze);
  const retryLastAction = useMoldStore((s) => s.retryLastAction);
  const cancelActiveRequest = useMoldStore((s) => s.cancelActiveRequest);
  const dismissError = useMoldStore((s) => s.dismissError);
  const dismissSuccess = useMoldStore((s) => s.dismissSuccess);

  const [isDragOver, setIsDragOver] = useState(false);
  const [localValidationError, setLocalValidationError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const isBusy = phase === 'analyzing' || phase === 'generating';

  const handleFileSelected = useCallback(
    (file: File | undefined | null) => {
      if (!file) return;
      if (!isSupportedMeshFile(file)) {
        setLocalValidationError(
          `Formato no compatible ("${file.name}"). Sube un archivo .stl, .obj o .3mf.`
        );
        return;
      }
      setLocalValidationError(null);
      void uploadAndAnalyze(file);
    },
    [uploadAndAnalyze]
  );

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    if (isBusy) return;
    if (!isDragOver) setIsDragOver(true);
  };

  const handleDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    // Only clear when leaving the outer workspace
    if (e.currentTarget.contains(e.relatedTarget as Node)) return;
    setIsDragOver(false);
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
    if (isBusy) return;
    const file = e.dataTransfer.files?.[0];
    handleFileSelected(file);
  };

  const activeError = localValidationError ?? error;

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden bg-slate-950 text-slate-100">
      {/* Top Navbar */}
      <header className="flex h-14 shrink-0 items-center justify-between border-b border-slate-800/90 bg-slate-900/95 px-4 py-2.5">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-cyan-500 to-blue-600 text-white shadow-md shadow-cyan-500/20">
            <Cuboid className="h-4 w-4" />
          </div>
          <div>
            <h1 className="text-sm font-bold tracking-tight text-white">
              Generador de Moldes de Silicona 3D
            </h1>
            <p className="hidden text-[11px] text-slate-400 sm:block">
              Análisis topológico, plano de partición interactivo y generación booleana Manifold
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span
            className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium ring-1 ${
              phase === 'generated'
                ? 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/30'
                : phase === 'analyzing' || phase === 'generating'
                  ? 'bg-cyan-500/15 text-cyan-300 ring-cyan-500/30'
                  : phase === 'ready'
                    ? 'bg-blue-500/15 text-blue-300 ring-blue-500/30'
                    : 'bg-slate-800 text-slate-300 ring-slate-700'
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                phase === 'generated'
                  ? 'bg-emerald-400'
                  : phase === 'analyzing' || phase === 'generating'
                    ? 'animate-pulse bg-cyan-400'
                    : phase === 'ready'
                      ? 'bg-blue-400'
                      : 'bg-slate-400'
              }`}
            />
            {phase === 'idle' && 'Esperando modelo'}
            {phase === 'analyzing' && 'Analizando malla'}
            {phase === 'ready' && 'Listo para generar'}
            {phase === 'generating' && 'Generando molde'}
            {phase === 'generated' && 'Molde generado'}
          </span>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="flex min-h-0 flex-1 flex-col md:flex-row">
        {/* 3D Viewport & Interactive Overlays */}
        <div
          className="relative min-h-[340px] flex-1 overflow-hidden"
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          <Canvas3D />

          {/* Floating Status Banners (Error / Success) */}
          <div className="pointer-events-none absolute left-1/2 top-4 z-30 flex w-[min(92%,520px)] -translate-x-1/2 flex-col gap-2">
            {activeError && (
              <div
                role="alert"
                data-testid="error-banner"
                className="pointer-events-auto flex items-start justify-between gap-3 rounded-xl border border-rose-500/50 bg-rose-950/95 px-4 py-3 text-xs text-rose-100 shadow-2xl backdrop-blur"
              >
                <div className="flex items-start gap-2.5">
                  <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose-400" />
                  <div>
                    <p className="font-semibold text-rose-200">
                      Ocurrió un problema
                    </p>
                    <p className="mt-0.5 text-rose-100/90">{activeError}</p>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                  {!localValidationError && (
                    <button
                      type="button"
                      data-testid="retry-button"
                      aria-label="Reintentar última operación"
                      onClick={() => void retryLastAction()}
                      className="inline-flex items-center gap-1 rounded-md border border-rose-400/40 bg-rose-900/70 px-2 py-1 text-[11px] font-medium text-rose-100 transition hover:bg-rose-800"
                    >
                      <RefreshCw className="h-3 w-3" />
                      Reintentar
                    </button>
                  )}
                  <button
                    type="button"
                    data-testid="error-dismiss-button"
                    onClick={() => {
                      setLocalValidationError(null);
                      dismissError();
                    }}
                    aria-label="Cerrar error"
                    className="rounded-md p-1 text-rose-300 transition hover:bg-rose-900/80 hover:text-white"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
              </div>
            )}

            {!activeError && successMessage && (
              <div
                role="status"
                data-testid="success-banner"
                className="pointer-events-auto flex items-center justify-between gap-3 rounded-xl border border-emerald-500/40 bg-emerald-950/90 px-4 py-2.5 text-xs text-emerald-100 shadow-xl backdrop-blur"
              >
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
                  <span>{successMessage}</span>
                </div>
                <button
                  type="button"
                  data-testid="success-dismiss-button"
                  onClick={dismissSuccess}
                  aria-label="Cerrar mensaje de éxito"
                  className="rounded-md p-1 text-emerald-300 transition hover:bg-emerald-900/70 hover:text-white"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            )}
          </div>

          {/* Empty State Dropzone when no model is loaded */}
          {!analysis && !isBusy && (
            <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center p-6">
              <input
                ref={fileInputRef}
                data-testid="file-input"
                type="file"
                accept=".stl,.obj,.3mf"
                className="hidden"
                onChange={(e) => {
                  handleFileSelected(e.target.files?.[0]);
                  e.target.value = '';
                }}
              />
              <div
                data-testid="file-dropzone"
                role="button"
                tabIndex={0}
                aria-label="Cargar modelo 3D (.stl, .obj, .3mf)"
                onClick={() => fileInputRef.current?.click()}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    fileInputRef.current?.click();
                  }
                }}
                className={`pointer-events-auto flex w-full max-w-md cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed p-8 text-center shadow-2xl backdrop-blur-md transition ${
                  isDragOver
                    ? 'scale-[1.02] border-cyan-400 bg-slate-900/95 ring-4 ring-cyan-500/20'
                    : 'border-slate-700/90 bg-slate-900/85 hover:border-cyan-500/70 hover:bg-slate-900/95'
                }`}
              >
                <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-cyan-500/15 text-cyan-400 ring-1 ring-cyan-500/30">
                  <UploadCloud className="h-7 w-7" />
                </div>
                <h2 className="text-base font-semibold text-white">
                  Arrastra tu modelo 3D aquí
                </h2>
                <p className="mt-1.5 text-xs leading-relaxed text-slate-400">
                  O haz clic para seleccionar un archivo desde tu equipo.
                  <br />
                  Formatos soportados:{' '}
                  <span className="font-mono text-cyan-300">.STL</span>,{' '}
                  <span className="font-mono text-cyan-300">.OBJ</span>,{' '}
                  <span className="font-mono text-cyan-300">.3MF</span>
                </p>

                <span className="mt-5 inline-flex items-center gap-2 rounded-xl bg-cyan-500 px-4 py-2 text-xs font-semibold text-slate-950 shadow-lg shadow-cyan-500/25 transition hover:bg-cyan-400">
                  Seleccionar Archivo 3D
                </span>
              </div>
            </div>
          )}

          {/* Drag-over highlight when replacing an already-loaded model */}
          {analysis && isDragOver && !isBusy && (
            <div className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center bg-slate-950/70 backdrop-blur-sm">
              <div className="rounded-2xl border-2 border-dashed border-cyan-400 bg-slate-900/90 px-8 py-6 text-center shadow-2xl">
                <UploadCloud className="mx-auto mb-2 h-8 w-8 text-cyan-400" />
                <p className="text-sm font-semibold text-white">
                  Suelta para cargar nuevo modelo 3D
                </p>
              </div>
            </div>
          )}

          {/* Loading Overlay */}
          {isBusy && (
            <div
              data-testid="loading-indicator"
              role="status"
              aria-live="polite"
              className="absolute inset-0 z-40 flex items-center justify-center bg-slate-950/75 backdrop-blur-sm"
            >
              <div className="flex w-full max-w-xs flex-col items-center rounded-2xl border border-slate-700/80 bg-slate-900/95 p-6 text-center shadow-2xl">
                <Loader2 className="mb-3 h-9 w-9 animate-spin text-cyan-400" />
                <p className="text-sm font-semibold text-white">
                  {phase === 'analyzing'
                    ? 'Analizando modelo 3D...'
                    : 'Generando piezas del molde...'}
                </p>
                <p className="mt-1 text-xs text-slate-400">
                  {phase === 'analyzing'
                    ? 'Reparando malla, calculando orientación óptima y atrapamientos de aire.'
                    : 'Ejecutando booleanas Manifold3D, llaves, bebedero y empaquetado.'}
                </p>
                <button
                  type="button"
                  data-testid="cancel-operation-button"
                  aria-label="Cancelar operación"
                  onClick={cancelActiveRequest}
                  className="mt-4 rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-300 transition hover:border-rose-500/50 hover:text-rose-200"
                >
                  Cancelar operación
                </button>
              </div>
            </div>
          )}

          {/* Explosion Slider (visible once mold parts are generated) */}
          <ExplosionSlider />
        </div>

        {/* Right Parameter Sidebar */}
        <ParameterPanel />
      </main>
    </div>
  );
}
