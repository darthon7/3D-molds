import { Expand, Minimize2 } from 'lucide-react';
import { useMoldStore } from '../store/useMoldStore';

export function ExplosionSlider() {
  const generated = useMoldStore((s) => s.generated);
  const analysis = useMoldStore((s) => s.analysis);
  const explosionDistance = useMoldStore((s) => s.explosionDistance);
  const setExplosionDistance = useMoldStore((s) => s.setExplosionDistance);

  if (!generated) return null;

  const maxDim = analysis
    ? Math.max(...analysis.dimensions, 30)
    : 50;
  const maxExplosion = Math.round(Math.max(40, maxDim * 1.5));

  return (
    <section
      aria-label="Vista explosionada del molde"
      className="pointer-events-auto absolute bottom-5 left-1/2 z-20 w-[min(92%,420px)] -translate-x-1/2 rounded-2xl border border-slate-700/80 bg-slate-900/90 px-4 py-3 shadow-2xl backdrop-blur-md"
    >
      <div className="mb-1.5 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Expand className="h-4 w-4 text-amber-400" />
          <label
            htmlFor="explosion-slider-input"
            className="text-xs font-semibold uppercase tracking-wider text-slate-200"
          >
            Vista Explosionada
          </label>
        </div>

        <div className="flex items-center gap-2">
          <span className="rounded-md bg-slate-800 px-2 py-0.5 font-mono text-xs text-amber-300">
            ±{explosionDistance.toFixed(1)} mm
          </span>
          {explosionDistance > 0 && (
            <button
              type="button"
              onClick={() => setExplosionDistance(0)}
              className="inline-flex items-center gap-1 rounded-md border border-slate-700 bg-slate-800/80 px-1.5 py-0.5 text-[11px] text-slate-300 transition hover:border-slate-500 hover:text-white"
              title="Cerrar molde"
            >
              <Minimize2 className="h-3 w-3" />
              Cerrar
            </button>
          )}
        </div>
      </div>

      <input
        id="explosion-slider-input"
        data-testid="explosion-slider"
        type="range"
        min={0}
        max={maxExplosion}
        step={0.5}
        value={explosionDistance}
        onChange={(e) => setExplosionDistance(Number(e.target.value))}
        className="h-2 w-full cursor-pointer appearance-none rounded-lg bg-slate-700 accent-amber-400"
      />

      <div className="mt-1 flex justify-between text-[10px] text-slate-400">
        <span>Cerrado (0 mm)</span>
        <span>Inspección cavidad (+Z / -Z)</span>
        <span>{maxExplosion} mm</span>
      </div>
    </section>
  );
}
