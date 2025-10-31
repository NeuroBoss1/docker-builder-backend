import React, { useEffect, useState, useRef } from 'react'
import api from '../api'

function ProgressBar({ value, color }) {
  return (
    <div style={{ width: '220px', height: '12px', background: '#eee', borderRadius: '8px', overflow: 'hidden' }}>
      <div style={{ width: `${Math.max(0, Math.min(100, value))}%`, height: '100%', background: color || '#1976d2', transition: 'width 150ms linear' }} />
    </div>
  )
}

function parseProgressFromLogs(logs) {
  if (!logs || logs.length === 0) return null
  // Search from end for lines matching PROGRESS:<num>
  for (let i = logs.length - 1; i >= 0; i--) {
    const ln = logs[i]
    const m = typeof ln === 'string' ? ln.match(/PROGRESS:(\d{1,3})/) : null
    if (m) {
      const v = parseInt(m[1], 10)
      if (!isNaN(v)) return Math.max(0, Math.min(100, v))
    }
  }
  return null
}

export default function Queue({ selectedJobId = null }) {
  const [jobs, setJobs] = useState([])
  const [selected, setSelected] = useState(selectedJobId)
  const [logs, setLogs] = useState([])
  const [autoScroll, setAutoScroll] = useState(true)
  const logsRef = useRef(null)
  const pollRef = useRef(null)

  // Re-enqueue state
  const [reenqueueing, setReenqueueing] = useState(false)
  const [reenqueueResult, setReenqueueResult] = useState(null)
  const [perJobReenqueueing, setPerJobReenqueueing] = useState({})

  useEffect(() => {
    // if prop selectedJobId is provided or changes, set selected
    if (selectedJobId) {
      setSelected(selectedJobId)
    }

    // check localStorage for last deployed job (auto-select once)
    try {
      const last = localStorage.getItem('last_deployed_job')
      if (last) {
        setSelected(last)
        // remove key so it doesn't auto-select again
        localStorage.removeItem('last_deployed_job')
      }
    } catch (e) {}
  }, [selectedJobId])

  // Load list of jobs periodically
  useEffect(() => {
    let mounted = true
    const load = async () => {
      try {
        const r = await api.get('/builds')
        if (!mounted) return
        const resJobs = r.data || []
        const enriched = resJobs.map(j => {
          const p = parseProgressFromLogs(j.logs)
          return { ...j, progress: p }
        })
        setJobs(enriched)

        // If we have a selected job id but it's not yet in the list, try to keep it selected
        if (selectedJobId && !enriched.find(j => j.id === selectedJobId)) {
          // noop - job might be created shortly, keep selection until appears
        }
      } catch (e) {
        console.error('Failed to load jobs', e)
      }
    }
    load()
    const iv = setInterval(load, 3000)
    return () => { mounted = false; clearInterval(iv) }
  }, [selectedJobId])

  // When selected job changes, load logs and start polling that job
  useEffect(() => {
    if (!selected) {
      setLogs([])
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
      return
    }

    const loadLogs = async () => {
      try {
        const r = await api.get(`/build/${selected}`)
        const j = r.data
        setLogs(j.logs || [])
      } catch (e) {
        console.error('Failed to load job logs', e)
      }
    }

    loadLogs()
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(loadLogs, 1000)

    return () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null } }
  }, [selected])

  // Auto-scroll logs
  useEffect(() => {
    if (autoScroll && logsRef.current) {
      logsRef.current.scrollTop = logsRef.current.scrollHeight
    }
  }, [logs, autoScroll])

  const estimateProgress = (job) => {
    // prefer explicit PROGRESS:<n> found in logs
    if (job.progress !== undefined && job.progress !== null) return job.progress
    const state = job.state || 'queued'
    if (state === 'queued') return 5
    if (state === 'running') {
      const n = (job.logs && job.logs.length) || 0
      return Math.min(95, 5 + n * 2)
    }
    if (state === 'done') return 100
    if (state === 'error') return 100
    return 0
  }

  const colorForState = (state) => {
    if (state === 'done') return '#4caf50'
    if (state === 'error') return '#f44336'
    if (state === 'running') return '#1976d2'
    return '#999'
  }

  // Re-enqueue all jobs
  const reenqueAll = async () => {
    setReenqueueResult(null)
    setReenqueueing(true)
    try {
      const r = await api.post('/queue/reenqueue')
      console.debug('reenqueAll response:', r)
      const payload = (r && typeof r.data !== 'undefined') ? r.data : { status: r && r.status, statusText: r && r.statusText }
      // set state and also alert for immediate visibility during debugging
      setReenqueueResult(payload || {})
      try { window.alert('Re-enqueue response:\n' + JSON.stringify(payload, null, 2)) } catch (e) {}
    } catch (e) {
      console.error('reenqueAll error:', e)
      const errPayload = e?.response?.data ?? { error: e.message }
      setReenqueueResult(errPayload)
      try { window.alert('Re-enqueue error:\n' + JSON.stringify(errPayload, null, 2)) } catch (err) {}
    } finally {
      setReenqueueing(false)
    }
  }

  const reenqueJob = async (jobId) => {
    setPerJobReenqueueing(prev => ({ ...prev, [jobId]: true }))
    try {
      const r = await api.post(`/queue/reenqueue/${jobId}`)
      console.debug('reenqueJob response:', r)
      const payload = (r && typeof r.data !== 'undefined') ? r.data : { status: r && r.status, statusText: r && r.statusText }
      setReenqueueResult(prev => ({ ...(prev||{}), perJob: { id: jobId, result: payload } }))
      try { window.alert('Re-enqueue (job) response:\n' + JSON.stringify(payload, null, 2)) } catch (e) {}
    } catch (e) {
      console.error('reenqueJob error:', e)
      const errPayload = e?.response?.data ?? { error: e.message }
      setReenqueueResult(prev => ({ ...(prev||{}), perJob: { id: jobId, result: errPayload } }))
      try { window.alert('Re-enqueue (job) error:\n' + JSON.stringify(errPayload, null, 2)) } catch (err) {}
    } finally {
      setPerJobReenqueueing(prev => ({ ...prev, [jobId]: false }))
    }
  }

  return (
    <div className="container">
      <header style={{display:'flex', justifyContent:'space-between', alignItems:'center'}}>
        <h1>🛰️ Queue</h1>
        <div style={{display:'flex', gap:12, alignItems:'center'}}>
          <div style={{fontSize:13,color:'#666'}}>Auto-refresh every 3s • Select a job to see logs</div>
          <button onClick={reenqueAll} disabled={reenqueueing} style={{padding:'8px 12px', borderRadius:8, background: reenqueueing ? '#ccc' : '#1976d2', color:'white', border:'none', cursor: reenqueueing ? 'wait' : 'pointer'}}>
            {reenqueueing ? 'Re-enqueueing...' : 'Re-enqueue all'}
          </button>
        </div>
      </header>

      {reenqueueResult && (
        <div style={{marginTop:12}}>
          <div className="card">
            <strong>Re-enqueue results</strong>
            <div style={{marginTop:8}}>
              {/* DEBUG: always show raw response */}
              <div style={{marginBottom:8}}>
                <div style={{fontWeight:700}}>Response (raw):</div>
                <pre style={{whiteSpace:'pre-wrap', marginTop:6, background:'#f7f7f7', padding:8, borderRadius:6}}>{JSON.stringify(reenqueueResult, null, 2)}</pre>
              </div>

              {/* show explicit error if present */}
              {reenqueueResult.error && <div style={{color:'red', marginBottom:8}}>Error: {String(reenqueueResult.error)}</div>}

              {/* typical structured result */}
              {reenqueueResult.count && (
                <div style={{marginBottom:8}}>
                  Found: {reenqueueResult.count.found} • Requeued: {reenqueueResult.count.requeued} • Skipped: {reenqueueResult.count.skipped} • Errors: {reenqueueResult.count.errors}
                </div>
              )}

              {reenqueueResult.requeued && reenqueueResult.requeued.length > 0 && (
                <div style={{marginBottom:8}}>
                  <div style={{fontWeight:700}}>Requeued:</div>
                  <div style={{display:'flex', gap:8, flexWrap:'wrap'}}>
                    {reenqueueResult.requeued.map(id => <div key={id} style={{padding:'6px 8px', background:'#eef', borderRadius:6}}>{id.slice(0,8)}</div>)}
                  </div>
                </div>
              )}

              {reenqueueResult.skipped && reenqueueResult.skipped.length > 0 && (
                <div style={{marginBottom:8}}>
                  <div style={{fontWeight:700}}>Skipped:</div>
                  <ul>
                    {reenqueueResult.skipped.map(s => <li key={s.id}>{s.id.slice(0,8)} — {s.reason}</li>)}
                  </ul>
                </div>
              )}

              {reenqueueResult.errors && reenqueueResult.errors.length > 0 && (
                <div style={{marginBottom:8}}>
                  <div style={{fontWeight:700}}>Errors:</div>
                  <ul>
                    {reenqueueResult.errors.map(e => <li key={e.id}>{e.id}: {e.error}</li>)}
                  </ul>
                </div>
              )}

              {/* per-job result if present */}
              {reenqueueResult.perJob && (
                <div style={{marginTop:6}}>
                  <div style={{fontWeight:700}}>Per-job result ({(reenqueueResult.perJob.id||'') .slice ? reenqueueResult.perJob.id.slice(0,8) : ''}):</div>
                  <pre style={{whiteSpace:'pre-wrap', marginTop:6, background:'#f7f7f7', padding:8, borderRadius:6}}>{JSON.stringify(reenqueueResult.perJob.result, null, 2)}</pre>
                </div>
              )}

              {/* fallback: show raw JSON if nothing matched */}
              {(!reenqueueResult.count && !reenqueueResult.requeued && !reenqueueResult.perJob && !reenqueueResult.error) && (
                <div style={{marginTop:8}}>
                  <div style={{fontWeight:700}}>Raw response:</div>
                  <pre style={{whiteSpace:'pre-wrap', marginTop:6, background:'#f7f7f7', padding:8, borderRadius:6}}>{JSON.stringify(reenqueueResult, null, 2)}</pre>
                </div>
              )}

              <div style={{marginTop:8, fontSize:12, color:'#666'}}>Updated: {new Date().toLocaleString()}</div>
            </div>
          </div>
        </div>
      )}

      <main style={{display:'flex', gap:'20px', paddingTop:12}}>
        <section style={{flex:'0 0 380px'}}>
          <div className="card">
            <h3>Jobs</h3>
            <div style={{display:'grid', gap:10}}>
              {jobs.length === 0 && <div style={{color:'#666'}}>No jobs yet</div>}
              {jobs.map(job => (
                <div key={job.id} style={{display:'flex', gap:12, alignItems:'center', padding:'8px', borderRadius:6, background: selected===job.id ? '#f5f9ff' : 'white', cursor:'pointer'}} onClick={() => { setSelected(job.id) }}>
                  <div style={{flex:1}}>
                    <div style={{display:'flex', justifyContent:'space-between', alignItems:'center'}}>
                      <div style={{fontWeight:700}}>{job.id.slice(0,8)}</div>
                      <div style={{fontSize:12, color:'#666'}}>{job.state || 'queued'}</div>
                    </div>
                    <div style={{marginTop:8}}>
                      <ProgressBar value={estimateProgress(job)} color={colorForState(job.state)} />
                    </div>
                    <div style={{marginTop:8, fontSize:12, color:'#666'}}>
                      {job.progress !== undefined && job.progress !== null ? `Progress: ${job.progress}% • ` : ''}Logs: {(job.logs && job.logs.length) || 0}
                    </div>
                  </div>

                  <div style={{display:'flex', flexDirection:'column', gap:8}}>
                    <button title="Re-enqueue this job" onClick={(e) => { e.stopPropagation(); reenqueJob(job.id) }} disabled={!!perJobReenqueueing[job.id]} style={{minWidth:90, padding:'6px 12px', borderRadius:6, border:'1px solid #ddd', background:'#fff', color: '#111', cursor:'pointer', boxShadow: 'inset 0 -1px 0 rgba(0,0,0,0.02)', fontWeight:600, textAlign:'center'}}>
                      {perJobReenqueueing[job.id]
                        ? <span className="spinner" style={{width:14, height:14, borderWidth:2, display:'inline-block', verticalAlign:'middle'}} />
                        : 'Re-enqueue'
                      }
                    </button>
                  </div>

                </div>
              ))}
            </div>
          </div>
        </section>

        <section style={{flex:1}}>
          <div className="card">
            <h3>Details</h3>
            {!selected && <div style={{color:'#666'}}>Select a job on the left to view details and live logs.</div>}
            {selected && (
              <div>
                <div style={{display:'flex', justifyContent:'space-between', alignItems:'center'}}>
                  <div style={{fontWeight:700}}>Job {selected}</div>
                  <div style={{display:'flex', gap:8, alignItems:'center'}}>
                    <label style={{fontSize:13, color:'#666'}}>Auto-scroll</label>
                    <input type="checkbox" checked={autoScroll} onChange={e => setAutoScroll(e.target.checked)} />
                    <button onClick={() => { setSelected(null) }} style={{marginLeft:8}}>Close</button>
                  </div>
                </div>

                <div style={{marginTop:12}}>
                  <div style={{fontSize:13, color:'#666'}}>Live logs</div>
                  <div ref={logsRef} style={{height: '320px', overflowY:'auto', background:'#111', color:'#eee', padding:12, borderRadius:6, marginTop:8, fontFamily:'monospace', fontSize:13}}>
                    {logs.length === 0 && <div style={{color:'#999'}}>No logs yet</div>}
                    {logs.map((ln, idx) => (
                      <div key={idx} style={{whiteSpace:'pre-wrap', paddingBottom:4}}>{ln}</div>
                    ))}
                  </div>

                  <div style={{marginTop:12, display:'flex', gap:8}}>
                    <button onClick={async () => {
                      try {
                        const r = await api.get(`/build/${selected}`)
                        setLogs(r.data.logs || [])
                      } catch (e) { alert('Failed to refresh logs') }
                    }}>Refresh now</button>
                    <button onClick={async () => {
                      try {
                        await api.post(`/service-image-mapping`, { mappings: {} })
                        alert('noop')
                      } catch (e) {
                        alert('noop fail')
                      }
                    }}>Debug action</button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </section>
      </main>

    </div>
  )
}
