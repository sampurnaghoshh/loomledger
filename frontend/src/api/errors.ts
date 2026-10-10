// Every API error has the same envelope: { "error": { "code", "message", "hint"?, "sqlstate"?, "fields"? } }
// Show error.message to the user. Branch on error.code, never on the message text.

export type ApiErrorCode =
  | "LOT_QUARANTINED" //      409  quarantined/recalled stock cannot move
  | "INSUFFICIENT_STOCK" //   422
  | "MACHINE_BUSY" //         409  machine already booked for that time
  | "ALREADY_DISPATCHED" //   409
  | "SHADE_MISMATCH" //       409  rolls from different dye batches in one dispatch (fields.batches); resend with shade_override_reason
  | "VALIDATION_FAILED" //    422  see fields
  | "INVALID_CREDENTIALS" //  401
  | "UNAUTHENTICATED" //      401
  | "FORBIDDEN" //            403
  | "NOT_FOUND" //            404
  | "LEDGER_IMMUTABLE" //     405  ledger rows can't be changed; post a correcting move
  | "NOT_QC_PASSED" //        409  dispatch: roll has not passed QC
  | "NOT_IN_ORDER" //         422  dispatch: roll is not reserved for this order
  | "DUPLICATE_REQUEST" //    409  same idempotency key already used (normally replayed as 200)
  | "CONFLICT_RETRY" //       409  concurrent change / deadlock — safe to resubmit
  | "DB_UNAVAILABLE" //       503  database unreachable
  | "METHOD_NOT_ALLOWED" //   405
  | "BAD_REQUEST" //          4xx  other HTTP errors
  | "INTERNAL" //             500
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
