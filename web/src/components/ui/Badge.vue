<script setup lang="ts">
import { cn } from "../../lib/utils";
import { cva, type VariantProps } from "class-variance-authority";

// P0 降噪规则延续：默认灰，彩色仅承载语义（ok/warn/danger/info）+ 品牌选中
const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs leading-none",
  {
    variants: {
      tone: {
        default: "border-line bg-surface-2 text-muted",
        ok: "border-ok/30 bg-ok-weak text-ok",
        warn: "border-warn/30 bg-warn-weak text-warn",
        danger: "border-danger/30 bg-danger-weak text-danger",
        info: "border-info/30 bg-info-weak text-info",
        brand: "border-primary/30 bg-primary/10 text-primary",
      },
    },
    defaultVariants: { tone: "default" },
  },
);

const props = defineProps<{
  tone?: VariantProps<typeof badgeVariants>["tone"];
  class?: string;
}>();
</script>

<template>
  <span :class="cn(badgeVariants({ tone }), props.class)">
    <slot />
  </span>
</template>
