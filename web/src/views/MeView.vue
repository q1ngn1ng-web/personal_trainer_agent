<script setup lang="ts">
import { authState, logout } from "../auth";
import { useRouter } from "vue-router";

const router = useRouter();

async function doLogout() {
  await logout();
  router.push({ name: "login" });
}

const roleLabel: Record<string, string> = {
  org_admin: "组织管理员",
  dept_manager: "部门管理员",
  employee: "员工",
};

const displayName = () => authState.viewer?.display_name || authState.viewer?.email || "成员";
const email = () => authState.viewer?.email || "";
</script>

<template>
  <div>
    <div class="page-head">
      <h1 class="page-title">我的</h1>
    </div>

    <div class="card">
      <div class="card-head">
        <div style="min-width: 0;">
          <div class="card-title">{{ authState.viewer ? displayName() : '本地个人版' }}</div>
          <div style="color: var(--muted); font-size: 13px; margin-top: 2px;">
            {{ authState.viewer ? roleLabel[authState.viewer.role] || authState.viewer.role : '单用户模式，无需登录' }}
          </div>
          <div v-if="authState.viewer && email()" style="color: var(--muted); font-size: 13px; margin-top: 2px; overflow-wrap: anywhere;">
            注册邮箱：{{ email() }}
          </div>
        </div>
      </div>
      <button v-if="authState.authEnabled" class="btn ghost" @click="doLogout">退出登录</button>
    </div>

    <div class="card" style="color: var(--muted); font-size: 13.5px;">
      <div class="card-title" style="margin-bottom: 8px;">关于</div>
      训练教练 · 意图驱动的自适应训练系统。描述学习目标 → AI 澄清 → 定位理解边缘 →
      生成训练路径 → 每日训练与反馈 → 测验达标。所有判分由「要点清单 × 规则层」给出，可解释。
    </div>
  </div>
</template>
