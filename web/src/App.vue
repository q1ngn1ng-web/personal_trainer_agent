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

// 侧栏收缩（记忆在 localStorage）
const collapsed = ref(localStorage.getItem("sb-collapsed") === "1");
function toggleSidebar() {
  collapsed.value = !collapsed.value;
  localStorage.setItem("sb-collapsed", collapsed.value ? "1" : "0");
}

// 右上角头像菜单
const menuOpen = ref(false);
function toggleMenu() {
  menuOpen.value = !menuOpen.value;
}
function closeMenu() {
  menuOpen.value = false;
}

import {
  CircleDot, Plus, LayoutDashboard, GraduationCap, CircleUser,
} from "lucide-vue-next";

const navs = [
  { name: "today", ico: CircleDot, label: "今日训练" },
  { name: "wizard", ico: Plus, label: "新建训练" },
  { name: "dashboard", ico: LayoutDashboard, label: "仪表盘" },
  { name: "trainings", ico: GraduationCap, label: "我的训练" },
  { name: "me", ico: CircleUser, label: "我的" },
];

const who = computed(() => {
  if (authState.viewer) {
    const v = authState.viewer as any;
    return v.display_name || v.email || "我";
  }
  return "我";
});
const initial = computed(() => who.value.slice(0, 1).toUpperCase());

function shortLabel(label: string) {
  return label.replace(/今日训练/, "今日").replace(/我的训练/, "训练").replace(/新建训练/, "新建");
}

async function doLogout() {
  await logout();
  router.push({ name: "login" });
}
</script>

<template>
  <div v-if="!authState.ready" class="loading-center"><span class="spinner"></span></div>
  <router-view v-else-if="isLoginPage" />
  <div v-else class="shell">
    <aside class="sidebar" :class="{ collapsed }">
      <div class="brand">
        <div class="brand-mark">练</div>
        <div v-if="!collapsed" class="brand-text">
          <div class="brand-name">训练教练</div>
          <div class="brand-sub">自适应训练</div>
        </div>
      </div>
      <button class="collapse-btn" :title="collapsed ? '展开' : '收起'" @click="toggleSidebar">
        {{ collapsed ? '»' : '«' }}
      </button>
      <router-link
        v-for="n in navs" :key="n.name" :to="{ name: n.name }"
        class="nav-item" :class="{ active: route.name === n.name }"
        :title="collapsed ? n.label : undefined"
      >
        <component :is="n.ico" class="ico-svg" />
        <span v-if="!collapsed">{{ n.label }}</span>
      </router-link>
      <div class="sidebar-foot" v-if="!collapsed">
        <div class="foot-hint">要点判分 · 可解释</div>
      </div>
    </aside>

    <div style="flex: 1; min-width: 0; display: flex; flex-direction: column;">
      <header class="topbar">
        <div class="topbar-title">{{ route.name === 'wizard' ? '新建训练' : navs.find((n) => n.name === route.name)?.label || '' }}</div>
        <div class="avatar-wrap" @click.stop>
          <button class="avatar" @click="toggleMenu">{{ initial }}</button>
          <div v-if="menuOpen" class="avatar-menu" @click="closeMenu">
            <div class="menu-header">
              <div class="menu-name">{{ who }}</div>
              <div class="menu-sub">{{ authState.viewer ? '已登录' : '本地模式' }}</div>
            </div>
            <router-link :to="{ name: 'me' }" class="menu-item">个人中心</router-link>
            <button v-if="authState.authEnabled" class="menu-item" @click="doLogout">退出登录</button>
          </div>
        </div>
      </header>

      <main class="main">
        <router-view />
      </main>

      <nav class="tabbar">
        <router-link v-for="n in navs" :key="n.name" :to="{ name: n.name }" class="tab-item"
          :class="{ active: route.name === n.name }">
          <component :is="n.ico" class="ico-svg ico-svg-sm" />{{ shortLabel(n.label) }}
        </router-link>
      </nav>
    </div>
  </div>
  <div v-if="toast" class="toast">{{ toast }}</div>
</template>
