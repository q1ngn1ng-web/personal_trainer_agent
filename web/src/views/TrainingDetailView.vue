<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import {
  api, type AssessmentStart, type AssessmentSubmit, type PathResponse,
  type WeeklyReviewResponse,
  type QuizOutcome, type QuizState, type SourceSummary, type TodayTask, type TrainingSummary,
} from "../api";
import { authState } from "../auth";
import TaskCard from "../components/TaskCard.vue";

const route = useRoute();
const trainingId = Number(route.params.id);

const section = ref<"path" | "plan" | "review" | "sources" | "quiz">("path");
const training = ref<TrainingSummary | null>(null);
const pathData = ref<PathResponse | null>(null);
const sources = ref<SourceSummary[]>([]);

// 可见性（change content-visibility 三档）：训练级 + 每条资料，指定人按邮箱输入
const isOwner = computed(
  () => !!authState.viewer?.user_id && training.value?.owner_user_id === authState.viewer.user_id
);
const trainingVisibility = ref("private");
const trainingVisEmails = ref("");
const sourceVisibility = ref<Record<number, string>>({});
const sourceVisEmails = ref<Record<number, string>>({});
const savingVisibility = ref(false);

const visibilityOptions = [
  { value: "private", label: "私有" },
  { value: "specific", label: "指定人" },
  { value: "public", label: "组织公开" },
];

function splitEmails(raw: string): string[] {
  return raw.split(/[,，\s]+/).map((s) => s.trim()).filter(Boolean);
}

async function saveTrainingVisibility() {
  savingVisibility.value = true;
  try {
    await api.setVisibility(trainingId, {
      visibility: trainingVisibility.value,
      shared_emails: trainingVisibility.value === "specific" ? splitEmails(trainingVisEmails.value) : [],
    });
    toast("可见性已更新");
    const ss = await api.sources(trainingId);
    trainingVisibility.value = ss.training_visibility;
  } catch (e: any) {
    toast(e.message || "保存失败");
  } finally {
    savingVisibility.value = false;
  }
}

async function saveSourceVisibility(sourceId: number) {
  const visibility = sourceVisibility.value[sourceId] || "private";
  try {
    await api.setSourceVisibility(trainingId, sourceId, {
      visibility,
      shared_emails: visibility === "specific" ? splitEmails(sourceVisEmails.value[sourceId] || "") : [],
    });
    toast("资料可见性已更新");
    const ss = await api.sources(trainingId);
    sources.value = ss.sources;
    syncSourceVisibilityState();
  } catch (e: any) {
    toast(e.message || "保存失败");
  }
}

function syncSourceVisibilityState() {
  const next: Record<number, string> = {};
  for (const s of sources.value) next[s.id] = s.scope || "private";
  sourceVisibility.value = next;
}
const quiz = ref<QuizState | null>(null);
const planRounds = ref<TodayTask[]>([]);
const planLoading = ref(false);
const regenerating = ref(false);
const loading = ref(true);

// 测验流程状态
const assessment = ref<AssessmentStart | null>(null);
const answers = ref<Record<number, string>>({});
const submitting = ref(false);
const starting = ref(false);
const manualItems = ref<AssessmentSubmit | null>(null);
const manualVerdicts = ref<Record<number, string>>({});
const outcome = ref<QuizOutcome | null>(null);
const openStages = ref<Set<number>>(new Set());
const openPlanId = ref<number | null>(null);
const reviewData = ref<WeeklyReviewResponse | null>(null);
const reviewLoading = ref(false);

async function prepareReview() {
  reviewLoading.value = true;
  try {
    reviewData.value = await api.weeklyReview(trainingId);
  } catch (e: any) {
    toast(e.message || "生成失败");
  } finally {
    reviewLoading.value = false;
  }
}

async function applyReview() {
  if (!reviewData.value) return;
  try {
    reviewData.value = await api.applyWeeklyReview(trainingId, reviewData.value.suggestion);
    toast("已应用并归档");
  } catch (e: any) {
    toast(e.message || "应用失败");
  }
}

async function skipReview() {
  if (!reviewData.value) return;
  try {
    reviewData.value = await api.skipWeeklyReview(trainingId);
    toast("已跳过并归档");
  } catch (e: any) {
    toast(e.message || "操作失败");
  }
}

