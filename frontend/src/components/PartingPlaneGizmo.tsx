import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ThreeEvent, useThree } from '@react-three/fiber';
import { Html } from '@react-three/drei';
import * as THREE from 'three';
import { getEffectivePartingZ, useMoldStore } from '../store/useMoldStore';

interface PartingPlaneGizmoProps {
  cadGroupRef: React.RefObject<THREE.Group | null>;
}

export function PartingPlaneGizmo({ cadGroupRef }: PartingPlaneGizmoProps) {
  const analysis = useMoldStore((s) => s.analysis);
  const partingZOffset = useMoldStore((s) => s.params.parting_z_offset);
  const wallThickness = useMoldStore((s) => s.params.wall_thickness);
  const setPartingZFromWorld = useMoldStore((s) => s.setPartingZFromWorld);
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

  const partingZ = getEffectivePartingZ(analysis, partingZOffset);

  const planeSpec = useMemo(() => {
    if (!analysis) {
      return { width: 60, height: 60, cx: 0, cy: 0 };
    }
    const [minX, minY] = analysis.bbox_min;
    const [maxX, maxY] = analysis.bbox_max;
    const margin = Math.max(wallThickness * 2 + 16, 20);
    return {
      width: maxX - minX + margin,
      height: maxY - minY + margin,
      cx: (minX + maxX) / 2,
      cy: (minY + maxY) / 2,
    };
  }, [analysis, wallThickness]);

  const borderGeometry = useMemo(() => {
    const geom = new THREE.PlaneGeometry(planeSpec.width, planeSpec.height);
    const edges = new THREE.EdgesGeometry(geom);
    geom.dispose();
    return edges;
  }, [planeSpec.width, planeSpec.height]);

  useEffect(() => {
    return () => {
      borderGeometry.dispose();
    };
  }, [borderGeometry]);

  const handlePointerDown = useCallback(
    (e: ThreeEvent<PointerEvent>) => {
      if (!analysis) return;
      e.stopPropagation();

      cleanupRef.current?.();

      setDragging(true);
      setIsDraggingGizmo(true);
      document.body.style.cursor = 'ns-resize';

      const startPointWorld = e.point.clone();
      const startPartingZ = getEffectivePartingZ(
        useMoldStore.getState().analysis,
        useMoldStore.getState().params.parting_z_offset
      );

      // Vertical drag plane facing camera horizontally in Three.js world space (Y is vertical)
      const camDir = new THREE.Vector3();
      camera.getWorldDirection(camDir);
      camDir.y = 0;
      if (camDir.lengthSq() < 1e-6) {
        camDir.set(0, 0, 1);
      } else {
        camDir.normalize();
      }
      const dragPlane = new THREE.Plane().setFromNormalAndCoplanarPoint(
        camDir,
        startPointWorld
      );

      const raycaster = new THREE.Raycaster();
      const ndc = new THREE.Vector2();
      const hitPoint = new THREE.Vector3();

      const onPointerMove = (ev: PointerEvent) => {
        const rect = gl.domElement.getBoundingClientRect();
        ndc.x = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
        ndc.y = -((ev.clientY - rect.top) / rect.height) * 2 + 1;

        raycaster.setFromCamera(ndc, camera);
        if (raycaster.ray.intersectPlane(dragPlane, hitPoint)) {
          // Convert world Y delta into CAD local Z delta via cadGroup if available
          let deltaZ = hitPoint.y - startPointWorld.y;
          if (cadGroupRef.current) {
            const localStart = cadGroupRef.current.worldToLocal(startPointWorld.clone());
            const localHit = cadGroupRef.current.worldToLocal(hitPoint.clone());
            deltaZ = localHit.z - localStart.z;
          }
          setPartingZFromWorld(startPartingZ + deltaZ);
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
    [analysis, cadGroupRef, camera, gl.domElement, setIsDraggingGizmo, setPartingZFromWorld]
  );

  if (!analysis) return null;

  const activeColor = dragging ? '#22d3ee' : hovered ? '#38bdf8' : '#06b6d4';

  return (
    <group position={[planeSpec.cx, planeSpec.cy, partingZ]}>
      {/* Semi-transparent parting plane */}
      <mesh
        onPointerDown={handlePointerDown}
        onPointerOver={(e) => {
          e.stopPropagation();
          setHovered(true);
          if (!dragging) document.body.style.cursor = 'ns-resize';
        }}
        onPointerOut={() => {
          setHovered(false);
          if (!dragging) document.body.style.cursor = 'auto';
        }}
      >
        <planeGeometry args={[planeSpec.width, planeSpec.height]} />
        <meshBasicMaterial
          color={activeColor}
          transparent
          opacity={dragging ? 0.32 : hovered ? 0.24 : 0.16}
          side={THREE.DoubleSide}
          depthWrite={false}
        />
      </mesh>

      {/* Crisp border frame */}
      <lineSegments geometry={borderGeometry}>
        <lineBasicMaterial color={activeColor} transparent opacity={0.9} />
      </lineSegments>

      {/* Front grab handle bar */}
      <mesh
        position={[0, -planeSpec.height / 2, 0]}
        onPointerDown={handlePointerDown}
        onPointerOver={(e) => {
          e.stopPropagation();
          setHovered(true);
          if (!dragging) document.body.style.cursor = 'ns-resize';
        }}
        onPointerOut={() => {
          setHovered(false);
          if (!dragging) document.body.style.cursor = 'auto';
        }}
      >
        <boxGeometry args={[Math.min(planeSpec.width * 0.35, 24), 2.2, 2.2]} />
        <meshStandardMaterial
          color={activeColor}
          emissive={activeColor}
          emissiveIntensity={dragging ? 0.6 : 0.3}
          roughness={0.3}
        />
      </mesh>

      {/* Z height badge while hovering or dragging */}
      {(hovered || dragging) && (
        <Html
          position={[planeSpec.width / 2, -planeSpec.height / 2, 2]}
          center
          style={{ pointerEvents: 'none' }}
        >
          <div className="whitespace-nowrap rounded-md border border-cyan-400/50 bg-slate-900/90 px-2 py-0.5 font-mono text-[11px] text-cyan-200 shadow-lg backdrop-blur">
            Corte Z: {partingZ.toFixed(2)} mm
          </div>
        </Html>
      )}
    </group>
  );
}
