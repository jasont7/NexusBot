import { useEffect, useRef, useState } from 'preact/hooks';

export type GraphNode = { id: string; type: 'brain' | 'skill'; size: number; group: string };
export type GraphEdge = { source: string; target: string };

type SimNode = GraphNode & { x: number; y: number; vx: number; vy: number; pinned?: boolean };

const COLORS: Record<string, string> = {
  bootstrap: '#4da6ff',
  project: '#bb88ff',
  memory: '#66dddd',
  skill: '#ff8844',
};

function nodeColor(n: GraphNode): string {
  return COLORS[n.group] || '#999';
}

function nodeRadius(n: GraphNode): number {
  return Math.max(8, Math.min(22, 4 + Math.log(Math.max(n.size, 1)) * 1.8));
}

export function ForceGraph({
  nodes,
  edges,
  onNodeClick,
  selectedNode,
  width = 600,
  height = 420,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  onNodeClick: (id: string) => void;
  selectedNode?: string | null;
  width?: number;
  height?: number;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const simRef = useRef<SimNode[]>([]);
  const frameRef = useRef<number>(0);
  const dragRef = useRef<{ idx: number; ox: number; oy: number } | null>(null);
  const [, forceRender] = useState(0);

  // Init simulation nodes
  useEffect(() => {
    const cx = width / 2;
    const cy = height / 2;
    simRef.current = nodes.map((n, i) => ({
      ...n,
      x: cx + (Math.cos(i * 2.4) * 120) + (Math.random() - 0.5) * 40,
      y: cy + (Math.sin(i * 2.4) * 120) + (Math.random() - 0.5) * 40,
      vx: 0,
      vy: 0,
    }));

    let running = true;
    const idxMap = new Map(simRef.current.map((n, i) => [n.id, i]));

    function tick() {
      if (!running) return;
      const sn = simRef.current;
      const N = sn.length;

      // Repulsion (all pairs)
      for (let i = 0; i < N; i++) {
        for (let j = i + 1; j < N; j++) {
          let dx = sn[i].x - sn[j].x;
          let dy = sn[i].y - sn[j].y;
          let d2 = dx * dx + dy * dy;
          if (d2 < 1) { dx = 1; dy = 0; d2 = 1; }
          const f = 3000 / d2;
          const fx = dx / Math.sqrt(d2) * f;
          const fy = dy / Math.sqrt(d2) * f;
          if (!sn[i].pinned) { sn[i].vx += fx; sn[i].vy += fy; }
          if (!sn[j].pinned) { sn[j].vx -= fx; sn[j].vy -= fy; }
        }
      }

      // Attraction (edges)
      for (const e of edges) {
        const si = idxMap.get(e.source);
        const ti = idxMap.get(e.target);
        if (si === undefined || ti === undefined) continue;
        const dx = sn[ti].x - sn[si].x;
        const dy = sn[ti].y - sn[si].y;
        const d = Math.sqrt(dx * dx + dy * dy) || 1;
        const f = (d - 80) * 0.03;
        const fx = (dx / d) * f;
        const fy = (dy / d) * f;
        if (!sn[si].pinned) { sn[si].vx += fx; sn[si].vy += fy; }
        if (!sn[ti].pinned) { sn[ti].vx -= fx; sn[ti].vy -= fy; }
      }

      // Center gravity + integrate + damp
      let totalKE = 0;
      for (const n of sn) {
        if (n.pinned) { n.vx = 0; n.vy = 0; continue; }
        n.vx += (cx - n.x) * 0.005;
        n.vy += (cy - n.y) * 0.005;
        n.vx *= 0.88;
        n.vy *= 0.88;
        n.x += n.vx;
        n.y += n.vy;
        // Keep in bounds
        n.x = Math.max(30, Math.min(width - 30, n.x));
        n.y = Math.max(30, Math.min(height - 30, n.y));
        totalKE += n.vx * n.vx + n.vy * n.vy;
      }

      forceRender((c) => c + 1);

      // Keep ticking if not settled
      if (totalKE > 0.01) {
        frameRef.current = requestAnimationFrame(tick);
      }
    }

    frameRef.current = requestAnimationFrame(tick);
    return () => { running = false; cancelAnimationFrame(frameRef.current); };
  }, [nodes, edges, width, height]);

  const sn = simRef.current;
  const idxMap = new Map(sn.map((n, i) => [n.id, i]));

  function onMouseDown(e: MouseEvent, idx: number) {
    e.preventDefault();
    dragRef.current = { idx, ox: e.clientX - sn[idx].x, oy: e.clientY - sn[idx].y };
    sn[idx].pinned = true;

    const onMove = (ev: MouseEvent) => {
      if (!dragRef.current) return;
      const svg = svgRef.current;
      if (!svg) return;
      const rect = svg.getBoundingClientRect();
      sn[dragRef.current.idx].x = ev.clientX - rect.left;
      sn[dragRef.current.idx].y = ev.clientY - rect.top;
      forceRender((c) => c + 1);
    };

    const onUp = () => {
      if (dragRef.current) sn[dragRef.current.idx].pinned = false;
      dragRef.current = null;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      // Restart simulation
      frameRef.current = requestAnimationFrame(function restart() {
        const sn2 = simRef.current;
        let totalKE = 0;
        for (const n of sn2) {
          if (n.pinned) continue;
          n.vx *= 0.88; n.vy *= 0.88;
          n.x += n.vx; n.y += n.vy;
          totalKE += n.vx * n.vx + n.vy * n.vy;
        }
        forceRender((c) => c + 1);
        if (totalKE > 0.01) frameRef.current = requestAnimationFrame(restart);
      });
    };

    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }

  return (
    <svg
      ref={svgRef}
      width={width}
      height={height}
      class="bg-bg rounded-lg border border-border"
      style={{ cursor: dragRef.current ? 'grabbing' : 'default' }}
    >
      {/* Edges */}
      {edges.map((e) => {
        const si = idxMap.get(e.source);
        const ti = idxMap.get(e.target);
        if (si === undefined || ti === undefined) return null;
        const highlighted =
          selectedNode && (e.source === selectedNode || e.target === selectedNode);
        return (
          <line
            key={`${e.source}-${e.target}`}
            x1={sn[si].x}
            y1={sn[si].y}
            x2={sn[ti].x}
            y2={sn[ti].y}
            stroke={highlighted ? '#4da6ff' : '#333'}
            stroke-width={highlighted ? 1.5 : 0.7}
            opacity={highlighted ? 0.8 : 0.3}
          />
        );
      })}

      {/* Nodes */}
      {sn.map((n, i) => {
        const r = nodeRadius(n);
        const isSelected = n.id === selectedNode;
        const col = nodeColor(n);
        return (
          <g
            key={n.id}
            style={{ cursor: 'pointer' }}
            onMouseDown={(e: MouseEvent) => onMouseDown(e, i)}
            onClick={() => onNodeClick(n.id)}
          >
            {isSelected && (
              <circle cx={n.x} cy={n.y} r={r + 4} fill="none" stroke={col} stroke-width={2} opacity={0.5} />
            )}
            <circle cx={n.x} cy={n.y} r={r} fill={col} opacity={isSelected ? 1 : 0.75} />
            <text
              x={n.x}
              y={n.y + r + 12}
              text-anchor="middle"
              fill="#aaa"
              font-size={10}
              font-family="monospace"
            >
              {n.id.replace('.md', '')}
            </text>
          </g>
        );
      })}

      {/* Legend */}
      {Object.entries(COLORS).map(([label, color], i) => (
        <g key={label}>
          <circle cx={14} cy={14 + i * 18} r={5} fill={color} opacity={0.8} />
          <text x={24} y={18 + i * 18} fill="#888" font-size={9} font-family="monospace">
            {label}
          </text>
        </g>
      ))}
    </svg>
  );
}
