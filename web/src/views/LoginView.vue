<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";
import { loginWithCode } from "../auth";

const router = useRouter();
const email = ref("");
const token = ref("");
const message = ref("");
const error = ref("");
const sending = ref(false);
const verifying = ref(false);

async function requestCode() {
  error.value = "";
  if (!email.value.trim()) {
    error.value = "请输入邮箱";
    return;
  }
  sending.value = true;
  try {
    const res = await (await import("../api")).api.requestCode(email.value.trim());
    message.value = res.message;
  } catch (e: any) {
    error.value = e.message || "申请失败";
  } finally {
    sending.value = false;
  }
}

async function verify() {
  error.value = "";
  if (!token.value.trim()) {
    error.value = "请输入登录码";
    return;
  }
  verifying.value = true;
  try {
    await loginWithCode(token.value.trim());
    router.push({ name: "today" });
  } catch (e: any) {
    error.value = e.message || "登录码无效或已过期";
  } finally {
    verifying.value = false;
  }
}
</script>

<template>
  <div class="login-wrap">
    <div class="login-card">
      <div class="brand" style="padding: 0 0 20px;">
        <div class="brand-mark" style="width: 44px; height: 44px; font-size: 21px;">练</div>
        <div>
          <div class="brand-name" style="font-size: 19px;">训练教练</div>
          <div class="brand-sub">自适应训练 · 个人版</div>
        </div>
      </div>

      <div v-if="error" class="error-tip">{{ error }}</div>
      <div v-if="message" class="ok-tip">{{ message }}</div>

      <div class="field">
        <label>邮箱</label>
        <input v-model="email" class="input" type="email" placeholder="you@company.com" @keyup.enter="requestCode" />
      </div>
      <button class="btn ghost block" :disabled="sending" @click="requestCode" style="margin-bottom: 18px;">
        {{ sending ? "提交中…" : "申请登录码" }}
      </button>

      <div class="field">
        <label>登录码</label>
        <input v-model="token" class="input" placeholder="输入管理员签发的登录码" @keyup.enter="verify" />
      </div>
      <button class="btn primary block" :disabled="verifying" @click="verify">
        {{ verifying ? "登录中…" : "登 录" }}
      </button>

      <p style="font-size: 12.5px; color: var(--faint); margin-top: 16px; text-align: center;">
        登录码由管理员签发，一次性有效
      </p>
    </div>
  </div>
</template>
