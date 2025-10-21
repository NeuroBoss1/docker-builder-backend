import React, { useEffect, useState } from 'react'
import api from '../api'

export default function History() {
  const [history, setHistory] = useState([])

  useEffect(() => {
    ;(async () => {
      try {
        const r = await api.get('/history')
        setHistory(r.data.history || [])
      } catch (e) {
        console.error(e)
      }
    })()
  }, [])

  return (
    <div className="card">
      <h2>📜 Build History</h2>
      {history.length===0 ? <div className="text-muted">No build history yet</div> : (
        <div style={{display: 'grid', gap: '8px'}}>
          {history.map(h => (
            <div key={h.id} style={{
              padding: '12px',
              background: '#f8fafc',
              border: '1px solid var(--border)',
              borderRadius: '6px',
              transition: 'var(--transition)'
            }}>
              <div style={{display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px'}}>
                <span style={{fontSize: '14px'}}>🏷️</span>
                <strong style={{fontSize: '14px', color: 'var(--text-primary)'}}>{h.tag}</strong>
              </div>
              <div className="text-small text-muted" style={{marginBottom: '4px', wordBreak: 'break-all'}}>{h.repo_url}</div>
              <div style={{fontSize: '11px', color: 'var(--text-secondary)', display: 'flex', gap: '8px', alignItems: 'center'}}>
                <span>🕐 {new Date(h.timestamp).toLocaleString()}</span>
                <span>•</span>
                <span>🌿 {h.branch}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

