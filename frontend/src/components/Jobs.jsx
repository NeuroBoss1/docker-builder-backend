import React, { useEffect, useState } from 'react'
import api from '../api'

export default function Jobs() {
  const [jobs, setJobs] = useState([])

  useEffect(() => {
    let mounted = true
    const load = async () => {
      try {
        const r = await api.get('/builds')
        if (mounted) setJobs(r.data)
      } catch (e) {
        console.error('load jobs', e)
      }
    }
    load()
    const iv = setInterval(load, 3000)
    return () => { mounted = false; clearInterval(iv) }
  }, [])

  const getStateBadge = (state) => {
    const badges = {
      'done': { emoji: '✅', text: 'Done', class: 'badge badge-success' },
      'running': { emoji: '⚙️', text: 'Running', class: 'badge badge-info' },
      'queued': { emoji: '⏳', text: 'Queued', class: 'badge badge-warning' },
      'error': { emoji: '❌', text: 'Error', class: 'badge badge-error' }
    }
    return badges[state] || { emoji: '❓', text: state, class: 'badge' }
  }

  return (
    <div className="card">
      <h2>📊 Recent Jobs</h2>
      {jobs.length===0 ? <div className="text-muted">No jobs yet</div> : (
        <div>
          {jobs.map(j => {
            const badge = getStateBadge(j.state)
            return (
              <div key={j.id} className="job-mini">
                <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px'}}>
                  <span style={{fontWeight: '500', fontSize: '13px', color: 'var(--text-secondary)', fontFamily: 'monospace'}}>{j.id.slice(0, 8)}...</span>
                  <span className={badge.class}>{badge.emoji} {badge.text}</span>
                </div>
                {(j.logs||[]).length > 0 && (
                  <pre style={{
                    whiteSpace:'pre-wrap',
                    fontSize: '12px',
                    background: '#f8fafc',
                    padding: '8px',
                    borderRadius: '4px',
                    border: '1px solid var(--border)',
                    marginTop: '8px',
                    marginBottom: '0'
                  }}>{(j.logs||[]).slice(-3).join('\n')}</pre>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

