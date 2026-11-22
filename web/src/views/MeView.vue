<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { authState, logout } from "../auth";
import { api } from "../api";
import { getPref, setPref, prefLabel, type ThemePref } from "../theme";
import { useRouter } from "vue-router";

const router = useRouter();

async function doLogout() {
  await logout();
  router.push({ name: "login" });
}

const roleLabel: Record<string, string> = {
  org_admin: "组织管理员",
  admin: "小组管理员",
  member: "成员",
};

const displayName = () => authState.viewer?.display_name || authState.viewer?.email || "成员";
const email = () => authState.viewer?.email || "";
const orgId = computed(() => authState.viewer?.org_id ?? null);
const role = computed(() => authState.viewer?.role ?? "member");

// 我的小组（member-invite）：个人模式可建组/等邀请；admin+ 可拉人
const invites = ref<{ membership_id: number; org_name: string; inviter_name: string | null }[]>([]);
const orgName = ref("");
const members = ref<{ user_id: number; email: string; display_name: string | null; role: string; status: string }[]>([]);
const candQuery = ref("");
const candidates = ref<{ user_id: number; email: string; display_name: string | null }[]>([]);
const newOrgName = ref("");
const inviteEmail = ref("");
const busy = ref(false);

function toast(msg: string) {
  (window as any).__toast?.(msg);
}

// 外观（主题三态）：从顶栏迁移到个人中心 + 头像菜单（2026-11-22 用户要求）
const themePref = ref<ThemePref>(getPref());
const THEME_OPTIONS: { value: ThemePref; label: string; hint: string }[] = [
  { value: "auto", label: "跟随系统", hint: "与操作系统亮暗保持一致" },
  { value: "light", label: "浅色", hint: "默认亮色主题" },
  { value: "dark", label: "深色", hint: "深灰蓝底 + 提亮状态色" },
];
function applyTheme(value: ThemePref) {
  themePref.value = value;
  setPref(value);
  toast(`主题：${prefLabel[value]}`);
}

async function loadOrg() {
  if (orgId.value == null) {
    try {
      invites.value = (await api.myInvites()).invites;
    } catch {
      invites.value = [];
    }
    return;
  }
  try {
    members.value = await fetchMembers();
  } catch {
    members.value = [];
  }
}

async function fetchMembers() {
  // /api/org/members 需管理动作权限：member 档不拉取（视图只对 admin+ 展示）
  if (role.value === "member") return [];
  const res = await api.orgMembers();
  return res.members;
}

async function createOrg() {
  if (!newOrgName.value.trim()) return;
  busy.value = true;
  try {
    const res = await api.createOrg(newOrgName.value.trim());
    toast(`已创建「${res.name}」，你是组织管理员`);
    authState.viewer = await api.me();
    newOrgName.value = "";
    await loadOrg();
  } catch (e: any) {
    toast(e.message || "建组失败");
  } finally {
    busy.value = false;
  }
}

async function searchCandidates() {
  if (orgId.value == null) return;
  try {
    candidates.value = (await api.listCandidates(orgId.value, candQuery.value)).candidates;
  } catch (e: any) {
    toast(e.message || "候选搜索失败");
  }
}

async function invite(email: string) {
  if (orgId.value == null) return;
  busy.value = true;
  try {
    await api.inviteMember(orgId.value, email);
    toast(`已邀请 ${email}（等待对方在「我的邀请」里接受）`);
    candidates.value = candidates.value.filter((c) => c.email !== email);
    members.value = await fetchMembers();
  } catch (e: any) {
    toast(e.message || "邀请失败");
  } finally {
    busy.value = false;
  }
}

async function remove(uid: number) {
  if (orgId.value == null || !window.confirm("移除该成员？其资格将被停用（数据保留）。")) return;
  try {
    await api.removeMember(orgId.value, uid);
    toast("已移除");
    members.value = await fetchMembers();
  } catch (e: any) {
    toast(e.message || "移除失败");
  }
}

async function promote(uid: number) {
  if (orgId.value == null) return;
  try {
    await api.setMemberRole(orgId.value, uid, { role: "admin" });
    toast("已升级为小组管理员（默认配额 10）");
    members.value = await fetchMembers();
  } catch (e: any) {
    toast(e.message || "操作失败");
  }
}

async function accept(membershipId: number) {
  try {
    await api.acceptInvite(membershipId);
    toast("已接受邀请——进组成功");
    authState.viewer = await api.me();
    invites.value = [];
    await loadOrg();
  } catch (e: any) {
    toast(e.message || "接受失败");
  }
}

