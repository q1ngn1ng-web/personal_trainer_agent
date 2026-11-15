// API 层：同域 HttpOnly Cookie 会话；401 统一抛出由调用方处理跳转

export type Viewer = {
  user_id: number;
  org_id: number;
  role: "org_admin" | "dept_manager" | "employee";
  department_ids: number[];
  email?: string;
  display_name?: string | null;
};

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init.headers || {}) },
    ...init,
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : {};
  if (!response.ok) {
    throw new ApiError(response.status, data?.detail || "请求失败 " + response.status);
  }
  return data as T;
}

export type TodayTask = {
  plan_id: number;
  training_id: number;
  training_topic: string;
  item_key: string;
  title: string;
  knowledge_point: string | null;
  item_type: string | null;
  round_index: number;
  planned_minutes: number;
  due_date: string;
  is_overdue: boolean;
  question: string | null;
  question_type: string | null;
  options: QuestionOption[] | null;
  reference_answer: string;
  answer_text: string | null;
  verdict: string | null;
  status: "planned" | "practiced" | "skipped";
};

export type PointSpec = {
  point_id?: string;
  text: string;
  weight: number;
  is_required: boolean;
};

export type QuestionOption = { key: string; text: string; is_correct?: boolean };

export type TodayGroup = {
  training_id: number;
  topic: string;
  total: number;
  practiced: number;
  minutes: number;
};

export type TodayResponse = {
  viewer: Viewer | null;
  count: number;
  minutes: number;
  groups: TodayGroup[];
  tasks: TodayTask[];
};

export type DashboardProgress = {
  training_id: number;
  topic: string;
  status: string;
  baseline_score: number;
  baseline_level: string;
  consecutive_days: number;
  days_since_creation: number;
  today_completion: number;
  today_completed: number;
  today_total: number;
  last_active_at: string | null;
  current_week: number;
};

export type DashboardResponse = {
  trainings: DashboardProgress[];
  total_active: number;
  total_all: number;
  avg_baseline: number | null;
};

export type WeeklyMetrics = {
  training_id: number;
  week_start: string;
  week_end: string;
  avg_completion: number;
  avg_recall_success: number;
  three_reflection_coverage: number;
  consecutive_days: number;
  weakest_topic: string | null;
  strongest_topic: string | null;
  missed_tasks: string[];
  days_logged: number;
};

export type CalibrationSuggestionDto = {
  baseline_score_delta: number;
  schedule_adjustment: Record<string, string>;
  material_recommendations: { title?: string; action?: string; [k: string]: unknown }[];
  reward_refresh: string;
  next_week_focus: string;
  raw: Record<string, unknown>;
  fallback_used: boolean;
};

export type WeeklyReviewResponse = {
  metrics: WeeklyMetrics;
  suggestion: CalibrationSuggestionDto;
  applied: boolean;
};

export type TrainingSummary = {
  id: number;
  topic: string;
  status: string;
  org_id: number;
  baseline_score: number;
};

export type PathItem = {
  id: number;
  ordinal: number;
  title: string;
  item_type: string | null;
  difficulty_tier: number | null;
  knowledge_point: string | null;
  status: string;
};

export type PathStage = {
  id: number;
  ordinal: number;
  title: string;
  goal: string | null;
  status: string;
  estimated_minutes: number;
  items: PathItem[];
};

export type PathResponse = {
  path: {
    id: number;
    version: number;
    status: string;
    mode: string;
    horizon_weeks: number | null;
    weekly_frequency: number | null;
    daily_budget_minutes: number | null;
    planned_minutes: number | null;
  } | null;
  stages: PathStage[];
  progress: {
    total_items: number;
    passed_items: number;
    practiced_items: number;
    coverage_done: boolean;
    quiz_passed: boolean;
    mastered: boolean;
    reason: string;
  } | null;
};

export type SourceSummary = {
  id: number;
  type: string;
  title: string;
  scope: string;
  department_id: number | null;
  enabled: number;
  parse_status: string;
  origin_url: string | null;
};

export type AnswerResult = {
  graded: boolean;
  verdict: "pass" | "fail" | null;
  reason: string;
  reference_answer: string;
  question_source?: string;
  mastered: boolean;
  score?: number | null;
};

export type SignalResult = {
  signal_type: string;
  action: string;
  applied: boolean;
  blocked_reason: string;
  message: string;
  objective: string;
};

export type QuizState = {
  pending: boolean;
  plan_id: number | null;
  pool_size: number;
  latest: { id: number; status: string; score: number | null; passed: boolean | null } | null;
};

export type AssessmentStart = {
  assessment_id: number;
  question_count: number;
  items: { item_id: number; ordinal: number; question: string; is_variant: boolean }[];
};

export type ManualItem = {
  item_id: number;
  ordinal: number;
  question: string;
  reference_answer: string;
  user_answer: string;
};

