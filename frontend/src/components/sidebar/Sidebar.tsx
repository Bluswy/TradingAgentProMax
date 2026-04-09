import type { Research } from "../../types";
import { displayResearchStatus, formatDateMinute } from "../../utils";
import { EmptyState } from "../common/EmptyState";

type SidebarProps = {
  mode: "user" | "dev";
  onModeChange: (mode: "user" | "dev") => void;
  researches: Research[];
  isLoading?: boolean;
  selectedResearchId: string | null;
  onSelectResearch: (researchId: string) => void;
};

function researchDisplayName(research: Research) {
  if (research.company_name) return String(research.company_name);
  const title = research.title.trim();
  if (title && title !== "新的研究") return title;
  if (research.ticker) return String(research.ticker);
  return "新的研究";
}

function researchMetaLine(research: Research) {
  return `${formatDateMinute(research.updated_at)} · ${displayResearchStatus(research.status, research.run_status)}`;
}

export function Sidebar({
  mode,
  onModeChange,
  researches,
  isLoading = false,
  selectedResearchId,
  onSelectResearch,
}: SidebarProps) {
  return (
    <aside className="sidebar">
      <div className="brand-card">
        <div className="brand-glow" aria-hidden="true" />
        <div className="brand-title brand-wordmark">
          <span className="brand-wordmark-line">TradingAgent</span>
          <span className="brand-wordmark-line">ProMax</span>
        </div>
        <div className="brand-divider" aria-hidden="true" />
        <div className="brand-subtitle">一站式投研</div>
      </div>

      <section className="sidebar-section mode-section">
        <div className="section-row mode-row">
          <div className="section-title">模式</div>
          <div className="mode-switch" data-mode={mode}>
            <span className="mode-switch-track" aria-hidden="true" />
            <button
              className={`mode-btn ${mode === "user" ? "is-active" : ""}`}
              onClick={() => onModeChange("user")}
              aria-pressed={mode === "user"}
            >
              用户模式
            </button>
            <button
              className={`mode-btn ${mode === "dev" ? "is-active" : ""}`}
              onClick={() => onModeChange("dev")}
              aria-pressed={mode === "dev"}
            >
              开发模式
            </button>
          </div>
        </div>
      </section>

      <section className="sidebar-section sidebar-nav-section sidebar-nav-primary">
        <div className="section-row sidebar-group-head">
          <div className="section-title">研究</div>
        </div>
        <div className="list-panel sidebar-list-panel conversation-list-panel conversation-list-panel-main">
          {isLoading ? (
            <EmptyState title="正在加载研究" text="正在同步最新研究列表，请稍候。" compact />
          ) : researches.length ? (
            researches.map((research) => (
              <button
                key={research.research_id}
                className={`list-item nav-list-item conversation-item ${selectedResearchId === research.research_id ? "is-selected" : ""}`}
                onClick={() => onSelectResearch(research.research_id)}
                aria-current={selectedResearchId === research.research_id ? "page" : undefined}
              >
                <div className="item-main">
                  <div className="item-title conversation-title">{researchDisplayName(research)}</div>
                  <div className="item-subtitle conversation-time">{researchMetaLine(research)}</div>
                </div>
              </button>
            ))
          ) : (
            <EmptyState title="暂无研究" text="点击右上角“新的研究”开始分析。" compact />
          )}
        </div>
      </section>
    </aside>
  );
}
