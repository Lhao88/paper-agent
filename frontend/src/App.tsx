import {
  NavLink,
  Navigate,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import { ProjectListPage } from "./features/projects/ProjectListPage";
import { ResearchPage } from "./features/research/ResearchPage";
import { PaperTable } from "./features/papers/PaperTable";
import { ReviewReader } from "./features/reviews/ReviewReader";

export default function App() {
  const path = useLocation().pathname;
  const project = path.match(/^\/projects\/([^/]+)/)?.[1];
  return (
    <div className="app-shell">
      <a href="#main" className="skip-link">
        跳到主要内容
      </a>
      <aside className="sidebar">
        <NavLink className="brand" to="/projects">
          <span className="brand-mark">研</span>
          <span>
            知研<small>RESEARCH DESK</small>
          </span>
        </NavLink>
        <span className="nav-label">工作空间</span>
        <nav aria-label="主导航">
          <NavLink to="/projects" end>
            ▦ <span>研究项目</span>
          </NavLink>
          {project && (
            <>
              <NavLink to={`/projects/${project}/research`}>
                ◈ <span>研究概览</span>
              </NavLink>
              <NavLink to={`/projects/${project}/papers`}>
                ▤ <span>文献与证据</span>
              </NavLink>
            </>
          )}
        </nav>
        <div className="sidebar-foot">
          <span className="status-dot" />
          本机研究工作台
          <p>
            每一个判断，
            <br />
            都应有迹可循。
          </p>
          <small>ACADEMIC WORKBENCH / 0.1</small>
        </div>
      </aside>
      <div className="main-shell">
        <div className="topbar">
          <span>知研 / 学术研究工作台</span>
          <span>以问题为起点 · 以证据为依据</span>
        </div>
        <main id="main">
          <Routes>
            <Route path="/projects" element={<ProjectListPage />} />
            <Route
              path="/projects/:projectId/research"
              element={<ResearchPage />}
            />
            <Route
              path="/projects/:projectId/papers"
              element={<PaperTable />}
            />
            <Route
              path="/projects/:projectId/reviews/:artifactId"
              element={<ReviewReader key={path} />}
            />
            <Route path="*" element={<Navigate to="/projects" replace />} />
          </Routes>
        </main>
        <footer>
          知研 RESEARCH DESK <span>AI 辅助研究 · 学术结论需人工核验</span>
        </footer>
      </div>
    </div>
  );
}
