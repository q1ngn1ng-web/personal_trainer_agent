<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { wizardApi, type ClarifySession, type ProbePaper, type ProbeGrade } from "../api_wizard";
import type { SourceSummary } from "../api";
import { api } from "../api";
import { sourceStatusView, sourcesReady, readinessHint } from "../lib/sourceStatus";

const router = useRouter();
const step = ref(1);
const error = ref("");
const busy = ref(false);

// 第 1 步：澄清
const topic = ref("");
const session = ref<ClarifySession | null>(null);
const answer = ref("");

// 训练节奏（user-defined-training-plan）：UI 控件收集，非对话；变更即提交
const paceWeeks = ref(2);
const paceSessions = ref(3);
const paceBusy = ref(false);
const paceRecommended = computed(() => session.value?.pace?.recommended ?? null);

async function onPaceChange() {
  if (!tid.value || paceBusy.value) return;
  paceBusy.value = true;
  try {
    session.value = await wizardApi.setPace(tid.value, paceWeeks.value, paceSessions.value);
    syncDraftControls();
  } catch (e: any) {
    error.value = e.message || "节奏保存失败";
  } finally {
    paceBusy.value = false;
  }
}

// 草案字段编辑（change 澄清编辑）：content/level/acceptance 与节奏一样可直接改
const draftContent = ref("");
const draftLevel = ref("");
const draftAcceptance = ref("");
const draftBusy = ref(false);
const LEVEL_OPTIONS = ["了解", "会用", "熟练", "能讲清"];

function formatAcceptance(value: unknown): string {
  if (!value) return "";
  if (typeof value === "string") return value;
  const v = value as any;
  if (v.type === "quantitative") {
    const metricLabel: Record<string, string> = {
      accuracy: "正确率", volume: "完成量", speed: "速度", streak: "连续通过",
    };
    const target = v.metric === "accuracy" ? `${Math.round(Number(v.target) * 100)}%` : String(v.target);
    return `量化判据：${metricLabel[v.metric] || v.metric} 达到 ${target}`;
  }
  if (v.type === "qualitative") {
    return `质性判据：${v.statement || ""}${v.check ? `（检查方式：${v.check}）` : ""}`;
  }
  return String(value);
}

function syncDraftControls() {
  const draft = session.value?.draft;
  if (!draft) return;
  draftContent.value = draft.content || "";
  draftLevel.value = draft.level || "";
  draftAcceptance.value = formatAcceptance(draft.acceptance);
}

async function saveDraftFields() {
  if (!tid.value || draftBusy.value) return;
  draftBusy.value = true;
  try {
    const body: { content?: string; level?: string; acceptance?: unknown } = {};
    if (draftContent.value.trim() && draftContent.value.trim() !== (session.value?.draft.content || "")) {
      body.content = draftContent.value.trim();
    }
    if (draftLevel.value && draftLevel.value !== (session.value?.draft.level || "")) {
      body.level = draftLevel.value;
    }
    const rawAcceptance = draftAcceptance.value.trim();
    if (rawAcceptance && rawAcceptance !== formatAcceptance(session.value?.draft.acceptance)) {
      body.acceptance = rawAcceptance;
    }
    if (!Object.keys(body).length) {
      toast("草案没有改动");
      return;
    }
    session.value = await wizardApi.updateDraftFields(tid.value, body);
    syncDraftControls();
    toast("草案已更新（AI 不会再覆盖你改过的字段）");
  } catch (e: any) {
    toast(e.message || "草案保存失败");
  } finally {
    draftBusy.value = false;
  }
}

// 会话响应后同步节奏控件：未设置时用推荐值并自动以 user_input 落快照（默认节奏）
function syncPaceControls() {
  const pace = session.value?.pace;
  if (!pace) return;
  if (pace.horizon_weeks == null || pace.session_count == null) {
    const rec = pace.recommended;
    paceWeeks.value = Math.max(1, Math.round((rec?.horizon_days ?? 14) / 7));
    paceSessions.value = rec?.session_count ?? 3;
    if (tid.value) onPaceChange();
  } else {
    paceWeeks.value = pace.horizon_weeks;
    paceSessions.value = pace.session_count;
  }
}

