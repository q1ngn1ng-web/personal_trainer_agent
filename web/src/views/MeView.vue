<script setup lang="ts">
import { onMounted, ref } from "vue";
import { authState, logout } from "../auth";
import { api, type MyAssignment } from "../api";
import { useRouter } from "vue-router";

const router = useRouter();
const assignments = ref<MyAssignment[]>([]);
const loading = ref(true);

onMounted(async () => {
  if (!authState.viewer) {
    loading.value = false;
    return;
  }
  try {
    const res = await api.myAssignments();
    assignments.value = res.pending;
  } catch {
    assignments.value = [];
  } finally {
    loading.value = false;
  }
});

async function accept(id: number) {
  try {
    const res = await api.acceptAssignment(id);
    (window as any).__toast?.("已接收，训练已创建");
    router.push("/trainings/" + res.training_id);
  } catch (e: any) {
    (window as any).__toast?.(e.message || "接收失败");
  }
}

async function doLogout() {
  await logout();
  router.push({ name: "login" });
}

const roleLabel: Record<string, string> = {
  org_admin: "组织管理员",
  dept_manager: "部门管理员",
  employee: "员工",
};
</script>

<template>
  <div>
    <div class="page-head">
      <h1 class="page-title">我的</h1>
    </div>

    <div class="card">
      <div class="card-head">
        <div>
          <div class="card-title">{{ authState.viewer ? (authState.viewer.email || '成员') : '本地个人版' }}</div>
          <div style="color: var(--muted); font-size: 13px; margin-top: 2px;">
            {{ authState.viewer ? roleLabel[authState.viewer.role] || authState.viewer.role : '单用户模式，无需登录' }}
          </div>
        </div>
      </div>
      <button v-if="authState.authEnabled" class="btn ghost" @click="doLogout">退出登录</button>
    </div>

    <div v-if="authState.viewer" class="card">
      <div class="card-title" style="margin-bottom: 10px;">待接收的培训任务</div>
      <div v-if="loading" class="loading-center" style="padding: 20px 0;"><span class="spinner"></span></div>
      <div v-else-if="!assignments.length" class="empty" style="padding: 20px 0;">暂无待接收任务</div>
      <div v-for="a in assignments" :key="a.id" class="list-item" style="cursor: default;">
        <div style="flex: 1; min-width: 0;">
          <div style="font-weight: 600;">{{ a.title }}</div>
          <div style="font-size: 12.5px; color: var(--muted);">截止 {{ a.due_date || '不限' }}</div>
        </div>
        <button class="btn primary sm" @click="accept(a.id)">接收</button>
      </div>
    </div>

    <div class="card" style="color: var(--muted); font-size: 13.5px;">
      <div class="card-title" style="margin-bottom: 8px;">关于</div>
      训练教练 · 意图驱动的自适应训练系统。描述学习目标 → AI 澄清 → 定位理解边缘 →
      生成训练路径 → 每日训练与反馈 → 测验达标。所有判分由「要点清单 × 规则层」给出，可解释。
    </div>
  </div>
</template>
