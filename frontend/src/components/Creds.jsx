import React, { useState, useEffect } from 'react'
import api from '../api'

export default function Creds() {
  const [creds, setCreds] = useState({})
  const [name, setName] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  const loadCreds = async () => {
    try {
      const r = await api.get('/creds')
      setCreds(r.data.creds || {})
    } catch (e) {
      console.error(e)
    }
  }

  useEffect(() => {
    loadCreds()
  }, [])

  const add = async () => {
    try {
      await api.post('/creds', { name, username, password })
      setName(''); setUsername(''); setPassword('')
      await loadCreds()
    } catch (e) {
      alert('Failed to add cred: ' + (e.response?.data?.detail || e.message))
    }
  }

  const deleteCred = async (credName) => {
    if (!confirm(`Delete credential "${credName}"?`)) return
    try {
      await api.delete(`/creds/${encodeURIComponent(credName)}`)
      await loadCreds()
    } catch (e) {
      alert('Failed to delete: ' + (e.response?.data?.detail || e.message))
    }
  }

  return (
    <div className="card">
      <h2>🔐 Private Repository Credentials</h2>
      <div className="text-muted" style={{marginBottom: '16px'}}>
        Use repository host as name (e.g., "git.ascender.space", "https://git.ascender.space/", or "github.com")
      </div>
      <div>
        <input placeholder="Name (e.g. https://git.ascender.space/)" value={name} onChange={e=>setName(e.target.value)} />
        <input placeholder="Username" value={username} onChange={e=>setUsername(e.target.value)} />
        <input placeholder="Password/token" value={password} onChange={e=>setPassword(e.target.value)} />
        <button onClick={add}>Add</button>
      </div>
      <div style={{marginTop: '20px'}}>
        <h3 style={{fontSize: '15px', fontWeight: '600', marginBottom: '12px'}}>💾 Saved Credentials</h3>
        {Object.keys(creds).length===0 ? <div className="text-muted">No credentials saved yet</div> : (
          <div style={{display: 'grid', gap: '8px'}}>
            {Object.entries(creds).map(([k,v])=> (
              <div key={k} style={{
                padding: '10px 14px',
                background: '#f8fafc',
                border: '1px solid var(--border)',
                borderRadius: '6px',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center'
              }}>
                <div>
                  <span style={{fontWeight: '500', color: 'var(--text-primary)'}}>{k}</span>
                  <span style={{marginLeft: '8px', fontSize: '13px', color: 'var(--text-secondary)'}}>• {v.username}</span>
                </div>
                <button
                  onClick={() => deleteCred(k)}
                  style={{
                    padding: '4px 12px',
                    fontSize: '13px',
                    background: '#fee',
                    color: '#c33',
                    border: '1px solid #fcc',
                    cursor: 'pointer'
                  }}
                >
                  🗑️ Delete
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

