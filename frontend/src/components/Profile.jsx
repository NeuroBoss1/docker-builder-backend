import React, { useState, useEffect } from 'react'
import api from '../api'

export default function Profile() {
  const [profile, setProfile] = useState({})
  const [creds, setCreds] = useState({})
  const [registries, setRegistries] = useState([])
  const [history, setHistory] = useState([])

  useEffect(() => {
    loadProfile()
    loadCreds()
    loadRegistries()
    loadHistory()
  }, [])

  const loadProfile = async () => {
    try {
      const r = await api.get('/profile')
      setProfile(r.data.profile || {})
    } catch (e) {
      console.error('Failed to load profile', e)
    }
  }

  const loadCreds = async () => {
    try {
      const r = await api.get('/creds')
      setCreds(r.data.creds || {})
    } catch (e) {
      console.error('Failed to load creds', e)
    }
  }

  const loadRegistries = async () => {
    try {
      const r = await api.get('/registry')
      setRegistries(r.data.registries || [])
    } catch (e) {
      console.error('Failed to load registries', e)
    }
  }

  const loadHistory = async () => {
    try {
      const r = await api.get('/history')
      setHistory(r.data.history || [])
    } catch (e) {
      console.error('Failed to load history', e)
    }
  }

  return (
    <div className="container">
      <header>
        <h1>👤 Profile</h1>
        <button onClick={() => window.location.hash = '/'} style={{display: 'flex', alignItems: 'center', gap: '6px'}}>
          ← Back to Builder
        </button>
      </header>

      <main style={{display: 'block'}}>
        <div className="card">
          <h2>ℹ️ User Information</h2>
          <div style={{display: 'grid', gap: '8px'}}>
            <div><strong>Email:</strong> {profile.email || 'N/A'}</div>
            <div><strong>Name:</strong> {profile.name || 'N/A'}</div>
            <div><strong>ID:</strong> {profile.sub || 'Service Account'}</div>
          </div>
        </div>

        <div className="card">
          <h2>🔐 Git Repository Credentials ({Object.keys(creds).length})</h2>
          {Object.keys(creds).length === 0 ? (
            <div>No credentials saved</div>
          ) : (
            <div style={{display: 'grid', gap: '8px'}}>
              {Object.entries(creds).map(([key, val]) => (
                <div key={key} style={{
                  border: '1px solid #eee',
                  padding: '8px',
                  borderRadius: '4px'
                }}>
                  <div style={{fontWeight: 'bold'}}>{key}</div>
                  <div style={{fontSize: '13px', color: '#666'}}>
                    Username: {val.username || 'N/A'}
                  </div>
                </div>
              ))}
            </div>
          )}
          <div style={{marginTop: '12px', fontSize: '13px', color: '#666'}}>
            Add more credentials on the main page
          </div>
        </div>

        <div className="card">
          <h2>📦 Docker Registries ({registries.length})</h2>
          {registries.length === 0 ? (
            <div>No registries added</div>
          ) : (
            <div style={{display: 'grid', gap: '8px'}}>
              {registries.map(reg => (
                <div key={reg.id} style={{
                  border: '1px solid #eee',
                  padding: '8px',
                  borderRadius: '4px',
                  backgroundColor: reg.is_default ? '#f0f8ff' : 'white'
                }}>
                  <div style={{fontWeight: 'bold'}}>
                    {reg.name}
                    {reg.is_default && <span style={{marginLeft: '8px', fontSize: '11px', color: '#1976d2'}}>DEFAULT</span>}
                  </div>
                  <div style={{fontSize: '13px', color: '#666'}}>{reg.url}</div>
                  <div style={{fontSize: '12px', marginTop: '4px'}}>
                    {reg.is_authenticated ? (
                      <span style={{color: '#4caf50'}}>✅ Authenticated</span>
                    ) : (
                      <span style={{color: '#f44336'}}>❌ Not authenticated</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
          <div style={{marginTop: '12px'}}>
            <button onClick={() => window.location.hash = '/registry'}>
              Manage Registries
            </button>
          </div>
        </div>

        <div className="card">
          <h2>📜 Build History ({history.length})</h2>
          {history.length === 0 ? (
            <div>No builds yet</div>
          ) : (
            <div style={{maxHeight: '400px', overflow: 'auto'}}>
              {history.slice(0, 20).map((h, idx) => (
                <div key={idx} style={{
                  borderBottom: '1px solid #eee',
                  padding: '8px 0',
                  fontSize: '13px'
                }}>
                  <div style={{fontWeight: 'bold'}}>{h.tag}</div>
                  <div style={{color: '#666', fontSize: '12px'}}>{h.repo_url}</div>
                  <div style={{color: '#999', fontSize: '11px', marginTop: '4px'}}>
                    {h.timestamp} • Branch: {h.branch}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  )
}

