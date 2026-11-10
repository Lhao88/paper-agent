export const stageLabels: Record<string, string> = {
  plan: "研究规划",
  approve_plan: "等待确认计划",
  retrieve: "检索文献",
  screen: "摘要初读",
  select: "精读选择",
  read: "文献精读",
  analyze: "综合分析",
  decide: "检查研究缺口",
  write: "综述写作",
  validate: "引用检查",
  finalize: "保存成果",
  done: "已完成",
  begin_round: "开始新一轮",
  propose: "规划本轮动作",
  execute: "执行检索",
  screen_new: "筛选新文献",
  read_selected: "阅读入选文献",
  note: "记录本轮笔记",
};
export const statusLabels: Record<string, string> = {
  queued: "等待执行",
  running: "研究中",
  waiting_user: "需要确认",
  interrupted: "运行中断",
  completed: "已完成",
  partial: "部分成果",
  failed: "运行失败",
  cancelled: "已取消",
};
export function pollingInterval(status?: string): number | false {
  return status &&
    ["completed", "partial", "failed", "cancelled", "interrupted"].includes(
      status,
    )
    ? false
    : 2000;
}
export function relevanceLabel(value: number | null | undefined): string {
  return value == null ? "信息不足" : `${value} / 4`;
}
