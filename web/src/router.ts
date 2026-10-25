import { createRouter, createWebHistory } from "vue-router";
import { authState } from "./auth";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "today", component: () => import("./views/TodayView.vue") },
    { path: "/login", name: "login", component: () => import("./views/LoginView.vue") },
    { path: "/trainings", name: "trainings", component: () => import("./views/TrainingsView.vue") },
    { path: "/trainings/:id", name: "training-detail", component: () => import("./views/TrainingDetailView.vue") },
    { path: "/me", name: "me", component: () => import("./views/MeView.vue") },
    { path: "/wizard", name: "wizard", component: () => import("./views/WizardView.vue") },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});

router.beforeEach((to) => {
  if (to.name !== "login" && authState.ready && authState.authEnabled && !authState.viewer) {
    return { name: "login" };
  }
  if (to.name === "login" && authState.ready && (!authState.authEnabled || authState.viewer)) {
    return { name: "today" };
  }
});
