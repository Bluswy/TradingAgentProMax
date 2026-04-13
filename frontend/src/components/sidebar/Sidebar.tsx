import { useEffect, useState } from "react";
import type { Research } from "../../types";
import { displayResearchStatus, formatDateMinute } from "../../utils";
import { EmptyState } from "../common/EmptyState";
import { TrashIcon } from "../common/Icons";

type SidebarProps = {
  mode: "user" | "dev";
  onModeChange: (mode: "user" | "dev") => void;
  researches: Research[];
  isLoading?: boolean;
  selectedResearchId: string | null;
  onSelectResearch: (researchId: string) => void;
  onDeleteResearch: (researchId: string) => void;
  deletingResearchId?: string | null;
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
  onDeleteResearch,
  deletingResearchId = null,
}: SidebarProps) {
  const [confirmingResearchId, setConfirmingResearchId] = useState<string | null>(null);

  useEffect(() => {
    if (confirmingResearchId && !researches.some((item) => item.research_id === confirmingResearchId)) {
      setConfirmingResearchId(null);
    }
  }, [confirmingResearchId, researches]);

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
              type="button"
              onClick={() => onModeChange("user")}
              aria-pressed={mode === "user"}
            >
              用户模式
            </button>
            <button
              className={`mode-btn ${mode === "dev" ? "is-active" : ""}`}
              type="button"
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
            researches.map((research) => {
              const isSelected = selectedResearchId === research.research_id;
              const isRunning = research.status === "running" || research.run_status === "running";
              const isConfirming = confirmingResearchId === research.research_id;
              const isDeleting = deletingResearchId === research.research_id;
              return (
                <div
                  key={research.research_id}
                  className={`sidebar-research-entry ${isConfirming ? "is-confirming" : ""}`.trim()}
                >
                  <button
                    className={`list-item nav-list-item conversation-item has-side-action ${isSelected ? "is-selected" : ""}`}
                    type="button"
                    onClick={() => onSelectResearch(research.research_id)}
                    aria-current={isSelected ? "page" : undefined}
                  >
                    <div className="item-main">
                      <div className="item-title conversation-title">{researchDisplayName(research)}</div>
                      <div className="item-subtitle conversation-time">{researchMetaLine(research)}</div>
                    </div>
                  </button>
                  <button
                    className={`sidebar-item-icon-btn ${isConfirming ? "is-visible" : ""}`.trim()}
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      setConfirmingResearchId((current) => (current === research.research_id ? null : research.research_id));
                    }}
                    disabled={isRunning || isDeleting}
                    title={isRunning ? "研究进行中，暂不支持删除" : "删除这条研究"}
                    aria-label={isRunning ? "研究进行中，暂不支持删除" : "删除这条研究"}
                  >
                    <TrashIcon />
                  </button>
                  {isConfirming ? (
                    <div className="sidebar-item-confirm">
                      <div className="sidebar-item-confirm-copy">删除后，这条研究以及对应的分析记录都会一起移除。</div>
                      <div className="sidebar-item-confirm-actions">
                        <button className="ghost-btn ghost-btn-small" type="button" onClick={() => setConfirmingResearchId(null)}>
                          取消
                        </button>
                        <button
                          className="ghost-btn ghost-btn-small danger-btn"
                          type="button"
                          onClick={() => {
                            onDeleteResearch(research.research_id);
                            setConfirmingResearchId(null);
                          }}
                          disabled={isDeleting}
                        >
                          {isDeleting ? "删除中..." : "删除"}
                        </button>
                      </div>
                    </div>
                  ) : null}
                </div>
              );
            })
          ) : (
            <EmptyState title="暂无研究" text="点击右上角“新的研究”开始分析。" compact />
          )}
        </div>
      </section>
    </aside>
  );
}
