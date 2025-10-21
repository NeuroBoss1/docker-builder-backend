import React, { useEffect } from 'react'
import api, { setToken } from '../api'

export default function GoogleOAuthCallback({ onSignIn }) {
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const code = params.get('code')
    if (!code) {
      alert('No code in callback URL')
      window.location.hash = '#/'
      return
    }

    ;(async () => {
      try {
        const redirect = window.location.origin + '/#/oauth_google_callback'
        const r = await api.post('/auth/google_exchange', { code, redirect_uri: redirect })
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
        alert('Google OAuth exchange failed: ' + (e.response?.data?.detail || e.message))
        window.location.hash = '#/'
      }
    })()
  }, [])

  return (
    <div style={{padding:20}}>
      <h3>Signing in with Google...</h3>
    </div>
  )
}

