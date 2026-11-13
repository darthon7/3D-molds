import { type ComponentRef, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Canvas, ThreeEvent, useThree } from '@react-three/fiber';
import { Grid, Html, OrbitControls } from '@react-three/drei';
import * as THREE from 'three';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js';
import { Eye, EyeOff, Layers, RotateCcw } from 'lucide-react';
import { fetchMeshBinary } from '../api/moldApi';
import { getEffectivePartingZ, useMoldStore } from '../store/useMoldStore';
import type { InteractiveMarkerKind, Vec3 } from '../types/mold';
import { PartingPlaneGizmo } from './PartingPlaneGizmo';

const PART_COLORS: Record<string, string> = {
  part_a: '#38bdf8',
  part_b: '#f59e0b',
  jacket_part_a: '#38bdf8',
  jacket_part_b: '#f59e0b',
  jacket_base: '#a855f7',
};

const FALLBACK_COLORS = ['#38bdf8', '#f59e0b', '#a855f7', '#34d399'];

function getPartColor(name: string, index: number): string {
  const lower = name.toLowerCase();
  for (const [key, color] of Object.entries(PART_COLORS)) {
    if (lower.includes(key)) {
      return color;
    }
  }
  return FALLBACK_COLORS[index % FALLBACK_COLORS.length];
}

function getExplosionOffset(
  name: string,
  index: number,
  moldType: string,
  distance: number
): Vec3 {
  if (distance === 0) return [0, 0, 0];
  const lower = name.toLowerCase();

  if (moldType === 'pouring_box') {
    if (lower.includes('base')) return [0, 0, -distance];
    if (lower.includes('part_a')) return [-distance * 0.55, 0, distance * 0.35];
    if (lower.includes('part_b')) return [distance * 0.55, 0, distance * 0.65];
  }

  if (lower.includes('part_b') || lower.includes('upper') || lower.includes('top')) {
    return [0, 0, distance];
  }
  if (
    lower.includes('part_a') ||
    lower.includes('lower') ||
    lower.includes('bottom') ||
    lower.includes('base')
  ) {
    return [0, 0, -distance];
  }

  return index % 2 === 0 ? [0, 0, -distance] : [0, 0, distance];
}

interface StlMeshProps {
  url: string;
  color: string;
  opacity?: number;
  transparent?: boolean;
  position?: Vec3;
  metalness?: number;
  roughness?: number;
  onLoadError?: (msg: string) => void;
}

function StlMesh({
  url,
  color,
  opacity = 1,
  transparent = false,
  position = [0, 0, 0],
  metalness = 0.12,
  roughness = 0.42,
  onLoadError,
}: StlMeshProps) {
  const [geometry, setGeometry] = useState<THREE.BufferGeometry | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    async function load() {
      try {
        if (url.toLowerCase().endsWith('.3mf')) {
          // 3MF preview fallback: skip STL binary parse if backend served .3mf
          setGeometry(null);
          return;
        }
        const buffer = await fetchMeshBinary(url, controller.signal);
        if (controller.signal.aborted) return;

        const loader = new STLLoader();
        const parsed = loader.parse(buffer);
        if (controller.signal.aborted) {
          parsed.dispose();
          return;
        }
        if (!parsed.attributes.normal) {
          parsed.computeVertexNormals();
        }
        parsed.computeBoundingBox();
        setGeometry(parsed);
      } catch (err) {
        if (
          (err instanceof DOMException && err.name === 'AbortError') ||
          (err instanceof Error && err.name === 'AbortError')
        ) {
          return;
        }
        onLoadError?.(
          err instanceof Error ? err.message : 'Error cargando geometría STL'
        );
      }
    }

    setGeometry(null);
    void load();

    return () => {
      controller.abort();
    };
  }, [url, onLoadError]);

  useEffect(() => {
    return () => {
      geometry?.dispose();
    };
  }, [geometry]);

  if (!geometry) return null;

  return (
    <mesh geometry={geometry} position={position} castShadow receiveShadow>
      <meshStandardMaterial
        color={color}
        transparent={transparent}
        opacity={opacity}
        metalness={metalness}
        roughness={roughness}
        depthWrite={!transparent || opacity >= 0.99}
      />
    </mesh>
  );
}

