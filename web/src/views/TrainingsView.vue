<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { api, type TrainingSummary } from "../api";

const router = useRouter();
const trainings = ref<TrainingSummary[]>([]);
const loading = ref(true);

const statusLabel: Record<string, { cls: string; text: string }> = {
  active: { cls: "ok", text: "进行中" },
  draft: { cls: "gray", text: "草稿" },
  confirmed: { cls: "info", text: "已确认" },
  completed: { cls: "brand", text: "已完成" },
  paused: { cls: "warn", text: "已暂停" },
};

onMounted(async () => {
  try {
    const res = await api.trainings();
    trainings.value = res.trainings;
  } catch (e: any) {
    (window as any).__toast?.(e.message || "加载失败");
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <div>
    <div class="page-head">
      <h1 class="page-title">我的训练</h1>
      <p class="page-sub">每个训练有独立的学习路径、资料与测验</p>
    </div>

    <div v-if="loading" class="loading-center"><span class="spinner"></span></div>

    <div v-else-if="!trainings.length" class="card empty">
      <span class="ico">🧭</span>还没有训练<br />
      <span style="font-size: 13px;">新建训练请前往桌面版或 Streamlit 入口</span>
    </div>

    <div v-else>
      <div v-for="t in trainings" :key="t.id" class="card" style="cursor: pointer;" @click="router.push('/trainings/' + t.id)">
        <div class="card-head" style="margin-bottom: 6px;">
          <div class="card-title" style="min-width: 0;">{{ t.topic }}</div>
          <span class="badge" :class="(statusLabel[t.status] || statusLabel.draft).cls">{{ (statusLabel[t.status] || statusLabel.draft).text }}</span>
        </div>
        <div style="display: flex; gap: 14px; color: var(--muted); font-size: 13px;">
          <span v-if="t.baseline_score">基线 {{ (t.baseline_score * 100).toFixed(0) }}</span>
          <span>点击查看路径 · 资料 · 测验 →</span>
        </div>
      </div>
    </div>
  </div>
</template>
