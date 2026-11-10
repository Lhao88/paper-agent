export class APIError extends Error {
  code: string;
  status: number;
  constructor(message: string, code: string, status: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: {
      ...(options.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...options.headers,
    },
  });
  const data: unknown = await response.json();
  if (!response.ok) {
    const error =
      typeof data === "object" && data !== null && "error" in data
        ? data.error
        : null;
    const message =
      typeof error === "object" && error !== null && "message" in error
        ? String(error.message)
        : "请求未完成，请检查输入或稍后重试。";
    const code =
      typeof error === "object" && error !== null && "code" in error
        ? String(error.code)
        : "REQUEST_FAILED";
    throw new APIError(message, code, response.status);
  }
  return data as T;
}

export function post<T>(path: string, body: unknown, key?: string): Promise<T> {
  return api<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
    headers: key ? { "Idempotency-Key": key } : {},
  });
}

export function errorText(error: unknown): string {
  if (error instanceof APIError) return `${error.message}（${error.code}）`;
  return error instanceof Error ? "连接暂不可用，请检查本机服务后重试。" : "";
}
