import React, { useState, useEffect } from 'react'
import api from '../api'

export default function Registry() {
  const [registries, setRegistries] = useState([])
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [isDefault, setIsDefault] = useState(false)
  const [useServiceAccount, setUseServiceAccount] = useState(false)
  const [projectId, setProjectId] = useState('')
  const [serviceAccountInfo, setServiceAccountInfo] = useState(null)
  const [selectedRegistry, setSelectedRegistry] = useState(null)
  const [images, setImages] = useState([])
  const [loadingImages, setLoadingImages] = useState(false)
  const [testingAuth, setTestingAuth] = useState(null)

  useEffect(() => {
    loadRegistries()
    loadServiceAccountInfo()
  }, [])

  const loadServiceAccountInfo = async () => {
    try {
      const r = await api.get('/service-account-info')
      setServiceAccountInfo(r.data)
      // Auto-fill project_id if available
      if (r.data.project_id && !projectId) {
        setProjectId(r.data.project_id)
      }
    } catch (e) {
      console.log('Service account not available:', e)
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

  const addRegistry = async () => {
    if (!name || !url) {
      alert('Please fill name and URL')
      return
    }

    // Validate: either service account or username+password
    if (!useServiceAccount && (!username || !password)) {
      alert('Please provide username and password, or use service account')
      return
    }

    try {
      await api.post('/registry', {
        name,
        url,
        username: useServiceAccount ? '' : username,
        password: useServiceAccount ? '' : password,
        is_default: isDefault,
        use_service_account: useServiceAccount,
        project_id: projectId
      })
      setName('')
      setUrl('')
      setUsername('')
      setPassword('')
      setIsDefault(false)
      setUseServiceAccount(false)
      await loadRegistries()
    } catch (e) {
      alert('Failed to add registry: ' + (e.response?.data?.detail || e.message))
    }
  }

  const deleteRegistry = async (id) => {
    if (!confirm('Delete this registry?')) return
    try {
      await api.delete(`/registry/${id}`)
      await loadRegistries()
      if (selectedRegistry?.id === id) {
        setSelectedRegistry(null)
        setImages([])
      }
    } catch (e) {
      alert('Failed to delete registry: ' + (e.response?.data?.detail || e.message))
    }
  }

  const testAuth = async (id) => {
    setTestingAuth(id)
    try {
      const r = await api.post(`/registry/${id}/test`)
      if (r.data.authenticated) {
        alert('✅ Authentication successful!')
      } else {
        alert('❌ Authentication failed: ' + (r.data.error || 'Unknown error'))
      }
      await loadRegistries()
    } catch (e) {
      alert('Failed to test authentication: ' + (e.response?.data?.detail || e.message))
    } finally {
      setTestingAuth(null)
    }
  }

  const loadImages = async (registry) => {
    setSelectedRegistry(registry)
    setImages([])
    setLoadingImages(true)

    try {
      const r = await api.get(`/registry/${registry.id}/images`)
      setImages(r.data.images || [])
      if (r.data.error) {
        alert('Note: ' + r.data.error)
      }
    } catch (e) {
      alert('Failed to load images: ' + (e.response?.data?.detail || e.message))
    } finally {
      setLoadingImages(false)
    }
  }

  return (
    <div className="container">
      <header>
        <h1>📦 Registry Management</h1>
        <button onClick={() => window.location.hash = '/'} style={{display: 'flex', alignItems: 'center', gap: '6px'}}>
          ← Back to Builder
        </button>
      </header>

      <main style={{display: 'block'}}>
        <div className="card">
          <h2>➕ Add Registry</h2>
          <div style={{fontSize: '13px', color: '#666', marginBottom: '12px'}}>
            Add Docker registries (Docker Hub, GCR, ACR, Harbor, etc.)
            {serviceAccountInfo && (
              <div style={{color: '#4caf50', marginTop: '4px'}}>
                ✅ Service Account available: {serviceAccountInfo.client_email}
              </div>
            )}
          </div>
          <div style={{display: 'grid', gap: '8px'}}>
            <input
              placeholder="Name (e.g., My GCR)"
              value={name}
              onChange={e => setName(e.target.value)}
            />
            <input
              placeholder="URL (e.g., gcr.io/my-project, docker.io/username)"
              value={url}
              onChange={e => setUrl(e.target.value)}
            />

            {serviceAccountInfo && (
              <label style={{border: '1px solid #1976d2', padding: '8px', borderRadius: '4px', backgroundColor: '#e3f2fd'}}>
                <input
                  type="checkbox"
                  checked={useServiceAccount}
                  onChange={e => setUseServiceAccount(e.target.checked)}
                />
                {' '}Use Service Account for authentication (recommended for GCR/Artifact Registry)
              </label>
            )}

            {!useServiceAccount && (
              <>
                <input
                  placeholder="Username (optional for public registries)"
                  value={username}
                  onChange={e => setUsername(e.target.value)}
                />
                <input
                  type="password"
                  placeholder="Password/Token"
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                />
              </>
            )}

            {(url.includes('gcr.io') || url.includes('pkg.dev') || url.includes('artifactregistry')) && (
              <div>
                <input
                  placeholder="Google Cloud Project ID (auto-filled from service account)"
                  value={projectId}
                  onChange={e => setProjectId(e.target.value)}
                />
                <div style={{fontSize: '11px', color: '#666', marginTop: '4px'}}>
                  For GCR: gcr.io/{projectId} or for Artifact Registry: {'{region}'}-docker.pkg.dev/{projectId}
                </div>
              </div>
            )}

            <label>
              <input
                type="checkbox"
                checked={isDefault}
                onChange={e => setIsDefault(e.target.checked)}
              />
              {' '}Set as default registry
            </label>
            <button onClick={addRegistry}>Add Registry</button>
          </div>
        </div>

        <div className="card">
          <h2>🗂️ My Registries</h2>
          {registries.length === 0 ? (
            <div>No registries added yet</div>
          ) : (
            <div style={{display: 'grid', gap: '12px'}}>
              {registries.map(reg => (
                <div key={reg.id} style={{
                  border: '1px solid #ddd',
                  borderRadius: '4px',
                  padding: '12px',
                  backgroundColor: reg.is_default ? '#f0f8ff' : 'white'
                }}>
                  <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'start'}}>
                    <div style={{flex: 1}}>
                      <div style={{fontWeight: 'bold', fontSize: '16px'}}>
                        {reg.name}
                        {reg.is_default && <span style={{marginLeft: '8px', fontSize: '12px', color: '#1976d2'}}>DEFAULT</span>}
                      </div>
                      <div style={{fontSize: '14px', color: '#666', marginTop: '4px'}}>
                        {reg.url}
                      </div>
                      {reg.use_service_account ? (
                        <div style={{fontSize: '12px', color: '#1976d2', marginTop: '4px'}}>
                          🔑 Using Service Account
                        </div>
                      ) : (
                        <div style={{fontSize: '12px', color: '#999', marginTop: '4px'}}>
                          User: {reg.username || '(none)'}
                        </div>
                      )}
                      {reg.project_id && (
                        <div style={{fontSize: '12px', color: '#666', marginTop: '2px'}}>
                          Project: {reg.project_id}
                        </div>
                      )}
                      <div style={{marginTop: '8px'}}>
                        {reg.is_authenticated ? (
                          <span style={{color: '#4caf50', fontSize: '13px'}}>✅ Authenticated</span>
                        ) : (
                          <span style={{color: '#f44336', fontSize: '13px'}}>❌ Not authenticated</span>
                        )}
                      </div>
                    </div>
                    <div style={{display: 'flex', gap: '8px', flexDirection: 'column'}}>
                      <button
                        onClick={() => testAuth(reg.id)}
                        disabled={testingAuth === reg.id}
                        style={{fontSize: '12px', padding: '4px 8px'}}
                      >
                        {testingAuth === reg.id ? 'Testing...' : 'Test Auth'}
                      </button>
                      <button
                        onClick={() => loadImages(reg)}
                        style={{fontSize: '12px', padding: '4px 8px'}}
                      >
                        View Images
                      </button>
                      <button
                        onClick={() => deleteRegistry(reg.id)}
                        style={{
                          fontSize: '12px',
                          padding: '4px 8px',
                          backgroundColor: '#fee',
                          color: '#c33',
                          border: '1px solid #fcc'
                        }}
                      >
                        🗑️ Delete
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {selectedRegistry && (
          <div className="card">
            <h2>🖼️ Images in {selectedRegistry.name}</h2>
            {loadingImages ? (
              <div>Loading images...</div>
            ) : images.length === 0 ? (
              <div>No images found or registry doesn't support listing</div>
            ) : (
              <div style={{display: 'grid', gap: '8px'}}>
                {images.map((img, idx) => (
                  <div key={idx} style={{
                    border: '1px solid #eee',
                    padding: '8px',
                    borderRadius: '4px'
                  }}>
                    <div style={{fontWeight: 'bold'}}>{img.name}</div>
                    <div style={{fontSize: '12px', color: '#666', marginTop: '4px'}}>
                      Tags: {img.tags.join(', ') || 'No tags'}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  )
}