interface DraggableMarkerProps {
  kind: InteractiveMarkerKind;
  index: number;
  position: Vec3;
  radius: number;
  label: string;
  dimmed?: boolean;
  cadGroupRef: React.RefObject<THREE.Group | null>;
  onDragPosition: (index: number, nextPos: Vec3) => void;
}

function DraggableMarker({
  kind,
  index,
  position,
  radius,
  label,
  dimmed = false,
  cadGroupRef,
  onDragPosition,
}: DraggableMarkerProps) {
  const analysis = useMoldStore((s) => s.analysis);
  const wallThickness = useMoldStore((s) => s.params.wall_thickness);
  const selectedMarker = useMoldStore((s) => s.selectedMarker);
  const setSelectedMarker = useMoldStore((s) => s.setSelectedMarker);
  const setIsDraggingGizmo = useMoldStore((s) => s.setIsDraggingGizmo);

  const { camera, gl } = useThree();
  const [hovered, setHovered] = useState(false);
  const [dragging, setDragging] = useState(false);
  const cleanupRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    return () => {
      cleanupRef.current?.();
      setIsDraggingGizmo(false);
      document.body.style.cursor = 'auto';
    };
  }, [setIsDraggingGizmo]);

  const isSelected =
    selectedMarker?.kind === kind && selectedMarker?.index === index;

  const palette = useMemo(() => {
    if (kind === 'key') return { base: '#22c55e', active: '#4ade80' };
    if (kind === 'spout') return { base: '#ef4444', active: '#f87171' };
    return { base: '#3b82f6', active: '#60a5fa' };
  }, [kind]);

  const handlePointerDown = useCallback(
    (e: ThreeEvent<PointerEvent>) => {
      e.stopPropagation();
      cleanupRef.current?.();

      setSelectedMarker({ kind, index });
      setDragging(true);
      setIsDraggingGizmo(true);
      document.body.style.cursor = 'grabbing';

      // Horizontal plane in Three.js world space passing through marker's initial world point
      const markerWorldPos = e.point.clone();
      const dragPlane = new THREE.Plane(
        new THREE.Vector3(0, 1, 0),
        -markerWorldPos.y
      );

      const fixedLocalZ = position[2];
      const raycaster = new THREE.Raycaster();
      const ndc = new THREE.Vector2();
      const hitWorld = new THREE.Vector3();

      const onPointerMove = (ev: PointerEvent) => {
        const rect = gl.domElement.getBoundingClientRect();
        ndc.x = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
        ndc.y = -((ev.clientY - rect.top) / rect.height) * 2 + 1;

        raycaster.setFromCamera(ndc, camera);
        if (raycaster.ray.intersectPlane(dragPlane, hitWorld)) {
          let localX = hitWorld.x;
          let localY = -hitWorld.z;
          if (cadGroupRef.current) {
            const localPt = cadGroupRef.current.worldToLocal(hitWorld.clone());
            localX = localPt.x;
            localY = localPt.y;
          }

          if (analysis) {
            const margin = Math.min(Math.max(radius, 1.5), wallThickness * 0.5);
            const minX = analysis.bbox_min[0] - wallThickness + margin;
            const maxX = analysis.bbox_max[0] + wallThickness - margin;
            const minY = analysis.bbox_min[1] - wallThickness + margin;
            const maxY = analysis.bbox_max[1] + wallThickness - margin;

            localX =
              minX <= maxX
                ? Math.max(minX, Math.min(maxX, localX))
                : (minX + maxX) / 2;
            localY =
              minY <= maxY
                ? Math.max(minY, Math.min(maxY, localY))
                : (minY + maxY) / 2;
          }

          onDragPosition(index, [localX, localY, fixedLocalZ]);
        }
      };

      const stopDragging = () => {
        window.removeEventListener('pointermove', onPointerMove);
        window.removeEventListener('pointerup', stopDragging);
        window.removeEventListener('pointercancel', stopDragging);
        window.removeEventListener('blur', stopDragging);
        cleanupRef.current = null;
        setDragging(false);
        setIsDraggingGizmo(false);
        document.body.style.cursor = 'auto';
      };

      window.addEventListener('pointermove', onPointerMove);
      window.addEventListener('pointerup', stopDragging);
      window.addEventListener('pointercancel', stopDragging);
      window.addEventListener('blur', stopDragging);
      cleanupRef.current = stopDragging;
    },
    [
      analysis,
      cadGroupRef,
      camera,
      gl.domElement,
      index,
      kind,
      onDragPosition,
      position,
      radius,
      setIsDraggingGizmo,
      setSelectedMarker,
      wallThickness,
    ]
  );

  const color = hovered || dragging || isSelected ? palette.active : palette.base;
  const opacity = dimmed ? 0.25 : 0.95;

  return (
    <group position={position}>
      {kind === 'key' && (
        <mesh
          onPointerDown={handlePointerDown}
          onPointerOver={(e) => {
            e.stopPropagation();
            setHovered(true);
            if (!dragging) document.body.style.cursor = 'grab';
          }}
          onPointerOut={() => {
            setHovered(false);
            if (!dragging) document.body.style.cursor = 'auto';
          }}
        >
          <sphereGeometry args={[radius, 20, 20]} />
          <meshStandardMaterial
            color={color}
            emissive={color}
            emissiveIntensity={hovered || dragging ? 0.45 : 0.15}
            transparent={dimmed}
            opacity={opacity}
            roughness={0.3}
          />
        </mesh>
      )}

      {kind === 'spout' && (
        <group
          onPointerDown={handlePointerDown}
          onPointerOver={(e) => {
            e.stopPropagation();
            setHovered(true);
            if (!dragging) document.body.style.cursor = 'grab';
          }}
          onPointerOut={() => {
            setHovered(false);
            if (!dragging) document.body.style.cursor = 'auto';
          }}
        >
          {/* Inverted funnel cone along +Z */}
          <mesh rotation={[Math.PI / 2, 0, 0]} position={[0, 0, radius * 1.1]}>
            <coneGeometry args={[radius * 1.1, radius * 2.2, 24]} />
            <meshStandardMaterial
              color={color}
              emissive={color}
              emissiveIntensity={hovered || dragging ? 0.45 : 0.18}
              roughness={0.3}
            />
          </mesh>
          <mesh>
            <sphereGeometry args={[radius * 0.55, 16, 16]} />
            <meshStandardMaterial color={color} roughness={0.3} />
          </mesh>
        </group>
      )}

      {kind === 'vent' && (
        <mesh
          rotation={[-Math.PI / 2, 0, 0]}
          position={[0, 0, radius * 1.2]}
          onPointerDown={handlePointerDown}
          onPointerOver={(e) => {
            e.stopPropagation();
            setHovered(true);
            if (!dragging) document.body.style.cursor = 'grab';
          }}
          onPointerOut={() => {
            setHovered(false);
            if (!dragging) document.body.style.cursor = 'auto';
          }}
        >
          <coneGeometry args={[radius * 0.75, radius * 2.4, 18]} />
          <meshStandardMaterial
            color={color}
            emissive={color}
            emissiveIntensity={hovered || dragging ? 0.45 : 0.15}
            transparent={dimmed}
            opacity={opacity}
            roughness={0.3}
          />
        </mesh>
      )}

      {(hovered || dragging || isSelected) && (
        <Html position={[0, 0, radius * 2.8]} center style={{ pointerEvents: 'none' }}>
          <div className="whitespace-nowrap rounded bg-slate-900/90 px-2 py-0.5 font-mono text-[10px] text-slate-100 ring-1 ring-slate-600/80 shadow-md">
            {label} ({position[0].toFixed(1)}, {position[1].toFixed(1)}, {position[2].toFixed(1)})
          </div>
        </Html>
      )}
    </group>
  );
}

