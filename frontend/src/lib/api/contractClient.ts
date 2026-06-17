import type { AxiosRequestConfig, RawAxiosResponseHeaders } from 'axios';

import { apiClient } from './config';
import type { paths } from './generated/schema';

type Method = 'get' | 'post' | 'patch' | 'delete';
type PathsWithMethod<M extends Method> = {
  [P in keyof paths]: M extends keyof paths[P] ? P : never;
}[keyof paths];
type Operation<P extends keyof paths, M extends Method> = M extends keyof paths[P] ? paths[P][M] : never;
type JsonBody<Op> = Op extends { requestBody: { content: infer Content } }
  ? Content extends { 'application/json': infer Body }
    ? Body
    : never
  : never;
type OperationParameters<Op> = Op extends { parameters: infer Params } ? Params : never;
type PathParameters<Op> = OperationParameters<Op> extends { path: infer Params } ? Params : never;
type QueryParameters<Op> = OperationParameters<Op> extends { query?: infer Params } ? Params : never;
type ResponseBody<Response> = Response extends { content: infer Content }
  ? Content extends { 'application/json': infer Body }
    ? Body
    : never
  : never;
type SuccessBody<Op> = Op extends { responses: infer Responses }
  ? Responses extends { 200: infer Ok }
    ? ResponseBody<Ok>
    : Responses extends { 201: infer Created }
      ? ResponseBody<Created>
      : Responses extends { 204: infer Empty }
        ? ResponseBody<Empty>
        : never
  : never;
type MaybeBody<Op> = [JsonBody<Op>] extends [never] ? undefined : JsonBody<Op>;

interface ApiRequestOptions<Op> {
  params?: {
    path?: PathParameters<Op>;
    query?: QueryParameters<Op>;
  };
  config?: AxiosRequestConfig;
}

export interface BlobApiResponse {
  blob: Blob;
  headers: RawAxiosResponseHeaders;
}

const toAxiosPath = (path: string, pathParams?: Record<string, unknown>): string => {
  let resolved = path;
  if (pathParams) {
    for (const [key, value] of Object.entries(pathParams)) {
      resolved = resolved.replace(`{${key}}`, encodeURIComponent(String(value)));
    }
  }
  return resolved.replace(/^\/api(?=\/)/, '');
};

const toAxiosConfig = <Op>(path: string, options?: ApiRequestOptions<Op>): AxiosRequestConfig => ({
  ...(options?.config ?? {}),
  params: options?.params?.query,
  url: toAxiosPath(path, options?.params?.path as Record<string, unknown> | undefined),
});

export async function apiGet<P extends PathsWithMethod<'get'>>(
  path: P,
  options?: ApiRequestOptions<Operation<P, 'get'>>
): Promise<SuccessBody<Operation<P, 'get'>>> {
  const config = toAxiosConfig(String(path), options);
  const response = await apiClient.get<SuccessBody<Operation<P, 'get'>>>(config.url!, config);
  return response.data;
}

export async function apiGetBlob<P extends PathsWithMethod<'get'>>(
  path: P,
  options?: ApiRequestOptions<Operation<P, 'get'>>
): Promise<BlobApiResponse> {
  const config = toAxiosConfig(String(path), options);
  const response = await apiClient.get<Blob>(config.url!, {
    ...config,
    responseType: 'blob',
  });
  return {
    blob: response.data,
    headers: response.headers,
  };
}

export async function apiPost<P extends PathsWithMethod<'post'>>(
  path: P,
  body?: MaybeBody<Operation<P, 'post'>>,
  options?: ApiRequestOptions<Operation<P, 'post'>>
): Promise<SuccessBody<Operation<P, 'post'>>> {
  const config = toAxiosConfig(String(path), options);
  const response = await apiClient.post<SuccessBody<Operation<P, 'post'>>>(config.url!, body, config);
  return response.data;
}

export async function apiPostForm<P extends PathsWithMethod<'post'>>(
  path: P,
  body: FormData,
  options?: ApiRequestOptions<Operation<P, 'post'>>
): Promise<SuccessBody<Operation<P, 'post'>>> {
  const config = toAxiosConfig(String(path), options);
  const response = await apiClient.post<SuccessBody<Operation<P, 'post'>>>(config.url!, body, {
    ...config,
    headers: {
      ...(config.headers ?? {}),
      'Content-Type': 'multipart/form-data',
    },
  });
  return response.data;
}

export async function apiPatch<P extends PathsWithMethod<'patch'>>(
  path: P,
  body?: MaybeBody<Operation<P, 'patch'>>,
  options?: ApiRequestOptions<Operation<P, 'patch'>>
): Promise<SuccessBody<Operation<P, 'patch'>>> {
  const config = toAxiosConfig(String(path), options);
  const response = await apiClient.patch<SuccessBody<Operation<P, 'patch'>>>(config.url!, body, config);
  return response.data;
}

export async function apiDelete<P extends PathsWithMethod<'delete'>>(
  path: P,
  options?: ApiRequestOptions<Operation<P, 'delete'>>
): Promise<SuccessBody<Operation<P, 'delete'>>> {
  const config = toAxiosConfig(String(path), options);
  const response = await apiClient.delete<SuccessBody<Operation<P, 'delete'>>>(config.url!, config);
  return response.data;
}
