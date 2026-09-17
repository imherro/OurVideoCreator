export const PAYWALL_ROLES = ["none", "setup", "conversion", "retention", "major_cliffhanger"] as const;
export const DURATION_OPTIONS = [15, 30, 45, 60, 90, 120, 180] as const;
export const RATIO_OPTIONS = ["16:9", "9:16", "1:1"] as const;
export const PLATFORM_OPTIONS = ["通用短视频", "抖音", "快手", "红果短剧", "微信视频号", "小红书", "B站", "YouTube"] as const;

export const STATUS_LABELS: Record<string, string> = {
  draft: "草稿",
  review: "待审核",
  approved: "已批准",
  stale: "已过期",
};

export const PAYWALL_LABELS: Record<string, string> = {
  none: "无",
  setup: "付费铺垫",
  conversion: "转付费",
  retention: "留存",
  major_cliffhanger: "强悬念",
};

export type EpisodePlan = {
  episodeNo: number;
  sourceChapterRefs: string[];
  logline: string;
  coreConflict: string;
  emotionalBeat: string;
  hook: string;
  cliffhanger: string;
  paywallRole: string;
  targetDuration: number;
  status: string;
};

export function createEpisodePlans(count: number, targetDuration: number, previous: EpisodePlan[] = []) {
  const safeCount = Math.max(1, Math.min(500, Math.round(Number(count) || 1)));
  const old = new Map(previous.map((plan) => [plan.episodeNo, plan]));
  return Array.from({ length: safeCount }, (_, index): EpisodePlan => {
    const episodeNo = index + 1;
    return old.get(episodeNo) || {
      episodeNo,
      sourceChapterRefs: [],
      logline: "",
      coreConflict: "",
      emotionalBeat: "",
      hook: "",
      cliffhanger: "",
      paywallRole: "none",
      targetDuration: Number(targetDuration) || 60,
      status: "draft",
    };
  });
}

export function appendEpisodeForChapter(previous: EpisodePlan[], targetDuration: number, chapterId = "") {
  const plans = createEpisodePlans(previous.length + 1, targetDuration, previous);
  if (chapterId) plans[plans.length - 1] = { ...plans[plans.length - 1], sourceChapterRefs: [chapterId] };
  return plans;
}

// A production-scoped planning focus may point at a plan whose Episode project
// has not been created yet.  Prefer that focus; otherwise lead the user to the
// first unfinished and unprotected plan instead of silently returning to EP01.
export function resolvePlanningEpisode(
  plans: Pick<EpisodePlan, "episodeNo" | "status">[],
  preferred?: number,
  protectedEpisodeNos: number[] = [],
) {
  if (preferred && plans.some((plan) => plan.episodeNo === preferred)) return preferred;
  return plans.find((plan) => plan.status !== "approved" && !protectedEpisodeNos.includes(plan.episodeNo))?.episodeNo
    || plans[0]?.episodeNo || 0;
}

export function normalizeEpisodeSelection(values: Iterable<number>, episodeCount: number) {
  return [...new Set(values)]
    .filter((value) => Number.isInteger(value) && value >= 1 && value <= episodeCount)
    .sort((a, b) => a - b);
}

export function splitList(value: string) {
  return [...new Set(value.split(/[，,\n]/).map((item) => item.trim()).filter(Boolean))];
}
