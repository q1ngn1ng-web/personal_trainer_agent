<script setup lang="ts">
import { cn } from "../../lib/utils";
import { cva, type VariantProps } from "class-variance-authority";

// 平面卡片：1px 边框无阴影（设计基调延续）
const cardVariants = cva("rounded-lg border border-line bg-surface text-text", {
  variants: {
    padding: { none: "", sm: "p-3", md: "p-5" },
  },
  defaultVariants: { padding: "md" },
});

const props = defineProps<{
  padding?: VariantProps<typeof cardVariants>["padding"];
  class?: string;
}>();
</script>

<template>
  <div :class="cn(cardVariants({ padding }), props.class)">
    <slot />
  </div>
</template>
