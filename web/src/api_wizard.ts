// 个人版账户 + 创建向导 API（2026-10-26）
import { request, type Viewer } from "./api";

export type ClarifyDraft = {
  content: string;
  level: string;
  acceptance: unknown;
  field_sources: Record<string, string>;
};

export type PaceInfo = {
  horizon_days: number | null;
  horizon_weeks: number | null;
  session_count: number | null;
  recommended: { horizon_days: number; session_count: number };
  ranges: { horizon_weeks: number[]; session_count: number[] };
};

export type ClarifySession = {
  training_id: number;
  topic: string;
  question: string;
  action: "ask" | "suggest" | "close" | string;
  rounds: number;
  can_confirm: boolean;
  draft: ClarifyDraft;
  pace?: PaceInfo;
  missing_fields: string[];
  history: { role: string; content: string }[];
  notes: string[];
};

export type ProbeItem = {
  index: number;
  knowledge_point: string;
  heading_path: string;
  difficulty: number;
  question: string;
  reference_answer: string;
};

export type ProbePaper = {
  training_id: number;
  items: ProbeItem[];
  total_points: number;
  selected_points: number;
  fallback_used: boolean;
  truncated: boolean;
};

export type GradedItem = {
  knowledge_point: string;
  question: string;
  answer: string;
  state: string | null;
  verdict: string | null;
  reason: string;
};

export type ProbeGrade = {
  training_id: number;
  counts: { mastered: number; edge: number; unreached: number };
  items: GradedItem[];
};

export type PathGenResult = {
  training_id: number;
  stages: number;
  items: number;
};

export const wizardApi = {
  register: (email: string, password: string, displayName: string) =>
    request<{ viewer: Viewer; expires_at: string }>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, display_name: displayName }),
    }),
  login: (email: string, password: string) =>
    request<{ viewer: Viewer; expires_at: string }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  start: (topic: string) =>
    request<ClarifySession>("/api/wizard/start", {
      method: "POST",
      body: JSON.stringify({ topic }),
    }),
  clarifyState: (trainingId: number) =>
    request<ClarifySession>("/api/wizard/" + trainingId + "/clarify"),
  setPace: (trainingId: number, horizonWeeks: number, sessionCount: number) =>
    request<ClarifySession>("/api/wizard/" + trainingId + "/pace", {
      method: "POST",
      body: JSON.stringify({ horizon_weeks: horizonWeeks, session_count: sessionCount }),
    }),
  answer: (trainingId: number, answer: string) =>
    request<ClarifySession>("/api/wizard/" + trainingId + "/answer", {
      method: "POST",
      body: JSON.stringify({ answer }),
    }),
  confirm: (trainingId: number) =>
    request<{ training_id: number; status: string }>("/api/wizard/" + trainingId + "/confirm", {
      method: "POST",
    }),
  addSource: (trainingId: number, body: { type: string; title?: string; content?: string; url?: string }) =>
    request<{ id: number; title: string; type: string; parse_status: string }>(
      "/api/wizard/" + trainingId + "/sources",
      { method: "POST", body: JSON.stringify(body) }
    ),
  uploadSource: (trainingId: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return fetch("/api/wizard/" + trainingId + "/sources/file", {
      method: "POST",
      credentials: "include",
      body: form,
    }).then(async (r) => {
      const data = r.ok ? await r.json() : await r.json().catch(() => ({}));
      if (!r.ok) throw new Error((data as any).detail || "上传失败");
      return data as { id: number; title: string; type: string; parse_status: string };
    });
  },
  generateProbe: (trainingId: number) =>
    request<ProbePaper>("/api/wizard/" + trainingId + "/probe", { method: "POST" }),
  gradeProbe: (trainingId: number, items: ProbeItem[] & { answer?: string }[]) =>
    request<ProbeGrade>("/api/wizard/" + trainingId + "/probe/grade", {
      method: "POST",
      body: JSON.stringify({ answers: [], items }),
    }),
  activate: (trainingId: number) =>
    request<{ training_id: number; status: string }>("/api/wizard/" + trainingId + "/activate", {
      method: "POST",
    }),
  generatePath: (trainingId: number) =>
    request<PathGenResult>("/api/wizard/" + trainingId + "/path", { method: "POST" }),
};
