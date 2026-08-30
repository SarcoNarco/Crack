import {
  ARCHITECTURE_GRAPH,
  deriveArchitectureMap,
  type ArchitectureNodeId,
} from './architecture'
import type { PresentationEvent } from './types'

function coordinate(value: number): number {
  return 6 + value * 88
}

function hasNode(nodeIds: readonly ArchitectureNodeId[], nodeId: ArchitectureNodeId): boolean {
  return nodeIds.includes(nodeId)
}

export function ArchitectureMap({ events }: { events: readonly PresentationEvent[] }) {
  const map = deriveArchitectureMap(events)
  const relatedNodes = map.relation?.nodeIds ?? []
  const relatedEdges = new Set(map.relatedEdgeIds)
  return (
    <section className="architecture-section" aria-labelledby="architecture-heading">
      <div className="section-heading">
        <div>
          <p className="kicker">Static target reference</p>
          <h2 id="architecture-heading">Target architecture map</h2>
          <p>Each received presentation event is related to canonical school-portal components. This is not a process-location map, active imported-runtime binding, or proof of attack activity.</p>
        </div>
      </div>
      <div className="architecture-layout">
        <svg className="architecture-map" viewBox="0 0 100 100" role="img" aria-labelledby="architecture-svg-title architecture-svg-description">
          <title id="architecture-svg-title">Static school portal architecture map</title>
          <desc id="architecture-svg-description">Six canonical school-portal components and their source-derived relationships. Highlighting relates only the latest received presentation event to components.</desc>
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
        </svg>
        <aside className="architecture-context" aria-live="polite" aria-atomic="true">
          {map.event && map.relation ? <>
            <p className="kicker">Latest received event</p>
            <h3>{map.event.headline}</h3>
            <dl>
              <div><dt>Actor</dt><dd>{map.relation.actor}</dd></div>
              <div><dt>State</dt><dd>{map.event.state}</dd></div>
              <div><dt>Related components</dt><dd>{relatedNodes.length ? relatedNodes.map((id) => ARCHITECTURE_GRAPH.nodes.find((node) => node.id === id)!.label).join(' · ') : 'Outside this static target map'}</dd></div>
            </dl>
          </> : <>
            <p className="kicker">Waiting</p>
            <h3>No presentation event received</h3>
            <p>No target components are currently related. The map remains a static reference.</p>
          </>}
        </aside>
      </div>
      <p className="architecture-note">Nodes and edges mirror Sprint 18’s fixed canonical school portal. Event relationships are presentation-only and do not load, revalidate, or run an imported target snapshot.</p>
    </section>
  )
}
