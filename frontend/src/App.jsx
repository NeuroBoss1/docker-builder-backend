import React, { useEffect, useState } from 'react'
import BuildForm from './components/BuildForm'
import Jobs from './components/Jobs'
import Creds from './components/Creds'
import History from './components/History'
import Registry from './components/Registry'
import Profile from './components/Profile'

export default function App() {
  const [route, setRoute] = useState(window.location.hash || '#/')

  useEffect(() => {
    const onHashChange = () => setRoute(window.location.hash || '#/')
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  // Navigation header component
  const NavHeader = () => (
    <header>
      <h1>🐳 Docker Builder</h1>
      <div style={{display: 'flex', gap: '12px', alignItems: 'center'}}>
        <button
          onClick={() => window.location.hash = '/'}
          style={{display: 'flex', alignItems: 'center', gap: '6px'}}
        >
          🏠 Home
        </button>
        <button
          onClick={() => window.location.hash = '/credentials'}
          style={{display: 'flex', alignItems: 'center', gap: '6px'}}
        >
          🔑 Credentials
        </button>
        <button
          onClick={() => window.location.hash = '/history'}
          style={{display: 'flex', alignItems: 'center', gap: '6px'}}
        >
          📜 History
        </button>
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
  )

  // Route to Credentials page
  if (route === '#/credentials') {
    return (
      <div className="container">
        <NavHeader />
        <main style={{display: 'flex', justifyContent: 'center', padding: '20px'}}>
          <div style={{maxWidth: '800px', width: '100%'}}>
            <Creds />
          </div>
        </main>
      </div>
    )
  }

  // Route to History page
  if (route === '#/history') {
    return (
      <div className="container">
        <NavHeader />
        <main style={{display: 'flex', justifyContent: 'center', padding: '20px'}}>
          <div style={{maxWidth: '800px', width: '100%'}}>
            <History />
          </div>
        </main>
      </div>
    )
  }

  // Route to Registry page
  if (route === '#/registry') {
    return (
      <div className="container">
        <NavHeader />
        <main style={{display: 'flex', justifyContent: 'center', padding: '20px'}}>
          <div style={{maxWidth: '1000px', width: '100%'}}>
            <Registry />
          </div>
        </main>
      </div>
    )
  }

  // Route to Profile page
  if (route === '#/profile') {
    return (
      <div className="container">
        <NavHeader />
        <main style={{display: 'flex', justifyContent: 'center', padding: '20px'}}>
          <div style={{maxWidth: '800px', width: '100%'}}>
            <Profile />
          </div>
        </main>
      </div>
    )
  }

  // Main page (Builder)
  return (
    <div className="container">
      <NavHeader />
      <main>
        <section className="left">
          <BuildForm />
        </section>
        <section className="right">
          <Jobs />
        </section>
      </main>
    </div>
  )
}
