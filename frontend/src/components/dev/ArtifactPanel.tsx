import { api } from "../../api";
import type { NodeDetail } from "../../types";
import { EmptyState } from "../common/EmptyState";
import { ExternalLinkIcon, FileJsonIcon } from "../common/Icons";

type ArtifactPanelProps = {
  nodeDetail: NodeDetail | null;
};

export function ArtifactPanel({ nodeDetail }: ArtifactPanelProps) {
  if (!nodeDetail?.artifacts?.length) {
    return <EmptyState text="当前节点还没有产物" compact />;
  }

  return (
    <>
      {nodeDetail.artifacts.map((artifact) => {
        const path = artifact.relative_path || artifact.absolute_path || "-";
        const fileName = path.split("/").filter(Boolean).pop() || artifact.artifact_type;

        return (
          <div key={artifact.artifact_id} className="artifact-item">
            <div className="artifact-icon">
              <FileJsonIcon />
            </div>
            <div className="artifact-content">
              <div className="artifact-title">{fileName}</div>
              <div className="artifact-meta">{artifact.artifact_type}</div>
              <div className="artifact-path">{path}</div>
            </div>
            <a
              className="artifact-open-btn"
              href={api.artifactUrl(artifact.artifact_id)}
              target="_blank"
              rel="noreferrer"
              title="打开产物文件"
              aria-label="打开产物文件"
            >
              <ExternalLinkIcon />
            </a>
          </div>
        );
      })}
    </>
  );
}
