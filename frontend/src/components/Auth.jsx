import React from 'react'
import { setToken } from '../api'

export default function Auth({ onSignIn, user }) {
  const signOut = () => {
    setToken(null)
    onSignIn && onSignIn(null, null)
  }

  const githubSignIn = () => {
    const clientId = import.meta.env.VITE_GITHUB_CLIENT_ID
    const redirect = encodeURIComponent(window.location.origin + '/oauth_callback')
    if (!clientId) {
      alert('GitHub OAuth not configured in frontend env (VITE_GITHUB_CLIENT_ID)')
      return
    }
    const url = `https://github.com/login/oauth/authorize?client_id=${clientId}&redirect_uri=${redirect}&scope=user:email`
    window.location.href = url
  }

  const googleSignIn = () => {
    const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID
    if (!clientId) {
      alert('Google OAuth not configured in frontend env (VITE_GOOGLE_CLIENT_ID)')
      return
    }
    const redirect = encodeURIComponent(window.location.origin + '/oauth_google_callback')
    // Request only basic OpenID scopes for initial sign-in to avoid verification requirements.
    const scope = encodeURIComponent('openid email profile')
    const url = `https://accounts.google.com/o/oauth2/v2/auth?client_id=${clientId}&redirect_uri=${redirect}&response_type=code&scope=${scope}&access_type=offline&prompt=consent`
    window.location.href = url
  }

  if (user) {
    return (
      <div className="auth">
        <div>Signed in: <strong>{user.email}</strong></div>
        <button onClick={signOut}>Sign out</button>
        <button onClick={() => window.location.hash = '#/profile'} style={{marginLeft:8}}>Profile</button>
      </div>
    )
  }

  return (
    <div className="auth">
      <div>
        <button onClick={googleSignIn}>Sign in with Google</button>
        <button onClick={githubSignIn} style={{marginLeft:8}}>Sign in with GitHub</button>
      </div>
    </div>
  )
}