// 从训练路径条目跳转到完整计划，并自动展开该训练项最早的未完成轮次
function openItemInPlan(itemKey: string) {
  section.value = "plan";
  const first =
    planRounds.value.find((r) => r.item_key === itemKey && r.status === "planned") ||
    planRounds.value.find((r) => r.item_key === itemKey);
  openPlanId.value = first?.plan_id ?? null;
}

function toast(msg: string) {
  (window as any).__toast?.(msg);
}

async function regeneratePlan() {
  regenerating.value = true;
  try {
    const res = await api.regeneratePlan(trainingId);
    toast("已补齐，当前 " + res.count + " 轮");
    await loadPlan();
  } catch (e: any) {
    toast(e.message || "操作失败");
  } finally {
    regenerating.value = false;
  }
}

async function loadPlan() {
  planLoading.value = true;
  try {
    const res = await api.planItems(trainingId);
    planRounds.value = res.items;
  } catch (e: any) {
    toast(e.message || "计划加载失败");
  } finally {
    planLoading.value = false;
  }
}

const shareUrl = ref("");
const sharing = ref(false);
async function createShare() {
  sharing.value = true;
  try {
    const res = await api.createShareLink(trainingId);
    shareUrl.value = location.origin + res.url;
    await navigator.clipboard.writeText(shareUrl.value);
    toast("分享链接已复制，发给组织内成员即可");
  } catch (e: any) {
    toast(e.message || "分享失败");
  } finally {
    sharing.value = false;
  }
}

async function load() {
  loading.value = true;
  try {
    const [ts, pd, ss, qs] = await Promise.all([
      api.trainings(),
      api.path(trainingId),
      api.sources(trainingId),
      api.quizState(trainingId),
    ]);
    training.value = ts.trainings.find((t) => t.id === trainingId) || null;
    pathData.value = pd;
    sources.value = ss.sources;
    trainingVisibility.value = ss.training_visibility || "private";
    syncSourceVisibilityState();
    quiz.value = qs;
    if (pd.stages.length) openStages.value = new Set([pd.stages[0].id]);
  } catch (e: any) {
    toast(e.message || "加载失败");
  } finally {
    loading.value = false;
  }
  await loadPlan();
}
onMounted(load);

const progressPct = computed(() => {
  const p = pathData.value?.progress;
  if (!p || !p.total_items) return 0;
  return Math.round((p.passed_items / p.total_items) * 100);
});

