// 资料解析状态的可视化映射（wizard 第 2 步 / 详情页资料 tab 共用）。
// 探测出题的硬前提：至少一份「启用 && parse_status=ok && 切片数>0」的来源。
import type { SourceSummary } from "../api";

export type SourceStatusView = {
  label: string; // 徽章文案
  cls: "ok" | "warn" | "gray" | "info"; // Badge 色调（对应 tailwind.css 兼容层语义类）
  hint?: string; // 需要展示给用户的原因/说明
};

export function sourceStatusView(s: SourceSummary): SourceStatusView {
  const chunks = s.chunk_count ?? 0;
  if (!s.enabled) return { label: "已停用", cls: "gray", hint: "停用的资料不参与出题" };
  switch (s.parse_status) {
    case "ok":
      if (chunks > 0) return { label: `已就绪 · ${chunks} 切片`, cls: "ok" };
      return { label: "无切片", cls: "warn", hint: "解析成功但没有切出任何内容，请检查文件是否有正文" };
    case "failed":
      return { label: "解析失败", cls: "warn", hint: s.parse_error || "解析出错，可删除后重新上传" };
    case "unsupported":
      return { label: "格式不支持", cls: "warn", hint: "支持 PDF / Word / Excel / Markdown / 纯文本 / 网页" };
    case "pending":
      return { label: "待解析", cls: "info" };
    default:
      return { label: s.parse_status || "未知", cls: "gray" };
  }
}

/** 探测出题就绪：至少一份启用 + 解析成功 + 有切片的来源。 */
export function sourcesReady(sources: SourceSummary[]): boolean {
  return sources.some((s) => s.enabled && s.parse_status === "ok" && (s.chunk_count ?? 0) > 0);
}

/** 未就绪时的一句话诊断（给门控提示用）。 */
export function readinessHint(sources: SourceSummary[]): string {
  if (!sources.length) return "还没有添加资料——出题与探测只依据你的资料。";
  const bad = sources.filter((s) => sourceStatusView(s).cls !== "ok");
  if (!bad.length) return "";
  const parts = bad.map((s) => `「${s.title || s.type}」${sourceStatusView(s).label}`);
  return `尚无就绪资料：${parts.join("、")}。回到资料来源处理，或删除后重传。`;
}
