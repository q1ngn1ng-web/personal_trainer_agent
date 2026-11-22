import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** shadcn 模式标配：条件 class 合并 + Tailwind 冲突消解（design D1）。 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
