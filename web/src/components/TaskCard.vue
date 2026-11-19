<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { api, type AnswerResult, type PointSpec, type TodayTask } from "../api";

const props = defineProps<{ task: TodayTask; autoOpen?: boolean; judging?: boolean }>();
const emit = defineEmits<{
  refresh: [];
  answered: [task: TodayTask];
  submitFailed: [planId: number];
}>();
const cardEl = ref<HTMLElement | null>(null);
const reanswer = ref(false);

const expanded = ref(false);
// autoOpen：从训练路径条目跳转过来时自动展开（并懒加载题目）
watch(
  () => props.autoOpen,
  (v) => {
    if (v && props.task.status === "planned") {
      expanded.value = true;
      void ensureQuestionLoaded();
      requestAnimationFrame(() =>
        cardEl.value?.scrollIntoView({ behavior: "smooth", block: "center" })
      );
    }
  },
  { immediate: true },
);
const question = ref<string | null>(props.task.question);
const questionMeta = ref<{ question_type: string | null; options: { key: string; text: string }[] | null; reference_answer?: string } | null>(null);
const loadingQ = ref(false);
const answer = ref(props.task.answer_text || "");
const selectedKey = ref("");
const skipOpen = ref(false);
const skipReason = ref("");
const isFill = computed(() => {
  const qtype = (questionMeta.value?.question_type ?? props.task.question_type) || "qa";
  return qtype === "fill";
});
const fillSegments = computed(() => (question.value || "").split(/_{3,}/));
const fillBlankCount = computed(() => Math.max(fillSegments.value.length - 1, 0));
const fillBlankValues = ref<string[]>([]);
const submitting = ref(false);
const result = ref<AnswerResult | null>(null);
const showPoints = ref(false);
const pointsLoaded = ref(false);
const savedPoints = ref<PointSpec[]>([]);
const draftPoints = ref<PointSpec[]>([]);
const savingPoints = ref(false);
const explaining = ref(false);
const explanation = ref<{ text: string; source_refs: string[]; attempts_used: number } | null>(null);

const done = computed(() => props.task.status !== "planned");
const isChoice = computed(() => {
  const qtype = (questionMeta.value?.question_type ?? props.task.question_type) || "qa";
  const options = questionMeta.value?.options ?? props.task.options;
  return qtype === "choice" && (options?.length ?? 0) > 0;
});
const optionsList = computed(() => questionMeta.value?.options ?? props.task.options ?? []);
const todayStr = new Date().toISOString().slice(0, 10);
const isFuture = computed(() => !done.value && props.task.due_date > todayStr);
const verdictBadge = computed(() => {
  if (props.task.verdict === "pass") return { cls: "ok", text: "通过" };
  if (props.task.verdict === "fail") return { cls: "warn", text: "未通过" };
  if (done.value) return { cls: "gray", text: props.task.status === "skipped" ? "已跳过" : "已练过" };
  return { cls: "brand", text: "待完成" };
});
const panelCls = computed(() => {
  if (result.value) {
    if (!result.value.graded) return "none";
    return result.value.verdict === "pass" ? "pass" : "fail";
  }
  if (done.value && props.task.verdict) return props.task.verdict === "pass" ? "pass" : "fail";
  return "none";
});

const typeLabel: Record<string, string> = {
  memory: "记忆", comprehension: "理解", application: "应用", analysis: "分析",
};

function toast(msg: string) {
  (window as any).__toast?.(msg);
}

function expand() {
  expanded.value = !expanded.value;
  if (expanded.value) void ensureQuestionLoaded();
}

async function ensureQuestionLoaded() {
  if (question.value || loadingQ.value) return;
  loadingQ.value = true;
  try {
    const res = await api.question(props.task.plan_id);
    question.value = res.question;
    questionMeta.value = { question_type: res.question_type, options: res.options };
    fillBlankValues.value = new Array(fillBlankCount.value).fill("");
    if (res.points) {
      savedPoints.value = res.points;
      pointsLoaded.value = true;
    }
  } catch (e: any) {
    toast(e.message || "出题失败");
  } finally {
    loadingQ.value = false;
  }
}

async function togglePoints() {
  showPoints.value = !showPoints.value;
  if (showPoints.value && !pointsLoaded.value) {
    try {
      const res = await api.question(props.task.plan_id);
      savedPoints.value = res.points || [];
      pointsLoaded.value = true;
    } catch (e: any) {
      toast(e.message || "读取要点失败");
    }
  }
  draftPoints.value = savedPoints.value.map((p) => ({
    text: p.text,
    weight: Number(p.weight) || 1,
    is_required: !!p.is_required,
  }));
  if (showPoints.value && !draftPoints.value.length) {
    draftPoints.value = [{ text: "", weight: 1, is_required: false }];
  }
}

async function savePoints() {
  savingPoints.value = true;
  try {
    const res = await api.editPoints(
      props.task.plan_id,
      draftPoints.value.map((p) => ({ text: p.text, weight: p.weight, is_required: p.is_required }))
    );
    savedPoints.value = res.points;
    showPoints.value = false;
    toast("要点已更新，之后的判分按新要点执行");
  } catch (e: any) {
    toast(e.message || "保存失败");
  } finally {
    savingPoints.value = false;
  }
}

