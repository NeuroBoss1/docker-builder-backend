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

  return (
    <div className="container">
      <header style={{display:'flex', justifyContent:'space-between', alignItems:'center'}}>
        <h1>🛰️ Queue</h1>
        <div style={{fontSize:13,color:'#666'}}>Auto-refresh every 3s • Select a job to see logs</div>
      </header>

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
