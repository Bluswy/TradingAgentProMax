import { memo, useEffect, useRef, useState } from "react";
import type { ReportSection } from "../../types";
import { stripMarkdownDecorators } from "../../utils";
import { EmptyState } from "../common/EmptyState";
import { MarkdownContent } from "../common/MarkdownContent";

type ReportNavigatorProps = {
  sections: ReportSection[];
};

function ReportNavigatorImpl({ sections }: ReportNavigatorProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const activeSectionIdRef = useRef<string | null>(sections[0]?.id ?? null);
  const [activeSectionId, setActiveSectionId] = useState<string | null>(sections[0]?.id ?? null);
  const reportHeadline = sections[0]?.title || "完整分析报告";

  useEffect(() => {
    setActiveSectionId(sections[0]?.id ?? null);
  }, [sections]);

  useEffect(() => {
    activeSectionIdRef.current = activeSectionId;
  }, [activeSectionId]);

  useEffect(() => {
    const root = containerRef.current;
    if (!root || !sections.length) return;

    const targets = sections
      .map((section) => root.querySelector<HTMLElement>(`#${CSS.escape(section.id)}`))
      .filter((section): section is HTMLElement => Boolean(section));

    if (!targets.length) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => {
            if (b.intersectionRatio !== a.intersectionRatio) {
              return b.intersectionRatio - a.intersectionRatio;
            }
            return a.boundingClientRect.top - b.boundingClientRect.top;
          });
        const nextId = visible[0]?.target.id || null;
        if (nextId && nextId !== activeSectionIdRef.current) {
          activeSectionIdRef.current = nextId;
          setActiveSectionId(nextId);
        }
      },
      {
        root: null,
        rootMargin: "-10% 0px -58% 0px",
        threshold: [0.12, 0.3, 0.55],
      },
    );

    targets.forEach((target) => observer.observe(target));
    return () => observer.disconnect();
  }, [sections]);

  return (
    <div className="report-layout">
      <nav className="report-nav">
        {sections.length ? (
          sections.map((section) => (
            <a
              key={section.id}
              href={`#${section.id}`}
              className={`report-nav-link ${activeSectionId === section.id ? "is-active" : ""}`}
              onClick={() => setActiveSectionId(section.id)}
            >
              <span className="report-nav-title">{section.title}</span>
              <span className="report-nav-preview">
                {stripMarkdownDecorators(section.body.split("\n").find(Boolean) || "").slice(0, 48) || "点击查看本章节内容"}
              </span>
            </a>
          ))
        ) : (
          <EmptyState compact title="暂无章节导航" text="完整报告生成后，这里会显示章节导航。" />
        )}
      </nav>
      <div className="report-content-column">
        <header className="report-doc-header">
          <div className="report-doc-kicker">完整分析报告</div>
          <h3 className="report-doc-title">{reportHeadline}</h3>
          <p className="report-doc-intro">以下为完整分析过程与论证依据，适合连续阅读与复核。</p>
        </header>
        <div ref={containerRef} className="report-sections">
          {sections.length ? (
            sections.map((section) => (
              <section key={section.id} id={section.id} className="report-section-card">
                <h3>{section.title}</h3>
                <MarkdownContent className="report-markdown" content={section.body || "暂无内容"} />
              </section>
            ))
          ) : (
            <EmptyState title="暂无报告内容" text="分析完成后，这里会显示完整报告。" />
          )}
        </div>
      </div>
    </div>
  );
}

export const ReportNavigator = memo(ReportNavigatorImpl);
