// Every API error has the same envelope: { "error": { "code", "message", "hint"?, "sqlstate"?, "fields"? } }
// Show error.message to the user. Branch on error.code, never on the message text.

export type ApiErrorCode =
  | "LOT_QUARANTINED" //      409  quarantined/recalled stock cannot move
  | "INSUFFICIENT_STOCK" //   422
  | "MACHINE_BUSY" //         409  machine already booked for that time
  | "ALREADY_DISPATCHED" //   409
  | "SHADE_MISMATCH" //       409  rolls from different dye batches in one order line
  | "VALIDATION_FAILED" //    422  see fields
  | "INVALID_CREDENTIALS" //  401
  | "UNAUTHENTICATED" //      401
  | "FORBIDDEN" //            403
  | "NOT_FOUND" //            404
  | "NETWORK" //              could not reach the server
  | "UNKNOWN";

export class ApiError extends Error {
  readonly code: ApiErrorCode;
  readonly status: number;
  readonly hint?: string;
  readonly fields?: Record<string, string>;

  constructor(code: ApiErrorCode, message: string, status = 0, hint?: string, fields?: Record<string, string>) {
    super(message);
    this.code = code;
    this.status = status;
    this.hint = hint;
    this.fields = fields;
  }

  static fromBody(status: number, body: unknown): ApiError {
    const e = (body as { error?: { code?: ApiErrorCode; message?: string; hint?: string; fields?: Record<string, string> } })
      ?.error;
    return new ApiError(e?.code ?? "UNKNOWN", e?.message ?? `Request failed (${status})`, status, e?.hint, e?.fields);
  }
}
