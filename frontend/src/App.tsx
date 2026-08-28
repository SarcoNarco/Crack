import { useEffect, useMemo, useReducer, useRef, useState } from 'react'
import { liveTransport, type ConsoleTransport } from './api'
import { previewEvents } from './fixtures'
import {
  consoleReducer,
  deriveConsole,
  eventsForStage,
  initialConsoleState,
} from './reducer'
import {
  STAGES,
  type DisplayMode,
  type PresentationEvent,
  type PreviewKind,
  type StageKey,
} from './types'
import './styles.css'

interface AppProps {
  preview?: PreviewKind | null
  initialEvents?: PresentationEvent[]
  transport?: ConsoleTransport
}

const NEXT_STEP: Record<StageKey | 'session', string> = {
  session: 'The coordinator either begins fixed preflight or closes the terminal state.',
  preflight: 'A successful preflight activates the source-only mapper.',
  mapper: 'A validated contract is handed to the authorization tester after a fresh reset.',
  authorization: 'One exact unverified hypothesis is handed to two sequential independent checks.',
  verifier_a: 'Verifier A must complete before Verifier B becomes active.',
  verifier_b: 'After Verifier B, ordinary code evaluates both deterministic checks.',
  consensus: 'A verified verdict may create a finding; every completed verdict can generate a report.',
  report: 'The final event exposes the exact static report link and code-owned outcome.',
}

const ALLOWED_REASON: Record<StageKey | 'session', string> = {
  session: 'The server created the session; the browser supplied no target, provider, credential, or prompt.',
  preflight: 'It checks only the fixed loopback demo app and committed model-role configuration.',
  mapper: 'Source reads stay inside the existing scope-controller allowlist.',
  authorization: 'Only two normal-flow GET calls use fixed synthetic Student A and Student B identities.',
  verifier_a: 'The plan is schema-limited to bounded GET calls and starts after a clean reset.',
  verifier_b: 'The second plan is isolated and begins only after the first check completes.',
  consensus: 'Ordinary Python code applies the fixed exact-submission predicate and verdict table.',
  report: 'The renderer reads the exact completed ledger run without invoking agents or providers.',
}

const EVIDENCE: Record<StageKey | 'session', string> = {
  session: 'A safe presentation journal records accepted and terminal session state.',
  preflight: 'Only readiness and configured provider/model labels are presented.',
  mapper: 'The ledger retains the mapper run status; completed mapping adds only route count and a safe artifact reference.',
  authorization: 'HTTP status, exact synthetic submission ID, student label, hypothesis ID, and ledger references.',
  verifier_a: 'Reset ID, logical state hash, plan hash, bounded call metadata, and deterministic check result.',
  verifier_b: 'A distinct reset ID with the equivalent state hash and the same safe evidence categories.',
  consensus: 'Both boolean check results, the ordinary-code verdict, and a finding reference only when verified.',
  report: 'Exact verifier run ID, static artifact reference, and deterministic SHA-256 hashes.',
}

function queryPreview(): PreviewKind | null {
  const value = new URLSearchParams(window.location.search).get('preview')
  return value === 'success' || value === 'failure' || value === 'reconnect' ? value : null
}

function querySession(): string | null {
  const value = new URLSearchParams(window.location.search).get('session')
  return value && /^demo:[0-9a-f-]{36}$/.test(value) ? value : null
}

function displayKey(key: string): string {
  return key.replaceAll('_', ' ').replace(/\b\w/g, (character) => character.toUpperCase())
}

function text(value: unknown, fallback = 'Not recorded yet'): string {
  if (value === null || value === undefined || value === '') return fallback
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (Array.isArray(value)) return value.join(' · ')
  return String(value)
}

function latest(events: PresentationEvent[], type: string): PresentationEvent | undefined {
  return [...events].reverse().find((event) => event.type === type)
}

function TechnicalDetails({ event }: { event: PresentationEvent }) {
  return (
    <details className="technical-details">
      <summary>Technical details</summary>
      <dl>
        <div><dt>Sequence</dt><dd>{event.sequence}</dd></div>
        <div><dt>Event type</dt><dd className="mono wrap">{event.type}</dd></div>
        <div><dt>Logical role</dt><dd>{event.logical_role ?? 'Coordinator-owned'}</dd></div>
        {Object.entries(event.metadata).map(([key, value]) => (
          <div key={key}><dt>{displayKey(key)}</dt><dd className="mono wrap">{text(value)}</dd></div>
        ))}
        {event.reference && <div><dt>Reference</dt><dd className="mono wrap">{event.reference}</dd></div>}
      </dl>
    </details>
  )
}

