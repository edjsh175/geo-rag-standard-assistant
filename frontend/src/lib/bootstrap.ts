let provincePromise: Promise<unknown> | null = null;

export async function ensureBackendHealth(): Promise<void> {
  const response = await fetch('/health', { credentials: 'include' });
  if (!response.ok) {
    throw new Error(`Health check failed with status ${response.status}.`);
  }
}

export async function loadProvinceCollection(): Promise<unknown> {
  if (!provincePromise) {
    provincePromise = fetch('/data/china-provinces.json', {
      credentials: 'include',
    }).then(async (response) => {
      if (!response.ok) {
        throw new Error(`Failed to load province data: ${response.status}`);
      }
      return response.json();
    });
  }

  return provincePromise;
}

export function resetBootstrapCache(): void {
  provincePromise = null;
}
