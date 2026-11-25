import { apiRequest } from './api';
import type {
  AbstentionAccuracyMetrics,
  BenchmarkCaseItem,
  BenchmarkCategoryStats,
  ModelVariantId,
  NativeBenchmarkEvaluation,
  NativeBenchmarkReport,
  SourceVerificationMetrics,
} from '../types';

export interface RunBenchmarkOptions {
  modelVersion?: ModelVariantId;
  logToConsole?: boolean;
}

interface BenchmarkApiResponse {
  ok: boolean;
  executed_at?: string;
  report?: NativeBenchmarkReport;
}

function getCaseResult(cases: BenchmarkCaseItem[], id: string): boolean {
  const found = cases.find((c) => c.id === id);
  return Boolean(found && found.passed);
}

/**
 * Enforces ZYRQUEN Anti-Fabrication Policy on benchmark payloads:
 * - No external models permitted (external_models_used === false)
 * - Summary metrics must reconcile strictly with the individual evaluated cases
 * - Non-empty case evidence required
 */
export function assertBenchmarkReportIntegrity(report: NativeBenchmarkReport | undefined): asserts report is NativeBenchmarkReport {
  if (!report || typeof report !== 'object') {
    throw new Error('Anti-Fabrication Policy Violation: Missing benchmark report payload');
  }
  if (!report.environment || report.environment.external_models_used !== false) {
    throw new Error(
      'Anti-Fabrication Policy Violation: External model dependency detected (external_models_used must be false)'
    );
  }
  if (!Array.isArray(report.cases) || report.cases.length === 0) {
    throw new Error('Anti-Fabrication Policy Violation: Benchmark report contains zero evaluated cases');
  }
  if (!report.summary) {
    throw new Error('Anti-Fabrication Policy Violation: Missing summary block in benchmark report');
  }

  const totalCases = report.cases.length;
  const passedCases = report.cases.filter((c) => c.passed).length;
  const failedCases = totalCases - passedCases;
  const negCases = report.cases.filter((c) => c.polarity === 'negative');
  const falsePositives = negCases.filter((c) => !c.passed).length;

  if (
    report.summary.total_cases !== totalCases ||
    report.summary.passed !== passedCases ||
    report.summary.failed !== failedCases ||
    report.summary.negative_cases_total !== negCases.length ||
    report.summary.false_positives !== falsePositives
  ) {
    throw new Error(
      'Anti-Fabrication Policy Violation: Summary counts do not match raw evaluated cases'
    );
  }
}

/**
 * Verifies Source Verification & Anti-Fabrication gates directly from evaluated cases:
 * - AFB-01: Fabricated/blocked-LLM source rejection
 * - AFB-02: Invalid/SSRF/non-allowlisted URL rejection
 * - AFB-03: Unsupported claim abstention (INSUFFICIENT_EVIDENCE)
 * - AFB-04: Stale evidence freshness detection (STALE)
 * - AFB-05: Missing evidence abstention (NOT_RUN, no fake accuracy)
 * - AFB-06: Mock data & DB isolation + zero external models
 * - AFB-07: False success prevention (BLOCKED/FAILED/PENDING_APPROVAL)
 */
export function evaluateSourceVerification(
  report: NativeBenchmarkReport
): SourceVerificationMetrics {
  const antiFabCases = report.cases.filter((c) => c.category === 'anti_fabrication');
  const failedCases = antiFabCases.filter((c) => !c.passed);
  const total = antiFabCases.length;
  const passed = total - failedCases.length;
  const externalModelsUsed = report.environment.external_models_used !== false;
  const fixtureIsolated = Boolean(report.leakage_detection?.fixture_isolation?.isolated);

  const checks = {
    fabricatedSourceRejected: getCaseResult(antiFabCases, 'AFB-01'),
    invalidUrlRejected: getCaseResult(antiFabCases, 'AFB-02'),
    unsupportedClaimRejected: getCaseResult(antiFabCases, 'AFB-03'),
    staleEvidenceFlagged: getCaseResult(antiFabCases, 'AFB-04'),
    missingEvidenceAbstained: getCaseResult(antiFabCases, 'AFB-05'),
    mockIsolationVerified:
      getCaseResult(antiFabCases, 'AFB-06') && !externalModelsUsed && fixtureIsolated,
    falseSuccessPrevented: getCaseResult(antiFabCases, 'AFB-07'),
  };

  const allChecksVerified =
    total > 0 &&
    passed === total &&
    !externalModelsUsed &&
    Object.values(checks).every(Boolean);

  return {
    status: allChecksVerified ? 'VERIFIED' : 'FAILED',
    score: total > 0 ? Math.round((passed / total) * 10000) / 10000 : 0,
    passed,
    total,
    externalModelsUsed,
    checks,
    failedCases,
  };
}

/**
 * Measures Abstention Accuracy on negative/unlearned probes (polarity === 'negative')
 * and strictly isolates False Positives where the model failed to output NOT_LEARNED / reject.
 */
