import { expect, test, type Page } from '@playwright/test';

type Vec3Tuple = [number, number, number];
type Triangle = [Vec3Tuple, Vec3Tuple, Vec3Tuple];

/**
 * Generates a valid, watertight binary STL buffer for an axis-aligned 20x20x20 mm cube
 * centered at the origin ([-10, 10]^3) with outward-facing triangle winding.
 */
function createWatertightCubeStlBuffer(halfSize = 10): Buffer {
  const s = halfSize;
  const triangles: Triangle[] = [
    // -X face (outward normal -1, 0, 0)
    [[-s, -s, -s], [-s, -s, s], [-s, s, s]],
    [[-s, -s, -s], [-s, s, s], [-s, s, -s]],
    // +X face (outward normal +1, 0, 0)
    [[s, -s, -s], [s, s, s], [s, -s, s]],
    [[s, -s, -s], [s, s, -s], [s, s, s]],
    // -Y face (outward normal 0, -1, 0)
    [[-s, -s, -s], [s, -s, -s], [s, -s, s]],
    [[-s, -s, -s], [s, -s, s], [-s, -s, s]],
    // +Y face (outward normal 0, +1, 0)
    [[-s, s, -s], [s, s, s], [s, s, -s]],
    [[-s, s, -s], [-s, s, s], [s, s, s]],
    // -Z face (outward normal 0, 0, -1)
    [[-s, -s, -s], [-s, s, -s], [s, s, -s]],
    [[-s, -s, -s], [s, s, -s], [s, -s, -s]],
    // +Z face (outward normal 0, 0, +1)
    [[-s, -s, s], [s, s, s], [-s, s, s]],
    [[-s, -s, s], [s, -s, s], [s, s, s]],
  ];

  const buffer = Buffer.alloc(80 + 4 + triangles.length * 50);
  buffer.write('Playwright Watertight Cube STL', 0, 'ascii');
  buffer.writeUInt32LE(triangles.length, 80);

  let offset = 84;
  for (const [v0, v1, v2] of triangles) {
    const ux = v1[0] - v0[0];
    const uy = v1[1] - v0[1];
    const uz = v1[2] - v0[2];
    const vx = v2[0] - v0[0];
    const vy = v2[1] - v0[1];
    const vz = v2[2] - v0[2];

    const nx = uy * vz - uz * vy;
    const ny = uz * vx - ux * vz;
    const nz = ux * vy - uy * vx;
    const len = Math.hypot(nx, ny, nz) || 1;

    buffer.writeFloatLE(nx / len, offset);
    buffer.writeFloatLE(ny / len, offset + 4);
    buffer.writeFloatLE(nz / len, offset + 8);
    offset += 12;

    for (const vertex of [v0, v1, v2]) {
      buffer.writeFloatLE(vertex[0], offset);
      buffer.writeFloatLE(vertex[1], offset + 4);
      buffer.writeFloatLE(vertex[2], offset + 8);
      offset += 12;
    }

    buffer.writeUInt16LE(0, offset);
    offset += 2;
  }

  return buffer;
}

function attachRuntimeErrorCollectors(page: Page) {
  const pageErrors: string[] = [];
  const consoleErrors: string[] = [];

  page.on('pageerror', (err) => {
    pageErrors.push(err.message);
  });

  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      consoleErrors.push(msg.text());
    }
  });

  return { pageErrors, consoleErrors };
}

async function uploadCubeAndWaitForAnalysis(page: Page, filename = 'cube.stl') {
  const stlBuffer = createWatertightCubeStlBuffer(10);
  await page.getByTestId('file-input').setInputFiles({
    name: filename,
    mimeType: 'application/octet-stream',
    buffer: stlBuffer,
  });

  await expect(page.getByTestId('canvas-3d-container')).toBeVisible();
  await expect(page.getByTestId('canvas-3d-container').locator('canvas')).toBeVisible();
  await expect(page.getByTestId('model-metrics')).toBeVisible();
  await expect(page.getByTestId('model-metrics')).toContainText('20.0 × 20.0 × 20.0');
  await expect(page.getByTestId('model-metrics')).toContainText('Watertight');
  await expect(page.getByTestId('generate-mold-button')).toBeEnabled();
}

