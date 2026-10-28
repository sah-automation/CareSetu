"use client";

// #794/#795: the operator Evals page. Read-only evaluation report plus admin
// controls guarded on the admin tier and operator-applied human labels.

import { useMemo, useState } from "react";
import {
  ObservabilityPanelPage,
  ReadPanel,
} from "@/components/observability/ObservabilityPanelPage";
import {
  activateEvaluationDataset,
  applyHumanLabel,
  createEvaluationDatasetDraft,
  editEvaluationDatasetDraft,
  fetchEvaluation,
  startJudgeRun,
} from "@/lib/operator/observability";
import { useAuth } from "@/lib/auth/AuthContext";
import { useI18n } from "@/lib/i18n/useI18n";
import { usePanelRead } from "@/lib/operator/usePanelRead";

function useAuthOrNull() {
  try {
    return useAuth();
  } catch {
    return null;
  }
}

function traceOf(error: unknown): string {
  return error instanceof Error && "traceId" in error
    ? ": " + String((error as { traceId?: string }).traceId)
    : "";
}

export default function ObservabilityEvalsPage() {
  const { t } = useI18n();
  const auth = useAuthOrNull();
  const isAdmin =
    auth?.user?.roles.includes("operator") === true &&
    auth.user?.tier === "admin";
  const evaluation = usePanelRead(() => fetchEvaluation());

  const [adminName, setAdminName] = useState("golden");
  const [adminVersion, setAdminVersion] = useState("2");
  const [adminExamples, setAdminExamples] = useState("[]");
  const [adminError, setAdminError] = useState("");
  const [adminBusy, setAdminBusy] = useState(false);
  const [labelExampleRef, setLabelExampleRef] = useState("");
  const [labelEvaluator, setLabelEvaluator] = useState("completeness");
  const [labelValue, setLabelValue] = useState("1");
  const [labelError, setLabelError] = useState("");
  const [labelBusy, setLabelBusy] = useState(false);

  const examples = useMemo(() => {
    try {
      const parsed = JSON.parse(adminExamples);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return null;
    }
  }, [adminExamples]);

  async function reload() {
    evaluation.reload();
  }

  async function handleCreateDraft() {
    setAdminError("");
    if (examples === null) {
      setAdminError(t.evals.adminErrorPrefix);
      return;
    }
    setAdminBusy(true);
    try {
      await createEvaluationDatasetDraft(
        adminName,
        Number(adminVersion),
        examples as any,
      );
      await reload();
    } catch (error) {
      setAdminError(`${t.evals.adminErrorPrefix} ${traceOf(error)}`.trim());
    } finally {
      setAdminBusy(false);
    }
  }

  async function handleEditDraft() {
    setAdminError("");
    if (examples === null) {
      setAdminError(t.evals.adminErrorPrefix);
      return;
    }
    setAdminBusy(true);
    try {
      await editEvaluationDatasetDraft(
        adminName,
        Number(adminVersion),
        examples as any,
      );
      await reload();
    } catch (error) {
      setAdminError(`${t.evals.adminErrorPrefix} ${traceOf(error)}`.trim());
    } finally {
      setAdminBusy(false);
    }
  }

  async function handleActivate() {
    setAdminError("");
    setAdminBusy(true);
    try {
      await activateEvaluationDataset(adminName, Number(adminVersion));
      await reload();
    } catch (error) {
      setAdminError(`${t.evals.adminErrorPrefix} ${traceOf(error)}`.trim());
    } finally {
      setAdminBusy(false);
    }
  }

  async function handleStartJudgeRun() {
    setAdminError("");
    setAdminBusy(true);
    try {
      await startJudgeRun();
      await reload();
    } catch (error) {
      setAdminError(`${t.evals.adminErrorPrefix} ${traceOf(error)}`.trim());
    } finally {
      setAdminBusy(false);
    }
  }

  async function handleApplyLabel() {
    setLabelError("");
    const value = Number(labelValue);
    if (Number.isNaN(value)) {
      setLabelError(t.evals.labelErrorPrefix);
      return;
    }
    setLabelBusy(true);
    try {
      await applyHumanLabel({
        example_ref: labelExampleRef,
        evaluator: labelEvaluator,
        value,
      });
      await reload();
    } catch (error) {
      setLabelError(`${t.evals.labelErrorPrefix} ${traceOf(error)}`.trim());
    } finally {
      setLabelBusy(false);
    }
  }

  const budgetCap = evaluation.data?.judge_run?.budget_paise ?? null;

  return (
    <ObservabilityPanelPage
      title={t.evals.title}
      description={t.evals.description}
    >
      <ReadPanel
        testId="evaluation-report"
        title={t.evals.datasetTitle}
        read={evaluation}
        isEmpty={(data) => data.active_dataset === null}
        emptyTitle={t.evals.noDatasetTitle}
        emptyBody={t.evals.noDatasetBody}
        errorMessage={t.evals.errorMessage}
      >
        {(data) => (
          <div className="flex flex-col gap-6">
            {data.active_dataset && (
              <section className="rounded-lg border border-hairline p-4">
                <h3 className="mb-2 text-sm font-medium text-txt-sub">
                  {t.evals.datasetTitle}
                </h3>
                <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <div>
                    <dt className="text-xs text-txt-muted">
                      {t.evals.datasetName}
                    </dt>
                    <dd className="text-sm font-medium text-txt">
                      {data.active_dataset.name}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-txt-muted">
                      {t.evals.datasetVersion}
                    </dt>
                    <dd className="text-sm font-medium text-txt">
                      {data.active_dataset.version}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-txt-muted">
                      {t.evals.datasetStatus}
                    </dt>
                    <dd className="text-sm font-medium text-txt">
                      {data.active_dataset.status}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-txt-muted">
                      {t.evals.datasetExamples}
                    </dt>
                    <dd className="text-sm font-medium text-txt">
                      {data.active_dataset.example_count}
                    </dd>
                  </div>
                  <div className="sm:col-span-2">
                    <dt className="text-xs text-txt-muted">
                      {t.evals.datasetCreated}
                    </dt>
                    <dd className="text-sm font-medium text-txt">
                      {data.active_dataset.created_at}
                    </dd>
                  </div>
                  <div className="sm:col-span-2">
                    <dt className="text-xs text-txt-muted">
                      {t.evals.datasetUpdated}
                    </dt>
                    <dd className="text-sm font-medium text-txt">
                      {data.active_dataset.updated_at}
                    </dd>
                  </div>
                </dl>
              </section>
            )}

            {data.judge_run && (
              <section className="rounded-lg border border-hairline p-4">
                <h3 className="mb-2 text-sm font-medium text-txt-sub">
                  {t.evals.judgeRunTitle}
                </h3>
                <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <div>
                    <dt className="text-xs text-txt-muted">
                      {t.evals.judgeRunRef}
                    </dt>
                    <dd className="text-sm font-mono text-txt">
                      {data.judge_run.run_ref}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-txt-muted">
                      {t.evals.judgeRunStatus}
                    </dt>
                    <dd className="text-sm font-medium text-txt">
                      {data.judge_run.status}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-txt-muted">
                      {t.evals.judgeRunBudget}
                    </dt>
                    <dd className="text-sm font-medium text-txt">
                      {t.evals.rupees(data.judge_run.budget_paise)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-txt-muted">
                      {t.evals.judgeRunCost}
                    </dt>
                    <dd className="text-sm font-medium text-txt">
                      {t.evals.rupees(data.judge_run.cost_paise)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-txt-muted">
                      {t.evals.judgeRunExamples}
                    </dt>
                    <dd className="text-sm font-medium text-txt">
                      {data.judge_run.example_count}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-txt-muted">
                      {t.evals.judgeRunScored}
                    </dt>
                    <dd className="text-sm font-medium text-txt">
                      {data.judge_run.scored_count}
                    </dd>
                  </div>
                  <div className="sm:col-span-2">
                    <dt className="text-xs text-txt-muted">
                      {t.evals.judgeRunStarted}
                    </dt>
                    <dd className="text-sm font-medium text-txt">
                      {data.judge_run.started_at ?? "-"}
                    </dd>
                  </div>
                  <div className="sm:col-span-2">
                    <dt className="text-xs text-txt-muted">
                      {t.evals.judgeRunCompleted}
                    </dt>
                    <dd className="text-sm font-medium text-txt">
                      {data.judge_run.completed_at ?? "-"}
                    </dd>
                  </div>
                  {data.judge_run.failure_reason && (
                    <div className="sm:col-span-4">
                      <dt className="text-xs text-txt-muted">
                        {t.evals.judgeRunFailure}
                      </dt>
                      <dd className="text-sm font-medium text-danger">
                        {data.judge_run.failure_reason}
                      </dd>
                    </div>
                  )}
                </dl>
              </section>
            )}

            {data.judge_scores.length > 0 && (
              <section className="rounded-lg border border-hairline p-4">
                <h3 className="mb-2 text-sm font-medium text-txt-sub">
                  {t.evals.scoresTitle.replace(
                    "{count}",
                    String(data.judge_scores.length),
                  )}
                </h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-hairline">
                        <th className="text-left px-3 py-2 text-xs text-txt-muted">
                          {t.evals.scoresEvaluator}
                        </th>
                        <th className="text-left px-3 py-2 text-xs text-txt-muted">
                          {t.evals.scoresObservation}
                        </th>
                        <th className="text-left px-3 py-2 text-xs text-txt-muted">
                          {t.evals.scoresKind}
                        </th>
                        <th className="text-left px-3 py-2 text-xs text-txt-muted">
                          {t.evals.scoresSource}
                        </th>
                        <th className="text-left px-3 py-2 text-xs text-txt-muted">
                          {t.evals.scoresType}
                        </th>
                        <th className="text-right px-3 py-2 text-xs text-txt-muted">
                          {t.evals.scoresValue}
                        </th>
                        <th className="text-left px-3 py-2 text-xs text-txt-muted">
                          {t.evals.scoresDate}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.judge_scores.map((score) => (
                        <tr
                          key={`${score.evaluator}-${score.observation_ref}`}
                          className="border-b border-hairline-soft hover:bg-hairline-soft"
                        >
                          <td className="px-3 py-2 font-mono text-txt">
                            {score.evaluator}
                          </td>
                          <td className="px-3 py-2 font-mono text-txt">
                            {score.observation_ref}
                          </td>
                          <td className="px-3 py-2 text-txt">
                            {score.observation_kind}
                          </td>
                          <td className="px-3 py-2 text-txt">{score.source}</td>
                          <td className="px-3 py-2 text-txt">
                            {score.data_type}
                          </td>
                          <td className="px-3 py-2 text-right font-mono text-txt">
                            {score.value.toFixed(6)}
                          </td>
                          <td className="px-3 py-2 text-txt">
                            {score.score_date}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}

            {data.agreement.length > 0 && (
              <section className="rounded-lg border border-hairline p-4">
                <h3 className="mb-2 text-sm font-medium text-txt-sub">
                  {t.evals.agreementTitle.replace(
                    "{count}",
                    String(data.agreement.length),
                  )}
                </h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-hairline">
                        <th className="text-left px-3 py-2 text-xs text-txt-muted">
                          {t.evals.agreementEvaluator}
                        </th>
                        <th className="text-right px-3 py-2 text-xs text-txt-muted">
                          {t.evals.agreementCount}
                        </th>
                        <th className="text-right px-3 py-2 text-xs text-txt-muted">
                          {t.evals.agreementMae}
                        </th>
                        <th className="text-right px-3 py-2 text-xs text-txt-muted">
                          {t.evals.agreementWithinTolerance}
                        </th>
                        <th className="text-right px-3 py-2 text-xs text-txt-muted">
                          {t.evals.agreementKappa}
                        </th>
                        <th className="text-right px-3 py-2 text-xs text-txt-muted">
                          {t.evals.agreementTolerance}
                        </th>
                        <th className="text-left px-3 py-2 text-xs text-txt-muted">
                          {t.evals.agreementType}
                        </th>
                        <th className="text-left px-3 py-2 text-xs text-txt-muted">
                          {t.evals.agreementEmpty}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.agreement.map((agree) => (
                        <tr
                          key={agree.evaluator}
                          className="border-b border-hairline-soft hover:bg-hairline-soft"
                        >
                          <td className="px-3 py-2 font-mono text-txt">
                            {agree.evaluator}
                          </td>
                          <td className="px-3 py-2 text-right text-txt">
                            {agree.count}
                          </td>
                          <td className="px-3 py-2 text-right text-txt">
                            {agree.mean_absolute_error.toFixed(4)}
                          </td>
                          <td className="px-3 py-2 text-right text-txt">
                            {t.evals.percent(agree.within_tolerance_share)}
                          </td>
                          <td className="px-3 py-2 text-right text-txt">
                            {agree.kappa !== null
                              ? agree.kappa.toFixed(4)
                              : "-"}
                          </td>
                          <td className="px-3 py-2 text-right text-txt">
                            {agree.tolerance.toFixed(2)}
                          </td>
                          <td className="px-3 py-2 text-txt">
                            {agree.data_type}
                          </td>
                          <td className="px-3 py-2 text-txt">
                            {agree.empty ? t.evals.yes : t.evals.no}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}

            {data.judge_scores.length > 0 && (
              <section className="rounded-lg border border-hairline p-4">
                <h3 className="mb-2 text-sm font-medium text-txt-sub">
                  {t.evals.labelingTitle}
                </h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-hairline">
                        <th className="text-left px-3 py-2 text-xs text-txt-muted">
                          {t.evals.labelingEvaluator}
                        </th>
                        <th className="text-left px-3 py-2 text-xs text-txt-muted">
                          {t.evals.labelingObservation}
                        </th>
                        <th className="text-left px-3 py-2 text-xs text-txt-muted">
                          {t.evals.labelingKind}
                        </th>
                        <th className="text-left px-3 py-2 text-xs text-txt-muted">
                          {t.evals.labelingSource}
                        </th>
                        <th className="text-left px-3 py-2 text-xs text-txt-muted">
                          {t.evals.labelingDataType}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.judge_scores.map((score) => (
                        <tr
                          key={`${score.evaluator}-${score.observation_ref}`}
                          className="border-b border-hairline-soft hover:bg-hairline-soft"
                        >
                          <td className="px-3 py-2 font-mono text-txt">
                            {score.evaluator}
                          </td>
                          <td className="px-3 py-2 font-mono text-txt">
                            {score.observation_ref}
                          </td>
                          <td className="px-3 py-2 text-txt">
                            {score.observation_kind}
                          </td>
                          <td className="px-3 py-2 text-txt">{score.source}</td>
                          <td className="px-3 py-2 text-txt">
                            {score.data_type}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div className="mt-4 flex flex-col gap-3 border-t border-hairline pt-3">
                  <h4 className="text-sm font-medium text-txt-sub">
                    {t.evals.labelExample}
                  </h4>
                  <div className="grid gap-2 sm:grid-cols-3">
                    <input
                      className="rounded-md border border-hairline px-3 py-2 text-sm"
                      placeholder={t.evals.labelingObservation}
                      value={labelExampleRef}
                      onChange={(event) =>
                        setLabelExampleRef(event.target.value)
                      }
                      data-testid="human-label-example-ref"
                    />
                    <input
                      className="rounded-md border border-hairline px-3 py-2 text-sm"
                      placeholder={t.evals.labelingEvaluator}
                      value={labelEvaluator}
                      onChange={(event) =>
                        setLabelEvaluator(event.target.value)
                      }
                      data-testid="human-label-evaluator"
                    />
                    <input
                      className="rounded-md border border-hairline px-3 py-2 text-sm"
                      placeholder="Value"
                      type="number"
                      value={labelValue}
                      onChange={(event) => setLabelValue(event.target.value)}
                      data-testid="human-label-value"
                    />
                  </div>
                  {labelError && (
                    <>
                      <p
                        className="text-sm text-danger"
                        data-testid="evals-label-error"
                      >
                        {labelError}
                      </p>
                      <p
                        className="text-sm text-danger"
                        data-testid="evaluation-label-error"
                      >
                        {labelError}
                      </p>
                    </>
                  )}
                  <button
                    type="button"
                    disabled={labelBusy}
                    onClick={() => void handleApplyLabel()}
                    className="inline-flex min-h-11 items-center rounded-md border border-hairline px-4 text-sm font-medium text-txt-sub hover:bg-hairline-soft disabled:opacity-50"
                    data-testid="apply-human-label"
                  >
                    {labelBusy ? "..." : t.evals.labelExample}
                  </button>
                </div>
              </section>
            )}

            {isAdmin && (
              <div data-testid="evals-admin-controls">
                <section
                  className="rounded-lg border border-hairline p-4"
                  data-testid="evaluation-admin-controls"
                >
                  <h3 className="mb-2 text-sm font-medium text-txt-sub">
                    {t.evals.adminTitle}
                  </h3>
                  <div className="mb-2 text-sm text-txt-muted">
                    {t.evals.judgeRunBudget}:{" "}
                    <span data-testid="judge-run-budget-cap">
                      {budgetCap !== null
                        ? t.evals.rupees(budgetCap)
                        : t.evals.judgeRunBudget}
                    </span>
                  </div>
                  <div className="grid gap-2 sm:grid-cols-2">
                    <input
                      className="rounded-md border border-hairline px-3 py-2 text-sm"
                      placeholder={t.evals.adminDatasetNameLabel}
                      value={adminName}
                      onChange={(event) => setAdminName(event.target.value)}
                      data-testid="admin-dataset-name"
                    />
                    <input
                      className="rounded-md border border-hairline px-3 py-2 text-sm"
                      placeholder={t.evals.adminDatasetVersionLabel}
                      value={adminVersion}
                      onChange={(event) => setAdminVersion(event.target.value)}
                      data-testid="admin-dataset-version"
                    />
                  </div>
                  <textarea
                    className="mt-2 w-full rounded-md border border-hairline px-3 py-2 text-sm"
                    placeholder={t.evals.adminDatasetExamplesLabel}
                    value={adminExamples}
                    onChange={(event) => setAdminExamples(event.target.value)}
                    data-testid="admin-dataset-examples"
                  />
                  {adminError && (
                    <>
                      <p
                        className="text-sm text-danger"
                        data-testid="evals-admin-error"
                      >
                        {adminError}
                      </p>
                      <p
                        className="text-sm text-danger"
                        data-testid="evaluation-admin-error"
                      >
                        {adminError}
                      </p>
                    </>
                  )}
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      type="button"
                      disabled={adminBusy}
                      onClick={() => void handleCreateDraft()}
                      className="inline-flex min-h-11 items-center rounded-md border border-hairline px-4 text-sm font-medium text-txt-sub hover:bg-hairline-soft disabled:opacity-50"
                      data-testid="create-dataset-draft"
                    >
                      {adminBusy ? "..." : t.evals.createDatasetDraft}
                    </button>
                    <button
                      type="button"
                      disabled={adminBusy}
                      onClick={() => void handleEditDraft()}
                      className="inline-flex min-h-11 items-center rounded-md border border-hairline px-4 text-sm font-medium text-txt-sub hover:bg-hairline-soft disabled:opacity-50"
                      data-testid="edit-dataset-draft"
                    >
                      {adminBusy ? "..." : t.evals.editDatasetDraft}
                    </button>
                    <button
                      type="button"
                      disabled={adminBusy}
                      onClick={() => void handleActivate()}
                      className="inline-flex min-h-11 items-center rounded-md border border-hairline px-4 text-sm font-medium text-txt-sub hover:bg-hairline-soft disabled:opacity-50"
                      data-testid="activate-dataset-version"
                    >
                      {adminBusy ? "..." : t.evals.activateDatasetVersion}
                    </button>
                    <button
                      type="button"
                      disabled={adminBusy}
                      onClick={() => void handleStartJudgeRun()}
                      className="inline-flex min-h-11 items-center rounded-md border border-hairline px-4 text-sm font-medium text-txt-sub hover:bg-hairline-soft disabled:opacity-50"
                      data-testid="start-judge-run"
                    >
                      {adminBusy ? "..." : t.evals.startJudgeRun}
                    </button>
                  </div>
                </section>
              </div>
            )}

            <section
              className="rounded-lg border border-hairline bg-hairline-soft p-4"
              data-testid="evals-synthetic-only"
            >
              <p className="text-sm text-txt">
                <strong>{t.evals.syntheticOnlyTitle}:</strong>{" "}
                {t.evals.syntheticOnlyBody}
              </p>
            </section>
          </div>
        )}
      </ReadPanel>
    </ObservabilityPanelPage>
  );
}
