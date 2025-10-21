import React, { useEffect } from 'react'
import api, { setToken } from '../api'

export default function OAuthCallback({ onSignIn }) {
  useEffect(() => {
    // parse code from querystring
    const params = new URLSearchParams(window.location.search)
    let code = params.get('code')
    if (!code) {
      // if no code, try hash fragment (some providers use it)
      const h = window.location.hash || ''
      const m = h.match(/[?&]code=([^&]+)/)
      if (m) {
        code = m[1]
      }
    }
    if (!code) {
      alert('No code in callback URL')
      window.location.hash = '#/'
      return
    }

    ;(async () => {
      try {
        const r = await api.post('/auth/github', { code })
        const tok = r.data.token
        if (tok) {
          setToken(tok)
          const user = r.data.user
          onSignIn && onSignIn(tok, user)
          window.location.hash = '#/'
        } else {
          alert('Failed to receive token from server')
          window.location.hash = '#/'
        }
      } catch (e) {
        alert('OAuth exchange failed: ' + (e.response?.data?.detail || e.message))
        window.location.hash = '#/'
      }
    })()
  }, [])

  return (
    <div style={{padding:20}}>
      <h3>Signing in...</h3>
    </div>
  )
}
