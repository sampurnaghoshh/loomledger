
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import type {
  QcResult,
  QualityQueueItem,
  Rejection,
} from "@/api/types";
import { useApi } from "@/hooks/useApi";
import { formatDate, formatDateTime, formatQty } from "@/lib/format";
import {
  Badge,
  Button,
  Card,
  ErrorBanner,
  Field,
  Input,
  Modal,
  PageHeader,
  Select,
  Spinner,
  Textarea,
} from "@/components/ui";

const DEFECT_TYPES = [
  { value: "colour_mismatch", label: "Colour mismatch" },
  { value: "missing_pick", label: "Missing pick" },
  { value: "oil_stain", label: "Oil stain" },
  { value: "hole", label: "Hole" },
  { value: "uneven_weave", label: "Uneven weave" },
  { value: "other", label: "Other" },
];

function defectLabel(value: string) {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export default function QualityPage() {
  const navigate = useNavigate();

  const queueState = useApi(() => api.quality.queue(), []);
  const rejectionState = useApi(() => api.quality.rejections(), []);

  const [selectedLot, setSelectedLot] = useState<QualityQueueItem | null>(null);
  const [result, setResult] = useState<QcResult>("pass");
  const [defectType, setDefectType] = useState("colour_mismatch");
  const [defectMeters, setDefectMeters] = useState("");
  const [notes, setNotes] = useState("");
  const [formError, setFormError] = useState("");
  const [saving, setSaving] = useState(false);
  const [successMessage, setSuccessMessage] = useState("");

  // The latest day anything was rejected, decided by the API in mill time (a Sunday demo still shows Saturday's).
  const latestState = useApi(() => api.quality.latestRejections(), []);
  const todayRejections = useMemo(() => latestState.data?.rejections ?? [], [latestState.data]);

  const colourMismatchToday = todayRejections.filter(
    (item) => item.defect_type === "colour_mismatch",
  );

  const causeLots = colourMismatchToday.length
    ? colourMismatchToday.map((item) => item.lot_code)
    : todayRejections.map((item) => item.lot_code);

  const alertDefect =
    todayRejections.length > 0 &&
    todayRejections.every((item) => item.defect_type === "colour_mismatch")
      ? "colour mismatch"
      : "quality defects";

  function openInspection(lot: QualityQueueItem) {
    setSelectedLot(lot);
    setResult("pass");
    setDefectType("colour_mismatch");
    setDefectMeters("");
    setNotes("");
    setFormError("");
    setSuccessMessage("");
  }

  function closeInspection() {
    if (saving) return;
    setSelectedLot(null);
    setFormError("");
  }

  async function submitInspection() {
    if (!selectedLot) return;

    const meters = Number(defectMeters);

    if (result !== "pass") {
      if (!defectType) {
        setFormError("Select a defect type.");
        return;
      }
      if (
        defectMeters.trim() === "" ||
        !Number.isFinite(meters) ||
        meters <= 0 ||
        meters > selectedLot.qty_m
      ) {
        setFormError(
          `Enter defect metres greater than 0 and no more than ${selectedLot.qty_m} m.`,
        );
        return;
      }
    }

    setSaving(true);
    setFormError("");
    setSuccessMessage("");

    try {
      await api.quality.inspect({
        lot_code: selectedLot.lot_code,
        result,
        ...(result !== "pass"
          ? { defect_type: defectType, defect_meters: meters }
          : {}),
        ...(notes.trim() ? { notes: notes.trim() } : {}),
      });

      setSuccessMessage(
        `${selectedLot.lot_code} inspection recorded as ${result.toUpperCase()}.`,
      );
      setSelectedLot(null);
      await Promise.all([queueState.reload(), rejectionState.reload(), latestState.reload()]);
    } catch (error) {
      setFormError(
        error instanceof Error
          ? error.message
          : "Inspection could not be saved. Please try again.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Quality"
        subtitle="Inspect finished dye lots, record defects and trace recurring quality issues."
        actions={

          <Button
            variant="secondary"
            onClick={() => {
              void Promise.all([
                queueState.reload(),
                rejectionState.reload(),
                latestState.reload(),
              ]);
            }}
            loading={
              queueState.loading ||
              rejectionState.loading ||
              latestState.loading
            }
          >
            Refresh
          </Button>
        }
      />

      {successMessage && (
        <div
          role="status"
          className="rounded-lg border border-ok/30 bg-ok-soft px-4 py-3 text-sm text-ok"
        >
          {successMessage}
        </div>
      )}

      {todayRejections.length > 0 && (
        <section
          aria-label="Today's quality alert"
          className="rounded-xl border border-bad/30 bg-bad-soft p-5"
        >
          <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
            <div>
              <div className="flex items-center gap-2">
                <Badge tone="bad">Attention required</Badge>
                <span className="text-sm text-bad">
                  {todayRejections.length} rejection
                  {todayRejections.length === 1 ? "" : "s"} on {formatDate(latestState.data?.day)}
                </span>
              </div>
              <h2 className="mt-2 text-lg font-semibold text-ink">
                {todayRejections.length} rolls rejected for {alertDefect}
              </h2>
              <p className="mt-1 text-sm text-muted">
                A recurring defect may need investigation. Review the affected
                lots to identify a possible cause.
              </p>
              <p className="mt-2 text-sm font-medium text-ink">
                Affected lots: {todayRejections.map((item) => item.lot_code).join(", ")}
              </p>
            </div>
            <Button
              onClick={() =>
                navigate(
                  `/trace?lots=${encodeURIComponent(causeLots.join(","))}`,
                )
              }
              disabled={causeLots.length === 0}
            >
              Find cause
            </Button>
          </div>
        </section>
      )}

      {queueState.error && (
        <ErrorBanner
          error={queueState.error}
          onRetry={() => void queueState.reload()}
        />
      )}

      {rejectionState.error && (
        <ErrorBanner
          error={rejectionState.error}
          onRetry={() => void rejectionState.reload()}
        />
      )}

      <Card
        title="Inspection queue"
        subtitle={`${queueState.data?.length ?? 0} rolls awaiting inspection. Select a row to record a result.`}
      >
        {queueState.loading && !queueState.data ? (
          <Spinner label="Loading inspection queue…" />
        ) : (queueState.data ?? []).length === 0 ? (
          <div className="py-8 text-center">
            <p className="font-medium text-ink">Inspection queue is clear</p>
            <p className="mt-1 text-sm text-muted">
              New rolls will appear here when they are ready for inspection.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-left text-sm">
              <thead className="bg-canvas text-muted">
                <tr>
                  <th className="px-3 py-3 font-medium">Roll</th>
                  <th className="px-3 py-3 font-medium">Product</th>
                  <th className="px-3 py-3 font-medium">Quantity</th>
                  <th className="px-3 py-3 font-medium">Dye batch</th>
                  <th className="px-3 py-3 font-medium">Dye location</th>
                  <th className="px-3 py-3 font-medium">Dyed at</th>
                  <th className="px-3 py-3 font-medium">Order</th>
                  <th className="px-3 py-3 font-medium">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {(queueState.data ?? []).map((lot) => (
                  <tr
                    key={lot.lot_code}
                    className="bg-surface hover:bg-canvas"
                  >
                    <td className="px-3 py-3 font-medium text-ink">
                      {lot.lot_code}
                    </td>
                    <td className="px-3 py-3 text-ink">{lot.product}</td>
                    <td className="px-3 py-3 text-ink">
                      {formatQty(lot.qty_m, "m")}
                    </td>
                    <td className="px-3 py-3 text-ink">{lot.dye_batch}</td>
                    <td className="px-3 py-3 text-ink">{formatDate(lot.dyed_on)}</td>
                    <td className="px-3 py-3 text-muted">
                      {formatDateTime(lot.dyed_at)}
                    </td>
                    <td className="px-3 py-3 text-ink">
                      {lot.order_code ?? "—"}
                    </td>
                    <td className="px-3 py-3">
                      <Button size="sm" onClick={() => openInspection(lot)}>
                        Inspect
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card
        title="Recent rejections"
        subtitle={`${rejectionState.data?.length ?? 0} recorded rejection${(rejectionState.data?.length ?? 0) === 1 ? "" : "s"}.`}
      >
        {rejectionState.loading && !rejectionState.data ? (
          <Spinner label="Loading rejection history…" />
        ) : (rejectionState.data ?? []).length === 0 ? (
          <div className="py-8 text-center">
            <p className="font-medium text-ink">No rejections recorded</p>
            <p className="mt-1 text-sm text-muted">
              Rejected rolls will appear here after an inspection.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[680px] text-left text-sm">
              <thead className="bg-canvas text-muted">
                <tr>
                  <th className="px-3 py-3 font-medium">Roll</th>
                  <th className="px-3 py-3 font-medium">Defect</th>
                  <th className="px-3 py-3 text-right font-medium">
                    Defect metres
                  </th>
                  <th className="px-3 py-3 font-medium">Inspector</th>
                  <th className="px-3 py-3 font-medium">Inspected at</th>
                  <th className="px-3 py-3 font-medium">Order</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {(rejectionState.data ?? []).map((item: Rejection) => (
                  <tr key={`${item.lot_code}-${item.inspected_at}`}>
                    <td className="px-3 py-3 font-medium text-ink">
                      {item.lot_code}
                    </td>
                    <td className="px-3 py-3">
                      <Badge tone="bad">{defectLabel(item.defect_type)}</Badge>
                    </td>
                    <td className="num px-3 py-3 text-right text-ink">
                      {item.defect_meters == null
                        ? "—"
                        : formatQty(item.defect_meters, "m")}
                    </td>
                    <td className="px-3 py-3 text-ink">{item.inspector}</td>
                    <td className="px-3 py-3 text-muted">
                      {formatDateTime(item.inspected_at)}
                    </td>
                    <td className="px-3 py-3 text-ink">
                      {item.order_code ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Modal
        open={selectedLot !== null}
        onClose={closeInspection}
        title={selectedLot ? `Inspect ${selectedLot.lot_code}` : "Inspect roll"}
        footer={
          <>
            <Button
              variant="secondary"
              onClick={closeInspection}
              disabled={saving}
            >
              Cancel
            </Button>
            <Button onClick={() => void submitInspection()} loading={saving}>
              Save inspection
            </Button>
          </>
        }
      >
        {selectedLot && (
          <div className="space-y-4">
            <div className="rounded-lg border border-line bg-canvas p-3 text-sm">
              <p className="font-medium text-ink">
                {selectedLot.product} · {selectedLot.dye_batch}
              </p>
              <p className="mt-1 text-muted">
                {formatQty(selectedLot.qty_m, "m")} ·{" "}
                {formatDate(selectedLot.dyed_on)} · Order {selectedLot.order_code ?? "—"}
              </p>
            </div>

            <Field label="Inspection result">
              <Select
                value={result}
                onChange={(event) => {
                  setResult(event.target.value as QcResult);
                  setFormError("");
                }}
              >
                <option value="pass">Pass</option>
                <option value="rework">Rework</option>
                <option value="reject">Reject</option>
              </Select>
            </Field>

            {result !== "pass" && (
              <>
                <Field label="Defect type">
                  <Select
                    value={defectType}
                    onChange={(event) => setDefectType(event.target.value)}
                  >
                    {DEFECT_TYPES.map((item) => (
                      <option key={item.value} value={item.value}>
                        {item.label}
                      </option>
                    ))}
                  </Select>
                </Field>

                <Field
                  label="Defect metres"
                  hint={`Enter a value greater than 0 and up to ${selectedLot.qty_m} m.`}
                >
                  <Input
                    type="number"
                    min="0.1"
                    max={selectedLot.qty_m}
                    step="0.1"
                    value={defectMeters}
                    onChange={(event) => setDefectMeters(event.target.value)}
                    placeholder="e.g. 5"
                  />
                </Field>
              </>
            )}

            <Field label="Notes (optional)">
              <Textarea
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
                placeholder="Add inspection notes…"
                rows={3}
              />
            </Field>

            {formError && (
              <p role="alert" className="rounded-lg bg-bad-soft p-3 text-sm text-bad">
                {formError}
              </p>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}