function applyRecommendedPace() {
  if (!paceRecommended.value) return;
  paceWeeks.value = Math.max(1, Math.round(paceRecommended.value.horizon_days / 7));
  paceSessions.value = paceRecommended.value.session_count;
  onPaceChange();
}

// 第 2 步：资料
const sourceTab = ref<"text" | "url" | "file">("text");
const srcTitle = ref("");
const srcContent = ref("");
const srcUrl = ref("");
const srcFile = ref<File | null>(null);
const sources = ref<SourceSummary[]>([]);

// 第 3 步：探测
const probePaper = ref<ProbePaper | null>(null);
const probeAnswers = ref<string[]>([]);
const probeGraded = ref<ProbeGrade | null>(null);
const probeSkipped = ref(false);

// 第 4 步：完成
const pathResult = ref<{ stages: number; items: number } | null>(null);
const activated = ref(false);

const tid = computed(() => session.value?.training_id ?? null);

// 进度持久化（用户报"刷新后回不到创建页"）：tid+step 存 localStorage，挂载时恢复
const RESUME_KEY = "wizard-in-progress";
const resumed = ref(false);
function saveProgress(step: number) {
  if (tid.value) localStorage.setItem(RESUME_KEY, JSON.stringify({ tid: tid.value, step }));
}
function clearProgress() {
  localStorage.removeItem(RESUME_KEY);
}

function abandonDraft() {
  clearProgress();
  session.value = null;
  sources.value = [];
  step.value = 1;
  topic.value = "";
  resumed.value = false;
  toast("已放弃该草稿——重新开始即可（草稿仍可在「我的训练」里删除）");
}

function toast(msg: string) {
  (window as any).__toast?.(msg);
}

async function startClarify() {
  if (topic.value.trim().length < 4) {
    error.value = "多用一句话描述你想学什么（例如：我想系统学习 MySQL 索引优化）";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    session.value = await wizardApi.start(topic.value.trim());
    syncPaceControls();
    syncDraftControls();
    saveProgress(1);
  } catch (e: any) {
    error.value = e.message || "启动失败";
  } finally {
    busy.value = false;
  }
}

async function sendAnswer() {
  if (!tid.value || !answer.value.trim()) return;
  busy.value = true;
  error.value = "";
  try {
    session.value = await wizardApi.answer(tid.value, answer.value.trim());
    answer.value = "";
    syncPaceControls();
    syncDraftControls();
  } catch (e: any) {
    error.value = e.message || "提交失败";
  } finally {
    busy.value = false;
  }
}

async function confirmGoal() {
  if (!tid.value) return;
  busy.value = true;
  try {
    await wizardApi.confirm(tid.value);
    const res = await api.sources(tid.value);
    sources.value = res.sources;
    step.value = 2;
    saveProgress(2);
  } catch (e: any) {
    error.value = e.message || "确认失败";
  } finally {
    busy.value = false;
  }
}

const FIELD_LABEL: Record<string, string> = {
  content: "学习内容",
  level: "目标等级",
  acceptance: "验收标准",
  horizon_days: "训练总时长",
  session_count: "训练次数",
};

// 第 2 步：资料来源操作
async function addSource() {
  if (!tid.value) return;
  busy.value = true;
  error.value = "";
  try {
    if (sourceTab.value === "text") {
      if (!srcContent.value.trim()) throw new Error("先粘贴一些学习资料");
      await wizardApi.addSource(tid.value, {
        type: "text", title: srcTitle.value.trim() || "粘贴的资料", content: srcContent.value,
      });
      srcContent.value = ""; srcTitle.value = "";
    } else if (sourceTab.value === "url") {
      if (!srcUrl.value.trim()) throw new Error("先填写网址");
      await wizardApi.addSource(tid.value, { type: "url", url: srcUrl.value.trim() });
      srcUrl.value = "";
    }
    const res = await api.sources(tid.value);
    sources.value = res.sources;
  } catch (e: any) {
    error.value = e.message || "添加失败";
  } finally {
    busy.value = false;
  }
}

