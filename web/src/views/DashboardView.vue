<script setup lang="ts">
import { Compass } from "lucide-vue-next";
import { TransitionGroup } from "vue";
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { api, type DashboardResponse } from "../api";
import Card from "../components/ui/Card.vue";
import Badge from "../components/ui/Badge.vue";
import Button from "../components/ui/Button.vue";

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

const knowledgeSummary = computed(() => {
  const rows = data.value?.trainings || [];
  const total = rows.reduce((s, t) => s + (t.knowledge_points_total ?? 0), 0);
  const covered = rows.reduce((s, t) => s + (t.knowledge_points_covered ?? 0), 0);
  return total ? { total, covered } : null;
});

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
    <div class="mb-5">
      <h1 class="text-[28px] font-semibold leading-tight">学习仪表盘</h1>
      <p class="mt-1 text-[13.5px] text-muted">{{ dateText }} · 从已有出发，逐步扩大</p>
    </div>

    <div v-if="loading && !data" class="flex h-40 items-center justify-center">
      <span class="inline-block h-6 w-6 animate-spin rounded-full border-2 border-line border-t-primary" />
    </div>

    <template v-else-if="data">
      <!-- 指标卡（4 列网格） -->
      <div class="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Card v-for="m in [
          { num: data.total_active, label: '活跃训练' },
          { num: totalPersistDays, label: '累计坚持天数' },
          { num: data.avg_baseline != null ? (data.avg_baseline * 100).toFixed(0) : '—', label: '平均基线分' },
          { num: data.total_all, label: '全部训练' },
        ]" :key="m.label" padding="sm" class="py-4 text-center">
          <div class="text-[22px] font-semibold tabular-nums">{{ m.num }}</div>
          <div class="mt-1 text-xs text-muted">{{ m.label }}</div>
        </Card>
      </div>

      <!-- 训练热力 -->
      <Card class="mt-4">
        <div class="mb-3 flex items-center gap-2">
          <div class="text-[15px] font-semibold">训练热力</div>
          <Badge>近 13 周 · {{ heatTotal }} 题</Badge>
          <Badge v-if="knowledgeSummary" tone="info">知识点 {{ knowledgeSummary.covered }}/{{ knowledgeSummary.total }} 已覆盖</Badge>
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
        <div class="mt-2 flex items-center gap-1 text-xs text-faint">
          少
          <span class="heat-cell" /><span class="heat-cell l1" /><span class="heat-cell l2" />
          <span class="heat-cell l3" /><span class="heat-cell l4" />
          多
        </div>
      </Card>

      <div v-if="!data.trainings.length" class="mt-4 rounded-lg border border-line bg-surface p-8 text-center text-muted">
        <Compass class="mx-auto mb-2 h-6 w-6" /> 还没有训练——去「新建训练」开始第一课。
      </div>

      <TransitionGroup name="card-fade" tag="div" class="mt-4 flex flex-col gap-3">
        <div
          v-for="t in data.trainings"
          :key="t.training_id"
          class="cursor-pointer rounded-lg border border-line bg-surface p-5 transition-colors hover:bg-surface-2"
          @click="openTraining(t.training_id)"
        >
          <div class="mb-2 flex items-center justify-between gap-3">
            <div class="min-w-0 text-[15px] font-semibold">{{ t.topic }}</div>
            <Badge :tone="t.status === 'active' ? 'ok' : 'default'">{{ statusLabel[t.status] || t.status }}</Badge>
          </div>
          <div class="flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-muted">
            <span>坚持 <b class="font-semibold text-text">{{ t.consecutive_days }}</b> 天</span>
            <span>今日 <b class="font-semibold text-text">{{ t.today_completed }}</b>/{{ t.today_total }}（{{ pct(t) }}%）</span>
            <span>题量 <b class="font-semibold text-text">{{ t.item_count ?? 0 }}</b></span>
            <span>知识点覆盖 <b class="font-semibold text-text">{{ t.knowledge_points_covered ?? 0 }}/{{ t.knowledge_points_total ?? 0 }}</b></span>
            <span>第 <b class="font-semibold text-text">{{ t.current_week }}</b> 周</span>
            <span>基线 {{ (t.baseline_score * 100).toFixed(0) }} 分</span>
            <span>最近活跃 {{ relDay(t.last_active_at) }}</span>
          </div>
          <div v-if="(t.knowledge_points || []).length" class="mt-2 flex flex-wrap gap-1.5">
            <Badge
              v-for="kp in (t.knowledge_points || []).slice(0, 8)"
              :key="kp.name"
              :tone="kp.covered ? 'ok' : 'default'"
              :title="kp.covered ? '已覆盖（有通过记录）' : '未覆盖'"
            >{{ kp.covered ? '✓ ' : '' }}{{ kp.name }}</Badge>
            <Badge v-if="(t.knowledge_points || []).length > 8">+{{ (t.knowledge_points || []).length - 8 }}</Badge>
          </div>
          <div class="mt-2.5 h-1.5 overflow-hidden rounded-full bg-surface-2">
            <i class="block h-full rounded-full bg-primary transition-all" :style="{ width: pct(t) + '%' }" />
          </div>
          <div class="mt-2.5 flex flex-wrap gap-2" @click.stop>
            <Button
              v-if="t.status === 'completed'"
              variant="ghost" size="sm"
              :disabled="archivingId === t.training_id"
              @click="archiveTrainingRow(t.training_id)"
            >{{ archivingId === t.training_id ? '归档中…' : '归档' }}</Button>
            <Button variant="danger" size="sm" :disabled="deletingId === t.training_id" @click="deleteTrainingRow(t.training_id)">
              {{ deletingId === t.training_id ? '删除中…' : '删除训练' }}
            </Button>
          </div>
        </div>
      </TransitionGroup>
    </template>
  </div>
</template>

<style scoped>
/* 热力档位（页内局部样式；暗色走 .dark 的 ok 色提亮，design D2） */
.heat-grid { display: grid; grid-template-rows: repeat(7, 1fr); grid-auto-flow: column; gap: 3px; }
.heat-cell { width: 11px; height: 11px; border-radius: 2px; background: var(--color-surface-2); }
.heat-cell.l1 { background: rgba(14, 124, 107, 0.30); }
.heat-cell.l2 { background: rgba(14, 124, 107, 0.55); }
.heat-cell.l3 { background: rgba(14, 124, 107, 0.80); }
.heat-cell.l4 { background: var(--color-primary); }
.dark .heat-cell.l1 { background: rgba(23, 181, 151, 0.18); }
.dark .heat-cell.l2 { background: rgba(23, 181, 151, 0.38); }
.dark .heat-cell.l3 { background: rgba(23, 181, 151, 0.62); }
.dark .heat-cell.l4 { background: rgba(44, 199, 170, 0.9); }
.heat-cell.future { visibility: hidden; }
</style>
