/* 主题偏好（三态：auto 跟随系统 / light / dark）
 * 解析结果写入 <html data-theme>，CSS 按 [data-theme="dark"] 覆盖 token；
 * index.html 里有同款内联脚本在样式加载前先行设置，防止暗色用户白闪。 */
export type ThemePref = "auto" | "light" | "dark";

const KEY = "theme-pref";
const MEDIA = "(prefers-color-scheme: dark)";

export function getPref(): ThemePref {
  const v = localStorage.getItem(KEY);
  return v === "light" || v === "dark" ? v : "auto";
}

function resolve(pref: ThemePref): "light" | "dark" {
  if (pref !== "auto") return pref;
  return window.matchMedia(MEDIA).matches ? "dark" : "light";
}

export function applyPref(pref: ThemePref) {
  localStorage.setItem(KEY, pref);
  const resolved = resolve(pref);
  document.documentElement.dataset.theme = resolved;
  // Tailwind dark: 变体走 .dark 类（ui-redesign D3）：与 data-theme 同步维护
  document.documentElement.classList.toggle("dark", resolved === "dark");
}

export function setPref(pref: ThemePref) {
  applyPref(pref);
}

export function cyclePref(): ThemePref {
  const order: ThemePref[] = ["auto", "light", "dark"];
  const next = order[(order.indexOf(getPref()) + 1) % order.length];
  applyPref(next);
  return next;
}

export const prefLabel: Record<ThemePref, string> = {
  auto: "跟随系统",
  light: "浅色",
  dark: "深色",
};

/** 应用启动时调用：设初值并跟随系统变化（auto 态）。 */
export function initTheme() {
  applyPref(getPref());
  window.matchMedia(MEDIA).addEventListener("change", () => {
    if (getPref() === "auto") applyPref("auto");
  });
}
