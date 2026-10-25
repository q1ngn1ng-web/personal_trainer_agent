<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { api, type TodayResponse, type TodayTask } from "../api";
import TaskCard from "../components/TaskCard.vue";

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
  } catch (e: any) {
    (window as any).__toast?.(e.message || "加载失败");
  } finally {
    loading.value = false;
  }
}
onMounted(load);

const groups = computed(() => {
  if (!data.value) return [];
  return data.value.groups.map((g) => ({
    ...g,
    pct: g.total ? Math.round((g.practiced / g.total) * 100) : 0,
    tasks: data.value!.tasks.filter((t) => t.training_id === g.training_id),
  }));
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
    <div class="page-head">
      <h1 class="page-title">{{ greeting }}，继续今天的训练</h1>
      <p class="page-sub">{{ dateText }}</p>
    </div>

    <div v-if="loading && !data" class="loading-center"><span class="spinner"></span></div>

    <template v-else-if="data">
      <div class="stat-row">
        <div class="stat"><div class="num">{{ data.count }}</div><div class="lbl">今日任务</div></div>
        <div class="stat"><div class="num">{{ data.minutes }}′</div><div class="lbl">预计时长</div></div>
        <div class="stat"><div class="num">{{ data.groups.length }}</div><div class="lbl">进行中的训练</div></div>
      </div>

      <div v-if="!data.tasks.length" class="card empty">
        <span class="ico">🌙</span>
        今天没有安排任务<br />
        <span style="font-size: 13px;">去「训练」页看看你的路径，或休息一下</span>
      </div>

      <div v-for="g in groups" :key="g.training_id" class="card">
        <div class="card-head">
          <div style="min-width: 0;">
            <div class="card-title">{{ g.topic }}</div>
            <div style="font-size: 12.5px; color: var(--muted); margin-top: 2px;">
              {{ g.practiced }}/{{ g.total }} 完成 · 约 {{ g.minutes }} 分钟
            </div>
          </div>
          <span class="badge" :class="g.pct === 100 ? 'ok' : 'brand'">{{ g.pct }}%</span>
        </div>
        <div class="progress" style="margin-bottom: 14px;"><i :style="{ width: g.pct + '%' }"></i></div>

        <TaskCard v-for="t in g.tasks" :key="t.plan_id" :task="t" @refresh="load" />

        <div style="margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--line);">
          <div style="font-size: 12.5px; color: var(--faint); margin-bottom: 8px;">今天的感受（反馈会调整训练安排）</div>
          <div class="signal-row">
            <button v-for="s in signals" :key="s.key" class="signal-btn" @click="sendSignal(g.training_id, s.key)">
              {{ s.label }}
            </button>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
