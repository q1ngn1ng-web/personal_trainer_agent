<script setup lang="ts">
import { cn } from "../../lib/utils";
import { cva, type VariantProps } from "class-variance-authority";

const buttonVariants = cva(
  // 基线：内联布局 + 圆角 + 过渡 + 按压 feedback（P2 规则延续）
  "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md border border-transparent font-medium transition-all duration-150 active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40",
  {
    variants: {
      variant: {
        // 青绿只给主操作（spec：黑白灰 + 青绿点缀）
        primary: "bg-primary text-white hover:brightness-110",
        // 中性面：1px 边框 + surface 底
        default: "border-line bg-surface text-text hover:bg-surface-2",
        ghost: "text-muted hover:bg-surface-2 hover:text-text",
        text: "text-primary hover:bg-primary/10",
        danger: "border-danger/30 text-danger hover:bg-danger-weak",
      },
      size: {
        sm: "h-8 px-3 text-[13px]",
        md: "h-9 px-4 text-sm",
      },
    },
    defaultVariants: { variant: "default", size: "md" },
  },
);

const props = defineProps<{
  variant?: VariantProps<typeof buttonVariants>["variant"];
  size?: VariantProps<typeof buttonVariants>["size"];
  class?: string;
}>();
</script>

<template>
  <button :class="cn(buttonVariants({ variant, size }), props.class)">
    <slot />
  </button>
</template>
