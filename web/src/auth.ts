import { reactive } from "vue";
import { api, type Viewer } from "./api";

// 全局会话状态：authEnabled=false（个人版）时不设登录门
export const authState = reactive({
  viewer: null as Viewer | null,
  authEnabled: false,
  ready: false,
});

export async function bootstrapAuth() {
  try {
    const mode = await api.authMode();
    authState.authEnabled = mode.auth_enabled;
  } catch {
    authState.authEnabled = false;
  }
  try {
    authState.viewer = await api.me();
  } catch {
    authState.viewer = null;
  }
  authState.ready = true;
}

export async function loginWithCode(token: string) {
  const result = await api.verify(token);
  authState.viewer = result.viewer;
}

export async function logout() {
  try {
    await api.logout();
  } finally {
    authState.viewer = null;
  }
}

// 个人版：邮箱+密码注册/登录（2026-10-26）
import { wizardApi } from "./api_wizard";

export async function registerAccount(email: string, password: string, displayName: string) {
  const result = await wizardApi.register(email, password, displayName);
  authState.viewer = result.viewer;
}

export async function loginPassword(email: string, password: string) {
  const result = await wizardApi.login(email, password);
  authState.viewer = result.viewer;
}
