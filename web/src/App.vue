<script setup lang="ts">
import { onMounted, ref, computed, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { authState, bootstrapAuth, logout } from "./auth";

const route = useRoute();
const router = useRouter();
const toast = ref("");
let toastTimer = 0;

function showToast(msg: string) {
  toast.value = msg;
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => (toast.value = ""), 2600);
}

onMounted(async () => {
  await bootstrapAuth();
  (window as any).__toast = showToast;
});

// 会话在页面停留期间失效（或首屏加载时守卫尚未就绪）：主动踢回登录页
watch(
  () => [authState.ready, authState.authEnabled, authState.viewer] as const,
  ([ready, enabled, viewer]) => {
    if (ready && enabled && !viewer && route.name !== "login") {
      router.push({ name: "login" });
    }
  }
);

const isLoginPage = computed(() => route.name === "login");

const navs = [
  { name: "today", ico: "◎", label: "今日" },
  { name: "trainings", ico: "◈", label: "训练" },
  { name: "me", ico: "◍", label: "我的" },
];

async function doLogout() {
  await logout();
  router.push({ name: "login" });
}
</script>

<template>
  <div v-if="!authState.ready" class="loading-center"><span class="spinner"></span></div>
  <router-view v-else-if="isLoginPage" />
  <div v-else class="shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">练</div>
        <div>
          <div class="brand-name">训练教练</div>
          <div class="brand-sub">自适应训练 · 个人版</div>
        </div>
      </div>
      <router-link v-for="n in navs" :key="n.name" :to="{ name: n.name }" class="nav-item"
        :class="{ active: route.name === n.name }">
        <span class="ico">{{ n.ico }}</span>{{ n.label }}
      </router-link>
      <div class="sidebar-foot">
        <div style="font-size: 12.5px; color: var(--muted); margin-bottom: 8px;">
          {{ authState.viewer ? authState.viewer.email : "本地个人版" }}
        </div>
        <button v-if="authState.authEnabled" class="btn text" style="padding-left: 0;" @click="doLogout">退出登录</button>
      </div>
    </aside>

    <div style="flex: 1; min-width: 0;">
      <div class="mobile-bar">
        <div class="brand" style="padding: 0;">
          <div class="brand-mark" style="width: 30px; height: 30px; font-size: 15px;">练</div>
          <div class="brand-name" style="font-size: 15px;">训练教练</div>
        </div>
        <button v-if="authState.authEnabled" class="btn text" @click="doLogout">退出</button>
      </div>
      <main class="main">
        <router-view />
      </main>
      <nav class="tabbar">
        <router-link v-for="n in navs" :key="n.name" :to="{ name: n.name }" class="tab-item"
          :class="{ active: route.name === n.name }">
          <span class="ico">{{ n.ico }}</span>{{ n.label }}
        </router-link>
      </nav>
    </div>
  </div>
  <div v-if="toast" class="toast">{{ toast }}</div>
</template>
