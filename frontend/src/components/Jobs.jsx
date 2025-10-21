import React, { useEffect, useState } from 'react'
import api from '../api'

export default function Jobs() {
  const [jobs, setJobs] = useState([])
  const [selectedJob, setSelectedJob] = useState(null)

  useEffect(() => {
    let mounted = true
    const load = async () => {
      try {
        const r = await api.get('/builds')
        if (mounted) {
          // Сортировка: running -> queued -> done -> error, затем по времени (новые сверху)
          const sorted = [...r.data].sort((a, b) => {
            const stateOrder = { running: 0, queued: 1, done: 2, error: 3 }
            const stateA = stateOrder[a.state] ?? 4
            const stateB = stateOrder[b.state] ?? 4

            if (stateA !== stateB) return stateA - stateB

            // Если статусы одинаковые, сортируем по времени (новые сверху)
            return (b.timestamp || 0) - (a.timestamp || 0)
          })
          setJobs(sorted)
        }
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

  const openJobModal = (job) => {
    setSelectedJob(job)
  }

  const closeModal = () => {
    setSelectedJob(null)
  }

  return (
    <>
      <div className="card">
        <h2>📊 Recent Jobs</h2>
        {jobs.length===0 ? <div className="text-muted">No jobs yet</div> : (
          <div>
            {jobs.map(j => {
              const badge = getStateBadge(j.state)
              return (
                <div
                  key={j.id}
                  className="job-mini"
                  onClick={() => openJobModal(j)}
                  style={{cursor: 'pointer'}}
                >
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

      {/* Modal window for job logs */}
      {selectedJob && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.5)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: '20px'
          }}
          onClick={closeModal}
        >
          <div
            style={{
              backgroundColor: 'white',
              borderRadius: '8px',
              maxWidth: '900px',
              width: '100%',
              maxHeight: '80vh',
              display: 'flex',
              flexDirection: 'column',
              boxShadow: '0 4px 20px rgba(0,0,0,0.15)'
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{
              padding: '20px',
              borderBottom: '1px solid var(--border)',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center'
            }}>
              <div>
                <h2 style={{margin: 0, fontSize: '20px'}}>📋 Job Logs</h2>
                <div style={{
                  marginTop: '8px',
                  fontSize: '13px',
                  color: 'var(--text-secondary)',
                  fontFamily: 'monospace'
                }}>
                  ID: {selectedJob.id}
                </div>
              </div>
              <div style={{display: 'flex', alignItems: 'center', gap: '12px'}}>
                {(() => {
                  const badge = getStateBadge(selectedJob.state)
                  return <span className={badge.class}>{badge.emoji} {badge.text}</span>
                })()}
                <button
                  onClick={closeModal}
                  style={{
                    fontSize: '24px',
                    background: 'none',
                    border: 'none',
                    cursor: 'pointer',
                    padding: '0 8px',
                    color: '#666'
                  }}
                >
                  ×
                </button>
              </div>
            </div>
            <div style={{
              padding: '20px',
              overflow: 'auto',
              flex: 1
            }}>
              {(selectedJob.logs || []).length === 0 ? (
                <div className="text-muted">No logs available</div>
              ) : (
                <pre style={{
                  whiteSpace: 'pre-wrap',
                  fontSize: '12px',
                  background: '#f8fafc',
                  padding: '16px',
                  borderRadius: '6px',
                  border: '1px solid var(--border)',
                  margin: 0,
                  fontFamily: 'monospace',
                  lineHeight: '1.5'
                }}>
                  {selectedJob.logs.join('\n')}
                </pre>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  )
}

