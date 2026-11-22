<script setup lang="ts">
import { Moon } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { api, type TodayResponse, type TodayTask } from "../api";
import TaskCard from "../components/TaskCard.vue";
import Card from "../components/ui/Card.vue";
import Badge from "../components/ui/Badge.vue";

const data = ref<TodayResponse | null>(null);
const loading = ref(true);

const greeting = computed(() => {
  const h = new Date().getHours();
  if (h < 6) return "夜深了";
  if (h < 12) return "早上好";
  if (h < 14) return "中午好";
  if (h < 18) return "下午好";
  return "晚上好";
});
const dateText = computed(() => {
  const d = new Date();
  const week = ["日", "一", "二", "三", "四", "五", "六"][d.getDay()];
  return d.getMonth() + 1 + "月" + d.getDate() + "日 星期" + week;
});

const signals = [
  { key: "too_much", label: "太多了" },
  { key: "too_narrow", label: "太窄了" },
  { key: "too_easy", label: "太简单" },
  { key: "too_hard", label: "太难了" },
];

async function load() {
  loading.value = true;
  try {
    data.value = await api.today();
    // 快照对账：后台 done 列表已落地（含判分结果）的，移除临时快照
    const landed = new Set((data.value?.done || []).map((t) => t.plan_id));
    pendingDone.value = pendingDone.value.filter((p) => !landed.has(p.task.plan_id));
  } catch (e: any) {
    (window as any).__toast?.(e.message || "加载失败");
  } finally {
    loading.value = false;
  }
}
onMounted(load);

const autoOpenId = ref<number | null>(null);
const doneTasks = computed(() => data.value?.done || []);
const pendingPlanIds = computed(() => new Set(pendingDone.value.map((p) => p.task.plan_id)));
const allDone = computed(() => {
  const landed = new Set(doneTasks.value.map((t) => t.plan_id));
  const snapshots = pendingDone.value
    .filter((p) => !landed.has(p.task.plan_id))
    .map((p) => ({ ...p.task, judging: true }));
  return [...snapshots, ...doneTasks.value.map((t) => ({ ...t, judging: pendingPlanIds.has(t.plan_id) }))];
});

// 提交即移入"今天已作答"：快照先行，判分由下方卡片完成（沉浸式）
const pendingDone = ref<{ task: TodayTask; judging: boolean }[]>([]);
const hiddenPlanIds = computed(() => new Set(pendingDone.value.map((p) => p.task.plan_id)));

function onAnswered(task: TodayTask) {
  pendingDone.value.push({ task: { ...task, status: "practiced" }, judging: true });
  // 自动切到下一个未完成任务
  const tasks = data.value?.tasks || [];
  const idx = tasks.findIndex((t) => t.plan_id === task.plan_id);
  const next = tasks.slice(idx + 1).find((t) => t.status === "planned" && t.plan_id !== task.plan_id);
  autoOpenId.value = next ? next.plan_id : null;
}

function onSubmitFailed(planId: number) {
  pendingDone.value = pendingDone.value.filter((p) => p.task.plan_id !== planId);
  toast("提交失败，题目已放回待完成");
}

const groups = computed(() => {
  if (!data.value) return [];
  return data.value.groups.map((g) => {
    const tasks = data.value!.tasks.filter((t) => t.training_id === g.training_id);
    // 红墙降噪：逾期不逐行挂标，聚合到组级一条（最早到期日提示先做哪道）
    const overdue = tasks.filter((t) => t.is_overdue);
    const earliestOverdue = overdue.length ? overdue.map((t) => t.due_date).sort()[0] : null;
    return {
      ...g,
      pct: g.total ? Math.round((g.practiced / g.total) * 100) : 0,
      tasks,
      overdueCount: overdue.length,
      earliestOverdue,
    };
  });
});

async function sendSignal(trainingId: number, type: string) {
  try {
    const res = await api.signal(trainingId, type);
    (window as any).__toast?.(res.applied ? res.message : res.blocked_reason || res.message);
    load();
  } catch (e: any) {
    (window as any).__toast?.(e.message || "反馈失败");
  }
}
</script>

