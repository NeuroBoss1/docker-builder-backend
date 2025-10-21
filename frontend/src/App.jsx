import React, { useEffect, useState } from 'react'
import BuildForm from './components/BuildForm'
import Jobs from './components/Jobs'
import Creds from './components/Creds'
import History from './components/History'
import Registry from './components/Registry'
import Profile from './components/Profile'

export default function App() {
  // Auth is handled on backend via secrets/docker-puller-key.json file
  // No frontend auth needed anymore

  const [route, setRoute] = useState(window.location.hash || '#/')

  useEffect(() => {
    const onHashChange = () => setRoute(window.location.hash || '#/')
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  // Route to Registry page
  if (route === '#/registry') {
    return <Registry />
  }

  // Route to Profile page
  if (route === '#/profile') {
    return <Profile />
  }

  // Main page (Builder)
  return (
    <div className="container">
      <header>
        <h1>🐳 Docker Builder</h1>
        <div style={{display: 'flex', gap: '12px', alignItems: 'center'}}>
          <button
            onClick={() => window.location.hash = '/registry'}
            style={{display: 'flex', alignItems: 'center', gap: '6px'}}
          >
            📦 Registry
          </button>
          <button
            onClick={() => window.location.hash = '/profile'}
            style={{display: 'flex', alignItems: 'center', gap: '6px'}}
          >
            👤 Profile
          </button>
        </div>
      </header>

      <main>
        <section className="left">
          <BuildForm />
          <Creds />
        </section>
        <section className="right">
          <Jobs />
          <History />
        </section>
      </main>
    </div>
  )
}
