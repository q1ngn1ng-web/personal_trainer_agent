<script setup lang="ts">
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

const sourcesOverview = ref<
  {
    checksum: string | null;
    title: string;
    type: string;
    parse_status: string;
    enabled: boolean;
    chunk_total: number;
    reference_count: number;
    trainings: { training_id: number; topic: string }[];
  }[]
>([]);
const sourcesLoading = ref(false);
const deletingId = ref<number | null>(null);
const archivingId = ref<number | null>(null);

async function loadSources() {
  sourcesLoading.value = true;
  try {
    const res = await api.sourcesOverview();
    sourcesOverview.value = res.sources;
  } catch (e: any) {
    toast(e.message || "资料加载失败");
  } finally {
    sourcesLoading.value = false;
  }
}

async function deleteTrainingRow(trainingId: number) {
  if (!window.confirm("彻底删除这个训练及其全部数据？不可恢复。")) return;
  deletingId.value = trainingId;
  try {
    await api.deleteTraining(trainingId);
    toast("已删除");
    await Promise.all([load(), loadSources()]);
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
    await Promise.all([load(), loadSources()]);
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
  await loadSources();
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
        <span class="ico">🧭</span>还没有训练——去「新建训练」开始第一课。
      </div>

      <div class="card" style="margin-top: 16px;">
        <div class="card-head">
          <div class="card-title">资料总览（按内容指纹聚合）</div>
          <span class="badge gray">{{ sourcesOverview.length }} 份</span>
        </div>
        <div v-if="sourcesLoading" class="loading-center" style="padding: 14px 0;"><span class="spinner"></span></div>
        <div v-else-if="!sourcesOverview.length" style="color: var(--muted); font-size: 13.5px;">还没有资料——创建训练并导入后这里会汇总。</div>
        <div v-for="s in sourcesOverview" :key="s.checksum ?? s.title" class="list-item" style="align-items: flex-start;">
          <span class="badge" :class="s.parse_status === 'ok' ? 'ok' : s.parse_status === 'ok' ? '' : 'warn'">{{ s.parse_status === 'ok' ? '✓' : s.parse_status }}</span>
          <div style="flex: 1; min-width: 0;">
            <div style="font-size: 14px;">{{ s.title }}<span v-if="!s.enabled" class="badge gray" style="margin-left: 6px;">已停用</span></div>
            <div style="font-size: 12px; color: var(--faint);">
              被引用于 <b>{{ s.reference_count }}</b> 个训练计划 · 切片 {{ s.chunk_total }} 条 · 类型 {{ s.type }}
            </div>
            <div v-if="s.trainings.length" style="font-size: 12px; color: var(--faint); margin-top: 2px;">
              {{ s.trainings.map((x) => x.topic).join(" / ") }}
            </div>
          </div>
        </div>
      </div>

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
            {{ archivingId === t.training_id ? '归档中…' : '📦 归档' }}
          </button>
          <button class="btn sm danger" :disabled="deletingId === t.training_id" @click="deleteTrainingRow(t.training_id)">
            {{ deletingId === t.training_id ? '删除中…' : '🗑 删除训练' }}
          </button>
        </div>
      </div>
    </template>
  </div>
</template>