function toggleStage(id: number) {
  const next = new Set(openStages.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  openStages.value = next;
}

async function startQuiz() {
  starting.value = true;
  outcome.value = null;
  manualItems.value = null;
  try {
    assessment.value = await api.startAssessment(trainingId);
    answers.value = {};
  } catch (e: any) {
    toast(e.message || "生成测验失败");
  } finally {
    starting.value = false;
  }
}

async function submitQuiz() {
  if (!assessment.value) return;
  const filled = Object.values(answers.value).filter((v) => v && v.trim()).length;
  if (filled < assessment.value.question_count) {
    toast("还有 " + (assessment.value.question_count - filled) + " 题未作答");
    return;
  }
  submitting.value = true;
  try {
    const res = await api.submitAssessment(assessment.value.assessment_id, answers.value);
    if (res.needs_manual) {
      manualItems.value = res;
      toast("AI 判分暂不可用，请自评");
    } else {
      outcome.value = res as QuizOutcome;
      await load();
    }
  } catch (e: any) {
    toast(e.message || "提交失败");
  } finally {
    submitting.value = false;
  }
}

async function submitManual() {
  if (!manualItems.value) return;
  try {
    outcome.value = await api.manualVerdicts(
      manualItems.value.assessment_id,
      manualVerdicts.value
    );
    manualItems.value = null;
    assessment.value = null;
    await load();
  } catch (e: any) {
    toast(e.message || "提交失败");
  }
}

const itemStatus: Record<string, { ico: string; cls: string }> = {
  planned: { ico: "○", cls: "gray" },
  practiced: { ico: "◔", cls: "info" },
  passed: { ico: "✓", cls: "ok" },
  skipped: { ico: "–", cls: "gray" },
};
const typeLabel: Record<string, string> = {
  memory: "记忆", comprehension: "理解", application: "应用", analysis: "分析",
};
</script>


<template>
  <div>
    <div class="page-head">
      <h1 class="page-title">{{ training ? training.topic : '训练详情' }}</h1>
      <p class="page-sub" v-if="pathData && pathData.path">
        路径 v{{ pathData.path.version }} · {{ pathData.path.horizon_weeks || '-' }} 周 ·
        每周 {{ pathData.path.weekly_frequency || '-' }} 次 · 每次 {{ pathData.path.daily_budget_minutes || '-' }} 分钟
      </p>
    </div>

    <div v-if="loading" class="loading-center"><span class="spinner"></span></div>

    <template v-else>
      <div class="section-switch">
        <button :class="{ active: section === 'path' }" @click="section = 'path'">训练路径</button>
        <button :class="{ active: section === 'plan' }" @click="section = 'plan'">完整计划</button>
        <button :class="{ active: section === 'review' }" @click="section = 'review'">周复盘</button>
        <button :class="{ active: section === 'sources' }" @click="section = 'sources'">资料来源</button>
        <button :class="{ active: section === 'quiz' }" @click="section = 'quiz'">测验达标</button>
      </div>

      <div class="section-content">

      <!-- ============ 完整计划（含提前练） ============ -->
      <template v-if="section === 'plan'">
        <div class="card">
          <div class="card-head">
            <div class="card-title">训练计划（全部轮次）</div>
            <span class="badge gray">{{ planRounds.length }} 项</span>
            <button class="btn sm ghost" :disabled="regenerating" @click="regeneratePlan">
              {{ regenerating ? '补齐中…' : '补齐缺失轮次' }}
            </button>
          </div>
          <p style="font-size: 13px; color: var(--muted); margin-top: 6px;">
            按到期日排序。未到期的轮次也可以提前练——展开即可作答。
          </p>
        </div>
        <div v-if="planLoading" class="loading-center" style="padding: 18px 0;"><span class="spinner"></span></div>
        <div v-else-if="!planRounds.length" class="card" style="color: var(--muted);">还没有训练轮次——完成向导后这里会显示五轮计划。</div>
        <div v-else>
          <div v-for="round in planRounds" :key="round.plan_id">
            <TaskCard :task="round" @refresh="loadPlan" />
          </div>
        </div>

        <div v-if="questionList.length" class="card" style="margin-top: 14px;">
          <div class="card-head">
            <div class="card-title">题库总览（{{ questionList.length }} 题）</div>
            <span class="badge gray">不含参考答案</span>
          </div>
          <div v-for="q in questionList" :key="q.item_key + q.question_text" class="list-item">
            <span class="badge" :class="q.in_cooldown ? 'gray' : 'ok'">{{ q.in_cooldown ? '冷却中' : '可用' }}</span>
            <div style="flex: 1; min-width: 0;">
              <div style="font-size: 13.5px;">{{ q.question_text || "（题目未生成）" }}</div>
              <div style="font-size: 12px; color: var(--faint);">
                {{ q.knowledge_point || "未分类" }} · {{ q.question_type }} · 练过 {{ q.practiced_count }} 次
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- ============ 路径 ============ -->
      <template v-if="section === 'path'">
        <div v-if="pathData && pathData.progress" class="card">
          <div class="card-head">
            <div class="card-title">整体进度</div>
            <span v-if="pathData.progress.mastered" class="badge ok">🏆 已达标</span>
            <span v-else-if="pathData.progress.quiz_passed" class="badge brand">测验已过 · 补齐剩余项</span>
            <span v-else class="badge gray">进行中</span>
          </div>
          <div class="progress" style="margin: 10px 0 8px;"><i :style="{ width: progressPct + '%' }"></i></div>
          <div style="display: flex; gap: 16px; color: var(--muted); font-size: 13px; flex-wrap: wrap;">
            <span>要点通过 {{ pathData.progress.passed_items }}/{{ pathData.progress.total_items }}</span>
            <span>已练 {{ pathData.progress.practiced_items }}</span>
            <span>覆盖 {{ pathData.progress.coverage_done ? '完成' : '未完成' }}</span>
          </div>
          <p v-if="pathData.progress.reason" style="font-size: 13px; color: var(--faint); margin-top: 8px;">
            {{ pathData.progress.reason }}
          </p>
        </div>

        <div v-if="pathData && pathData.stages.length">
          <div v-for="st in pathData.stages" :key="st.id" class="card stage" style="padding: 0; overflow: hidden;">
            <div class="stage-head" style="padding: 13px 20px 6px;" @click="toggleStage(st.id)">
              <span class="badge gray">阶段 {{ st.ordinal }}</span>
              <div style="flex: 1; min-width: 0;">
                <div style="font-weight: 600;">{{ st.title }}</div>
                <div v-if="st.goal" style="font-size: 12.5px; color: var(--muted);">{{ st.goal }}</div>
              </div>
              <span style="color: var(--faint); font-size: 12.5px;">{{ st.estimated_minutes }}′ · {{ st.items.length }} 项</span>
              <span style="color: var(--faint);">{{ openStages.has(st.id) ? '▾' : '▸' }}</span>
            </div>
            <div v-if="openStages.has(st.id)" style="padding: 0 20px 14px;">
              <div v-for="it in st.items" :key="it.id" class="list-item" @click="openItemInPlan(it.item_key)">
                <span :style="{ color: 'var(--' + ((itemStatus[it.status] || itemStatus.planned).cls === 'ok' ? 'ok' : (itemStatus[it.status] || itemStatus.planned).cls === 'info' ? 'info' : 'faint') + ')' }">
                  {{ (itemStatus[it.status] || itemStatus.planned).ico }}
                </span>
                <div style="flex: 1; min-width: 0;">
                  <div style="font-size: 14px;">{{ it.title }}</div>
                  <div v-if="it.knowledge_point" style="font-size: 12px; color: var(--faint);">{{ it.knowledge_point }}</div>
                </div>
                <span v-if="it.item_type" class="badge gray">{{ typeLabel[it.item_type] || it.item_type }}</span>
                <span v-if="it.difficulty_tier" class="badge gray">难度 {{ it.difficulty_tier }}</span>
                <span class="badge brand">去练习 →</span>
              </div>
            </div>
          </div>
        </div>
        <div v-else class="card empty"><span class="ico">🧭</span>路径尚未生成</div>
      </template>

      <!-- ============ 周复盘 ============ -->
      <template v-else-if="section === 'review'">
        <div class="card">
          <div class="card-head">
            <div class="card-title">周复盘</div>
            <span v-if="reviewData?.applied" class="badge ok">已应用</span>
            <span v-else-if="reviewData" class="badge gray">未应用</span>
          </div>
          <p style="font-size: 13px; color: var(--muted); margin-top: 6px;">
            汇总最近 7 天的完成度、坚持与薄弱主题，由模型给出基线/排期/资料/奖励的调整建议；可应用或跳过（都会归档）。
          </p>
          <div v-if="reviewLoading" class="loading-center" style="padding: 14px 0;"><span class="spinner"></span></div>
          <div v-else-if="!reviewData" style="margin-top: 10px;">
            <button class="btn primary" @click="prepareReview">生成周复盘</button>
          </div>
          <template v-else>
            <div class="dash-row-metrics" style="margin-top: 10px;">
              <span>本周完成度 <b>{{ (reviewData.metrics.avg_completion * 100).toFixed(0) }}%</b></span>
              <span>坚持 <b>{{ reviewData.metrics.consecutive_days }}</b> 天</span>
              <span>记录 <b>{{ reviewData.metrics.days_logged }}</b>/7 天</span>
            </div>
            <div class="dash-row-metrics" style="margin-top: 6px;">
              <span v-if="reviewData.metrics.weakest_topic">最弱主题：<b>{{ reviewData.metrics.weakest_topic }}</b></span>
              <span v-if="reviewData.metrics.strongest_topic">最强主题：<b>{{ reviewData.metrics.strongest_topic }}</b></span>
            </div>
            <div v-if="reviewData.metrics.missed_tasks.length" class="ref-answer" style="margin-top: 6px;">
              遗漏任务：{{ reviewData.metrics.missed_tasks.join("；") }}
            </div>
            <div class="verdict-panel" :class="reviewData.suggestion.fallback_used ? 'none' : 'pass'" style="margin-top: 12px; text-align: left;">
              <b>校准建议{{ reviewData.suggestion.fallback_used ? "（模型不可用，启发式兜底）" : "" }}</b>
              <p style="margin-top: 6px;"><b>下周重点</b>：{{ reviewData.suggestion.next_week_focus || "—" }}</p>
              <p><b>基线调整</b>：{{ reviewData.suggestion.baseline_score_delta >= 0 ? "+" : "" }}{{ (reviewData.suggestion.baseline_score_delta * 100).toFixed(0) }} 分</p>
              <p><b>奖励刷新</b>：{{ reviewData.suggestion.reward_refresh || "—" }}</p>
              <div v-if="Object.keys(reviewData.suggestion.schedule_adjustment).length" style="margin-top: 6px;">
                <b>排期调整</b>：
                <div v-for="(v, k) in reviewData.suggestion.schedule_adjustment" :key="k">· {{ k }}：{{ v }}</div>
              </div>
              <div v-if="reviewData.suggestion.material_recommendations.length" style="margin-top: 6px;">
                <b>资料建议</b>：
                <div v-for="(m, i) in reviewData.suggestion.material_recommendations" :key="i">· {{ m.title || m.action || JSON.stringify(m) }}</div>
              </div>
            </div>
            <div style="display: flex; gap: 8px; margin-top: 10px;">
              <button class="btn primary" @click="applyReview">应用建议</button>
              <button class="btn ghost" @click="skipReview">跳过本周</button>
            </div>
          </template>
        </div>
      </template>

      <!-- ============ 资料 ============ -->
      <template v-else-if="section === 'sources'">
        <div v-if="isOwner" class="card">
          <div class="card-head" style="margin-bottom: 8px;">
            <div class="card-title">训练可见性</div>
            <span class="badge gray">{{ visibilityOptions.find((v) => v.value === trainingVisibility)?.label || trainingVisibility }}</span>
          </div>
          <div style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center;">
            <select v-model="trainingVisibility" class="input" style="width: auto; padding: 6px 10px;">
              <option v-for="v in visibilityOptions" :key="v.value" :value="v.value">{{ v.label }}</option>
            </select>
            <input
              v-if="trainingVisibility === 'specific'"
              v-model="trainingVisEmails"
              class="input"
              style="flex: 1; min-width: 220px; padding: 6px 10px;"
              placeholder="指定成员邮箱（多个用逗号分隔）"
            />
            <button class="btn" :disabled="savingVisibility" @click="saveTrainingVisibility">保存</button>
          </div>
          <div style="font-size: 12px; color: var(--faint); margin-top: 6px;">
            私有仅自己可见 · 指定人按邮箱授权 · 组织公开对同组织成员可见
          </div>
        </div>

        <div v-if="!sources.length" class="card empty"><span class="ico">📚</span>暂无资料来源</div>
        <div v-for="s in sources" :key="s.id" class="card">
          <div class="card-head" style="margin-bottom: 6px;">
            <div class="card-title" style="min-width: 0;">
              {{ s.type === 'url' ? '🔗' : s.type === 'file' ? '📄' : '📝' }} {{ s.title }}
            </div>
            <span class="badge" :class="s.enabled ? 'ok' : 'gray'">{{ s.enabled ? '启用' : '停用' }}</span>
          </div>
          <div style="display: flex; gap: 12px; color: var(--muted); font-size: 12.5px; flex-wrap: wrap;">
            <span>类型 {{ s.type }}</span>
            <span>解析 {{ s.parse_status }}</span>
            <span v-if="s.origin_url" style="max-width: 60vw; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
              {{ s.origin_url }}
            </span>
          </div>
          <div v-if="isOwner" style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-top: 10px;">
            <select v-model="sourceVisibility[s.id]" class="input" style="width: auto; padding: 5px 9px; font-size: 13px;">
              <option v-for="v in visibilityOptions" :key="v.value" :value="v.value">{{ v.label }}</option>
            </select>
            <input
              v-if="sourceVisibility[s.id] === 'specific'"
              v-model="sourceVisEmails[s.id]"
              class="input"
              style="flex: 1; min-width: 200px; padding: 5px 9px; font-size: 13px;"
              placeholder="指定成员邮箱（多个用逗号分隔）"
            />
            <button class="btn" style="padding: 5px 12px; font-size: 13px;" @click="saveSourceVisibility(s.id)">保存</button>
          </div>
        </div>
      </template>

      <!-- ============ 测验 ============ -->
      <template v-else>
        <!-- 结果页 -->
        <div v-if="outcome" class="card">
          <div class="card-head">
            <div class="card-title">测验结果</div>
            <span class="badge" :class="outcome.passed ? 'ok' : 'warn'">
              {{ outcome.passed ? '达标' : '未达标' }}
            </span>
          </div>
          <div class="stat-row">
            <div class="stat"><div class="num">{{ (outcome.score * 100).toFixed(0) }}</div><div class="lbl">得分</div></div>
            <div class="stat"><div class="num">{{ outcome.question_count }}</div><div class="lbl">题目数</div></div>
            <div class="stat"><div class="num">{{ outcome.extra_rounds }}</div><div class="lbl">追加轮次</div></div>
          </div>
          <p style="font-size: 13px; color: var(--muted);">判分方式：{{ outcome.graded_by === 'llm' ? 'AI 要点判分' : '自评' }}</p>
          <button class="btn ghost sm" @click="outcome = null; assessment = null">再来一次</button>
        </div>

        <!-- 答题中 -->
        <div v-else-if="assessment" class="card">
          <div class="card-head">
            <div class="card-title">测验 · 共 {{ assessment.question_count }} 题</div>
            <span class="badge brand">AI 判分</span>
          </div>
          <div v-for="q in assessment.items" :key="q.item_id" style="margin-bottom: 16px;">
            <div class="question-box" style="margin-bottom: 8px;">
              <span style="color: var(--faint); font-size: 12.5px;">第 {{ q.ordinal }} 题</span>
              <span v-if="q.is_variant" class="badge info" style="margin-left: 6px;">变式题</span>
              <div style="margin-top: 4px;">{{ q.question }}</div>
            </div>
            <textarea v-model="answers[q.item_id]" class="textarea" placeholder="作答…"></textarea>
          </div>
          <button class="btn primary block" :disabled="submitting" @click="submitQuiz">
            {{ submitting ? 'AI 判分中…' : '提交测验' }}
          </button>
        </div>

                <!-- 自评兜底 -->
        <div v-else-if="manualItems && manualItems.needs_manual" class="card">
          <div class="card-head">
            <div class="card-title">AI 判分暂不可用 · 请自评</div>
          </div>
          <div v-for="it in manualItems.items" :key="it.item_id" style="margin-bottom: 14px; padding-bottom: 12px; border-bottom: 1px dashed var(--line);">
            <div style="font-weight: 600; margin-bottom: 4px;">{{ it.ordinal }}. {{ it.question }}</div>
            <div style="font-size: 13.5px; color: var(--muted);">你的作答：{{ it.user_answer || '（未作答）' }}</div>
            <div class="ref-answer"><b>参考答案</b>：{{ it.reference_answer }}</div>
            <div style="display: flex; gap: 8px; margin-top: 8px;">
              <button class="btn sm ghost" @click="manualVerdicts[it.item_id] = 'pass'">✓ 我答对了</button>
              <button class="btn sm ghost" @click="manualVerdicts[it.item_id] = 'fail'">✗ 没答好</button>
              <span v-if="manualVerdicts[it.item_id]" class="badge" :class="manualVerdicts[it.item_id] === 'pass' ? 'ok' : 'warn'">
                已选：{{ manualVerdicts[it.item_id] === 'pass' ? '对' : '错' }}
              </span>
            </div>
          </div>
          <button class="btn primary block" @click="submitManual">提交自评结果</button>
        </div>

        <!-- 状态页 -->
        <div v-else-if="quiz" class="card">
          <div class="card-head">
            <div class="card-title">测验达标</div>
            <span v-if="quiz.latest" class="badge" :class="quiz.latest.passed ? 'ok' : 'warn'">
              上次 {{ (quiz.latest.score != null ? (quiz.latest.score * 100).toFixed(0) + ' 分 · ' : '') + (quiz.latest.passed ? '达标' : '未达标') }}
            </span>
          </div>
          <p style="color: var(--muted); font-size: 14px; margin-bottom: 14px;">
            从题库（冷却期外）抽题组卷，AI 按要点逐条判分，规则层算总分；
            得分 ≥ 80 且无必答要点缺失即达标。当前可用题库 {{ quiz.pool_size }} 题。
          </p>
          <button class="btn primary" :disabled="starting || quiz.pool_size === 0" @click="startQuiz">
            {{ starting ? '组卷中…' : quiz.pool_size === 0 ? '题库不足（先完成训练）' : '开始测验' }}
          </button>
        </div>
      </template>
      </div>
    </template>
  </div>
</template>
