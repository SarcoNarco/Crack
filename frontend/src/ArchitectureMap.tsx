import {
  ARCHITECTURE_GRAPH,
  deriveArchitectureEffect,
  deriveArchitectureMap,
  type ArchitectureEffectKind,
  type ArchitectureNodeId,
} from './architecture'
import type { PresentationEvent } from './types'

function coordinate(value: number): number {
  return 6 + value * 88
}

function hasNode(nodeIds: readonly ArchitectureNodeId[], nodeId: ArchitectureNodeId): boolean {
  return nodeIds.includes(nodeId)
}

function AgentGlyph() {
  return <svg data-agent-glyph="true" className="architecture-agent-glyph" viewBox="0 0 20 20" aria-hidden="true" focusable="false"><circle cx="10" cy="8" r="5" /><circle cx="8" cy="7" r=".8" /><circle cx="12" cy="7" r=".8" /><path d="M7 11c2 1 4 1 6 0M5 15l2-3M15 15l-2-3" /></svg>
}

function EffectIcon({ kind }: { kind: ArchitectureEffectKind }) {
  if (kind === 'scan') return <svg className="architecture-tool-icon" viewBox="0 0 20 20" aria-hidden="true" focusable="false"><circle cx="8" cy="8" r="5" /><path d="m12 12 5 5" /></svg>
  if (kind === 'probe') return <svg className="architecture-tool-icon" viewBox="0 0 20 20" aria-hidden="true" focusable="false"><path d="M4 16V8a6 6 0 0 1 12 0v8" /><path d="M3 16h14M8 12h4M10 4v8" /></svg>
  if (kind === 'pickaxe') return <svg className="architecture-tool-icon" viewBox="0 0 20 20" aria-hidden="true" focusable="false"><path d="M3 5c4-3 10-3 14 0M10 5v11M7 16h6" /></svg>
  if (kind === 'beam') return <svg className="architecture-tool-icon" viewBox="0 0 20 20" aria-hidden="true" focusable="false"><path d="m3 10 10-5v10L3 10ZM13 7l4-2M13 10h5M13 13l4 2" /></svg>
  return <svg className="architecture-tool-icon" viewBox="0 0 20 20" aria-hidden="true" focusable="false"><path d="M4 10h12M10 4v12M6 6l8 8M14 6l-8 8" /></svg>
}

export function ArchitectureMap({ events }: { events: readonly PresentationEvent[] }) {
  const map = deriveArchitectureMap(events)
  const relatedNodes = map.relation?.nodeIds ?? []
  const relatedEdges = new Set(map.relatedEdgeIds)
  const effect = map.event && map.relation ? deriveArchitectureEffect(map.event, map.relation) : null
  const effectNode = effect?.nodeId
    ? ARCHITECTURE_GRAPH.nodes.find((node) => node.id === effect.nodeId) ?? null
    : null
  return (
    <section className="architecture-section" aria-labelledby="architecture-heading">
      <div className="section-heading">
        <div>
          <p className="kicker">Static target reference</p>
          <h2 id="architecture-heading">Target architecture map</h2>
          <p>Latest received event can show one finite presentation tool marker beside a related canonical component. It is not a process-location map, active imported-runtime binding, or proof of attack activity.</p>
        </div>
      </div>
      <div className="architecture-layout">
        <svg className="architecture-map" viewBox="0 0 100 100" role="img" aria-labelledby="architecture-svg-title architecture-svg-description">
          <title id="architecture-svg-title">Static school portal architecture map</title>
          <desc id="architecture-svg-description">Six canonical school-portal components and their source-derived relationships. Highlighting and any finite tool marker relate only the latest received presentation event to components; they do not prove an attack result.</desc>
          {ARCHITECTURE_GRAPH.edges.map((edge) => {
            const source = ARCHITECTURE_GRAPH.nodes.find((node) => node.id === edge.source)!
            const target = ARCHITECTURE_GRAPH.nodes.find((node) => node.id === edge.target)!
            return <line key={edge.id} data-edge-id={edge.id} className={`architecture-edge${relatedEdges.has(edge.id) ? ' is-related' : ''}`} x1={coordinate(source.coordinates.x)} y1={coordinate(source.coordinates.y)} x2={coordinate(target.coordinates.x)} y2={coordinate(target.coordinates.y)} />
          })}
          {ARCHITECTURE_GRAPH.nodes.map((node) => {
            const related = hasNode(relatedNodes, node.id)
            return (
              <g key={node.id} data-node-id={node.id} className={`architecture-node${related ? ' is-related' : ''}`} transform={`translate(${coordinate(node.coordinates.x)} ${coordinate(node.coordinates.y)})`}>
                <title>{node.label}: {node.description}</title>
                <rect x="-10" y="-5.5" width="20" height="11" rx="1" />
                <text textAnchor="middle" y="-1.1">{node.label}</text>
                <text textAnchor="middle" y="2.5" className="architecture-layer">{node.layer}</text>
              </g>
            )
          })}
          {effect && effectNode && <g transform={`translate(${coordinate(effectNode.coordinates.x)} ${coordinate(effectNode.coordinates.y)})`} aria-hidden="true">
            <g key={effect.key} data-effect-key={effect.key} data-effect-kind={effect.kind} className={`architecture-effect is-${effect.kind}`}>
              <AgentGlyph />
              <EffectIcon kind={effect.kind} />
            </g>
          </g>}
        </svg>
        <aside className="architecture-context" aria-live="polite" aria-atomic="true">
          {map.event && map.relation ? <>
            <p className="kicker">Latest received event</p>
            <h3>{map.event.headline}</h3>
            <dl>
              <div><dt>Actor</dt><dd>{map.relation.actor}</dd></div>
              <div><dt>Presentation state</dt><dd><span className={`architecture-state state-${map.event.state}`}>{map.event.state}</span></dd></div>
              <div><dt>Tool marker</dt><dd className="architecture-effect-label"><AgentGlyph /><EffectIcon kind={effect?.kind ?? 'static'} />{effect?.label ?? 'Static actor marker'} <span>presentation-only</span></dd></div>
              <div><dt>Related components</dt><dd>{relatedNodes.length ? relatedNodes.map((id) => ARCHITECTURE_GRAPH.nodes.find((node) => node.id === id)!.label).join(' · ') : 'Outside this static target map'}</dd></div>
            </dl>
          </> : <>
            <p className="kicker">Waiting</p>
            <h3>No presentation event received</h3>
            <p>No target components are currently related. The map remains a static reference.</p>
          </>}
        </aside>
      </div>
      <p className="architecture-note">Nodes and edges mirror Sprint 18’s fixed canonical school portal. Marker motion is finite, presentation-only, and never asserts breach success; verified findings remain code-owned consensus. This map does not load, revalidate, or run an imported target snapshot.</p>
    </section>
  )
}