async function submit() {
  let value: string;
  if (isChoice.value) {
    value = selectedKey.value.trim();
    if (!value) {
      toast("请先选择一个选项");
      return;
    }
  } else if (isFill.value) {
    value = fillBlankValues.value.map((v) => v.trim()).join("|");
    if (!value.replace(/\|/g, "").trim()) {
      toast("请把每个空都填上");
      return;
    }
  } else {
    value = answer.value.trim();
    if (!value) {
      toast("先写下你的作答");
      return;
    }
  }
  // 沉浸式：提交瞬间卡片即移入"今天已作答"分组，判分在下方完成（父层按快照渲染）
  emit("answered", { ...props.task, answer_text: value, status: "practiced" as const });
  submitting.value = true;
  try {
    result.value = await api.answer(props.task.plan_id, value);
    reanswer.value = false;
    emit("refresh");
  } catch (e: any) {
    // 判分失败：让父层把卡片放回待完成，并提示
    emit("submitFailed", props.task.plan_id);
    toast(e.message || "提交失败");
  } finally {
    submitting.value = false;
  }
}

async function practiceOnly() {
  try {
    await api.practiceOnly(props.task.plan_id);
    emit("refresh");
    toast("已记录练习");
  } catch (e: any) {
    toast(e.message || "操作失败");
  }
}

async function loadExplanation() {
  if (explaining.value) return;
  explaining.value = true;
  try {
    const res = await api.explanation(props.task.plan_id);
    explanation.value = { text: res.text, source_refs: res.source_refs || [], attempts_used: res.attempts_used };
  } catch (e: any) {
    toast(e.message || "解析失败");
  } finally {
    explaining.value = false;
  }
}

async function skip() {
  if (!skipOpen.value) {
    skipOpen.value = true;
    return;
  }
  const reason = skipReason.value.trim() || "未填写原因";
  try {
    await api.skip(props.task.plan_id, reason);
    skipOpen.value = false;
    emit("refresh");
    toast("已跳过");
  } catch (e: any) {
    toast(e.message || "操作失败");
  }
}
</script>

