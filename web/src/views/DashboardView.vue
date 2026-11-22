<script setup lang="ts">
import { Compass } from "lucide-vue-next";
import { TransitionGroup } from "vue";
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { api, type DashboardResponse } from "../api";

const router = useRouter();
const data = ref<DashboardResponse | null>(null);
const loading = ref(true);

// ---- 每日训练热力（GitHub 贡献图风格）：近 13 周，列=周、行=周一~周日 ----
const heatCells = computed(() => {
  const act = data.value?.activity || [];
  if (!act.length) return [];
  const byDate = new Map(act.map((a) => [a.date, a.count]));
  const today = new Date();
  // 起点：13 周前的周一（对齐列）
  const start = new Date(today);
  start.setDate(today.getDate() - 90);
  start.setDate(start.getDate() - ((start.getDay() + 6) % 7)); // 回退到周一
  const cells: { date: string; count: number; level: number; future: boolean; label: string }[] = [];
  const localIso = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  for (let d = new Date(start); d <= today; d.setDate(d.getDate() + 1)) {
    const iso = localIso(d);
    const count = byDate.get(iso) || 0;
    const level = count === 0 ? 0 : count <= 2 ? 1 : count <= 5 ? 2 : count <= 9 ? 3 : 4;
    cells.push({
      date: iso,
      count,
      level,
      future: false,
      label: `${d.getMonth() + 1}月${d.getDate()}日：${count} 题`,
    });
  }
  // 本周剩余天数补隐藏格（保持 7 行网格对齐）
  const dow = (today.getDay() + 6) % 7;
  for (let i = dow + 1; i <= 6; i++) {
    cells.push({ date: "", count: 0, level: 0, future: true, label: "" });
  }
  return cells;
});
const heatTotal = computed(() => (data.value?.activity || []).reduce((s, a) => s + a.count, 0));

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

      <div class="card heat-card">
        <div class="card-head" style="margin-bottom: 0;">
          <div class="card-title">训练热力</div>
          <span class="badge gray">近 13 周 · {{ heatTotal }} 题</span>
        </div>
        <div v-if="heatCells.length" class="heat-grid">
          <div
            v-for="(c, i) in heatCells"
            :key="i"
            class="heat-cell"
            :class="[c.level ? 'l' + c.level : '', { future: c.future }]"
            :title="c.label"
          />
        </div>
        <div class="heat-legend">
          少
          <span class="heat-cell" /><span class="heat-cell l1" /><span class="heat-cell l2" />
          <span class="heat-cell l3" /><span class="heat-cell l4" />
          多
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