async function uploadFile() {
  if (!tid.value || !srcFile.value) return;
  busy.value = true;
  error.value = "";
  try {
    await wizardApi.uploadSource(tid.value, srcFile.value);
    const res = await api.sources(tid.value);
    sources.value = res.sources;
    srcFile.value = null;
  } catch (e: any) {
    error.value = e.message || "上传失败";
  } finally {
    busy.value = false;
  }
}

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement;
  srcFile.value = input.files && input.files[0] ? input.files[0] : null;
}

// 资料就绪判定（探测出题的硬前提）：至少一份启用+解析成功+有切片
const probeReady = computed(() => sourcesReady(sources.value));

async function gotoProbe() {
  // 进入探测步前重拉资料状态，避免拿着旧状态做门控
  if (tid.value) {
    try {
      const res = await api.sources(tid.value);
      sources.value = res.sources;
    } catch {
      /* 网络失败时按现有列表判定 */
    }
  }
  step.value = 3;
  error.value = "";
  saveProgress(3);
}

// 第 3 步：探测
async function generateProbe() {
  if (!tid.value) return;
  busy.value = true;
  error.value = "";
  try {
    probePaper.value = await wizardApi.generateProbe(tid.value);
    probeAnswers.value = new Array(probePaper.value.items.length).fill("");
  } catch (e: any) {
    error.value = e.message || "出题失败";
  } finally {
    busy.value = false;
  }
}

async function gradeProbe() {
  if (!tid.value || !probePaper.value) return;
  busy.value = true;
  error.value = "";
  try {
    const items = probePaper.value.items.map((it, i) => ({
      ...it,
      answer: probeAnswers.value[i] || "未作答",
    }));
    probeGraded.value = await wizardApi.gradeProbe(tid.value, items as any);
  } catch (e: any) {
    error.value = e.message || "判定失败";
  } finally {
    busy.value = false;
  }
}

async function skipProbe() {
  probeSkipped.value = true;
  await activateAndPath();
}

async function activateAndPath() {
  if (!tid.value) return;
  busy.value = true;
  error.value = "";
  try {
    await wizardApi.activate(tid.value);
    activated.value = true;
    step.value = 4;
    clearProgress();
  } catch (e: any) {
    error.value = e.message || "激活失败";
  } finally {
    busy.value = false;
  }
}

async function generatePath() {
  if (!tid.value) return;
  busy.value = true;
  try {
    pathResult.value = await wizardApi.generatePath(tid.value);
  } catch (e: any) {
    error.value = e.message || "路径生成失败";
  } finally {
    busy.value = false;
  }
}

onMounted(async () => {
  const saved = localStorage.getItem(RESUME_KEY);
  if (!saved) return;
  try {
    const { tid: savedTid, step: savedStep } = JSON.parse(saved);
    const ts = await api.trainings();
    const t = ts.trainings.find((x) => x.id === savedTid);
    if (!t) {
      localStorage.removeItem(RESUME_KEY);
      return;
    }
    if (t.status === "draft" || t.status === "pending_confirm") {
      // 澄清中：恢复会话与草案（含节奏/字段编辑），从第 1 步继续
      session.value = await wizardApi.clarifyState(savedTid);
      step.value = 1;
      syncPaceControls();
      syncDraftControls();
      resumed.value = true;
      toast("已回到上次的创建进度");
    } else if (t.status === "confirmed") {
      // 目标已确认：恢复到资料来源步（探测可重新生成）
      session.value = await wizardApi.clarifyState(savedTid);
      const res = await api.sources(savedTid);
      sources.value = res.sources;
      step.value = Math.max(2, Math.min(savedStep || 2, 2));
      resumed.value = true;
      toast("已回到资料来源步骤——完成理解探测即可激活训练");
    } else {
      // 已激活/完成：向导使命结束
      localStorage.removeItem(RESUME_KEY);
    }
  } catch (e: any) {
    localStorage.removeItem(RESUME_KEY);
  }
});