<template>
  <div>
    <div class="mb-5">
      <h1 class="text-[28px] font-semibold leading-tight">{{ greeting }}，继续今天的训练</h1>
      <p class="mt-1 text-[13.5px] text-muted">{{ dateText }}</p>
    </div>

    <div v-if="loading && !data" class="flex h-40 items-center justify-center">
      <span class="inline-block h-6 w-6 animate-spin rounded-full border-2 border-line border-t-primary" />
    </div>

    <template v-else-if="data">
      <div class="grid grid-cols-3 gap-3">
        <Card v-for="m in [
          { num: data.count, label: '今日任务' },
          { num: data.minutes + '′', label: '预计时长' },
          { num: data.groups.length, label: '进行中的训练' },
        ]" :key="m.label" padding="sm" class="py-4 text-center">
          <div class="text-[22px] font-semibold tabular-nums">{{ m.num }}</div>
          <div class="mt-1 text-xs text-muted">{{ m.label }}</div>
        </Card>
      </div>

      <div v-if="!data.tasks.length" class="mt-4 rounded-lg border border-line bg-surface p-8 text-center text-muted">
        <Moon class="mx-auto mb-2 h-6 w-6" />
        今天没有安排任务<br />
        <span class="text-[13px]">去「训练」页看看你的路径，或休息一下</span>
      </div>

      <TransitionGroup name="card-fade" tag="div" class="mt-4 flex flex-col gap-4">
        <div v-for="g in groups" :key="g.training_id" class="rounded-lg border border-line bg-surface p-5">
          <div class="mb-2 flex items-center justify-between gap-3">
            <div class="min-w-0">
              <div class="text-[15px] font-semibold">{{ g.topic }}</div>
              <div class="mt-0.5 text-[12.5px] text-muted">
                <template v-if="g.total">{{ g.practiced }}/{{ g.total }} 完成 · 约 {{ g.minutes }} 分钟</template>
                <template v-else>今天已完成 {{ g.practiced }} 题 · 无待办</template>
              </div>
            </div>
            <Badge v-if="g.total" :tone="g.pct === 100 ? 'ok' : 'brand'">{{ g.pct }}%</Badge>
          </div>
          <div v-if="g.total" class="mb-3.5 h-1.5 overflow-hidden rounded-full bg-surface-2">
            <i class="block h-full rounded-full bg-primary transition-all" :style="{ width: g.pct + '%' }" />
          </div>

          <div
            v-if="g.overdueCount"
            class="mb-2.5 w-full rounded-md border border-danger/30 bg-danger-weak px-3 py-1.5 text-left text-[13px] font-medium text-danger"
          >
            ⚠ 以下 {{ g.overdueCount }} 题均逾期（最早 {{ g.earliestOverdue }}）——按顺序从最早的一道开始即可，不用一次还清
          </div>
          <div class="flex flex-col gap-2">
            <TaskCard
              v-for="t in g.tasks.filter((t) => !hiddenPlanIds.has(t.plan_id))"
              :key="t.plan_id"
              :task="t"
              compact
              :auto-open="autoOpenId === t.plan_id"
              @answered="onAnswered"
              @submit-failed="onSubmitFailed"
              @refresh="load"
            />
          </div>

          <div class="mt-3.5 border-t border-line pt-3">
            <div class="mb-2 text-[12.5px] text-faint">今天的感受（反馈会调整训练安排）</div>
            <div class="flex flex-wrap gap-2">
              <button
                v-for="s in signals"
                :key="s.key"
                class="rounded-full border border-line px-3 py-1 text-[12.5px] text-muted transition-colors hover:border-primary/40 hover:text-primary"
                @click="sendSignal(g.training_id, s.key)"
              >{{ s.label }}</button>
            </div>
          </div>
        </div>
      </TransitionGroup>

      <!-- 今天已作答：不闪走，留在这里看结果与解析 -->
      <Card v-if="doneTasks.length" class="mt-4">
        <div class="mb-3 flex items-center justify-between">
          <div class="text-[15px] font-semibold">今天已作答</div>
          <Badge>{{ doneTasks.length }} 项</Badge>
        </div>
        <TransitionGroup name="card-fade" tag="div" class="flex flex-col gap-2">
          <TaskCard
            v-for="t in allDone"
            :key="t.plan_id"
            :task="t"
            :judging="pendingPlanIds.has(t.plan_id)"
          />
        </TransitionGroup>
      </Card>
    </template>
  </div>
</template>
