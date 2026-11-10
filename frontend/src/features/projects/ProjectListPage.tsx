import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { api, post } from "../../api/client";
import type { Project, ProjectPage } from "../../api/types";
import { Empty, ErrorNotice, Loading } from "../../components";

export function ProjectListPage() {
  const [cursor, setCursor] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [topic, setTopic] = useState("");
  const navigate = useNavigate();
  const client = useQueryClient();
  const list = useQuery({
    queryKey: ["projects", cursor],
    queryFn: ({ signal }) =>
      api<ProjectPage>(
        `/projects?limit=20${cursor ? `&cursor=${cursor}` : ""}`,
        { signal },
      ),
  });
  const create = useMutation({
    mutationFn: () => post<Project>("/projects", { title, topic }),
    onSuccess: (project) => {
      void client.invalidateQueries({ queryKey: ["projects"] });
      void navigate(`/projects/${project.id}/research`);
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }
  return (
    <>
      <header className="page-heading">
        <div>
          <span className="eyebrow">YOUR RESEARCH, CONNECTED</span>
          <h1>
            从一个问题，
            <br />
            走向有据可查的研究。
          </h1>
          <p>检索、分层阅读与综述写作，在同一个研究项目中持续进行。</p>
        </div>
        <span className="folio">工作台 / 01</span>
      </header>
      <div className="home-grid">
        <section>
          <div className="section-heading">
            <h2>研究项目</h2>
            <span>每个主题，独立积累</span>
          </div>
          <ErrorNotice error={list.error} />
          {list.isPending && <Loading />}
          {list.data?.items.length === 0 && (
            <Empty title="你的第一项研究，从这里开始">
              为一个具体的学术问题建立项目，研究计划会在开始后生成。
            </Empty>
          )}
          <div className="project-list">
            {list.data?.items.map((project, index) => (
              <Link
                className="project-row"
                to={`/projects/${project.id}/research`}
                key={project.id}
              >
                <span className="index">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <div>
                  <h3>{project.title}</h3>
                  <p>{project.topic}</p>
                  <small>
                    {new Date(project.updated_at).toLocaleDateString("zh-CN")}
                  </small>
                </div>
                <span aria-hidden>↗</span>
              </Link>
            ))}
          </div>
          <div className="actions">
            {cursor && (
              <button className="quiet" onClick={() => setCursor(null)}>
                回到首页
              </button>
            )}
            {list.data?.next_cursor && (
              <button
                className="quiet"
                onClick={() => setCursor(list.data!.next_cursor)}
              >
                下一页 →
              </button>
            )}
          </div>
        </section>
        <aside className="new-project">
          <span className="eyebrow">START A STUDY</span>
          <h2>建立新的研究项目</h2>
          <form onSubmit={submit}>
            <label>
              项目名称
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                maxLength={300}
                required
                placeholder="例如：知识图谱辅助文献检索"
              />
            </label>
            <label>
              研究主题
              <textarea
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                maxLength={2000}
                required
                rows={5}
                placeholder="描述你希望理解的研究问题、对象和范围…"
              />
            </label>
            <p className="hint">
              建议从一个可回答的问题出发。开始研究后，你可以编辑并确认子问题、年份和资源预算。
            </p>
            <ErrorNotice error={create.error} />
            <button
              className="primary wide"
              disabled={create.isPending || !topic.trim() || !title.trim()}
            >
              {create.isPending ? "正在建立…" : "建立项目 →"}
            </button>
          </form>
          <div className="note-line">
            <span>01</span>
            <p>先看摘要，再按相关性精读。每一次深入，都留下可以回溯的依据。</p>
          </div>
        </aside>
      </div>
    </>
  );
}
