import { useState } from "react";

type Value = Record<string, any>;

export function RunWorkflow({
  nodes,
  edges,
  providers,
  selected,
  onRun,
}: {
  nodes: Value[];
  edges: Value[];
  providers: Value[];
  selected: string | null;
  onRun: (options: Value) => Promise<void>;
}) {
  const [scope, setScope] = useState(selected ? "branch" : "all");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const workflowNodes = nodes.filter(
    (node) =>
      !(node.data?.managed === true && node.data?.kind === "visual_asset"),
  );
  const workflowNodeIds = new Set(workflowNodes.map((node) => node.id));
  const workflowEdges = edges.filter(
    (edge) =>
      workflowNodeIds.has(edge.source) &&
      workflowNodeIds.has(edge.target) &&
      !(
        edge.data?.managed === true &&
        edge.data?.origin === "visual_binding"
      ),
  );
  const selection = selected && workflowNodeIds.has(selected) ? selected : null;
  const wanted = new Set(
    scope === "all" ? workflowNodes.map((node) => node.id) : [selection],
  );
  if (scope === "branch") {
    let changed = true;
    while (changed) {
      changed = false;
      for (const edge of workflowEdges)
        if (wanted.has(edge.source) && !wanted.has(edge.target)) {
          wanted.add(edge.target);
          changed = true;
        }
    }
  }
  let changed = true;
  while (changed) {
    changed = false;
    for (const edge of workflowEdges)
      if (wanted.has(edge.target) && !wanted.has(edge.source)) {
        wanted.add(edge.source);
        changed = true;
      }
  }
  const planned = workflowNodes.filter(
    (node) =>
      wanted.has(node.id) &&
      ["text", "storyboard", "image", "video"].includes(node.data.kind),
  );
  return (
    <>
      <p className="muted">
        任务按连线顺序执行。每次运行都会重新生成范围内的节点，包括所需上游；已经生成的历史素材会保留。
      </p>
      <label>
        执行范围
        <select
          value={scope}
          onChange={(event) => setScope(event.target.value)}
        >
          <option value="all">整个画布</option>
          {selection && (
            <>
              <option value="branch">所选节点及下游分支</option>
              <option value="ancestors">所选节点及所需上游</option>
            </>
          )}
        </select>
      </label>
      <h3>本次 {planned.length} 个任务</h3>
      {planned.map((node) => (
        <p key={node.id}>
          {node.data.label || node.data.kind} ·{" "}
          {node.data.model_id === "local" || !node.data.model_id
            ? "未配置外部 Provider"
            : providers.find((provider) => provider.id === node.data.model_id)
                ?.name || "服务未配置"}
        </p>
      ))}
      {error && <p className="error">{error}</p>}
      <button
        className="primary full"
        disabled={busy || !planned.length}
        onClick={async () => {
          setBusy(true);
          setError("");
          try {
            await onRun({
              node_ids: scope === "all" ? undefined : [selection],
              include_descendants: scope === "branch",
            });
          } catch (reason: any) {
            setError(reason.message);
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "提交中" : "加入生成队列"}
      </button>
    </>
  );
}