onMounted(loadOrg);
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
            <template v-if="authState.viewer && orgId != null"> · 我的小组</template>
          </div>
          <div v-if="authState.viewer && email()" style="color: var(--muted); font-size: 13px; margin-top: 2px; overflow-wrap: anywhere;">
            注册邮箱：{{ email() }}
          </div>
        </div>
      </div>
      <button v-if="authState.authEnabled" class="btn ghost" @click="doLogout">退出登录</button>
    </div>

    <!-- 外观设置 -->
    <div v-if="authState.viewer" class="card">
      <div class="card-title" style="margin-bottom: 8px;">外观</div>
      <div style="display: flex; gap: 8px; flex-wrap: wrap;">
        <button
          v-for="opt in THEME_OPTIONS"
          :key="opt.value"
          class="btn sm"
          :class="themePref === opt.value ? 'primary' : 'ghost'"
          :title="opt.hint"
          @click="applyTheme(opt.value)"
        >{{ opt.label }}</button>
      </div>
      <div style="font-size: 12px; color: var(--faint); margin-top: 6px;">当前：{{ prefLabel[themePref] }}——右上角头像菜单里也可以快速切换</div>
    </div>

    <!-- 我的邀请（被邀请人侧） -->
    <div v-if="authState.viewer && invites.length" class="card">
      <div class="card-title" style="margin-bottom: 8px;">我的邀请</div>
      <div v-for="i in invites" :key="i.membership_id" class="list-item">
        <div style="flex: 1; min-width: 0;">
          <b>{{ i.org_name }}</b>
          <div style="font-size: 12.5px; color: var(--muted);">邀请人：{{ i.inviter_name || '管理员' }}</div>
        </div>
        <button class="btn primary sm" :disabled="busy" @click="accept(i.membership_id)">接受</button>
      </div>
    </div>

    <!-- 个人模式：建组入口 -->
    <div v-if="authState.viewer && orgId == null && !invites.length" class="card">
      <div class="card-title" style="margin-bottom: 8px;">我的小组</div>
      <p style="font-size: 13px; color: var(--muted); margin: 0 0 8px;">
        你还没有加入任何小组——创建一个（你是组织管理员），或等待朋友邀请。
      </p>
      <div style="display: flex; gap: 8px;">
        <input v-model="newOrgName" class="input" style="flex: 1;" placeholder="小组名称（如：Redis 互助小组）" />
        <button class="btn primary" :disabled="busy" @click="createOrg">创建小组</button>
      </div>
    </div>

    <!-- 组内：成员管理（admin+ 可拉人；org_admin 可升降/移除） -->
    <div v-if="authState.viewer && orgId != null" class="card">
      <div class="card-head" style="margin-bottom: 8px;">
        <div class="card-title">成员管理</div>
        <span class="badge gray">{{ roleLabel[role] || role }}</span>
      </div>

      <template v-if="role !== 'member'">
        <div style="display: flex; gap: 8px; margin-bottom: 8px;">
          <input v-model="candQuery" class="input" style="flex: 1;" placeholder="按邮箱/昵称搜索已注册用户" @keyup.enter="searchCandidates" />
          <button class="btn sm" :disabled="busy" @click="searchCandidates">搜索</button>
        </div>
        <div v-if="candidates.length" style="margin-bottom: 10px;">
          <div v-for="c in candidates" :key="c.user_id" class="list-item">
            <div style="flex: 1; min-width: 0;">{{ c.display_name || c.email }}<span style="color: var(--faint); font-size: 12px; margin-left: 6px;">{{ c.email }}</span></div>
            <button class="btn primary sm" :disabled="busy" @click="invite(c.email)">邀请</button>
          </div>
        </div>
        <div style="display: flex; gap: 8px; margin-bottom: 10px;">
          <input v-model="inviteEmail" class="input" style="flex: 1;" placeholder="或直接输入邮箱邀请" @keyup.enter="invite(inviteEmail)" />
          <button class="btn sm" :disabled="busy || !inviteEmail" @click="invite(inviteEmail)">邀请</button>
        </div>
      </template>

      <div v-if="members.length">
        <div v-for="m in members" :key="m.user_id" class="list-item">
          <div style="flex: 1; min-width: 0;">
            {{ m.display_name || m.email }}
            <span class="badge" :class="m.role === 'org_admin' ? 'brand' : m.role === 'admin' ? 'info' : 'gray'">
              {{ roleLabel[m.role] || m.role }}{{ m.status === 'invited' ? ' · 待接受' : '' }}
            </span>
          </div>
          <template v-if="role === 'org_admin' && m.role === 'member'">
            <button class="btn ghost sm" @click="promote(m.user_id)">升为管理员</button>
            <button class="btn ghost sm" style="color: var(--danger, #c0392b);" @click="remove(m.user_id)">移除</button>
          </template>
        </div>
      </div>
      <div v-else-if="role === 'member'" style="color: var(--muted); font-size: 13.5px;">
        你是普通成员——互相看进度的入口在小组内分享的计划里。
      </div>
    </div>

    <div class="card" style="color: var(--muted); font-size: 13.5px;">
      <div class="card-title" style="margin-bottom: 8px;">关于</div>
      训练教练 · 意图驱动的自适应训练系统。描述学习目标 → AI 澄清 → 定位理解边缘 →
      生成训练路径 → 每日训练与反馈 → 测验达标。所有判分由「要点清单 × 规则层」给出，可解释。
    </div>
  </div>
</template>
