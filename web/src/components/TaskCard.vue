<script setup lang="ts">
import { computed, ref } from "vue";
import { api, type AnswerResult, type TodayTask } from "../api";

const props = defineProps<{ task: TodayTask }>();
const emit = defineEmits<{ refresh: [] }>();

const expanded = ref(false);
const question = ref<string | null>(props.task.question);
const questionMeta = ref<{ question_type: string | null; options: { key: string; text: string }[] | null } | null>(null);
const loadingQ = ref(false);
const answer = ref(props.task.answer_text || "");
const selectedKey = ref("");
const submitting = ref(false);
const result = ref<AnswerResult | null>(null);
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

async function expand() {
  expanded.value = !expanded.value;
  if (expanded.value && !question.value && !loadingQ.value) {
    loadingQ.value = true;
    try {
      const res = await api.question(props.task.plan_id);
      question.value = res.question;
      questionMeta.value = { question_type: res.question_type, options: res.options };
    } catch (e: any) {
      toast(e.message || "出题失败");
    } finally {
      loadingQ.value = false;
    }
  }
}

async function submit() {
  const value = (isChoice.value ? selectedKey.value : answer.value).trim();
  if (!value) {
    toast(isChoice.value ? "请先选择一个选项" : "先写下你的作答");
    return;
  }
  submitting.value = true;
  try {
    result.value = await api.answer(props.task.plan_id, value);
    emit("refresh");
  } catch (e: any) {
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
  try {
    await api.skip(props.task.plan_id);
    emit("refresh");
    toast("已跳过");
  } catch (e: any) {
    toast(e.message || "操作失败");
  }
}
</script>

<template>
  <div class="task">
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

        <template v-if="!done">
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
          <textarea v-else v-model="answer" class="textarea" placeholder="凭理解作答，判分口径与测验一致（按要点覆盖判分）"></textarea>
          <div style="display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap;">
            <button class="btn primary" :disabled="submitting" @click="submit">
              {{ submitting ? '判分中…' : isChoice ? '提交选择' : '提交作答' }}
            </button>
            <button v-if="!isChoice" class="btn ghost" @click="practiceOnly">只练不判</button>
            <button class="btn text" @click="skip">跳过</button>
          </div>
        </template>

        <div v-if="result || (done && task.verdict)" class="verdict-panel" :class="panelCls">
          <template v-if="result">
            <b>{{ !result.graded ? '暂未判分（LLM 不可用，可自评对照参考答案）' : result.verdict === 'pass' ? '✓ 通过' : '✗ 未通过' }}</b>
            <span v-if="result.score != null" style="margin-left: 8px; font-weight: 600;">得分 {{ (result.score * 100).toFixed(0) }}</span>
            <p style="margin-top: 4px;">{{ result.reason }}</p>
            <p v-if="result.mastered" style="margin-top: 6px;"><span class="badge ok">🎉 连续通过，已达标</span></p>
            <div v-if="result.reference_answer" class="ref-answer"><b>参考答案</b>：{{ result.reference_answer }}</div>
          </template>
          <template v-else>
            <b>{{ task.verdict === 'pass' ? '✓ 通过' : '✗ 未通过' }}</b>
            <div v-if="task.reference_answer" class="ref-answer"><b>参考答案</b>：{{ task.reference_answer }}</div>
          </template>
        </div>
        <div v-else-if="done" class="verdict-panel none">已记录练习，未系统判分</div>

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