interface SceneContentProps {
  resetCameraTrigger: number;
  onMeshError: (msg: string) => void;
}

function SceneContent({ resetCameraTrigger, onMeshError }: SceneContentProps) {
  const analysis = useMoldStore((s) => s.analysis);
  const generated = useMoldStore((s) => s.generated);
  const params = useMoldStore((s) => s.params);
  const explosionDistance = useMoldStore((s) => s.explosionDistance);
  const showOriginalMesh = useMoldStore((s) => s.showOriginalMesh);
  const showMoldParts = useMoldStore((s) => s.showMoldParts);
  const isDraggingGizmo = useMoldStore((s) => s.isDraggingGizmo);
  const updateKeyPosition = useMoldStore((s) => s.updateKeyPosition);
  const updateSpoutPosition = useMoldStore((s) => s.updateSpoutPosition);
  const updateVentPosition = useMoldStore((s) => s.updateVentPosition);

  const cadGroupRef = useRef<THREE.Group | null>(null);
  const controlsRef = useRef<ComponentRef<typeof OrbitControls> | null>(null);
  const { camera } = useThree();

  const partingZ = getEffectivePartingZ(analysis, params.parting_z_offset);

  // Auto-frame camera when analysis changes or user clicks reset camera
  useEffect(() => {
    if (!analysis) {
      camera.position.set(85, 65, 85);
      controlsRef.current?.target.set(0, 0, 0);
      controlsRef.current?.update();
      return;
    }

    const [dx, dy, dz] = analysis.dimensions;
    const maxDim = Math.max(dx, dy, dz, 25);
    const cx = (analysis.bbox_min[0] + analysis.bbox_max[0]) / 2;
    const cy = (analysis.bbox_min[1] + analysis.bbox_max[1]) / 2;
    const cz = (analysis.bbox_min[2] + analysis.bbox_max[2]) / 2;

    // CAD (cx, cy, cz) maps to Three world (cx, cz, -cy) under rotation [-PI/2, 0, 0]
    const targetX = cx;
    const targetY = cz;
    const targetZ = -cy;

    const dist = maxDim * 1.65;
    camera.position.set(targetX + dist * 0.85, targetY + dist * 0.68, targetZ + dist * 0.85);
    if (controlsRef.current) {
      controlsRef.current.target.set(targetX, targetY, targetZ);
      controlsRef.current.update();
    }
  }, [analysis, camera, resetCameraTrigger]);

  const effectiveKeys = useMemo(() => {
    const raw = params.custom_key_positions ?? analysis?.key_positions ?? [];
    return raw.map((k): Vec3 => [k[0], k[1], partingZ]);
  }, [analysis?.key_positions, params.custom_key_positions, partingZ]);

  const effectiveSpout = useMemo(() => {
    return params.custom_spout_position ?? analysis?.spout_position ?? null;
  }, [analysis?.spout_position, params.custom_spout_position]);

  const effectiveVents = useMemo(() => {
    return params.custom_vent_points ?? analysis?.air_traps ?? [];
  }, [analysis?.air_traps, params.custom_vent_points]);

  const gridY = analysis ? analysis.bbox_min[2] - 0.1 : 0;

  return (
    <>
      <color attach="background" args={['#090d16']} />

      {/* Studio Lighting */}
      <ambientLight intensity={0.55} />
      <hemisphereLight args={['#e2e8f0', '#0f172a', 0.65]} />
      <directionalLight position={[120, 180, 140]} intensity={1.15} castShadow />
      <directionalLight position={[-110, 80, -120]} intensity={0.45} color="#7dd3fc" />

      {/* Millimetric base grid in Three.js world XZ plane */}
      <Grid
        position={[0, gridY, 0]}
        args={[300, 300]}
        cellSize={1}
        cellThickness={0.45}
        cellColor="#1e293b"
        sectionSize={10}
        sectionThickness={0.95}
        sectionColor="#334155"
        fadeDistance={240}
        fadeStrength={1.5}
        infiniteGrid
      />

      {/* CAD Z-up coordinate group: rotates CAD (X, Y, Z) -> Three World (X, Z, -Y) */}
      <group ref={cadGroupRef} rotation={[-Math.PI / 2, 0, 0]}>
        {/* Oriented original model */}
        {analysis && showOriginalMesh && (
          <StlMesh
            url={analysis.oriented_mesh_url}
            color="#cbd5e1"
            opacity={generated && showMoldParts ? 0.55 : 1}
            transparent={Boolean(generated && showMoldParts)}
            roughness={0.38}
            metalness={0.14}
            onLoadError={onMeshError}
          />
        )}

        {/* Interactive Parting Plane Gizmo */}
        {analysis && <PartingPlaneGizmo cadGroupRef={cadGroupRef} />}

        {/* Interactive Registration Keys (Green Spheres) */}
        {analysis &&
          effectiveKeys.map((pos, idx) => (
            <DraggableMarker
              key={`key-${idx}`}
              kind="key"
              index={idx}
              position={pos}
              radius={Math.max(params.key_radius * 0.72, 2.2)}
              label={`Llave #${idx + 1}`}
              cadGroupRef={cadGroupRef}
              onDragPosition={updateKeyPosition}
            />
          ))}

        {/* Interactive Pour Spout (Red Cone) */}
        {analysis && effectiveSpout && (
          <DraggableMarker
            kind="spout"
            index={0}
            position={effectiveSpout}
            radius={Math.max(params.spout_radius * 0.75, 2.8)}
            label="Bebedero"
            cadGroupRef={cadGroupRef}
            onDragPosition={(_, pos) => updateSpoutPosition(pos)}
          />
        )}

        {/* Interactive Air Vents / Traps (Blue Cones) */}
        {analysis &&
          params.auto_vents &&
          effectiveVents.map((pos, idx) => (
            <DraggableMarker
              key={`vent-${idx}`}
              kind="vent"
              index={idx}
              position={pos}
              radius={2.2}
              label={`Respiradero #${idx + 1}`}
              cadGroupRef={cadGroupRef}
              onDragPosition={updateVentPosition}
            />
          ))}

        {/* Generated Translucent Mold Parts */}
        {generated &&
          showMoldParts &&
          generated.parts.map((part, idx) => (
            <StlMesh
              key={`${generated.job_id}-${part.name}`}
              url={part.preview_url ?? part.url}
              color={getPartColor(part.name, idx)}
              opacity={0.75}
              transparent
              position={getExplosionOffset(
                part.name,
                idx,
                generated.mold_type,
                explosionDistance
              )}
              roughness={0.32}
              metalness={0.08}
              onLoadError={onMeshError}
            />
          ))}
      </group>

      <OrbitControls
        ref={controlsRef}
        makeDefault
        enabled={!isDraggingGizmo}
        enableDamping
        dampingFactor={0.08}
        minDistance={12}
        maxDistance={600}
      />
    </>
  );
}