test.describe('Generador de Moldes de Silicona 3D - E2E Antifallos', () => {
  test('1. Empty State: dropzone visible y controles de generación ocultos/deshabilitados', async ({
    page,
  }) => {
    const { pageErrors, consoleErrors } = attachRuntimeErrorCollectors(page);

    await page.goto('/');

    await expect(page.getByTestId('file-dropzone')).toBeVisible();
    await expect(page.getByTestId('canvas-3d-container')).toBeVisible();
    await expect(page.getByText('Ningún modelo cargado')).toBeVisible();

    await expect(page.getByTestId('generate-mold-button')).toBeDisabled();
    await expect(page.getByTestId('model-metrics')).toBeHidden();
    await expect(page.getByTestId('generated-parts-list')).toBeHidden();
    await expect(page.getByTestId('explosion-slider')).toBeHidden();
    await expect(page.getByTestId('download-zip-button')).toBeHidden();

    expect(pageErrors).toEqual([]);
    expect(consoleErrors).toEqual([]);
  });

  test('2. Happy Path (direct_negative + .stl): analiza, genera, explosiona y descarga ZIP válido', async ({
    page,
  }) => {
    const { pageErrors, consoleErrors } = attachRuntimeErrorCollectors(page);

    await page.goto('/');
    await uploadCubeAndWaitForAnalysis(page, 'test_cube.stl');

    const wallInput = page.getByTestId('input-wall-thickness');
    await wallInput.fill('8');
    await wallInput.blur();
    await expect(wallInput).toHaveValue('8');

    const toleranceInput = page.getByTestId('input-tolerance');
    await toleranceInput.fill('0.25');
    await toleranceInput.blur();
    await expect(toleranceInput).toHaveValue('0.25');

    await page.getByTestId('generate-mold-button').click();

    const partsList = page.getByTestId('generated-parts-list');
    await expect(partsList).toBeVisible();
    await expect(partsList).toContainText('part_a.stl');
    await expect(partsList).toContainText('part_b.stl');
    await expect(partsList.getByText('Watertight')).toHaveCount(2);

    await expect(page.getByTestId('success-banner')).toBeVisible();

    const explosionSlider = page.getByTestId('explosion-slider');
    await expect(explosionSlider).toBeVisible();
    await explosionSlider.fill('20');
    await expect(explosionSlider).toHaveValue('20');
    await expect(page.getByText('±20.0 mm')).toBeVisible();

    const downloadZipBtn = page.getByTestId('download-zip-button');
    await expect(downloadZipBtn).toBeVisible();
    const zipHref = await downloadZipBtn.getAttribute('href');
    expect(zipHref).toBeTruthy();

    const zipResponse = await page.request.get(zipHref!);
    expect(zipResponse.status()).toBe(200);
    const zipBytes = await zipResponse.body();
    expect(zipBytes.byteLength).toBeGreaterThan(22);
    // ZIP local file header signature: 'PK' (0x50, 0x4B)
    expect(zipBytes[0]).toBe(0x50);
    expect(zipBytes[1]).toBe(0x4b);

    expect(pageErrors).toEqual([]);
    expect(consoleErrors).toEqual([]);
  });

  test('3. Flujo pouring_box + 3mf: genera 3 piezas .3mf y el slider de explosión funciona sin errores 3D', async ({
    page,
  }) => {
    const { pageErrors, consoleErrors } = attachRuntimeErrorCollectors(page);

    await page.goto('/');
    await uploadCubeAndWaitForAnalysis(page, 'pouring_cube.stl');

    await page.getByTestId('select-mold-type').selectOption('pouring_box');
    await page.getByTestId('select-export-format').selectOption('3mf');

    await page.getByTestId('generate-mold-button').click();

    const partsList = page.getByTestId('generated-parts-list');
    await expect(partsList).toBeVisible();
    await expect(partsList).toContainText('jacket_part_a.3mf');
    await expect(partsList).toContainText('jacket_part_b.3mf');
    await expect(partsList).toContainText('jacket_base.3mf');

    await expect(page.getByTestId('success-banner')).toBeVisible();

    const explosionSlider = page.getByTestId('explosion-slider');
    await expect(explosionSlider).toBeVisible();
    await explosionSlider.fill('18');
    await expect(explosionSlider).toHaveValue('18');
    await expect(page.getByText('±18.0 mm')).toBeVisible();

    // Ensure Canvas3D rendered preview_url STLs without mesh load warning
    await expect(page.getByText(/No se pudo descargar la malla 3D|Error cargando geometría/i)).toBeHidden();

    expect(pageErrors).toEqual([]);
    expect(consoleErrors).toEqual([]);
  });

  test('4a. Caso borde: archivo con extensión inválida (.txt) muestra error local sin crash', async ({
    page,
  }) => {
    const { pageErrors, consoleErrors } = attachRuntimeErrorCollectors(page);

    await page.goto('/');

    await page.getByTestId('file-input').setInputFiles({
      name: 'not_a_mesh.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('contenido invalido'),
    });

    const errorBanner = page.getByTestId('error-banner');
    await expect(errorBanner).toBeVisible();
    await expect(errorBanner).toContainText('Formato no compatible');
    await expect(page.getByTestId('file-dropzone')).toBeVisible();
    await expect(page.getByTestId('generate-mold-button')).toBeDisabled();

    await page.getByTestId('error-dismiss-button').click();
    await expect(errorBanner).toBeHidden();

    expect(pageErrors).toEqual([]);
    expect(consoleErrors).toEqual([]);
  });

  test('4b. Caso borde: archivo .stl corrupto/vacío muestra error-banner (400/422) y permite cerrarlo', async ({
    page,
  }) => {
    const { pageErrors } = attachRuntimeErrorCollectors(page);

    await page.goto('/');

    const analyzeResponsePromise = page.waitForResponse(
      (res) => res.url().includes('/api/v1/analyze') && res.request().method() === 'POST'
    );

    await page.getByTestId('file-input').setInputFiles({
      name: 'corrupt.stl',
      mimeType: 'application/octet-stream',
      buffer: Buffer.alloc(0),
    });

    const analyzeResponse = await analyzeResponsePromise;
    expect([400, 422]).toContain(analyzeResponse.status());

    const errorBanner = page.getByTestId('error-banner');
    await expect(errorBanner).toBeVisible();
    await expect(page.getByTestId('file-dropzone')).toBeVisible();

    await page.getByTestId('error-dismiss-button').click();
    await expect(errorBanner).toBeHidden();

    expect(pageErrors).toEqual([]);
  });

  test('4c. Caso borde: doble clic rápido sobre generate-mold-button es resiliente sin pageerror ni console.error', async ({
    page,
  }) => {
    const { pageErrors, consoleErrors } = attachRuntimeErrorCollectors(page);

    await page.goto('/');
    await uploadCubeAndWaitForAnalysis(page, 'dblclick_cube.stl');

    const generateButton = page.getByTestId('generate-mold-button');
    await generateButton.dblclick();

    await expect(page.getByTestId('generated-parts-list')).toBeVisible();
    await expect(page.getByTestId('generated-parts-list')).toContainText('part_a.stl');
    await expect(page.getByTestId('generated-parts-list')).toContainText('part_b.stl');
    await expect(page.getByTestId('success-banner')).toBeVisible();

    expect(pageErrors).toEqual([]);
    expect(consoleErrors).toEqual([]);
  });
});
