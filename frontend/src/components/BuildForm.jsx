import React, { useState, useEffect, useRef } from 'react'
import api from '../api'

export default function BuildForm() {
  const [repo, setRepo] = useState('')
  const [branches, setBranches] = useState([])
  const [branchesLoading, setBranchesLoading] = useState(false)
  const [branchesLoaded, setBranchesLoaded] = useState(false)
  const [branch, setBranch] = useState('main')
  const [tag, setTag] = useState('')
  const [registry, setRegistry] = useState('')
  const [registries, setRegistries] = useState([])
  const [customRegistry, setCustomRegistry] = useState(false)
  const [dockerfile, setDockerfile] = useState('')
  const [push, setPush] = useState(true)
  const [dryRun, setDryRun] = useState(false)
  const [noCache, setNoCache] = useState(false)
  const [buildArgs, setBuildArgs] = useState([])
  const [loadingBuildArgs, setLoadingBuildArgs] = useState(false)
  const [logs, setLogs] = useState(null)
  const [jobId, setJobId] = useState(null)
  const [tagError, setTagError] = useState('')
  const timerRef = useRef(null)

  useEffect(() => {
    // Load registries on mount
    (async () => {
      try {
        const r = await api.get('/registry')
        const regs = r.data.registries || []
        setRegistries(regs)

        // Set default registry if available
        const defaultReg = regs.find(reg => reg.is_default && reg.is_authenticated)
        if (defaultReg) {
          setRegistry(defaultReg.url)
        } else if (regs.length > 0 && regs[0].is_authenticated) {
          setRegistry(regs[0].url)
        }
      } catch (e) {
        console.error('Failed to load registries', e)
      }
    })()
  }, [])

  useEffect(() => {
    // debounce repo input then fetch branches
    if (timerRef.current) clearTimeout(timerRef.current)
    if (!repo) {
      setBranches([])
      setBranchesLoaded(false)
      setBranchesLoading(false)
      return
    }

    setBranchesLoading(true)
    setBranchesLoaded(false)

    timerRef.current = setTimeout(async () => {
      try {
        const r = await api.get('/branches', { params: { repo_url: repo } })
        const fetchedBranches = r.data.branches || []
        setBranches(fetchedBranches)
        setBranchesLoaded(true)
        setBranchesLoading(false)
        if (fetchedBranches.length > 0) {
          setBranch(fetchedBranches[0])
        }
      } catch (e) {
        console.error('branches error', e)
        setBranches([])
        setBranchesLoaded(true)
        setBranchesLoading(false)
      }
    }, 600)
  }, [repo])

  useEffect(() => {
    if (!jobId) return
    const iv = setInterval(async () => {
      try {
        const r = await api.get(`/build/${jobId}`)
        setLogs(r.data.logs.join('\n'))
        if (r.data.state === 'done' || r.data.state === 'error') clearInterval(iv)
      } catch (e) {
        clearInterval(iv)
      }
    }, 1000)
    return () => clearInterval(iv)
  }, [jobId])

  // Load build args from Dockerfile when repo, branch, or dockerfile path changes
  useEffect(() => {
    if (!repo || !branch || branchesLoading) return

    // Debounce to avoid too many requests
    const timer = setTimeout(async () => {
      setLoadingBuildArgs(true)
      try {
        const r = await api.get('/parse-dockerfile', {
          params: {
            repo_url: repo,
            branch: branch,
            dockerfile_path: dockerfile || 'Dockerfile'
          }
        })
        setBuildArgs(r.data.build_args || [])
      } catch (e) {
        console.error('Failed to parse Dockerfile:', e)
        setBuildArgs([])
      } finally {
        setLoadingBuildArgs(false)
      }
    }, 800)

    return () => clearTimeout(timer)
  }, [repo, branch, dockerfile])

  const generateTag = () => {
    const pad = (n) => String(n).padStart(2, '0')
    const d = new Date()
    const y = d.getUTCFullYear()
    const m = pad(d.getUTCMonth() + 1)
    const day = pad(d.getUTCDate())
    const hh = pad(d.getUTCHours())
    const mm = pad(d.getUTCMinutes())
    const ss = pad(d.getUTCSeconds())
    return `${y}${m}${day}-${hh}${mm}${ss}`
  }

  const validateTag = (raw) => {
    const t = (raw || '').trim()
    // Allow empty (will be auto-generated). If not empty, validate docker tag rules
    if (t.length === 0) return { ok: true, value: '' }
    const ok = t.length <= 128 && /^[A-Za-z0-9_][A-Za-z0-9_.-]*$/.test(t)
    return { ok, value: t }
  }

  const submit = async (e) => {
    e.preventDefault()

    // Validate that branches are loaded and available
    if (branchesLoaded && branches.length === 0) {
      alert('Cannot start build: No branches found. Please add credentials for this private repository.')
      return
    }

    if (!branch) {
      alert('Please select a branch')
      return
    }

    // Trim registry and validate/trim tag
    const registryTrimmed = (registry || '').trim()
    const { ok, value: tagTrimmed } = validateTag(tag)
    if (!ok) {
      setTagError('Invalid tag. Allowed: letters, digits, underscore, dot, dash; max 128; no spaces.')
      return
    } else {
      setTagError('')
    }

    const finalTag = tagTrimmed || generateTag()
    if (!tagTrimmed) {
      // reflect auto-generated tag in UI so пользователь видит, что будет использовано
      setTag(finalTag)
    }

    try {
      // Convert build args array to object {name: value}
      const buildArgsObject = {}
      buildArgs.forEach(arg => {
        if (arg.value !== undefined && arg.value !== null && arg.value !== '') {
          buildArgsObject[arg.name] = arg.value
        }
      })

      const payload = {
        repo_url: repo,
        branch,
        tag: finalTag,
        registry: registryTrimmed,
        dockerfile_path: dockerfile,
        build_args: buildArgsObject,
        push,
        dry_run: dryRun,
        no_cache: noCache
      }
      const r = await api.post('/build', payload)
      setJobId(r.data.id)
      setLogs('queued...')
    } catch (err) {
      alert('Failed to create build: ' + (err.response?.data?.detail || err.message))
    }
  }

  return (
    <div className="card">
      <h2>🚀 Start Build</h2>
      <form onSubmit={submit}>
        <label>Repository URL
          <input value={repo} onChange={e=>setRepo(e.target.value)} placeholder="https://github.com/user/repo.git" required />
        </label>
        <label>Branch
          <select value={branch} onChange={e=>setBranch(e.target.value)} disabled={branchesLoading || (branchesLoaded && branches.length === 0)}>
            {branchesLoading && <option value="">Loading branches...</option>}
            {!branchesLoading && branchesLoaded && branches.length === 0 && <option value="">No branches found (check credentials)</option>}
            {!branchesLoading && branches.length > 0 && branches.map(b=> <option key={b} value={b}>{b}</option>)}
            {!branchesLoading && !branchesLoaded && <option value="main">main</option>}
          </select>
          {branchesLoaded && branches.length === 0 && repo && (
            <div style={{fontSize: '12px', color: '#d32f2f', marginTop: '4px'}}>
              ⚠️ No branches found. Please add credentials for this repository.
            </div>
          )}
        </label>
        <label>Tag
          <input value={tag} onChange={e=>{ setTag(e.target.value); setTagError('') }} placeholder="auto if empty (UTC yyyymmdd-hhmmss)" />
          {tagError && <div style={{fontSize:'12px', color:'#d32f2f', marginTop:'4px'}}>{tagError}</div>}
          <div style={{fontSize:'11px', color:'#666', marginTop:'4px'}}>Leave empty to auto-generate (UTC yyyymmdd-hhmmss). Allowed: letters, digits, underscore, dot, dash; no spaces.</div>
        </label>
        <label>Registry
          {customRegistry ? (
            <div>
              <input value={registry} onChange={e=>setRegistry(e.target.value)} placeholder="gcr.io/project/image" required />
              <button type="button" onClick={() => setCustomRegistry(false)} style={{fontSize: '12px', marginTop: '4px'}}>
                Use saved registry
              </button>
            </div>
          ) : (
            <div>
              <select value={registry} onChange={e=>setRegistry(e.target.value)} required>
                <option value="">-- Select registry --</option>
                {registries.filter(r => r.is_authenticated).map(r => (
                  <option key={r.id} value={r.url}>
                    {r.name} ({r.url}) {r.is_default ? '⭐' : ''}
                  </option>
                ))}
              </select>
              {registries.filter(r => r.is_authenticated).length === 0 && (
                <div style={{fontSize: '12px', color: '#f44336', marginTop: '4px'}}>
                  ⚠️ No authenticated registries. <a href="#/registry">Add registry</a>
                </div>
              )}
              <button type="button" onClick={() => setCustomRegistry(true)} style={{fontSize: '12px', marginTop: '4px'}}>
                Use custom registry URL
              </button>
            </div>
          )}
        </label>
        <label>Dockerfile path
          <input value={dockerfile} onChange={e=>setDockerfile(e.target.value)} placeholder="Dockerfile" />
        </label>

        {/* Build Arguments Section */}
        {loadingBuildArgs && (
          <div style={{fontSize: '13px', color: '#666', padding: '8px', backgroundColor: '#f5f5f5', borderRadius: '4px'}}>
            Loading build arguments from Dockerfile...
          </div>
        )}

        {!loadingBuildArgs && buildArgs.length > 0 && (
          <div style={{border: '1.5px solid var(--primary-color)', borderRadius: '8px', padding: '16px', backgroundColor: 'var(--primary-light)', marginTop: '8px', marginBottom: '8px'}}>
            <div style={{fontWeight: '600', marginBottom: '8px', fontSize: '15px', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '6px'}}>
              ⚙️ Build Arguments (from Dockerfile)
            </div>
            <div style={{fontSize: '13px', color: 'var(--text-secondary)', marginBottom: '12px'}}>
              Found {buildArgs.length} ARG directive{buildArgs.length > 1 ? 's' : ''} in Dockerfile
            </div>
            <div style={{display: 'grid', gap: '8px'}}>
              {buildArgs.map((arg, idx) => (
                <div key={idx} style={{display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '8px', alignItems: 'center'}}>
                  <label style={{fontSize: '13px', fontWeight: '500'}}>
                    {arg.name}:
                  </label>
                  <input
                    value={arg.value || ''}
                    onChange={e => {
                      const newArgs = [...buildArgs]
                      newArgs[idx].value = e.target.value
                      setBuildArgs(newArgs)
                    }}
                    placeholder={arg.default_value ? `Default: ${arg.default_value}` : 'Enter value'}
                    style={{fontSize: '13px', padding: '6px'}}
                  />
                </div>
              ))}
            </div>
          </div>
        )}

        <label><input type="checkbox" checked={push} onChange={e=>setPush(e.target.checked)} /> Push after build</label>
        <label><input type="checkbox" checked={dryRun} onChange={e=>setDryRun(e.target.checked)} /> Dry run</label>
        <label><input type="checkbox" checked={noCache} onChange={e=>setNoCache(e.target.checked)} /> Build without cache (--no-cache)</label>
        <button type="submit" disabled={branchesLoading || (branchesLoaded && branches.length === 0)}>
          {branchesLoading ? 'Loading...' : 'Start'}
        </button>
      </form>

      {jobId && (
        <div className="logs">
          <h3>Job {jobId}</h3>
          <pre>{logs}</pre>
        </div>
      )}
    </div>
  )
}
