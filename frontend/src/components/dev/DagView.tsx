import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { GRAPH_LAYERS } from "../../constants";
import type { GraphNode, RunDetail } from "../../types";
import { displayNodeName, formatDuration, statusClass } from "../../utils";
import { StatusBadge } from "../common/StatusBadge";

type DagViewProps = {
  runDetail: RunDetail | null;
  selectedNodeName: string | null;
  onSelectNode: (nodeName: string) => void;
};

type EdgePath = {
  key: string;
  d: string;
  status: string;
};

export function DagView({ runDetail, selectedNodeName, onSelectNode }: DagViewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const nodeRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const [edgePaths, setEdgePaths] = useState<EdgePath[]>([]);

  const nodesByName = useMemo(() => {
    const map = new Map<string, GraphNode>();
    (runDetail?.graph.nodes || []).forEach((node) => map.set(node.node_name, node));
    return map;
  }, [runDetail]);

  useLayoutEffect(() => {
    const container = containerRef.current;
    const edges = runDetail?.graph.edges || [];
    if (!container || !edges.length) {
      setEdgePaths([]);
      return;
    }

    const updatePaths = () => {
      const rootRect = container.getBoundingClientRect();
      const nextPaths = edges
        .map(([from, to]) => {
          const fromEl = nodeRefs.current[from];
          const toEl = nodeRefs.current[to];
          if (!fromEl || !toEl) return null;
          const fromRect = fromEl.getBoundingClientRect();
          const toRect = toEl.getBoundingClientRect();
          const x1 = fromRect.left + fromRect.width / 2 - rootRect.left;
          const y1 = fromRect.bottom - rootRect.top;
          const x2 = toRect.left + toRect.width / 2 - rootRect.left;
          const y2 = toRect.top - rootRect.top;
          const deltaY = Math.max(24, (y2 - y1) * 0.45);
          const c1y = y1 + deltaY;
          const c2y = y2 - deltaY;
          const d = `M ${x1} ${y1} C ${x1} ${c1y}, ${x2} ${c2y}, ${x2} ${y2}`;
          const fromStatus = nodesByName.get(from)?.status;
          const toStatus = nodesByName.get(to)?.status;
          const status = toStatus === "failed" || fromStatus === "failed" ? "failed" : toStatus === "success" ? "success" : toStatus === "running" ? "running" : "queued";
          return { key: `${from}-${to}`, d, status };
        })
        .filter((item): item is EdgePath => Boolean(item));
      setEdgePaths(nextPaths);
    };

    updatePaths();
    const observer = new ResizeObserver(() => updatePaths());
    observer.observe(container);
    Object.values(nodeRefs.current).forEach((element) => element && observer.observe(element));
    window.addEventListener("resize", updatePaths);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", updatePaths);
    };
  }, [nodesByName, runDetail]);

  return (
    <div ref={containerRef} className="dag-flow">
      <svg className="dag-edge-layer" aria-hidden="true">
        {edgePaths.map((edge) => (
          <path key={edge.key} d={edge.d} className={`dag-edge ${statusClass(edge.status)}`} />
        ))}
      </svg>
      {GRAPH_LAYERS.map((layer, index) => (
        <div key={index} className="dag-layer">
          {layer.map((nodeName) => {
            const node = nodesByName.get(nodeName);
            const shouldShowBadge = node?.status === "running" || node?.status === "failed";
            return (
              <button
                key={nodeName}
                ref={(element) => {
                  nodeRefs.current[nodeName] = element;
                }}
                className={`dag-node ${statusClass(node?.status)} ${selectedNodeName === nodeName ? "is-selected" : ""}`}
                onClick={() => onSelectNode(nodeName)}
              >
                <div className="dag-node-head">
                  <span className="dag-node-title">{displayNodeName(nodeName)}</span>
                  {shouldShowBadge ? <StatusBadge status={node?.status} label={node?.status} /> : null}
                </div>
                <div className="dag-node-duration">{formatDuration(node?.duration_ms)}</div>
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}
