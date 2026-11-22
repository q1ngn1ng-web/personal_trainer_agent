<script setup lang="ts">
import { onMounted, ref, computed, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { authState, bootstrapAuth, logout } from "./auth";
import {
  CircleDot, Plus, LayoutDashboard, GraduationCap, CircleUser, Sun, Moon, SunMoon,
} from "lucide-vue-next";
import { cyclePref, prefLabel, getPref, type ThemePref } from "./theme";
import { cn } from "./lib/utils";

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

// 头像菜单
const menuOpen = ref(false);
function toggleMenu() {
  menuOpen.value = !menuOpen.value;
}
function closeMenu() {
  menuOpen.value = false;
}

const themePref = ref<ThemePref>(getPref());
const ThemeIcon = computed(() =>
  themePref.value === "light" ? Sun : themePref.value === "dark" ? Moon : SunMoon
);
function toggleTheme() {
  themePref.value = cyclePref();
  toast(`主题：${prefLabel[themePref.value]}`);
}

// rail 导航（design D4：纯图标 + hover tooltip + active 左缘指示条）
const navs = [
  { name: "today", ico: CircleDot, label: "今日训练" },
  { name: "wizard", ico: Plus, label: "新建训练" },
  { name: "dashboard", ico: LayoutDashboard, label: "仪表盘" },
  { name: "trainings", ico: GraduationCap, label: "我的训练" },
  { name: "me", ico: CircleUser, label: "我的" },
];

const pageTitle = computed(() => {
  if (route.name === "wizard") return "新建训练";
  return navs.find((n) => n.name === route.name)?.label || "";
});

const who = computed(() => {
  if (authState.viewer) {
    const v = authState.viewer as any;
    return v.display_name || v.email || "我";
  }
  return "我";
});
const initial = computed(() => who.value.slice(0, 1).toUpperCase());

async function doLogout() {
  await logout();
  router.push({ name: "login" });
}
</script>

<template>
  <div v-if="!authState.ready" class="flex min-h-screen items-center justify-center">
    <span class="inline-block h-6 w-6 animate-spin rounded-full border-2 border-line border-t-primary" />
  </div>
  <router-view v-else-if="isLoginPage" />
  <div v-else class="flex min-h-screen bg-bg text-text">
    <!-- 72px 图标 rail（design D4） -->
    <aside class="sticky top-0 flex h-screen w-[72px] flex-shrink-0 flex-col items-center border-r border-line bg-surface">
      <router-link
        :to="{ name: 'today' }"
        class="mt-3 mb-2 flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-[15px] font-semibold text-white"
        title="训练教练 · 回首页"
      >练</router-link>

      <nav class="flex flex-col items-center gap-1">
        <router-link
          v-for="n in navs"
          :key="n.name"
          :to="{ name: n.name }"
          class="group relative flex h-11 w-11 items-center justify-center rounded-lg transition-colors"
          :class="route.name === n.name ? 'text-primary' : 'text-faint hover:bg-surface-2 hover:text-text'"
        >
          <!-- active 左缘 2px 青绿指示条 -->
          <span
            v-if="route.name === n.name"
            class="absolute left-[-14px] top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-full bg-primary"
          />
          <component :is="n.ico" class="h-5 w-5" />
          <!-- hover tooltip：图标右侧浮层 -->
          <span
            class="pointer-events-none absolute left-[52px] z-50 whitespace-nowrap rounded-md border border-line bg-surface px-2 py-1 text-xs text-text opacity-0 shadow-sm transition-opacity duration-150 group-hover:opacity-100"
          >{{ n.label }}</span>
        </router-link>
      </nav>

      <!-- rail 底部：主题三态 + 关于 mini（原侧栏关于区块压缩） -->
      <div class="mt-auto mb-3 flex flex-col items-center gap-1">
        <button
          class="group relative flex h-9 w-9 items-center justify-center rounded-lg text-faint transition-colors hover:bg-surface-2 hover:text-text"
          :title="'主题：' + prefLabel[themePref] + '（点击切换）'"
          @click="toggleTheme"
        >
          <ThemeIcon class="h-4 w-4" />
          <span
            class="pointer-events-none absolute left-[46px] z-50 whitespace-nowrap rounded-md border border-line bg-surface px-2 py-1 text-xs text-text opacity-0 shadow-sm transition-opacity duration-150 group-hover:opacity-100"
          >主题：{{ prefLabel[themePref] }}</span>
        </button>
        <button
          class="group relative flex h-9 w-9 items-center justify-center rounded-lg text-faint transition-colors hover:bg-surface-2 hover:text-text"
          title="训练教练：意图驱动 → 澄清 → 边缘定位 → 路径 → 每日训练 → 测验达标；判分 = 要点清单 × 规则层，可解释"
        >
          <span class="text-[13px] font-medium">?</span>
          <span
            class="pointer-events-none absolute left-[46px] z-50 w-64 whitespace-normal rounded-md border border-line bg-surface p-2 text-xs leading-relaxed text-muted opacity-0 shadow-sm transition-opacity duration-150 group-hover:opacity-100"
          >意图驱动的自适应训练：目标澄清 → 边缘定位 → 路径 → 每日训练 → 测验达标。判分 = 要点清单 × 规则层，可解释。</span>
        </button>
      </div>
    </aside>

    <!-- 52px 顶栏 + 1080px 内容区 -->
    <div class="flex min-w-0 flex-1 flex-col">
      <header class="sticky top-0 z-40 flex h-[52px] items-center justify-between border-b border-line bg-surface/90 px-5 backdrop-blur">
        <div class="text-[15px] font-semibold">{{ pageTitle }}</div>
        <div class="relative" @click.stop>
          <button
            class="flex h-8 w-8 items-center justify-center rounded-full bg-primary text-[13px] font-semibold text-white"
            @click="toggleMenu"
          >{{ initial }}</button>
          <div v-if="menuOpen" class="absolute right-0 top-10 z-50 w-44 rounded-lg border border-line bg-surface p-1 shadow-lg" @click="closeMenu">
            <div class="border-b border-line px-3 py-2">
              <div class="text-sm font-medium">{{ who }}</div>
              <div class="text-xs text-faint">{{ authState.viewer ? '已登录' : '本地模式' }}</div>
            </div>
            <router-link :to="{ name: 'me' }" class="block rounded-md px-3 py-2 text-sm text-text hover:bg-surface-2">个人中心</router-link>
            <button
              class="flex w-full items-center justify-between rounded-md px-3 py-2 text-sm text-text hover:bg-surface-2"
              @click.stop="toggleTheme"
            >
              <span>主题</span>
              <span class="text-xs text-faint">{{ prefLabel[themePref] }}</span>
            </button>
            <button v-if="authState.authEnabled" class="w-full rounded-md px-3 py-2 text-left text-sm text-danger hover:bg-danger-weak" @click="doLogout">退出登录</button>
          </div>
        </div>
      </header>

      <main class="mx-auto w-full max-w-[1080px] px-6 py-6">
        <router-view />
      </main>
    </div>
  </div>
  <div
    v-if="toast"
    class="fixed bottom-6 left-1/2 z-[100] -translate-x-1/2 rounded-lg border border-line bg-surface px-4 py-2 text-sm text-text shadow-lg"
  >{{ toast }}</div>
</template>

<style scoped>
/* cn 在本文件仅用于 class 绑定场景；此处保留空 style 块占位以便后续局部样式 */
</style>
