<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api, authState } from "../auth";
import { api as apiClient } from "../api";

const route = useRoute();
const router = useRouter();
const token = String(route.params.token || "");

const preview = ref<{
  topic: string;
  stages: { ordinal: number; title: string; goal: string | null; estimated_minutes: number; items: { title: string; knowledge_point: string | null; item_type: string | null }[] }[];
  acceptance: unknown;
  keywords: string[];
} | null>(null);
const loading = ref(true);
const pulling = ref(false);
const pulled = ref<number | null>(null);
const error = ref("");

function toast(msg: string) {
  (window as any).__toast?.(msg);
}

async function load() {
  loading.value = true;
  try {
    preview.value = await apiClient.sharePreview(token);
  } catch (e: any) {
    error.value = e.message || "链接不存在或已撤销";
  } finally {
    loading.value = false;
  }
}

async function pull() {
  if (!authState.viewer) {
    router.push({ name: "login" });
    return;
  }
  pulling.value = true;
  try {
    const res = await apiClient.pullShare(token);
    pulled.value = res.training_id;
    toast(res.created ? "已加入我的训练" : "你已拉取过这份计划");
  } catch (e: any) {
    toast(e.message || "拉取失败");
  } finally {
    pulling.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div>
    <div class="page-head">
      <h1 class="page-title">分享的训练计划</h1>
      <p class="page-sub">拉取后会创建一份属于你的独立训练，进度互不影响</p>
    </div>

    <div v-if="loading" class="loading-center"><span class="spinner"></span></div>

    <div v-else-if="error" class="card empty">{{ error }}</div>

    <template v-else-if="preview">
      <div class="card">
        <div class="card-head">
          <div class="card-title">{{ preview.topic }}</div>
        </div>
        <div v-if="preview.keywords.length" style="display: flex; gap: 6px; flex-wrap: wrap; margin-top: 6px;">
          <span v-for="k in preview.keywords" :key="k" class="badge gray">{{ k }}</span>
        </div>
        <div v-if="preview.acceptance" class="ref-answer" style="margin-top: 8px;">
          <b>验收标准</b>：
          <span v-if="typeof preview.acceptance === 'object'">
            {{ (preview.acceptance as any).statement || (preview.acceptance as any).metric || "见训练详情" }}
          </span>
          <span v-else>{{ preview.acceptance }}</span>
        </div>
      </div>

      <div v-for="st in preview.stages" :key="st.ordinal" class="card stage" style="padding: 0; overflow: hidden;">
        <div class="stage-head">
          <span class="badge gray">阶段 {{ st.ordinal }}</span>
          <div style="flex: 1; min-width: 0;">
            <div style="font-weight: 600;">{{ st.title }}</div>
            <div v-if="st.goal" style="font-size: 12.5px; color: var(--muted);">{{ st.goal }}</div>
          </div>
          <span style="color: var(--faint); font-size: 12.5px;">{{ st.estimated_minutes }}′ · {{ st.items.length }} 项</span>
        </div>
        <div style="padding: 0 20px 14px;">
          <div v-for="(it, i) in st.items" :key="i" class="list-item">
            <span class="ico">·</span>
            <div style="flex: 1; min-width: 0;">
              <div style="font-size: 14px;">{{ it.title }}</div>
              <div v-if="it.knowledge_point" style="font-size: 12px; color: var(--faint);">{{ it.knowledge_point }}</div>
            </div>
          </div>
        </div>
      </div>

      <div class="card">
        <button class="btn primary block" :disabled="pulling" @click="pull">
          {{ pulling ? '拉取中…' : pulled ? '✓ 已加入我的训练' : '拉取为我的训练' }}
        </button>
        <p style="font-size: 12.5px; color: var(--faint); margin-top: 8px; text-align: center;">
          拉取会创建独立副本（含资料与题库），原计划的后续修改不影响你的副本。
        </p>
        <button v-if="pulled" class="btn primary block" @click="router.push('/trainings/' + pulled)">
          进入我的训练 →
        </button>
      </div>
    </template>
  </div>
</template>
