import React, { useEffect, useState } from 'react'
import api from '../api'

// Статический список сервисов и их репо-имен
const DEFAULT_BASE = 'us-central1-docker.pkg.dev/augmented-audio-474107-v3/neuroboss-docker-repo'
const SERVICES = [
  { id: 'rag', name: 'Rag', repoName: 'rag-service', base: `${DEFAULT_BASE}/rag-service` },
  { id: 'neuroboss', name: 'Neuroboss', repoName: 'neuroboss-service', base: `${DEFAULT_BASE}/neuroboss-service` },
  { id: 'agent', name: 'Agent', repoName: 'agent-service', base: `${DEFAULT_BASE}/agent-service` }
]

// Страница для назначения образов сервисам: выпадающие списки тегов для каждого сервиса
export default function ServicesImages() {
  const [registries, setRegistries] = useState([])
  const [imagesByRegistry, setImagesByRegistry] = useState({}) // registryId -> images[]
  const [defaultRegistryId, setDefaultRegistryId] = useState(null)
  const [mappings, setMappings] = useState({}) // serviceId -> full image with tag
  const [loadingImages, setLoadingImages] = useState({}) // registryId -> bool
  const [saving, setSaving] = useState(false)
  const [serviceImageInfo, setServiceImageInfo] = useState({}) // serviceId -> { registryId, entry }

  useEffect(() => {
    (async () => {
      try {
        const r = await api.get('/registry')
        const regs = r.data.registries || []
        setRegistries(regs)

        // Try to auto-select registry that contains DEFAULT_BASE for all services
        const matched = regs.find(rr => (rr.url || '').includes('us-central1-docker.pkg.dev') && (rr.url || '').includes('neuroboss-docker-repo'))
        if (matched) {
          setDefaultRegistryId(matched.id)
        }

        // Load images for all registries (sequentially) and build service -> entry mapping
        const info = {}
        for (const reg of regs) {
          try {
            const imgs = await loadImagesForRegistry(reg)
            // check each service if not yet mapped
            for (const svc of SERVICES) {
              if (info[svc.id]) continue
              const found = (imgs || []).find(i => i.name === svc.repoName || i.name.endsWith('/' + svc.repoName) || i.name.includes(svc.repoName))
              if (found) {
                info[svc.id] = { registryId: reg.id, entry: found }
              }
            }
          } catch (e) {
            // ignore individual registry failures
          }
        }
        setServiceImageInfo(info)
      } catch (e) {
        console.error('Failed to load registries', e)
        setRegistries([])
      }

      // Try load saved mappings
      try {
        const r2 = await api.get('/service-image-mapping')
        setMappings(r2.data.mappings || {})
      } catch (e) {
        // noop
      }
    })()
  }, [])

  const loadImagesForRegistry = async (registry) => {
    if (!registry) return []
    if (imagesByRegistry[registry.id]) return imagesByRegistry[registry.id]
    setLoadingImages(prev => ({ ...prev, [registry.id]: true }))
    try {
      const r = await api.get(`/registry/${registry.id}/images`)
      const imgs = r.data.images || []
      setImagesByRegistry(prev => ({ ...prev, [registry.id]: imgs }))
      return imgs
    } catch (e) {
      // don't alert here; just return empty
      return []
    } finally {
      setLoadingImages(prev => ({ ...prev, [registry.id]: false }))
    }
  }

  const setTagForService = (serviceId, fullImage) => {
    setMappings(prev => ({ ...prev, [serviceId]: fullImage }))
  }

  const saveMappings = async () => {
    setSaving(true)
    try {
      // save mappings first
      await api.post('/service-image-mapping', { mappings })
    } catch (e) {
      alert('Failed to save mappings: ' + (e.response?.data?.detail || e.message))
      setSaving(false)
      return
    }

    // then trigger deploy
    try {
      const r = await api.post('/deploy-services', { mappings })
      const id = r.data?.id
      const enqueued = r.data?.enqueued
      alert('Deploy started. id=' + id + ' enqueued=' + enqueued)
      if (id) {
        // store id so Queue page can auto-select
        try { localStorage.setItem('last_deployed_job', id) } catch (err) {}
        // navigate to Queue
        window.location.hash = '/queue'
      }
    } catch (e) {
      alert('Failed to start deploy: ' + (e.response?.data?.detail || e.message))
    } finally {
      setSaving(false)
    }
  }

  const getInfoForService = (serviceId) => {
    return serviceImageInfo[serviceId] || null
  }

  return (
    <div className="container">
      <header>
        <h1>🧩 Service → Image mapping</h1>
        <button onClick={() => window.location.hash = '/'} style={{display: 'flex', alignItems: 'center', gap: '6px'}}>← Back</button>
      </header>

      <main style={{paddingTop: '12px'}}>
        <div style={{display:'grid', gap:'12px'}}>
          {SERVICES.map(service => (
            <div key={service.id} className="card">
              <div style={{display:'flex', justifyContent:'space-between', alignItems:'center'}}>
                <div>
                  <div style={{fontWeight:700}}>{service.name}</div>
                  <div style={{fontSize:'13px', color:'#666'}}>{service.base}</div>
                </div>

                <div style={{display:'flex', gap:'12px', alignItems:'center'}}>
                  <div>
                    <div style={{fontSize:'12px', color:'#333', marginBottom:'6px', fontWeight:600}}>Select TAG</div>

                    {getInfoForService(service.id) ? (
                      (() => {
                        const info = getInfoForService(service.id)
                        const entry = info.entry
                        const reg = registries.find(r => r.id === info.registryId)
                        const tags = entry.tags || []
                        return (
                          <div>
                            <div style={{fontSize:'12px', color:'#666', marginBottom:'6px'}}>Registry: <strong>{reg?.name || reg?.url}</strong></div>
                            <select value={mappings[service.id] || ''} onChange={e => setTagForService(service.id, e.target.value)} style={{padding:'6px 8px'}}>
                              <option value="">TAG</option>
                              {tags.map(t => {
                                const base = reg ? reg.url.replace(/\/+$/,'') : ''
                                // entry.name may already include the base (or a full path). Avoid duplicating.
                                let repoPath = entry.name || ''
                                if (base && repoPath.startsWith(base)) {
                                  // remove the base prefix from repoPath to avoid base/base/... duplication
                                  repoPath = repoPath.slice(base.length).replace(/^\/+/, '')
                                }
                                // If repoPath is empty for some reason, fall back to entry.name
                                const effectiveRepo = repoPath || entry.name || ''
                                let full
                                if (base) {
                                  full = effectiveRepo ? `${base}/${effectiveRepo}:${t}` : `${base}:${t}`
                                } else {
                                  full = effectiveRepo ? `${effectiveRepo}:${t}` : `${t}`
                                }
                                return <option key={t} value={full}>{t}</option>
                              })}
                            </select>
                          </div>
                        )
                      })()
                    ) : (
                      // not found in any registry -> manual input
                      <div style={{display:'flex', gap:'8px', alignItems:'center'}}>
                        <div style={{fontSize:'13px', color:'#d32f2f'}}>Repo not found in known registries</div>
                        <input
                          placeholder="manually: registry/repo:tag"
                          value={mappings[service.id] || ''}
                          onChange={e => setTagForService(service.id, e.target.value)}
                          style={{minWidth:'320px', padding:'6px 8px'}}
                        />
                      </div>
                    )}

                  </div>
                </div>

              </div>
            </div>
          ))}
        </div>

        <div style={{display:'flex', justifyContent:'center', marginTop:'28px', marginBottom:'40px'}}>
          <button
            onClick={saveMappings}
            disabled={saving}
            style={{
              padding: '12px 28px',
              borderRadius: '10px',
              border: 'none',
              cursor: 'pointer',
              background: 'linear-gradient(90deg, #1976d2 0%, #42a5f5 100%)',
              color: 'white',
              fontWeight: 700,
              fontSize: '15px',
              boxShadow: '0 8px 20px rgba(25,118,210,0.18)',
              opacity: saving ? 0.7 : 1
            }}
          >
            {saving ? 'Deploying...' : 'Deploy'}
          </button>
        </div>
      </main>
    </div>
  )
}