function StageGraph({
  events,
  stages,
  onSelect,
}: {
  events: PresentationEvent[]
  stages: ReturnType<typeof deriveConsole>['stages']
  onSelect: (event: PresentationEvent) => void
}) {
  return (
    <ol className="stage-graph" aria-label="Live operation graph">
      {STAGES.map((stage, index) => {
        const stageEvents = eventsForStage(events, stage.key)
        const last = stageEvents.at(-1)
        return (
          <li key={stage.key} className={`stage-node is-${stages[stage.key]}`}>
            <button
              type="button"
              onClick={() => last && onSelect(last)}
              disabled={!last}
              aria-label={`${stage.label}: ${stages[stage.key]}`}
            >
              <span className="stage-index">0{index + 1}</span>
              <span><strong>{stage.label}</strong><small>{stage.short}</small></span>
              <span className="state-label">{stages[stage.key]}</span>
            </button>
          </li>
        )
      })}
    </ol>
  )
}

function AuthorizationStory({ events, mode }: { events: PresentationEvent[]; mode: DisplayMode }) {
  const discovery = latest(events, 'identity.student_b_discovery')
  const retrieval = latest(events, 'identity.student_a_retrieval')
  const discoveredId = discovery?.metadata.submission_id
  const requestedId = retrieval?.metadata.requested_submission_id
  const returnedId = retrieval?.metadata.returned_submission_id
  const matched = retrieval?.metadata.exact_submission_match
  return (
    <div className="authorization-story">
      <ol>
        <li className={discovery ? 'resolved student-b' : ''}><span>1</span><div><strong>Student B lists their own submission</strong><p>{discovery ? `HTTP ${text(discovery.metadata.status_code)}` : 'Waiting for the received discovery event.'}</p></div></li>
        <li className={discoveredId ? 'resolved submission' : ''}><span>2</span><div><strong>Exact submission ID captured</strong><p className="mono wrap">{text(discoveredId)}</p></div></li>
        <li className={requestedId ? 'resolved student-a' : ''}><span>3</span><div><strong>Student A requests that submission detail</strong><p className="mono wrap">{text(requestedId)}</p></div></li>
        <li className={retrieval ? 'resolved boundary' : ''}><span>4</span><div><strong>Returned detail crosses student ownership</strong><p>{retrieval ? `HTTP ${text(retrieval.metadata.status_code)} · student ${text(retrieval.metadata.returned_student)}` : 'Waiting for the received retrieval event.'}</p></div></li>
        <li className={matched !== undefined ? 'resolved predicate' : ''}><span>5</span><div><strong>Code compares submission ID and student</strong><p>{matched === undefined ? 'Not evaluated yet' : matched ? 'Exact-submission match observed' : 'Exact-submission match not observed'}</p></div></li>
      </ol>
      {mode === 'technical' && retrieval && (
        <div className="story-technical">
          <span>Requested <code>{text(requestedId)}</code></span>
          <span>Returned <code>{text(returnedId)}</code></span>
        </div>
      )}
    </div>
  )
}

function VerifierLane({
  stage,
  title,
  events,
  state,
  mode,
}: {
  stage: 'verifier_a' | 'verifier_b'
  title: string
  events: PresentationEvent[]
  state: string
  mode: DisplayMode
}) {
  const lane = eventsForStage(events, stage)
  const reset = lane.find((event) => event.type.endsWith('reset_completed'))
  const plan = lane.find((event) => event.type.endsWith('plan_validated'))
  const calls = lane.filter((event) => event.type.endsWith('call_recorded'))
  const check = lane.find((event) => event.type.endsWith('check_completed'))
  return (
    <article className={`verifier-lane is-${state}`} aria-label={`${title}: ${state}`}>
      <header><div><p className="kicker">Sequential logical role</p><h3>{title}</h3></div><span className="state-label">{state}</span></header>
      <ul className="lane-checklist">
        <li className={reset ? 'done' : ''}><span />Fresh reset</li>
        <li className={plan ? 'done' : ''}><span />Plan validated</li>
        <li className={calls.length ? 'done' : ''}><span />Bounded calls <em>{calls.length || '—'}</em></li>
        <li className={check ? 'done' : ''}><span />Deterministic check <em>{check ? text(check.metadata.satisfied) : '—'}</em></li>
      </ul>
      {mode === 'technical' && (
        <dl className="lane-metadata">
          <div><dt>Reset ID</dt><dd className="mono wrap">{text(reset?.metadata.reset_id)}</dd></div>
          <div><dt>State hash</dt><dd className="mono wrap">{text(reset?.metadata.state_hash)}</dd></div>
          <div><dt>Plan hash</dt><dd className="mono wrap">{text(plan?.metadata.plan_sha256)}</dd></div>
        </dl>
      )}
    </article>
  )
}

