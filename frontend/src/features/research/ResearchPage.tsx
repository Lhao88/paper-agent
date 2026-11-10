import { useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorText, post } from "../../api/client";
import type {
  NotebookView,
  PlanDraft,
  PlanView,
  ProjectDetails,
  ResearchSpec,
  ReviewListItem,
  Run,
} from "../../api/types";
import { ErrorNotice, Loading } from "../../components";
import { PlanEditor } from "./PlanEditor";
import { RoundNotes } from "./RoundNotes";
import { pollingInterval, stageLabels, statusLabels } from "./status";

export function ResearchPage() {
  const { projectId } = useParams();
  const [selectedRun, setSelectedRun] = useState("");
  const [yearFrom, setYearFrom] = useState("");
  const [yearTo, setYearTo] = useState("");
  const [preset, setPreset] = useState("standard");
  const startKey = useRef(crypto.randomUUID());
  const approvalKey = useRef(crypto.randomUUID());
  const client = useQueryClient();
  const project = useQuery({
    queryKey: ["project", projectId],
    queryFn: ({ signal }) =>
      api<ProjectDetails>(`/projects/${projectId}`, { signal }),
  });
  const runId = selectedRun || project.data?.runs[0]?.id;
  const run = useQuery({
    queryKey: ["run", runId],
    queryFn: ({ signal }) => api<Run>(`/runs/${runId}`, { signal }),
    enabled: !!runId,
    refetchInterval: (query) => pollingInterval(query.state.data?.status),
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
  });
  const plan = useQuery({
    queryKey: ["plan", runId, run.data?.plan_id],
    queryFn: ({ signal }) => api<PlanView>(`/runs/${runId}/plan`, { signal }),
    enabled: !!run.data?.plan_id,
  });
  const notes = useQuery({
    queryKey: ["notebook", runId, run.data?.status],
    queryFn: ({ signal }) => api<NotebookView>(`/runs/${runId}/notebook`, { signal }),
    enabled: !!runId && !!run.data,
    refetchInterval: (query) => pollingInterval(query.state.data ? run.data?.status : undefined),
  });
  const reviews = useQuery({
    queryKey: ["reviews", projectId, run.data?.status],
    queryFn: ({ signal }) =>
      api<ReviewListItem[]>(`/projects/${projectId}/reviews`, { signal }),
  });
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ["run", runId] });
    void client.invalidateQueries({ queryKey: ["project", projectId] });
  };
  const start = useMutation({
    mutationFn: () =>
      post<Run>(
        `/projects/${projectId}/runs`,
        {
          scope: {
            year_from: yearFrom ? Number(yearFrom) : null,
            year_to: yearTo ? Number(yearTo) : null,
          },
          budgets:
            preset === "small"
              ? {
                  max_candidates: 30,
                  max_screen_papers: 10,
                  max_deep_read_papers: 3,
                  max_llm_calls: 40,
                }
              : {},
        },
        startKey.current,
      ),
    onSuccess: (value) => {
      setSelectedRun(value.id);
      startKey.current = crypto.randomUUID();
      refresh();
    },
  });
  const approve = useMutation({
    mutationFn: (payload: { draft: PlanDraft; spec?: ResearchSpec }) =>
      post<Run>(
        `/runs/${runId}/approve`,
        {
          expected_version: plan.data?.plan.version,
          plan: payload.draft,
          ...(payload.spec ? { spec: payload.spec } : {}),
        },
        approvalKey.current,
      ),
    onSuccess: () => {
      approvalKey.current = crypto.randomUUID();
      refresh();
      void client.invalidateQueries({ queryKey: ["plan", runId] });
    },
  });
  const cancel = useMutation({
    mutationFn: () => post<Run>(`/runs/${runId}/cancel`, {}),
    onSuccess: refresh,
  });
  if (project.isPending) return <Loading />;
  if (!project.data) return <ErrorNotice error={project.error} />;
  const active =
    run.data &&
    ["queued", "running", "waiting_user", "interrupted"].includes(
      run.data.status,
    );
  const current = run.data;
  return (
    <>
      <header className="page-heading compact">
        <div>
          <span className="eyebrow">RESEARCH WORKSPACE</span>
          <h1>{project.data.title}</h1>
          <p>{project.data.topic}</p>
        </div>
        <Link className="quiet" to={`/projects/${projectId}/papers`}>
          打开文献库 ↗
        </Link>
      </header>
      <div className="tabs">
        <span className="active">研究概览</span>
        <Link to={`/projects/${projectId}/papers`}>文献与证据</Link>
        <span className="muted">{project.data.runs.length} 次研究记录</span>
      </div>
      {current && (
        <section className="panel run-panel">
          <div className="section-heading">
            <div>
              <span className="badge">
                {statusLabels[current.status] ?? current.status}
              </span>
              <h2>{stageLabels[current.stage] ?? current.stage}</h2>
            </div>
            <div className="actions">
              <button className="quiet" onClick={refresh}>
                刷新状态
              </button>
              {active && (
                <button
                  className="quiet danger"
                  disabled={cancel.isPending}
                  onClick={() => cancel.mutate()}
                >
                  取消研究
                </button>
              )}
            </div>
          </div>
          <div className="metrics">
            <div>
              <strong>{current.counts?.screening ?? 0}</strong>
              <span>已初读文献</span>
            </div>
            <div>
              <strong>{current.counts?.reading ?? 0}</strong>
              <span>已完成精读</span>
            </div>
            <div>
              <strong>
                {current.used_calls}
                <small> / {current.max_calls}</small>
              </strong>
              <span>模型调用</span>
            </div>
            <div>
              <strong>{current.used_source_requests}</strong>
              <span>来源请求</span>
            </div>
          </div>
          <p className="hint">
            累计研究 {Math.round(current.active_elapsed_seconds)} 秒 · 已报告{" "}
            {current.used_tokens.toLocaleString()} token · 预留{" "}
            {current.reserved_tokens.toLocaleString()} token ·
            等待确认不计入研究时间
          </p>
          {current.config_snapshot.llm_mode === "mock" && (
            <div className="notice">
              当前使用合成语料与模拟模型，演示结果不能作为真实学术结论。
            </div>
          )}
          {current.unknown_calls > 0 && (
            <div className="notice error">
              有 {current.unknown_calls}{" "}
              次模型调用结果未知，预留用量未释放。请先核对供应商账单与调用记录。
            </div>
          )}
          {current.suspected_interruption && (
            <div className="notice error">
              worker心跳已失联，需确认旧进程退出后恢复。
            </div>
          )}
          {current.error_json && (
            <div className="notice error">
              停止原因：
              {String(current.error_json.message ?? current.error_json.code)}
              。已保存的文献和成果仍可查阅。
            </div>
          )}
          {current.status === "queued" && (
            <p className="hint">
              任务已入队。若长时间未推进，请确认独立 worker 已启动。
            </p>
          )}
          <ErrorNotice error={run.error || cancel.error} />
        </section>
      )}
      {!!notes.data?.pages.length && (
        <RoundNotes
          pages={notes.data.pages}
          unmet={notes.data.unmet_question_ids ?? []}
        />
      )}
      {current?.status === "waiting_user" && plan.data && (
        <PlanEditor
          key={plan.data.plan.plan_id}
          plan={plan.data.plan}
          spec={plan.data.spec}
          busy={approve.isPending}
          error={approve.error ? errorText(approve.error) : undefined}
          onApprove={(draft, spec) => approve.mutate({ draft, spec })}
        />
      )}
      {!active && (
        <section className="panel">
          <div className="section-heading">
            <h2>{current ? "开始后续研究" : "准备开始研究"}</h2>
            <span className="eyebrow">01 / DEFINE THE SCOPE</span>
          </div>
          <p className="muted">
            先生成可编辑的研究计划。计划确认后，才会开始检索与精读。
          </p>
          <div className="field-pair">
            <label>
              起始年份
              <input
                type="number"
                min={1800}
                max={2200}
                value={yearFrom}
                onChange={(e) => setYearFrom(e.target.value)}
                placeholder="不限"
              />
            </label>
            <label>
              截止年份
              <input
                type="number"
                min={1800}
                max={2200}
                value={yearTo}
                onChange={(e) => setYearTo(e.target.value)}
                placeholder="不限"
              />
            </label>
          </div>
          <label>
            资源预设
            <select value={preset} onChange={(e) => setPreset(e.target.value)}>
              <option value="standard">标准 · 使用服务器默认预算</option>
              <option value="small">
                小样本 · 30篇候选 / 10篇初读 / 3篇精读
              </option>
            </select>
          </label>
          <ErrorNotice error={start.error} />
          <button
            className="primary"
            disabled={start.isPending}
            onClick={() => start.mutate()}
          >
            {start.isPending ? "正在提交…" : "生成研究计划 →"}
          </button>
        </section>
      )}
      <section>
        <div className="section-heading">
          <h2>可阅读的研究成果</h2>
          <span>保存每一个版本</span>
        </div>
        {!reviews.data?.length && (
          <p className="muted">
            综述生成后会出现在这里。研究停止时，可先到文献库查看已经整理的资料。
          </p>
        )}
        {reviews.data?.map((item) => (
          <Link
            className="review-link"
            key={item.id}
            to={`/projects/${projectId}/reviews/${item.id}`}
          >
            <div>
              <span className="eyebrow">
                LITERATURE REVIEW · V{item.version}
              </span>
              <h3>
                {item.origin === "review_edit" ? "用户编辑综述" : "研究综述"}
              </h3>
              <small>{new Date(item.created_at).toLocaleString("zh-CN")}</small>
            </div>
            <span>阅读综述 ↗</span>
          </Link>
        ))}
      </section>
    </>
  );
}
