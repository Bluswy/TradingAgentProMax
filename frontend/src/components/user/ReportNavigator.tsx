import { useEffect, useRef, useState } from "react";
import type { ReportSection } from "../../types";
import { stripMarkdownDecorators } from "../../utils";
import { EmptyState } from "../common/EmptyState";
import { MarkdownContent } from "../common/MarkdownContent";

type ReportNavigatorProps = {
  sections: ReportSection[];
};

export function ReportNavigator({ sections }: ReportNavigatorProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [activeSectionId, setActiveSectionId] = useState<string | null>(sections[0]?.id ?? null);

  useEffect(() => {
    setActiveSectionId(sections[0]?.id ?? null);
  }, [sections]);

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
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio);
        if (visible[0]) {
          setActiveSectionId(visible[0].target.id);
        }
      },
      {
        root,
        rootMargin: "0px 0px -55% 0px",
        threshold: [0.2, 0.4, 0.6],
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
      <div ref={containerRef} className="report-sections">
        {sections.length ? (
          sections.map((section) => (
            <section key={section.id} id={section.id} className="report-section-card">
              <h3>{section.title}</h3>
              <MarkdownContent content={section.body || "暂无内容"} />
            </section>
          ))
        ) : (
          <EmptyState title="暂无报告内容" text="分析完成后，这里会显示完整报告。" />
        )}
      </div>
    </div>
  );
}