function ConsensusGate({ event }: { event: PresentationEvent | null }) {
  const first = event?.metadata.check_1_satisfied
  const second = event?.metadata.check_2_satisfied
  return (
    <div className={`consensus-gate ${event ? 'resolved' : ''}`}>
      <div className="gate-input"><span>Check 1</span><strong>{first === undefined ? 'Waiting' : first ? 'Pass' : 'Fail'}</strong></div>
      <div className="gate-input"><span>Check 2</span><strong>{second === undefined ? 'Waiting' : second ? 'Pass' : 'Fail'}</strong></div>
      <div className="gate-core"><span>Ordinary code</span><strong>Exact-submission predicate</strong><small>Models plan. Code decides.</small></div>
      <div className="gate-output"><span>Verdict</span><strong>{text(event?.metadata.verdict, 'Pending')}</strong></div>
      <details>
        <summary>Consensus truth table</summary>
        <ul><li>Two passes → verified</li><li>Two failures → unverified</li><li>Disagreement → inconclusive</li><li>Incomplete provider or schema execution → no verdict</li></ul>
      </details>
    </div>
  )
}

export default function App({ preview, initialEvents, transport = liveTransport }: AppProps) {
  const previewKind = preview === undefined ? queryPreview() : preview
  const [consoleState, dispatch] = useReducer(consoleReducer, initialConsoleState)
  const [mode, setMode] = useState<DisplayMode>('simple')
  const [selectedSequence, setSelectedSequence] = useState<number | null>(null)
  const [startError, setStartError] = useState<string | null>(null)
  const unsubscribe = useRef<(() => void) | null>(null)
  const derived = useMemo(() => deriveConsole(consoleState), [consoleState])
  const selected = consoleState.events.find((event) => event.sequence === selectedSequence)
    ?? consoleState.events.at(-1)
    ?? null

  useEffect(() => {
    const source = initialEvents ?? (previewKind ? previewEvents(previewKind) : [])
    for (const event of source) dispatch({ type: 'event', event })
  }, [initialEvents, previewKind])

  useEffect(() => {
    const sessionId = !previewKind && !initialEvents ? querySession() : null
    if (!sessionId) return
    let cancelled = false
    let localUnsubscribe: (() => void) | null = null
    transport.observe(sessionId)
      .then((status) => {
        if (cancelled) return
        unsubscribe.current?.()
        localUnsubscribe = transport.subscribe(
          status,
          (event) => dispatch({ type: 'event', event }),
          (message) => dispatch({ type: 'error', message }),
        )
        unsubscribe.current = localUnsubscribe
      })
      .catch((error) => {
        if (!cancelled) setStartError(error instanceof Error ? error.message : 'The contained session could not be reopened.')
      })
    return () => {
      cancelled = true
      localUnsubscribe?.()
      if (unsubscribe.current === localUnsubscribe) unsubscribe.current = null
    }
  }, [initialEvents, previewKind, transport])

  useEffect(() => () => {
    unsubscribe.current?.()
    unsubscribe.current = null
  }, [])

  async function start() {
    setStartError(null)
    unsubscribe.current?.()
    unsubscribe.current = null
    dispatch({ type: 'reset' })
    setSelectedSequence(null)
    if (previewKind) {
      for (const event of previewEvents(previewKind)) dispatch({ type: 'event', event })
      return
    }
    try {
      const status = await transport.start()
      const url = new URL(window.location.href)
      url.searchParams.set('session', status.session_id)
      window.history.replaceState({}, '', url)
      unsubscribe.current = transport.subscribe(
        status,
        (event) => dispatch({ type: 'event', event }),
        (message) => dispatch({ type: 'error', message }),
      )
    } catch (error) {
      setStartError(error instanceof Error ? error.message : 'The contained run could not start.')
    }
  }

  const discovery = latest(consoleState.events, 'identity.student_b_discovery')
  const retrieval = latest(consoleState.events, 'identity.student_a_retrieval')
  const sessionId = consoleState.events[0]?.session_id
  const verdict = derived.consensus?.metadata.verdict ?? derived.terminal?.metadata.verdict
  const reportUrl = typeof derived.report?.metadata.report_url === 'string'
    ? derived.report.metadata.report_url
    : null
  const verifierRunId = derived.terminal?.metadata.verifier_run_id
  const latestAnnouncement = consoleState.events.at(-1)?.headline ?? 'Console ready'

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to operations</a>
      <header className="topbar">
        <div><p className="brand"><span>CRACK</span> / LIVE RED-TEAM OPERATIONS</p><p className="boundary">Developer-owned · loopback only · synthetic Teacher, students, submissions, and grades</p></div>
        <div className="mode-switch" role="group" aria-label="Display mode">
          <button type="button" className={mode === 'simple' ? 'selected' : ''} aria-pressed={mode === 'simple'} onClick={() => setMode('simple')}>Simple</button>
          <button type="button" className={mode === 'technical' ? 'selected' : ''} aria-pressed={mode === 'technical'} onClick={() => setMode('technical')}>Technical</button>
        </div>
      </header>

      {previewKind && <div className="preview-banner" role="status"><strong>REPLAY / SYNTHETIC PREVIEW</strong><span>Recorded fixture data — not a live run and no provider call is occurring.</span></div>}

      <main id="main-content">
        <section className="control-panel" aria-labelledby="control-heading">
          <div><p className="kicker">Fixed canonical workflow</p><h1 id="control-heading">See the evidence form as the code executes.</h1><p className="lede">One contained workflow. No target input. No fake progress. Every transition below comes from the validated event stream.</p></div>
          <div className="run-control">
            <p><strong>Provider boundary</strong>The live run sends bounded synthetic context to the configured Groq and Gemini roles. No credentials, source files, database contents, or raw responses enter this console.</p>
            <button type="button" className="start-button" onClick={start} disabled={derived.active} aria-describedby="run-boundary">
              {derived.active ? 'Contained run active' : previewKind ? 'Replay recorded preview' : 'Start contained verification run'}
            </button>
            <span id="run-boundary">Server-generated session · one active run maximum</span>
            {startError && <p className="inline-error" role="alert">{startError}</p>}
          </div>
        </section>

        <section className="operations-section" aria-labelledby="operations-heading">
          <div className="section-heading"><div><p className="kicker">Received state transitions</p><h2 id="operations-heading">Live operation graph</h2></div><span className="completion-count">{Object.values(derived.stages).filter((state) => state === 'completed').length} / {STAGES.length} stages complete</span></div>
          <StageGraph events={consoleState.events} stages={derived.stages} onSelect={(event) => setSelectedSequence(event.sequence)} />
          {derived.sequenceGap && <p className="inline-error" role="alert">The event stream contains a sequence gap. Presentation is incomplete.</p>}
          {consoleState.streamError && <p className="inline-error" role="alert">{consoleState.streamError}</p>}
        </section>

        <div className="primary-grid">
          <section className="story-section" aria-labelledby="story-heading">
            <div className="section-heading"><div><p className="kicker">Ownership boundary</p><h2 id="story-heading">Authorization story</h2></div></div>
            <AuthorizationStory events={consoleState.events} mode={mode} />
          </section>
          <aside className="explain-panel" aria-labelledby="explain-heading">
            <p className="kicker">Selected evidence</p><h2 id="explain-heading">Explainability panel</h2>
            {selected ? <>
              <span className={`event-state is-${selected.state}`}>{selected.state}</span>
              <h3>{selected.headline}</h3>
              <dl className="explain-list">
                <div><dt>What is happening?</dt><dd>{selected.explanation}</dd></div>
                <div><dt>Why is this allowed?</dt><dd>{ALLOWED_REASON[selected.stage]}</dd></div>
                <div><dt>What evidence is recorded?</dt><dd>{EVIDENCE[selected.stage]}</dd></div>
                <div><dt>What happens next?</dt><dd>{NEXT_STEP[selected.stage]}</dd></div>
                <div><dt>Decision owner</dt><dd>{selected.logical_role === 'ordinary_code' ? 'Code-owned deterministic decision' : selected.logical_role === 'coordinator' || selected.stage === 'report' || selected.stage === 'preflight' || selected.stage === 'session' ? 'Ordinary coordinator code' : 'AI-planned step inside code-enforced bounds'}</dd></div>
              </dl>
              {mode === 'technical' && <TechnicalDetails event={selected} />}
            </> : <p className="empty-state">Select a received stage or event to explain it.</p>}
          </aside>
        </div>

        <section aria-labelledby="verification-heading">
          <div className="section-heading"><div><p className="kicker">Independent, not simultaneous</p><h2 id="verification-heading">Sequential verification lanes</h2><p>These are isolated logical roles activated one after the other through Python function calls. They are not parallel agents, processes, or communicating services.</p></div></div>
          <div className="lane-grid">
            <VerifierLane stage="verifier_a" title="Independent check 1 — Verifier A" events={consoleState.events} state={derived.stages.verifier_a} mode={mode} />
            <VerifierLane stage="verifier_b" title="Independent check 2 — Verifier B" events={consoleState.events} state={derived.stages.verifier_b} mode={mode} />
          </div>
          <p className="state-proof">Distinct reset IDs prove different reset operations. A shared logical hash proves equivalent ordered seeded school-portal data.</p>
        </section>

        <section aria-labelledby="consensus-heading">
          <div className="section-heading"><div><p className="kicker">Models plan · code decides</p><h2 id="consensus-heading">Code-owned consensus gate</h2></div></div>
          <ConsensusGate event={derived.consensus} />
        </section>

        <section className="feed-section" aria-labelledby="feed-heading">
          <div className="section-heading"><div><p className="kicker">Ordered safe presentation layer</p><h2 id="feed-heading">Live activity feed</h2></div>{mode === 'technical' && sessionId && <code className="session-id">{sessionId}</code>}</div>
          <ol className="activity-feed">
            {consoleState.events.length ? consoleState.events.map((event) => (
              <li key={event.sequence}>
                <button type="button" onClick={() => setSelectedSequence(event.sequence)} aria-label={`Inspect event ${event.sequence}: ${event.headline}`}>
                  <time dateTime={event.timestamp}>{new Date(event.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</time>
                  <span className="feed-role">{event.logical_role ?? 'system'}</span>
                  <span className="feed-copy"><strong>{event.headline}</strong><small>{event.explanation}</small></span>
                  <span className={`event-state is-${event.state}`}>{event.state}</span>
                  {mode === 'technical' && <span className="feed-sequence">#{event.sequence}</span>}
                </button>
              </li>
            )) : <li className="empty-state">No events received. The graph remains pending.</li>}
          </ol>
        </section>

        {derived.terminal && (
          <section className={`final-result ${derived.terminal.type === 'session.failed' ? 'failed' : ''}`} aria-labelledby="result-heading">
            <p className="kicker">Terminal event received</p>
            <h2 id="result-heading">{derived.terminal.type === 'session.failed' ? 'Run stopped safely.' : verdict === 'verified' ? 'Cross-student detail read verified.' : `Run completed: ${text(verdict)}.`}</h2>
            <p>{derived.terminal.explanation}</p>
            <div className="result-facts">
              <div><span>Verdict</span><strong>{text(verdict, 'No verdict')}</strong></div>
              {derived.finding && <div><span>Finding ID</span><strong className="mono wrap">{text(derived.finding.metadata.finding_id)}</strong></div>}
              {mode === 'technical' && verifierRunId !== null && verifierRunId !== undefined && <div><span>Verifier run</span><strong className="mono wrap">{text(verifierRunId)}</strong></div>}
            </div>
            {derived.report && reportUrl && (previewKind
              ? <span className="report-link disabled" aria-disabled="true">Static report link available after a real live run</span>
              : <a className="report-link" href={text(reportUrl)} target="_blank" rel="noreferrer">Open exact Sprint 12 HTML report</a>)}
            <p className="limitation">Local synthetic evidence only. This is not a public-target scan, security certification, or claim of complete coverage.</p>
          </section>
        )}
      </main>
      <p className="sr-only" aria-live="polite" aria-atomic="true">{latestAnnouncement}</p>
      <footer><span>Presentation events are replayable.</span><strong>The append-only SQLite ledger remains the evidence authority.</strong></footer>
    </div>
  )
}
