import { createRouter, createWebHistory } from "vue-router";
import { authState } from "./auth";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "today", component: () => import("./views/TodayView.vue") },
    { path: "/login", name: "login", component: () => import("./views/LoginView.vue") },
    { path: "/dashboard", name: "dashboard", component: () => import("./views/DashboardView.vue") },
    { path: "/trainings", name: "trainings", component: () => import("./views/TrainingsView.vue") },
    { path: "/trainings/:id", name: "training-detail", component: () => import("./views/TrainingDetailView.vue") },
    { path: "/me", name: "me", component: () => import("./views/MeView.vue") },
    { path: "/share/:token", name: "share", component: () => import("./views/ShareView.vue") },
    { path: "/wizard", name: "wizard", component: () => import("./views/WizardView.vue") },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});

router.beforeEach((to) => {
  if (to.name !== "login" && to.name !== "share" && authState.ready && authState.authEnabled && !authState.viewer) {
    return { name: "login" };
  }
  if (to.name === "login" && authState.ready && (!authState.authEnabled || authState.viewer)) {
    return { name: "today" };
  }
});
