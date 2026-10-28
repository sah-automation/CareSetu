import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import ObservabilityEvalsPage from "./page";
import { fetchEvaluation } from "@/lib/operator/observability";
import { I18nProvider } from "@/lib/i18n/I18nProvider";

vi.mock("@/lib/operator/observability");
vi.mock("@/lib/operator/usePanelRead");

const mockFetchEvaluation = vi.mocked(fetchEvaluation);

const renderWithI18n = (component: React.ReactNode) => {
  return render(<I18nProvider lang="en">{component}</I18nProvider>);
};

describe("ObservabilityEvalsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders loading skeleton", async () => {
    mockFetchEvaluation.mockReturnValue(
      Promise.resolve({
        active_dataset: null,
        judge_run: null,
        judge_scores: [],
        agreement: [],
        synthetic_only: true,
      }),
    );

    renderWithI18n(<ObservabilityEvalsPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("evaluation-report-loading"),
      ).toBeInTheDocument();
    });
  });

  it("renders empty state when no active dataset", async () => {
    mockFetchEvaluation.mockResolvedValue({
      active_dataset: null,
      judge_run: null,
      judge_scores: [],
      agreement: [],
      synthetic_only: true,
    });

    renderWithI18n(<ObservabilityEvalsPage />);

    await waitFor(() => {
      expect(screen.getByText("No active dataset")).toBeInTheDocument();
      expect(
        screen.getByText("No evaluation dataset has been activated yet"),
      ).toBeInTheDocument();
    });
  });

  it("renders active dataset, judge run, scores, agreement, labeling, and synthetic-only statement", async () => {
    mockFetchEvaluation.mockResolvedValue({
      active_dataset: {
        id: 1,
        name: "golden",
        version: 1,
        status: "active",
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-02T00:00:00Z",
        example_count: 50,
        is_active: true,
      },
      judge_run: {
        run_ref: "run-abc123",
        dataset_name: "golden",
        dataset_version: 1,
        status: "completed",
        budget_paise: 100000,
        cost_paise: 5000,
        started_at: "2026-01-01T10:00:00Z",
        completed_at: "2026-01-01T10:05:00Z",
        failure_reason: null,
        example_count: 50,
        scored_count: 50,
        synthetic_only: true,
      },
      judge_scores: [
        {
          evaluator: "job_succeeded",
          observation_ref: "example-1",
          observation_kind: "golden",
          source: "judge",
          data_type: "BOOLEAN",
          value: 1.0,
          judge_run_ref: "run-abc123",
          score_date: "2026-01-01",
          trace_id: "trace-123",
          metadata: {},
        },
      ],
      agreement: [
        {
          evaluator: "job_succeeded",
          count: 50,
          mean_absolute_error: 0.02,
          within_tolerance_share: 0.96,
          kappa: 0.92,
          tolerance: 0.05,
          data_type: "BOOLEAN",
          synthetic_only: true,
          empty: false,
        },
      ],
      synthetic_only: true,
    });

    renderWithI18n(<ObservabilityEvalsPage />);

    await waitFor(() => {
      expect(screen.getByText("golden")).toBeInTheDocument();
      expect(screen.getByText("Version 1")).toBeInTheDocument();
      expect(screen.getByText("run-abc123")).toBeInTheDocument();
      expect(screen.getByText("completed")).toBeInTheDocument();
      expect(screen.getByText("₹1,000.00")).toBeInTheDocument();
      expect(screen.getByText("job_succeeded")).toBeInTheDocument();
      expect(screen.getByText("96.0%")).toBeInTheDocument();
      expect(screen.getByText("0.9200")).toBeInTheDocument();
      expect(screen.getByText("Labeling view")).toBeInTheDocument();
      expect(screen.getByText("Synthetic-only:")).toBeInTheDocument();
    });
  });

  it("renders error state on fetch failure", async () => {
    mockFetchEvaluation.mockRejectedValue(new Error("Network error"));

    renderWithI18n(<ObservabilityEvalsPage />);

    await waitFor(() => {
      expect(screen.getByTestId("evaluation-report-error")).toBeInTheDocument();
      expect(
        screen.getByText("Could not load the evaluation report."),
      ).toBeInTheDocument();
    });
  });
});
