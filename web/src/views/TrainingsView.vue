<script setup lang="ts">
import { Compass } from "lucide-vue-next";
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { api, type TrainingSummary } from "../api";

type DashRow = {
  training_id: number;
  today_completed: number;
  today_total: number;
  item_count?: number;
  knowledge_points_total?: number;
  knowledge_points_covered?: number;
};

const router = useRouter();
const trainings = ref<TrainingSummary[]>([]);
const dashById = ref<Record<number, DashRow>>({});
const loading = ref(true);

const todayIso = new Date().toLocaleDateString("sv-SE"); // 本地 YYYY-MM-DD
function daysFromToday(iso: string | null): number | null {
  if (!iso) return null;
  const diff = Math.round((new Date(iso + "T00:00:00").getTime() - new Date(todayIso + "T00:00:00").getTime()) / 86400000);
  return diff;
}

// 资料总览（按内容指纹聚合）：同文档被几个训练计划引用，从桌面迁到训练页
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

const statusLabel: Record<string, { cls: string; text: string }> = {
  active: { cls: "ok", text: "进行中" },
  draft: { cls: "gray", text: "草稿" },
  confirmed: { cls: "info", text: "已确认" },
  completed: { cls: "brand", text: "已完成" },
  paused: { cls: "warn", text: "已暂停" },
};

async function loadSources() {
  sourcesLoading.value = true;
  try {
    const res = await api.sourcesOverview();
    sourcesOverview.value = res.sources;
  } catch (e: any) {
    (window as any).__toast?.(e.message || "资料加载失败");
  } finally {
    sourcesLoading.value = false;
  }
}

onMounted(async () => {
  try {
    const [res, dash] = await Promise.all([api.trainings(), api.dashboard().catch(() => null)]);
    trainings.value = res.trainings;
    const map: Record<number, DashRow> = {};
    for (const row of dash?.trainings || []) map[row.training_id] = row;
    dashById.value = map;
  } catch (e: any) {
    (window as any).__toast?.(e.message || "加载失败");
  } finally {
    loading.value = false;
  }
  await loadSources();
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
      <Compass class="ico-svg ico-svg-lg" style="margin: 0 auto 8px;" />还没有训练<br />
      <span style="font-size: 13px;">新建训练请前往桌面版或 Streamlit 入口</span>
    </div>

    <div v-else>
      <div v-for="t in trainings" :key="t.id" class="card" style="cursor: pointer;" @click="router.push('/trainings/' + t.id)">
        <div class="card-head" style="margin-bottom: 6px;">
          <div class="card-title" style="min-width: 0;">{{ t.topic }}</div>
          <span class="badge" :class="(statusLabel[t.status] || statusLabel.draft).cls">{{ (statusLabel[t.status] || statusLabel.draft).text }}</span>
        </div>
        <div style="display: flex; gap: 12px; color: var(--muted); font-size: 13px; flex-wrap: wrap;">
          <span v-if="dashById[t.id]?.knowledge_points_total">
            知识点覆盖 <b>{{ dashById[t.id].knowledge_points_covered }}/{{ dashById[t.id].knowledge_points_total }}</b> · 题量 <b>{{ dashById[t.id].item_count }}</b>
          </span>
          <span v-if="t.next_due">
            下次任务 <b :style="daysFromToday(t.next_due)! < 0 ? 'color: var(--danger);' : ''">
              {{ t.next_due.slice(5) }}{{ (daysFromToday(t.next_due) ?? 0) < 0 ? `（逾期 ${-(daysFromToday(t.next_due) ?? 0)} 天）` : "" }}
            </b>
          </span>
          <span v-if="t.final_due">
            终测 <b>{{ t.final_due.slice(5) }}</b>（{{ (daysFromToday(t.final_due) ?? 0) < 0 ? "已到期" : `还有 ${daysFromToday(t.final_due)} 天` }}）
          </span>
          <span v-if="(dashById[t.id]?.today_total ?? 0) > 0">今日 {{ dashById[t.id]?.today_completed }}/{{ dashById[t.id]?.today_total }}</span>
          <span v-if="t.baseline_score">基线分 {{ (t.baseline_score * 100).toFixed(0) }}</span>
        </div>
      </div>
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
  </div>
</template>