const STATE_LABEL: Record<string, string> = {
  mastered: "已掌握（跳过）",
  edge: "边缘（教学重点）",
  unreached: "未达（先铺垫）",
};
</script>

<template>
  <div>
    <div class="wizard-steps">
      <div class="wstep" :class="{ active: step === 1, done: step > 1 }"><span class="n">{{ step > 1 ? '✓' : 1 }}</span>澄清目标</div>
      <div class="wstep" :class="{ active: step === 2, done: step > 2 }"><span class="n">{{ step > 2 ? '✓' : 2 }}</span>资料来源</div>
      <div class="wstep" :class="{ active: step === 3, done: step > 3 }"><span class="n">{{ step > 3 ? '✓' : 3 }}</span>理解探测</div>
      <div class="wstep" :class="{ active: step === 4, done: step > 4 }"><span class="n">4</span>开始训练</div>
    </div>

    <div v-if="error" class="error-tip">{{ error }}</div>

    <!-- 第 1 步：澄清目标 -->
    <div v-if="step === 1" class="card">
      <template v-if="!session">
        <div class="card-title" style="margin-bottom: 6px;">你想学什么？</div>
        <p style="color: var(--muted); font-size: 14px; margin-bottom: 14px;">
          用一句话描述。AI 会追问补全三个目标字段：学习内容 / 目标等级 / 验收标准。
        </p>
        <textarea v-model="topic" class="textarea" placeholder="例如：我想系统学习 MySQL 索引优化，能应付后端面试"></textarea>
        <button class="btn primary" style="margin-top: 12px;" :disabled="busy" @click="startClarify">
          {{ busy ? 'AI 正在理解…' : '开始澄清 →' }}
        </button>
      </template>

      <template v-else>
        <div v-if="resumed" style="display: flex; justify-content: flex-end; margin-bottom: 8px;">
          <button class="btn ghost sm" @click="abandonDraft">放弃这个草稿，重新开始</button>
        </div>
        <div class="chat-box">
          <div class="chat-line ai">
            <div class="who">AI 教练</div>
            <div class="bubble">{{ session.question || '我先记录一下你的目标，看看还缺什么。' }}</div>
          </div>
          <div v-for="(h, i) in session.history.filter((x) => x.role === 'user') " :key="i" class="chat-line user">
            <div class="who">你</div>
            <div class="bubble">{{ h.content }}</div>
          </div>
        </div>

        <div class="draft-box">
          <div class="card-title" style="font-size: 14px; margin-bottom: 8px;">训练节奏</div>
          <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap; font-size: 13.5px;">
            <label>总时长
              <select v-model.number="paceWeeks" class="input" style="width: auto; padding: 5px 8px; margin-left: 4px;" :disabled="paceBusy" @change="onPaceChange">
                <option v-for="w in 8" :key="w" :value="w">{{ w }} 周</option>
              </select>
            </label>
            <label>训练次数
              <select v-model.number="paceSessions" class="input" style="width: auto; padding: 5px 8px; margin-left: 4px;" :disabled="paceBusy" @change="onPaceChange">
                <option v-for="c in 5" :key="c + 1" :value="c + 1">{{ c + 1 }} 次</option>
              </select>
            </label>
            <button
              v-if="paceRecommended && (paceWeeks !== Math.round(paceRecommended.horizon_days / 7) || paceSessions !== paceRecommended.session_count)"
              class="btn ghost sm" :disabled="paceBusy" @click="applyRecommendedPace"
            >
              用推荐（{{ Math.round(paceRecommended.horizon_days / 7) }} 周 × {{ paceRecommended.session_count }} 次）
            </button>
          </div>
          <div style="font-size: 12px; color: var(--faint); margin-top: 6px;">
            系统按此节奏安排会话：每次覆盖部分知识点，复习与错题回炉按你的近期表现动态配比；对话里 AI 不再追问这些。
          </div>
        </div>

        <div class="draft-box">
          <div class="card-head" style="margin-bottom: 8px;">
            <div class="card-title" style="font-size: 14px;">
              训练标题：<span style="color: var(--brand);">{{ session.title || '（生成中…）' }}</span>
            </div>
            <div style="font-size: 12px; color: var(--faint);">AI 根据你的描述起的名字，会显示在「我的训练」列表里</div>
          </div>
          <div class="card-head" style="margin-bottom: 8px; margin-top: 10px;">
            <div class="card-title" style="font-size: 14px;">目标草案（可直接编辑，AI 不会覆盖你改过的字段）</div>
            <button class="btn sm" :disabled="draftBusy" @click="saveDraftFields">
              {{ draftBusy ? '保存中…' : '保存修改' }}
            </button>
          </div>
          <div class="row" style="align-items: center; gap: 8px;">
            <span class="k" style="flex-shrink: 0;">学习内容</span>
            <input v-model="draftContent" class="input" style="flex: 1; padding: 5px 9px; font-size: 13.5px;" placeholder="学习内容（待补全）" />
          </div>
          <div class="row" style="align-items: center; gap: 8px; margin-top: 6px;">
            <span class="k" style="flex-shrink: 0;">目标等级</span>
            <select v-model="draftLevel" class="input" style="width: auto; padding: 5px 9px; font-size: 13.5px;">
              <option value="">（待定——AI 建议）</option>
              <option v-for="lv in LEVEL_OPTIONS" :key="lv" :value="lv">{{ lv }}</option>
            </select>
          </div>
          <div style="margin-top: 6px;">
            <span class="k" style="font-size: 12.5px; color: var(--muted);">验收标准（AI 先给一版，不满意直接改）</span>
            <textarea v-model="draftAcceptance" class="textarea" style="min-height: 52px; margin-top: 4px; font-size: 13px;"
              placeholder="怎样才算学会？给一个能验证的说法，比如「10 题对 8 题」或「能不看稿讲清核心内容」"></textarea>
          </div>
          <div v-if="session.missing_fields.length" style="font-size: 12.5px; color: var(--warn); margin-top: 4px;">
            还缺：{{ session.missing_fields.map((f) => FIELD_LABEL[f] || f).join('、') }}（可直接在上面改，也可以继续对话）
          </div>
        </div>

        <div style="display: flex; gap: 8px; margin-top: 14px;">
          <textarea v-if="!session.can_confirm" v-model="answer" class="textarea" style="min-height: 60px;"
            placeholder="回答 AI 的问题，或直接补充目标信息" @keyup.ctrl.enter="sendAnswer"></textarea>
        </div>
        <div style="display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap;">
          <button v-if="!session.can_confirm" class="btn primary" :disabled="busy" @click="sendAnswer">
            {{ busy ? 'AI 思考中…' : '发送回答' }}
          </button>
          <button class="btn ghost" :disabled="busy || !session.can_confirm" @click="confirmGoal">
            {{ session.can_confirm ? '✓ 确认目标，去加资料' : '目标完整后可确认' }}
          </button>
        </div>
      </template>
    </div>

    <!-- 第 2 步：资料来源 -->
    <div v-else-if="step === 2" class="card">
      <div class="card-title" style="margin-bottom: 6px;">给训练配资料</div>
      <p style="color: var(--muted); font-size: 13.5px; margin-bottom: 14px;">
        出题与探测只依据这些资料（不考资料之外的内容）。三种来源，加多少都行——
        <b>至少一份资料解析成功（有切片）才能进入理解探测</b>。
      </p>

      <div class="section-switch" style="margin-bottom: 14px;">
        <button :class="{ active: sourceTab === 'text' }" @click="sourceTab = 'text'">粘贴文本</button>
        <button :class="{ active: sourceTab === 'url' }" @click="sourceTab = 'url'">网页 URL</button>
        <button :class="{ active: sourceTab === 'file' }" @click="sourceTab = 'file'">上传文件</button>
      </div>

      <template v-if="sourceTab === 'text'">
        <div class="field"><label>标题</label><input v-model="srcTitle" class="input" placeholder="给这份资料起个名" /></div>
        <div class="field"><label>内容</label><textarea v-model="srcContent" class="textarea" style="min-height: 140px;" placeholder="粘贴学习资料、笔记、八股要点…"></textarea></div>
        <button class="btn primary sm" :disabled="busy" @click="addSource">{{ busy ? '处理中…' : '添加资料' }}</button>
      </template>
      <template v-else-if="sourceTab === 'url'">
        <div class="field"><label>网址</label><input v-model="srcUrl" class="input" placeholder="https://…" /></div>
        <button class="btn primary sm" :disabled="busy" @click="addSource">{{ busy ? '抓取中…' : '抓取并添加' }}</button>
        <p style="font-size: 12.5px; color: var(--faint); margin-top: 8px;">会保存网页正文快照（ADR-0008），原网址可追溯。</p>
      </template>
      <template v-else>
        <div class="field"><label>文件（PDF / Word / Excel / Markdown）</label><input type="file" class="input" @change="onFileChange" /></div>
        <button class="btn primary sm" :disabled="busy || !srcFile" @click="uploadFile">{{ busy ? '解析中…' : '上传并解析' }}</button>
      </template>

      <div v-if="sources.length" style="margin-top: 18px;">
        <div style="font-size: 13px; font-weight: 600; color: var(--muted); margin-bottom: 6px;">
          已添加 {{ sources.length }} 份 · 每份资料走到哪一步：
          上传 ✓ → 解析 ✓ → 切片（见各条状态）
        </div>
        <div v-for="s in sources" :key="s.id" class="list-item" style="cursor: default; align-items: flex-start;">
          <span style="margin-top: 2px;">{{ s.type === 'user_paste' ? '粘贴' : s.type === 'web_url' ? '链接' : s.type === 'user_upload' ? '文件' : 'AI 生成' }}</span>
          <div style="flex: 1; min-width: 0;">
            <div style="font-size: 14px;">{{ s.title }}</div>
            <div
              v-if="sourceStatusView(s).hint"
              style="font-size: 12px; color: var(--warn); margin-top: 2px;"
            >{{ sourceStatusView(s).hint }}</div>
          </div>
          <span class="badge" :class="sourceStatusView(s).cls">{{ sourceStatusView(s).label }}</span>
        </div>
      </div>

      <div style="display: flex; gap: 8px; margin-top: 16px; align-items: center; flex-wrap: wrap;">
        <button class="btn ghost sm" @click="step = 1">← 上一步</button>
        <button class="btn primary" :disabled="!probeReady || busy" @click="gotoProbe">下一步：理解探测 →</button>
        <span v-if="!probeReady" style="font-size: 12.5px; color: var(--warn);">{{ readinessHint(sources) }}</span>
      </div>
    </div>

    <!-- 第 3 步：理解边缘探测 -->
    <div v-else-if="step === 3" class="card">
      <div class="card-title" style="margin-bottom: 6px;">定位你的理解边缘</div>
      <p style="color: var(--muted); font-size: 13.5px; margin-bottom: 14px;">
        每个知识点答一题，判定三态：已掌握 / 边缘 / 未达。训练会从「边缘」重点教，
        「未达」先铺垫。不查资料凭理解作答，不会就写「不会」。
      </p>

      <template v-if="!probePaper && !probeSkipped">
        <div v-if="!probeReady" class="error-tip" style="margin-bottom: 12px;">
          {{ readinessHint(sources) }}
          <button class="btn ghost sm" style="margin-left: 8px;" @click="step = 2">← 回资料来源</button>
        </div>
        <button class="btn primary" :disabled="busy || !probeReady" @click="generateProbe">
          {{ busy ? 'AI 出题中…' : '开始探测出题' }}
        </button>
        <button class="btn text" style="margin-left: 8px;" :disabled="busy" @click="skipProbe">
          跳过探测（按中位难度起步）
        </button>
        <p v-if="!probeReady" style="font-size: 12.5px; color: var(--faint); margin-top: 8px;">
          没有资料时跳过探测，训练路径会为空——建议先回上一步补资料。
        </p>
      </template>

      <template v-else-if="probePaper && !probeGraded">
        <div v-if="probePaper.fallback_used" class="ok-tip" style="background: var(--warn-weak); color: var(--warn);">模型出题失败，已退回按知识点生成的朴素问法。</div>
        <div v-for="(item, i) in probePaper.items" :key="i" style="margin-bottom: 16px;">
          <div class="question-box" style="margin-bottom: 8px;">
            <span style="color: var(--faint); font-size: 12px;">Q{{ i + 1 }} · {{ item.knowledge_point }} · 难度 {{ '★'.repeat(Math.max(1, Math.min(4, item.difficulty))) }}</span>
            <div style="margin-top: 4px;">{{ item.question }}</div>
          </div>
          <textarea v-model="probeAnswers[i]" class="textarea" placeholder="凭理解作答；不会就写「不会」"></textarea>
        </div>
        <div style="display: flex; gap: 8px;">
          <button class="btn ghost sm" :disabled="busy" @click="step = 2">← 上一步</button>
          <button class="btn primary" :disabled="busy" @click="gradeProbe">{{ busy ? 'AI 判定中…' : '提交并判定 →' }}</button>
        </div>
      </template>

      <template v-else-if="probeGraded">
        <div class="stat-row">
          <div class="stat"><div class="num">{{ probeGraded.counts.mastered }}</div><div class="lbl">已掌握（跳过）</div></div>
          <div class="stat"><div class="num">{{ probeGraded.counts.edge }}</div><div class="lbl">边缘（重点）</div></div>
          <div class="stat"><div class="num">{{ probeGraded.counts.unreached }}</div><div class="lbl">未达（铺垫）</div></div>
        </div>
        <div v-for="(g, i) in probeGraded.items" :key="i" style="padding: 10px 0; border-bottom: 1px dashed var(--line);">
          <div style="display: flex; align-items: center; gap: 8px;">
            <span class="badge" :class="g.state === 'mastered' ? 'ok' : g.state === 'edge' ? 'info' : 'warn'">{{ STATE_LABEL[g.state || ''] || g.state }}</span>
            <span style="font-weight: 600; font-size: 14px;">{{ g.knowledge_point }}</span>
          </div>
          <p v-if="g.reason" style="font-size: 12.5px; color: var(--faint); margin-top: 4px;">{{ g.reason }}</p>
        </div>
        <button class="btn primary" style="margin-top: 14px;" :disabled="busy" @click="activateAndPath">
          {{ busy ? '处理中…' : '激活训练 →' }}
        </button>
      </template>
    </div>

    <!-- 第 4 步：开始训练 -->
    <div v-else class="card">
      <div style="text-align: center; padding: 16px 0;">
        <div style="font-size: 44px;">✓</div>
        <h2 style="margin: 8px 0 4px;">训练已就绪</h2>
        <p style="color: var(--muted); font-size: 14px;">
          {{ probeSkipped ? '你跳过了探测：训练项按中位难度起步，会在训练中用实际表现修正。' : '训练路径将根据探测结果分层生成。' }}
        </p>
      </div>

      <div v-if="!pathResult" style="text-align: center; padding: 8px 0 20px;">
        <button class="btn primary" :disabled="busy" @click="generatePath">
          {{ busy ? 'AI 生成路径中（约 30 秒）…' : '生成训练路径' }}
        </button>
      </div>
      <div v-else style="text-align: center; padding: 8px 0 20px;">
        <div class="ok-tip" style="display: inline-block;">
          路径已生成：{{ pathResult.stages }} 个阶段 · {{ pathResult.items }} 个训练项
        </div>
        <div style="margin-top: 14px; display: flex; gap: 10px; justify-content: center;">
          <button class="btn primary" @click="router.push({ name: 'today' })">去今日训练 →</button>
          <button class="btn ghost" v-if="tid" @click="router.push('/trainings/' + tid)">查看路径详情</button>
        </div>
      </div>
    </div>
  </div>
</template>
