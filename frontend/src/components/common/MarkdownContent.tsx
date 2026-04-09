import { Suspense, lazy } from "react";

type MarkdownContentProps = {
  content?: string | null;
  className?: string;
};

const MarkdownRenderer = lazy(async () => {
  const [{ default: ReactMarkdown }, { default: remarkGfm }] = await Promise.all([
    import("react-markdown"),
    import("remark-gfm"),
  ]);

  return {
    default: function MarkdownRendererImpl({ content }: { content: string }) {
      return <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>;
    },
  };
});

export function MarkdownContent({ content, className = "" }: MarkdownContentProps) {
  return (
    <div className={`markdown-content ${className}`.trim()}>
      <Suspense fallback={<div className="markdown-fallback">{content || ""}</div>}>
        <MarkdownRenderer content={content || ""} />
      </Suspense>
    </div>
  );
}
