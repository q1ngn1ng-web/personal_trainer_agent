<script setup lang="ts">
import { Compass } from "lucide-vue-next";
import { TransitionGroup } from "vue";
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { api, type DashboardResponse } from "../api";

const router = useRouter();
const data = ref<DashboardResponse | null>(null);
const loading = ref(true);

const dateText = computed(() => {
  const d = new Date();
  const week = ["日", "一", "二", "三", "四", "五", "六"][d.getDay()];
  return d.getMonth() + 1 + "月" + d.getDate() + "日 星期" + week;
});

const statusLabel: Record<string, string> = {
  created: "已创建", draft: "草稿", pending_confirm: "待确认目标", confirmed: "待选资料/路径",
  active: "活跃", paused: "暂停", completed: "已达标", archived: "已归档", failed: "失败",
};

const totalPersistDays = computed(() =>
  (data.value?.trainings || []).reduce((sum, t) => sum + t.consecutive_days, 0)
);

function pct(t: { today_total: number; today_completed: number }) {
  return t.today_total ? Math.round((t.today_completed / t.today_total) * 100) : 0;
}

function relDay(value: string | null) {
  if (!value) return "—";
  const d = new Date(value);
  const today = new Date();
  const diff = Math.floor((today.getTime() - d.getTime()) / 86400000);
  if (diff <= 0) return "今天";
  if (diff < 7) return `${diff} 天前`;
  return value.slice(0, 10);
}

function openTraining(id: number) {
  router.push("/trainings/" + id);
}

function toast(msg: string) {
  (window as any).__toast?.(msg);
}

const deletingId = ref<number | null>(null);
const archivingId = ref<number | null>(null);

async function deleteTrainingRow(trainingId: number) {
  if (!window.confirm("彻底删除这个训练及其全部数据？不可恢复。")) return;
  deletingId.value = trainingId;
  try {
    await api.deleteTraining(trainingId);
    toast("已删除");
    await load();
  } catch (e: any) {
    toast(e.message || "删除失败");
  } finally {
    deletingId.value = null;
  }
}

async function archiveTrainingRow(trainingId: number) {
  archivingId.value = trainingId;
  try {
    await api.archiveTraining(trainingId);
    toast("已归档");
    await load();
  } catch (e: any) {
    toast(e.message || "归档失败");
  } finally {
    archivingId.value = null;
  }
}

async function load() {
  loading.value = true;
  try {
    data.value = await api.dashboard();
  } catch (e: any) {
    toast(e.message || "加载失败");
  } finally {
    loading.value = false;
  }
}
onMounted(load);
</script>

<template>
  <div>
    <div class="page-head">
      <h1 class="page-title">学习仪表盘</h1>
      <p class="page-sub">{{ dateText }}·从已有出发，逐步扩大</p>
    </div>

    <div v-if="loading && !data" class="loading-center"><span class="spinner"></span></div>

    <template v-else-if="data">
      <div class="dash-metrics">
        <div class="card dash-metric">
          <div class="dash-num">{{ data.total_active }}</div>
          <div class="dash-label">活跃训练</div>
        </div>
        <div class="card dash-metric">
          <div class="dash-num">{{ totalPersistDays }}</div>
          <div class="dash-label">累计坚持天数</div>
        </div>
        <div class="card dash-metric">
          <div class="dash-num">{{ data.avg_baseline != null ? (data.avg_baseline * 100).toFixed(0) : "—" }}</div>
          <div class="dash-label">平均基线分</div>
        </div>
        <div class="card dash-metric">
          <div class="dash-num">{{ data.total_all }}</div>
          <div class="dash-label">全部训练</div>
        </div>
      </div>

      <div v-if="!data.trainings.length" class="card empty">
        <Compass class="ico-svg ico-svg-lg empty-ico" /> 还没有训练——去「新建训练」开始第一课。
      </div>

      <TransitionGroup name="card-fade">
      <div
        v-for="t in data.trainings"
        :key="t.training_id"
        class="card dash-row"
        @click="openTraining(t.training_id)"
      >
        <div class="card-head" style="margin-bottom: 8px;">
          <div class="card-title" style="min-width: 0;">{{ t.topic }}</div>
          <span class="badge" :class="t.status === 'active' ? 'ok' : 'gray'">{{ statusLabel[t.status] || t.status }}</span>
        </div>
        <div class="dash-row-metrics">
          <span>坚持 <b>{{ t.consecutive_days }}</b> 天</span>
          <span>今日 <b>{{ t.today_completed }}</b>/{{ t.today_total }}（{{ pct(t) }}%）</span>
          <span>第 <b>{{ t.current_week }}</b> 周</span>
          <span>基线 {{ (t.baseline_score * 100).toFixed(0) }} 分</span>
          <span>最近活跃 {{ relDay(t.last_active_at) }}</span>
        </div>
        <div class="progress" style="margin-top: 8px;"><i :style="{ width: pct(t) + '%' }"></i></div>
        <div style="display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap;" @click.stop>
          <button v-if="t.status === 'completed'" class="btn sm ghost" :disabled="archivingId === t.training_id" @click="archiveTrainingRow(t.training_id)">
            {{ archivingId === t.training_id ? '归档中…' : '归档' }}
          </button>
          <button class="btn sm danger" :disabled="deletingId === t.training_id" @click="deleteTrainingRow(t.training_id)">
            {{ deletingId === t.training_id ? '删除中…' : '删除训练' }}
          </button>
        </div>
      </div>
      </TransitionGroup>
    </template>
  </div>
</template>
