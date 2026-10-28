"use client";

// #794: the operator Evals page (PHASE-14B Batch 2),
// over GET /v1/operator/observability/evaluation.
//
// One read, one panel: the active dataset, the latest judge run and its
// progress, the judge scores, the judge-vs-human agreement, and the labeling
// view. All data is synthetic-only; the synthetic_only marker is always true.

import {
  ObservabilityPanelPage,
  ReadPanel,
} from "@/components/observability/ObservabilityPanelPage";
import { fetchEvaluation } from "@/lib/operator/observability";
import { useI18n } from "@/lib/i18n/useI18n";
import { usePanelRead } from "@/lib/operator/usePanelRead";

export default function ObservabilityEvalsPage() {
  const { t } = useI18n();
  const evaluation = usePanelRead(() => fetchEvaluation());

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
            {/* Active Dataset */}
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

            {/* Judge Run Progress */}
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

            {/* Judge Scores */}
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

            {/* Agreement */}
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

            {/* Labeling View */}
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
              </section>
            )}

            {/* Synthetic-only statement */}
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
