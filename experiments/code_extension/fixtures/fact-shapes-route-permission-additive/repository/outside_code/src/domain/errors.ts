export class ServiceError extends Error {
  constructor(
    public readonly status: 400 | 403 | 404 | 409 | 413,
    public readonly code: string,
    message: string,
    public readonly detail: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ServiceError";
  }
}

export function missing(entity: string, id: string): never {
  throw new ServiceError(404, "not_found", `${entity} ${id} was not found`);
}

export function conflict(message: string, detail: Record<string, unknown> = {}): never {
  throw new ServiceError(409, "conflict", message, detail);
}

export function invalid(message: string): never {
  throw new ServiceError(400, "invalid_request", message);
}

export function forbidden(message = "permission required"): never {
  throw new ServiceError(403, "forbidden", message);
}

export function limitExceeded(message: string): never {
  throw new ServiceError(413, "limit_exceeded", message);
}

export function revisionMatches(actual: number, expected: number): void {
  if (actual !== expected) {
    conflict("revision changed", { expected, actual });
  }
}
