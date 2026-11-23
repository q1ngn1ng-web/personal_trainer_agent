// API 层：同域 HttpOnly Cookie 会话；401 统一抛出由调用方处理跳转

export type Viewer = {
  user_id: number;
  org_id: number | null; // member-invite：null = 个人模式（无组织成员资格）
  role: "org_admin" | "admin" | "member";
  department_ids: number[];
  email?: string;
  display_name?: string | null;
};

// share-gate：门禁清单条目
export type BlockedSource = {
  source_id: number;
  title: string;
  visibility: string;
  uncovered_targets?: boolean;
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
  let data: any = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      // 非 JSON 响应体（如 500 的 "Internal Server Error" 纯文本）：给出可读错误而非解析崩溃
      throw new ApiError(response.status, text.slice(0, 200) || "非 JSON 响应 " + response.status);
    }
  }
  if (!response.ok) {
    const detail = data?.detail;
    const message =
      typeof detail === "string" ? detail : (detail?.message ?? "请求失败 " + response.status);
    throw Object.assign(new ApiError(response.status, message), { detail });
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
  judging?: boolean;
  // 训练路径场次视图（plan-items 端点附带）：最近一次判分得分（0-1）与掌握度（0-1）
  last_score?: number | null;
  mastery?: number | null;
  difficulty_tier?: number | null;
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
  done: TodayTask[];
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
  item_count?: number;
  knowledge_points_total?: number;
  knowledge_points_covered?: number;
  knowledge_points?: { name: string; covered: boolean }[];
};

export type DashboardResponse = {
  trainings: DashboardProgress[];
  total_active: number;
  total_all: number;
  avg_baseline: number | null;
  activity: { date: string; count: number }[];
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
  owner_user_id?: number | null;
  schedule_mode?: string;
  baseline_score: number;
  next_due?: string | null;
  final_due?: string | null;
};

export type PathItem = {
  id: number;
  item_key?: string;
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
  chunk_count?: number | null;
  parse_error?: string | null;
  origin_url: string | null;
  owner_user_id?: number | null;
};

export type AnswerResult = {
  graded: boolean;
  verdict: "pass" | "fail" | null;
  reason: string;
  reference_answer: string;
  question_source?: string;
  mastered: boolean;
  score?: number | null;
  failure_streak?: number;
  coach_hint?: string;
};