export function Canvas3D() {
  const analysis = useMoldStore((s) => s.analysis);
  const generated = useMoldStore((s) => s.generated);
  const params = useMoldStore((s) => s.params);
  const showOriginalMesh = useMoldStore((s) => s.showOriginalMesh);
  const showMoldParts = useMoldStore((s) => s.showMoldParts);
  const setShowOriginalMesh = useMoldStore((s) => s.setShowOriginalMesh);
  const setShowMoldParts = useMoldStore((s) => s.setShowMoldParts);

  const effectiveKeyCount =
    params.custom_key_positions?.length ?? analysis?.key_positions.length ?? 0;
  const effectiveVentCount = params.auto_vents
    ? (params.custom_vent_points?.length ?? analysis?.air_traps.length ?? 0)
    : 0;

  const [resetTick, setResetTick] = useState(0);
  const [meshLoadError, setMeshLoadError] = useState<string | null>(null);

  useEffect(() => {
    setMeshLoadError(null);
  }, [analysis?.model_id, generated?.job_id]);

  return (
    <div
      data-testid="canvas-3d-container"
      className="relative h-full w-full overflow-hidden bg-slate-950"
    >
      <Canvas
        shadows
        dpr={[1, 2]}
        camera={{ position: [85, 65, 85], fov: 42, near: 0.5, far: 2000 }}
        gl={{ antialias: true, preserveDrawingBuffer: false }}
      >
        <SceneContent
          resetCameraTrigger={resetTick}
          onMeshError={setMeshLoadError}
        />
      </Canvas>

      {/* Top-left scene controls & visibility toggles */}
      {analysis && (
        <div className="pointer-events-auto absolute left-4 top-4 flex flex-wrap items-center gap-2">
          <button
            type="button"
            data-testid="reset-camera-button"
            onClick={() => setResetTick((t) => t + 1)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700/80 bg-slate-900/85 px-2.5 py-1.5 text-xs font-medium text-slate-200 shadow-lg backdrop-blur transition hover:border-cyan-500/60 hover:text-white"
            title="Restablecer vista de cámara"
          >
            <RotateCcw className="h-3.5 w-3.5 text-cyan-400" />
            Centrar cámara
          </button>

          {generated && (
            <>
              <button
                type="button"
                data-testid="toggle-original-mesh-button"
                onClick={() => setShowOriginalMesh(!showOriginalMesh)}
                className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium shadow-lg backdrop-blur transition ${
                  showOriginalMesh
                    ? 'border-slate-600 bg-slate-900/85 text-slate-100'
                    : 'border-slate-800 bg-slate-950/75 text-slate-400'
                }`}
              >
                {showOriginalMesh ? (
                  <Eye className="h-3.5 w-3.5 text-slate-300" />
                ) : (
                  <EyeOff className="h-3.5 w-3.5 text-slate-500" />
                )}
                Modelo original
              </button>

              <button
                type="button"
                data-testid="toggle-mold-parts-button"
                onClick={() => setShowMoldParts(!showMoldParts)}
                className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium shadow-lg backdrop-blur transition ${
                  showMoldParts
                    ? 'border-amber-500/50 bg-slate-900/85 text-amber-200'
                    : 'border-slate-800 bg-slate-950/75 text-slate-400'
                }`}
              >
                <Layers className="h-3.5 w-3.5 text-amber-400" />
                Piezas molde ({generated.parts.length})
              </button>
            </>
          )}
        </div>
      )}

      {/* Bottom-left Legend */}
      {analysis && (
        <div className="pointer-events-none absolute bottom-4 left-4 hidden rounded-xl border border-slate-800/90 bg-slate-900/80 px-3 py-2 text-[11px] text-slate-300 shadow-lg backdrop-blur sm:block">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full bg-cyan-400" />
              Plano de partición Z (arrastrable)
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full bg-green-500" />
              Llaves ({effectiveKeyCount})
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full bg-red-500" />
              Bebedero
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full bg-blue-500" />
              Respiraderos ({effectiveVentCount})
            </span>
          </div>
        </div>
      )}

      {/* Non-fatal mesh load warning inside canvas */}
      {meshLoadError && (
        <div className="absolute right-4 top-4 max-w-xs rounded-lg border border-amber-500/50 bg-amber-950/90 px-3 py-2 text-xs text-amber-200 shadow-lg">
          {meshLoadError}
        </div>
      )}
    </div>
  );
}