export type AssessmentSubmit =
  | {
      graded_by: "llm";
      needs_manual: false;
      assessment_id: number;
      question_count: number;
      score: number;
      passed: boolean;
      extra_rounds: number;
    }
  | { graded_by: "unavailable"; needs_manual: true; assessment_id: number; items: ManualItem[] };

export type QuizOutcome = {
  graded_by: "llm" | "self";
  needs_manual: false;
  assessment_id: number;
  question_count: number;
  score: number;
  passed: boolean;
  extra_rounds: number;
};

export type MyAssignment = {
  id: number;
  title: string;
  description: string | null;
  due_date: string | null;
  acceptance: string | null;
};

export const api = {
  authMode: () => request<{ auth_enabled: boolean }>("/api/auth/mode"),
  requestCode: (email: string) =>
    request<{ message: string }>("/api/auth/request-code", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),
  verify: (token: string) =>
    request<{ viewer: Viewer; expires_at: string }>("/api/auth/verify", {
      method: "POST",
      body: JSON.stringify({ token }),
    }),
  logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
  me: () => request<Viewer>("/api/me"),
  today: () => request<TodayResponse>("/api/today"),
  question: (planId: number) =>
    request<{
      question: string;
      reference_answer?: string;
      source: string;
      question_type: string | null;
      options: QuestionOption[] | null;
      points?: PointSpec[];
    }>(
      "/api/plan-items/" + planId + "/question",
      { method: "POST" }
    ),
  regeneratePlan: (trainingId: number) =>
    request<{ ok: boolean; count: number; created: number }>(
      "/api/trainings/" + trainingId + "/plan/regenerate",
      { method: "POST" }
    ),
  dashboard: () => request<DashboardResponse>("/api/dashboard"),
  weeklyReview: (trainingId: number) =>
    request<WeeklyReviewResponse>("/api/trainings/" + trainingId + "/review/weekly"),
  applyWeeklyReview: (trainingId: number, suggestion: CalibrationSuggestionDto) =>
    request<WeeklyReviewResponse>("/api/trainings/" + trainingId + "/review/apply", {
      method: "POST",
      body: JSON.stringify({ suggestion }),
    }),
  skipWeeklyReview: (trainingId: number) =>
    request<WeeklyReviewResponse>("/api/trainings/" + trainingId + "/review/skip", {
      method: "POST",
    }),
  planItems: (trainingId: number) =>
    request<{ count: number; items: TodayTask[] }>(
      "/api/trainings/" + trainingId + "/plan-items"
    ),
  answer: (planId: number, answer: string) =>
    request<AnswerResult>("/api/plan-items/" + planId + "/answer", {
      method: "POST",
      body: JSON.stringify({ answer }),
    }),
  practiceOnly: (planId: number) =>
    request<{ ok: boolean }>("/api/plan-items/" + planId + "/practice-only", {
      method: "POST",
    }),
  skip: (planId: number) =>
    request<{ ok: boolean }>("/api/plan-items/" + planId + "/skip", { method: "POST" }),
  editPoints: (planId: number, points: PointSpec[]) =>
    request<{ ok: boolean; points: PointSpec[] }>(
      "/api/plan-items/" + planId + "/points",
      { method: "PATCH", body: JSON.stringify({ points }) }
    ),
  explanation: (planId: number) =>
    request<{
      ok: boolean;
      text: string;
      source_refs: string[];
      attempts_used: number;
      prompt_version?: string;
    }>("/api/plan-items/" + planId + "/explanation", { method: "POST" }),
  signal: (trainingId: number, signalType: string) =>
    request<SignalResult>("/api/signals", {
      method: "POST",
      body: JSON.stringify({ training_id: trainingId, signal_type: signalType }),
    }),
  trainings: () => request<{ trainings: TrainingSummary[] }>("/api/trainings"),
  path: (trainingId: number) => request<PathResponse>("/api/trainings/" + trainingId + "/path"),
  sources: (trainingId: number) =>
    request<{ sources: SourceSummary[] }>("/api/trainings/" + trainingId + "/sources"),
  quizState: (trainingId: number) => request<QuizState>("/api/trainings/" + trainingId + "/quiz"),
  startAssessment: (trainingId: number) =>
    request<AssessmentStart>("/api/assessments", {
      method: "POST",
      body: JSON.stringify({ training_id: trainingId, trigger: "manual" }),
    }),
  submitAssessment: (assessmentId: number, answers: Record<number, string>) =>
    request<AssessmentSubmit>("/api/assessments/" + assessmentId + "/submit", {
      method: "POST",
      body: JSON.stringify({ answers }),
    }),
  manualVerdicts: (assessmentId: number, verdicts: Record<number, string>) =>
    request<QuizOutcome>("/api/assessments/" + assessmentId + "/manual", {
      method: "POST",
      body: JSON.stringify({ verdicts }),
    }),
  myAssignments: () => request<{ pending: MyAssignment[] }>("/api/assignments/mine"),
  acceptAssignment: (id: number) =>
    request<{ assignment_id: number; training_id: number }>("/api/assignments/" + id + "/accept", {
      method: "POST",
    }),
};