export type SessionSummary = {
  training_id: number;
  date: string;
  question_count: number;
  item_count: number;
  pass_rate: number | null;
  mistake_points: { point: string; count: number }[];
  weakest_knowledge_point: { knowledge_point: string; fail_count: number } | null;
  items: {
    item_key: string;
    knowledge_point: string;
    attempts: number;
    fails: number;
    failure_streak: number;
    scores: (number | null)[];
  }[];
  narrative: string;
  llm_narrative_enabled: boolean;
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
  createShareLink: (
    trainingId: number,
    body?: { open_level?: "org" | "anyone"; confirm_source_ids?: number[] }
  ) =>
    request<{
      token: string;
      created: boolean;
      url: string;
      open_level?: string;
      upgraded?: { source_id: number; title: string }[];
    }>(
      "/api/trainings/" + trainingId + "/share/link",
      { method: "POST", body: body ? JSON.stringify(body) : undefined }
    ),
  shareGate: (trainingId: number, action: string, openLevel?: string) =>
    request<{ ready: boolean; blocked: BlockedSource[]; action: string; audience: string }>(
      "/api/trainings/" + trainingId + "/share/gate",
      { method: "POST", body: JSON.stringify({ action, open_level: openLevel }) }
    ),
  sharePreview: (token: string) =>
    request<{
      training_id: number;
      topic: string;
      org_id: number;
      stages: { ordinal: number; title: string; goal: string | null; estimated_minutes: number; status: string; items: { title: string; knowledge_point: string | null; item_type: string | null }[] }[];
      acceptance: unknown;
      keywords: string[];
    }>("/api/share/" + token),
  pullShare: (token: string) =>
    request<{ training_id: number; created: boolean }>("/api/share/" + token + "/pull", {
      method: "POST",
    }),
  regeneratePlan: (trainingId: number) =>
    request<{ ok: boolean; count: number; created: number }>(
      "/api/trainings/" + trainingId + "/plan/regenerate",
      { method: "POST" }
    ),
  createOrg: (name: string) =>
    request<{ org_id: number; name: string; role: string }>("/api/org/create", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  listCandidates: (orgId: number, q = "") =>
    request<{ candidates: { user_id: number; email: string; display_name: string | null }[] }>(
      "/api/org/" + orgId + "/candidates?q=" + encodeURIComponent(q)
    ),
  inviteMember: (orgId: number, email: string) =>
    request<{ membership: { status: string }; email: string }>("/api/org/" + orgId + "/invite", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),
  removeMember: (orgId: number, userId: number) =>
    request<{ removed: number; status: string }>(
      "/api/org/" + orgId + "/members/" + userId,
      { method: "DELETE" }
    ),
  setMemberRole: (
    orgId: number,
    userId: number,
    body: { role: string; admin_quota?: number; admin_can_remove?: boolean }
  ) =>
    request<{ role: string; admin_quota: number | null }>(
      "/api/org/" + orgId + "/members/" + userId + "/role",
      { method: "PUT", body: JSON.stringify(body) }
    ),
  orgMembers: (departmentId?: number) =>
    request<{
      members: {
        user_id: number;
        email: string;
        display_name: string | null;
        role: string;
        status: string;
      }[];
    }>("/api/org/members" + (departmentId ? "?department_id=" + departmentId : "")),
  myInvites: () =>
    request<{
      invites: {
        membership_id: number;
        org_id: number;
        org_name: string;
        inviter_name: string | null;
      }[];
    }>("/api/my/invites"),
  acceptInvite: (membershipId: number) =>
    request<{ org_id: number; role: string; status: string }>(
      "/api/my/invites/" + membershipId + "/accept",
      { method: "POST" }
    ),
  memberProgress: (orgId: number, userId: number) =>
    request<{
      display_name: string;
      trainings: { training_id: number; topic: string; status: string; completion: number | null }[];
      avg_quiz_score: number | null;
      passed_quiz_count: number;
    }>("/api/org/" + orgId + "/members/" + userId + "/progress"),
  sourcesOverview: () =>
    request<{
      sources: {
        checksum: string | null;
        title: string;
        type: string;
        parse_status: string;
        enabled: boolean;
        chunk_total: number;
        reference_count: number;
        trainings: { training_id: number; topic: string }[];
      }[];
    }>("/api/sources/overview"),
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
  skip: (planId: number, reason: string) =>
    request<{ ok: boolean }>("/api/plan-items/" + planId + "/skip", {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  pregenerateQuestions: (trainingId: number) =>
    request<{ generated: number; total: number; skipped?: string }>(
      "/api/trainings/" + trainingId + "/questions/pregenerate",
      { method: "POST" }
    ),
  deleteTraining: (trainingId: number) =>
    request<{ ok: boolean }>("/api/trainings/" + trainingId, { method: "DELETE" }),
  archiveTraining: (trainingId: number) =>
    request<{ ok: boolean; status: string }>("/api/trainings/" + trainingId + "/archive", {
      method: "POST",
    }),
  questionsOverview: (trainingId: number) =>
    request<{
      count: number;
      questions: {
        item_key: string;
        knowledge_point: string | null;
        question_type: string;
        question_text: string | null;
        practiced_count: number;
        status: string | null;
        in_cooldown: boolean;
      }[];
    }>("/api/trainings/" + trainingId + "/questions"),
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
    request<{
      training_visibility: string;
      training_shared_user_ids: number[];
      sources: SourceSummary[];
    }>("/api/trainings/" + trainingId + "/sources"),
  sessionSummary: (trainingId: number, date?: string) =>
    request<SessionSummary>("/api/trainings/" + trainingId + "/session-summary" + (date ? "?date=" + date : "")),
  getPreferences: () => request<{ preferences: Record<string, string> }>("/api/preferences"),
  putPreferences: (values: Record<string, string>) =>
    request<{ ok: boolean; preferences: Record<string, string> }>("/api/preferences", {
      method: "PUT",
      body: JSON.stringify({ values }),
    }),
  setVisibility: (
    trainingId: number,
    body: { visibility: string; shared_emails?: string[]; confirm_source_ids?: number[] }
  ) =>
    request<{ ok: boolean; visibility: string; shared_user_ids: number[] }>(
      "/api/trainings/" + trainingId + "/visibility",
      { method: "PUT", body: JSON.stringify(body) }
    ),
  setSourceVisibility: (
    trainingId: number,
    sourceId: number,
    body: { visibility: string; shared_emails?: string[] }
  ) =>
    request<{ ok: boolean; visibility: string }>(
      "/api/trainings/" + trainingId + "/sources/" + sourceId + "/visibility",
      { method: "PUT", body: JSON.stringify(body) }
    ),
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