export function evaluateAbstentionAccuracy(
  report: NativeBenchmarkReport
): AbstentionAccuracyMetrics {
  const negCases = report.cases.filter((c) => c.polarity === 'negative');
  const breaches = negCases.filter((c) => !c.passed);
  const negativeCasesTotal = negCases.length;
  const falsePositives = breaches.length;
  const negativeCasesPassed = negativeCasesTotal - falsePositives;

  const overallAbstentionAccuracy =
    negativeCasesTotal > 0
      ? Math.round((negativeCasesPassed / negativeCasesTotal) * 10000) / 10000
      : 0;
  const falsePositiveRate =
    negativeCasesTotal > 0
      ? Math.round((falsePositives / negativeCasesTotal) * 10000) / 10000
      : 0;

  const negCategoryCases = report.cases.filter((c) => c.category === 'negative_abstention');
  const negCatPassed = negCategoryCases.filter((c) => c.passed).length;
  const negCatTotal = negCategoryCases.length;
  const negativeAbstentionCategory: BenchmarkCategoryStats = {
    total: negCatTotal,
    passed: negCatPassed,
    failed: negCatTotal - negCatPassed,
    score: negCatTotal > 0 ? Math.round((negCatPassed / negCatTotal) * 10000) / 10000 : 0,
  };

  return {
    status: negativeCasesTotal > 0 && falsePositives === 0 ? 'VERIFIED' : 'FAILED',
    overallAbstentionAccuracy,
    negativeCasesPassed,
    negativeCasesTotal,
    falsePositives,
    falsePositiveRate,
    negativeAbstentionCategory,
    breaches,
  };
}

/**
 * Formats and emits real benchmark results to the developer browser console
 * without concealing failures or unmeasurable limitations.
 */
export function logBenchmarkReportToConsole(evaluation: NativeBenchmarkEvaluation): void {
  const { report, sourceVerification, abstentionAccuracy, executedAt } = evaluation;
  const env = report.environment;
  const summary = report.summary;

  console.group?.(
    `[ZYRQUEN Benchmark] ${report.benchmark_version} · ${env.model_version} · ${summary.passed}/${summary.total_cases} (${(summary.overall_score * 100).toFixed(1)}%)`
  );
  console.info('[ZYRQUEN] Provenance:', {
    executedAt,
    pythonVersion: env.python_version,
    checkpointVersion: env.checkpoint_version,
    externalModelsUsed: env.external_models_used,
  });
  console.info('[ZYRQUEN] Source Verification:', {
    status: sourceVerification.status,
    score: `${sourceVerification.passed}/${sourceVerification.total}`,
    checks: sourceVerification.checks,
  });
  console.info('[ZYRQUEN] Abstention Accuracy:', {
    status: abstentionAccuracy.status,
    accuracy: `${(abstentionAccuracy.overallAbstentionAccuracy * 100).toFixed(1)}%`,
    negativeCases: `${abstentionAccuracy.negativeCasesPassed}/${abstentionAccuracy.negativeCasesTotal}`,
    falsePositives: abstentionAccuracy.falsePositives,
    falsePositiveRate: `${(abstentionAccuracy.falsePositiveRate * 100).toFixed(1)}%`,
    negativeAbstentionSuite: `${abstentionAccuracy.negativeAbstentionCategory.passed}/${abstentionAccuracy.negativeAbstentionCategory.total}`,
  });

  if (typeof console.table === 'function') {
    console.table(
      Object.entries(report.category_scores).map(([category, stats]) => ({
        category,
        passed: stats.passed,
        total: stats.total,
        scorePct: `${(stats.score * 100).toFixed(1)}%`,
      }))
    );
  }

  if (report.failures.length > 0) {
    console.warn(`[ZYRQUEN] Recorded Failures (${report.failures.length}):`, report.failures);
  }
  if (report.unmeasurable_limitations.length > 0) {
    console.info('[ZYRQUEN] Unmeasurable Limitations:', report.unmeasurable_limitations);
  }
  console.groupEnd?.();
}

/**
 * Executes the real Python Native AI Core benchmark suite via the authenticated backend
 * endpoint (`POST /api/developer/benchmark`). Never synthesizes or falls back to mock data.
 */
export async function runNativeCapabilityBenchmark(
  token: string | null | undefined,
  options: RunBenchmarkOptions = {}
): Promise<NativeBenchmarkEvaluation> {
  const res = await apiRequest<BenchmarkApiResponse>('/api/developer/benchmark', {
    method: 'POST',
    token,
    body: {
      modelVersion: options.modelVersion || 'zyrquen-omega-v1',
    },
  });

  if (!res.ok) {
    throw new Error('Native capability benchmark execution did not succeed');
  }

  assertBenchmarkReportIntegrity(res.report);

  const sourceVerification = evaluateSourceVerification(res.report);
  const abstentionAccuracy = evaluateAbstentionAccuracy(res.report);

  const evaluation: NativeBenchmarkEvaluation = {
    executedAt: res.executed_at || new Date().toISOString(),
    report: res.report,
    sourceVerification,
    abstentionAccuracy,
    integrityVerified: true,
  };

  if (options.logToConsole !== false) {
    logBenchmarkReportToConsole(evaluation);
  }

  return evaluation;
}
