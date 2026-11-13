import type { AnalyzeResponse, GenerateRequest, GenerateResponse } from '../types/mold';

const API_BASE = '';
const DEFAULT_REQUEST_TIMEOUT_MS = 120_000;

export class ApiError extends Error {
  status: number;
  constructor(message: string, status = 500) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

function createRequestSignal(
  externalSignal?: AbortSignal,
  timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS
): { signal: AbortSignal; cleanup: () => void } {
  const abortSignalStatic = AbortSignal as typeof AbortSignal & {
    any?: (signals: AbortSignal[]) => AbortSignal;
    timeout?: (ms: number) => AbortSignal;
  };

  if (
    typeof abortSignalStatic.any === 'function' &&
    typeof abortSignalStatic.timeout === 'function'
  ) {
    const timeoutSignal = abortSignalStatic.timeout(timeoutMs);
    const signal = externalSignal
      ? abortSignalStatic.any([externalSignal, timeoutSignal])
      : timeoutSignal;
    return { signal, cleanup: () => {} };
  }

  const controller = new AbortController();
  const timeoutId = globalThis.setTimeout(() => {
    controller.abort(
      new DOMException('La solicitud superó el tiempo límite de espera.', 'TimeoutError')
    );
  }, timeoutMs);

  const onExternalAbort = () => {
    controller.abort(externalSignal?.reason);
  };

  if (externalSignal) {
    if (externalSignal.aborted) {
      controller.abort(externalSignal.reason);
    } else {
      externalSignal.addEventListener('abort', onExternalAbort, { once: true });
    }
  }

  return {
    signal: controller.signal,
    cleanup: () => {
      globalThis.clearTimeout(timeoutId);
      externalSignal?.removeEventListener('abort', onExternalAbort);
    },
  };
}

async function parseErrorMessage(response: Response): Promise<string> {
  try {
    const contentType = response.headers.get('content-type') ?? '';
    if (contentType.includes('application/json')) {
      const data = (await response.json()) as {
        detail?: string | Array<{ msg?: string; loc?: Array<string | number> }>;
        message?: string;
      };
      if (typeof data.detail === 'string') {
        return data.detail;
      }
      if (Array.isArray(data.detail) && data.detail.length > 0) {
        return data.detail
          .map((item) => {
            const loc = item.loc ? item.loc.join('.') : '';
            return loc ? `${loc}: ${item.msg ?? 'Valor inválido'}` : (item.msg ?? 'Error de validación');
          })
          .join('; ');
      }
      if (typeof data.message === 'string') {
        return data.message;
      }
    }
    const text = await response.text();
    if (text.trim()) {
      return text.slice(0, 300);
    }
  } catch {
    // Fallback to HTTP status message below
  }
  return `Error del servidor (HTTP ${response.status})`;
}

export async function analyzeModel(
  file: File,
  autoOrient: boolean,
  signal?: AbortSignal
): Promise<AnalyzeResponse> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('auto_orient', autoOrient ? 'true' : 'false');

  const requestSignal = createRequestSignal(signal);
  try {
    const response = await fetch(`${API_BASE}/api/v1/analyze`, {
      method: 'POST',
      body: formData,
      signal: requestSignal.signal,
    });

    if (!response.ok) {
      throw new ApiError(await parseErrorMessage(response), response.status);
    }

    return (await response.json()) as AnalyzeResponse;
  } finally {
    requestSignal.cleanup();
  }
}

export async function generateMold(
  payload: GenerateRequest,
  signal?: AbortSignal
): Promise<GenerateResponse> {
  const requestSignal = createRequestSignal(signal);
  try {
    const response = await fetch(`${API_BASE}/api/v1/generate`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
      signal: requestSignal.signal,
    });

    if (!response.ok) {
      throw new ApiError(await parseErrorMessage(response), response.status);
    }

    return (await response.json()) as GenerateResponse;
  } finally {
    requestSignal.cleanup();
  }
}

export async function fetchMeshBinary(url: string, signal?: AbortSignal): Promise<ArrayBuffer> {
  const requestSignal = createRequestSignal(signal);
  try {
    const response = await fetch(url, { signal: requestSignal.signal });
    if (!response.ok) {
      throw new ApiError(
        `No se pudo descargar la malla 3D (${response.status}): ${url}`,
        response.status
      );
    }
    return await response.arrayBuffer();
  } finally {
    requestSignal.cleanup();
  }
}
