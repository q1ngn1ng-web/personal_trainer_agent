<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";
import { loginWithCode, registerAccount, loginPassword } from "../auth";

const router = useRouter();
const mode = ref<"login" | "register">("login");
const email = ref("");
const password = ref("");
const password2 = ref("");
const displayName = ref("");
const error = ref("");
const busy = ref(false);

async function submit() {
  error.value = "";
  if (mode.value === "register") {
    if (password.value.length < 8) {
      error.value = "密码至少 8 位";
      return;
    }
    if (password.value !== password2.value) {
      error.value = "两次输入的密码不一致";
      return;
    }
  }
  if (!email.value.trim() || !password.value) {
    error.value = "请填写邮箱和密码";
    return;
  }
  busy.value = true;
  try {
    if (mode.value === "register") {
      await registerAccount(email.value.trim(), password.value, displayName.value.trim());
    } else {
      await loginPassword(email.value.trim(), password.value);
    }
    router.push({ name: "today" });
  } catch (e: any) {
    error.value = e.message || "操作失败，请稍后再试";
  } finally {
    busy.value = false;
  }
}

// 企业培训分支的登录码入口保留但不再默认展示
const showLegacy = ref(false);
const legacyToken = ref("");
async function legacyLogin() {
  try {
    await loginWithCode(legacyToken.value.trim());
    router.push({ name: "today" });
  } catch (e: any) {
    error.value = e.message || "登录码无效";
  }
}
</script>

<template>
  <div class="login-wrap">
    <div class="login-card">
      <div class="brand" style="padding: 0 0 18px;">
        <div class="brand-mark" style="width: 44px; height: 44px; font-size: 21px;">练</div>
        <div>
          <div class="brand-name" style="font-size: 19px;">训练教练</div>
          <div class="brand-sub">自适应训练 · 个人版</div>
        </div>
      </div>

      <div class="login-switch">
        <button :class="{ active: mode === 'login' }" @click="mode = 'login'">登录</button>
        <button :class="{ active: mode === 'register' }" @click="mode = 'register'">注册</button>
      </div>

      <div v-if="error" class="error-tip">{{ error }}</div>

      <div class="field">
        <label>邮箱</label>
        <input v-model="email" class="input" type="email" placeholder="you@example.com" @keyup.enter="submit" />
      </div>
      <div v-if="mode === 'register'" class="field">
        <label>昵称（可选）</label>
        <input v-model="displayName" class="input" placeholder="怎么称呼你" />
      </div>
      <div class="field">
        <label>密码</label>
        <input v-model="password" class="input" type="password" placeholder="至少 8 位" @keyup.enter="submit" />
      </div>
      <div v-if="mode === 'register'" class="field">
        <label>确认密码</label>
        <input v-model="password2" class="input" type="password" @keyup.enter="submit" />
      </div>

      <button class="btn primary block" :disabled="busy" @click="submit">
        {{ busy ? '请稍候…' : mode === 'login' ? '登 录' : '注册并开始' }}
      </button>

      <p style="font-size: 12px; color: var(--faint); margin-top: 14px; text-align: center;">
        <a href="javascript:void(0)" @click="showLegacy = !showLegacy">企业培训版入口（登录码）</a>
      </p>
      <div v-if="showLegacy" style="display: flex; gap: 8px; margin-top: 8px;">
        <input v-model="legacyToken" class="input" placeholder="登录码" @keyup.enter="legacyLogin" />
        <button class="btn ghost sm" @click="legacyLogin">进入</button>
      </div>
    </div>
  </div>
</template>