<template>
  <div ref="cardEl" class="task">
    <div class="task-head" @click="expand">
      <span class="t-title">{{ task.title }}</span>
      <span class="t-meta">
        <span v-if="isFuture" class="badge gray">未到期 · 可提前练</span>
        <span v-if="task.is_overdue" class="badge danger">逾期</span>
        <span class="badge gray">第{{ task.round_index }}轮</span>
        <span v-if="task.item_type" class="badge gray">{{ typeLabel[task.item_type] || task.item_type }}</span>
        <span class="badge" :class="verdictBadge.cls">{{ verdictBadge.text }}</span>
        <span style="color: var(--faint); font-size: 12px;">{{ task.planned_minutes }}′</span>
      </span>
    </div>

    <div v-if="expanded" class="task-body">
      <div v-if="loadingQ" class="loading-center" style="padding: 18px 0;"><span class="spinner"></span></div>
      <template v-else>
        <div v-if="question" class="question-box">{{ question }}</div>

        <div v-if="question && !done" style="margin: 6px 0 2px;">
          <button class="btn text" @click="togglePoints">
            {{ showPoints ? '收起要点' : '要点清单（判分依据，答前可修正）' }}
          </button>
          <div v-if="showPoints" style="margin-top: 8px; display: flex; flex-direction: column; gap: 6px;">
            <div v-for="(p, i) in draftPoints" :key="i" style="display: flex; gap: 6px; align-items: center; flex-wrap: wrap;">
              <input v-model="p.text" class="input" style="flex: 1; min-width: 180px;" :placeholder="'要点 ' + (i + 1)" />
              <input v-model.number="p.weight" class="input" type="number" min="0.5" max="5" step="0.5" style="width: 70px;" title="权重 0.5-5" />
              <label style="font-size: 12px; display: flex; gap: 4px; align-items: center; white-space: nowrap;">
                <input v-model="p.is_required" type="checkbox" />必答
              </label>
              <button class="btn text" @click="draftPoints.splice(i, 1)">删</button>
            </div>
            <div style="display: flex; gap: 8px; align-items: center;">
              <button class="btn ghost" @click="draftPoints.push({ text: '', weight: 1, is_required: false })">加一条</button>
              <button class="btn primary" :disabled="savingPoints" @click="savePoints">
                {{ savingPoints ? '保存中…' : '保存要点' }}
              </button>
            </div>
            <p style="color: var(--faint); font-size: 12px; margin: 0;">首次判分后要点锁定；编辑只影响之后的判分，不改历史作答。</p>
          </div>
        </div>

        <template v-if="!done || reanswer">
          <div v-if="isChoice && optionsList.length" class="question-options">
            <label
              v-for="opt in optionsList"
              :key="opt.key"
              class="option-row"
              :class="{ picked: selectedKey === opt.key }"
            >
              <input type="radio" :name="'q-' + task.plan_id" :value="opt.key" v-model="selectedKey" />
              <span class="opt-key">{{ opt.key }}</span>
              <span>{{ opt.text }}</span>
            </label>
          </div>
          <div v-else-if="isFill && fillSegments.length > 1" class="question-fill">
            <template v-for="(seg, i) in fillSegments" :key="i">
              <span class="fill-seg">{{ seg }}</span>
              <input
                v-if="i < fillSegments.length - 1"
                v-model="fillBlankValues[i]"
                class="fill-input"
                :placeholder="'第 ' + (i + 1) + ' 空'"
              />
            </template>
          </div>
          <textarea v-else v-model="answer" class="textarea" placeholder="凭理解作答，判分口径与测验一致（按要点覆盖判分）"></textarea>
          <div style="display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap;">
            <button class="btn primary" :disabled="submitting" @click="submit">
              {{ submitting ? '判分中…' : isChoice ? '提交选择' : isFill ? '提交填空' : '提交作答' }}
            </button>
            <button v-if="!isChoice" class="btn ghost" @click="practiceOnly">只练不判</button>
            <button class="btn text" @click="skip">跳过</button>
          </div>
          <div v-if="skipOpen" style="display: flex; gap: 8px; margin-top: 8px; align-items: center;">
            <input v-model="skipReason" class="input" style="flex: 1;" placeholder="跳过原因（必填，例如：今天没时间）" />
            <button class="btn ghost" @click="skip">确认跳过</button>
            <button class="btn text" @click="skipOpen = false">取消</button>
          </div>
        </template>

        <div v-if="result || (done && task.verdict)" class="verdict-panel" :class="panelCls">
          <template v-if="result">
            <b>{{ !result.graded ? '暂未判分（LLM 不可用，可自评对照参考答案）' : result.verdict === 'pass' ? '✓ 通过' : '✗ 未通过' }}</b>
            <span v-if="result.score != null" style="margin-left: 8px; font-weight: 600;">得分 {{ (result.score * 100).toFixed(0) }}</span>
            <p style="margin-top: 4px;">{{ result.reason }}</p>
            <p v-if="result.mastered" style="margin-top: 6px;"><span class="badge ok">🎉 连续通过，已达标</span></p>
            <div v-if="task.answer_text" class="ref-answer"><b>我的作答</b>：{{ task.answer_text }}</div>
            <div v-if="result.reference_answer" class="ref-answer"><b>参考答案</b>：{{ result.reference_answer }}</div>
          </template>
          <template v-else>
            <b>{{ task.verdict === 'pass' ? '✓ 通过' : '✗ 未通过' }}</b>
            <div v-if="task.answer_text" class="ref-answer"><b>我的作答</b>：{{ task.answer_text }}</div>
            <div v-if="task.reference_answer" class="ref-answer"><b>参考答案</b>：{{ task.reference_answer }}</div>
          </template>
        </div>
        <div v-else-if="done" class="verdict-panel none">
          <div v-if="judging" style="display: flex; gap: 8px; align-items: center; margin-bottom: 8px;">
            <span class="spinner"></span>
            <b>大模型判分中…结果出来会自动更新</b>
          </div>
          <template v-if="question">
            <div class="question-box">{{ question }}</div>
            <div v-if="task.answer_text" class="ref-answer"><b>我的作答</b>：{{ task.answer_text }}</div>
            <div v-if="questionMeta?.reference_answer" class="ref-answer"><b>参考答案</b>：{{ questionMeta.reference_answer }}</div>
          </template>
          <template v-else>
            该轮次没有存储题目（「只练不判」的记录不会自动出题）
            <div style="margin-top: 8px;">
              <button class="btn ghost" :disabled="loadingQ" @click="ensureQuestionLoaded">
                {{ loadingQ ? '生成中…' : '📝 生成题目查看' }}
              </button>
            </div>
          </template>
          <div v-if="task.status === 'practiced' && !task.verdict && !judging && !reanswer" style="margin-top: 8px;">
            <button class="btn ghost" @click="reanswer = true">✍️ 重新作答并判分</button>
          </div>
        </div>

        <div style="margin-top: 10px;">
          <button class="btn text" :disabled="explaining" @click="loadExplanation">
            {{ explaining ? '解析生成中…' : '🔍 深度解析（对比我的历史作答）' }}
          </button>
        </div>
        <div v-if="explanation" class="verdict-panel none" style="text-align: left;">
          <b>深度解析<span v-if="explanation.attempts_used > 0">（基于最近 {{ explanation.attempts_used }} 次作答）</span></b>
          <p style="margin-top: 6px; white-space: pre-wrap;">{{ explanation.text }}</p>
          <p v-if="explanation.source_refs.length" style="margin-top: 4px; color: var(--faint); font-size: 12px;">
            依据资料：{{ explanation.source_refs.join('；') }}
          </p>
        </div>
      </template>
    </div>
  </div>
</template>
