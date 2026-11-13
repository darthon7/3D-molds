# Generador Automatizado de Moldes de Silicona 3D

Sistema fullstack para analizar mallas 3D (`.stl`, `.obj`, `.3mf`), reparar su topología (*watertight*), determinar la orientación óptima con menor área de contrasalidas (*undercuts*), detectar puntos de atrapamiento de aire y generar automáticamente moldes listos para impresión 3D usando operaciones booleanas **100% manifold** (`manifold3d`).

## Modos de Generación
1. **Molde Negativo Bivalvo (`direct_negative`)**: Genera `part_a` y `part_b` con cavidad negativa, plano de partición ajustable, 4 llaves de registro cónicas con ángulo de desmoldeo $\ge 15^\circ$ y holgura configurable (`clearance`), bebedero de vertido, respiraderos automáticos y muescas de apertura.
2. **Caja de Moldeo (`pouring_box`)**: Genera `jacket_part_a`, `jacket_part_b` y `jacket_base` con pared de `2.4 mm`, pestañas y perforaciones M3 para vaciado de silicona líquida.

## Stack Tecnológico
- **Backend (`backend/`)**: Python 3.12, FastAPI, Pydantic, Trimesh, Manifold3D (`engine="manifold"`), PyMeshFix, SciPy, NumPy, rtree.
- **Frontend (`frontend/`)**: React 18, TypeScript, Vite, Three.js (`@react-three/fiber`, `@react-three/drei`), Zustand, TailwindCSS.
- **Pruebas**: Pytest (backend) + Playwright E2E (fullstack).

## Ejecución Local

### Backend (Python 3.11+ / Linux o WSL)
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

O con Docker Compose:
```bash
docker compose up --build
```

### Frontend (Node 18+)
```bash
cd frontend
npm install
npm run dev
```
La aplicación estará disponible en `http://127.0.0.1:5173` (con proxy `/api` hacia `http://127.0.0.1:8000`).

## Pruebas
- **Backend**:
  ```bash
  cd backend
  pytest -v
  ```
- **E2E (Playwright)**:
  ```bash
  cd frontend
  npm run test:e2e
  ```

