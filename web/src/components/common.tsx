import type { ReactNode } from "react";

import { CLASS_LABELS, CLASS_PLURALS, ERROR_CLASSES, RESULT_LABELS } from "../format";
import { useJob } from "../hooks";
import type { Classification, ErrorCounts, Job, UserResult } from "../types";

export function Alert({
  kind = "info",
  children,
}: {
  kind?: "info" | "warning" | "error" | "success";
  children: ReactNode;
}) {
  return (
    <div className={`alert alert-${kind}`} role={kind === "error" ? "alert" : "status"}>
      {children}
    </div>
  );
}

export function Loading({ label = "Cargando…" }: { label?: string }) {
  return (
    <p className="loading" aria-live="polite">
      <span className="spinner" aria-hidden="true" /> {label}
    </p>
  );
}

export function ClassBadge({ classification }: { classification: Classification }) {
  if (classification === "ok") return null;
  return <span className={`badge badge-${classification}`}>{CLASS_LABELS[classification]}</span>;
}

export function ErrorCountBadges({ counts }: { counts: ErrorCounts }) {
  return (
    <span className="count-badges">
      {ERROR_CLASSES.map((cls) => (
        <span
          key={cls}
          className={`count count-${cls} ${counts[cls] ? "" : "count-zero"}`}
          title={`${CLASS_PLURALS[cls]}: ${counts[cls]}`}
        >
          {counts[cls]}
        </span>
      ))}
    </span>
  );
}

export function ResultBadge({ result }: { result: UserResult }) {
  return <span className={`result result-${result}`}>{RESULT_LABELS[result]}</span>;
}

/** Progress of a background job; calls `onFinish` once when it ends. */
export function JobProgress<R>({
  job: initial,
  onFinish,
  renderResult,
}: {
  job: Job<R>;
  onFinish?: (job: Job<R>) => void;
  renderResult?: (result: R) => ReactNode;
}) {
  const { job, error } = useJob<R>(initial, onFinish);
  if (error) return <Alert kind="error">{error}</Alert>;
  if (!job) return null;
  if (job.status === "error") return <Alert kind="error">{job.error}</Alert>;
  if (job.status === "done") {
    return job.result && renderResult ? <>{renderResult(job.result)}</> : null;
  }
  const pct = job.total ? Math.round((job.current / job.total) * 100) : null;
  return (
    <div className="job-progress">
      <div className="progress" aria-hidden="true">
        <div
          className={`progress-bar ${pct === null ? "progress-indeterminate" : ""}`}
          style={pct === null ? undefined : { width: `${pct}%` }}
        />
      </div>
      <p className="muted">
        {job.message || "En cola…"}
        {job.total ? ` (${job.current}/${job.total})` : ""}
      </p>
    </div>
  );
}
