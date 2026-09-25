import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import ErrorBoundary from './components/common/ErrorBoundary'
// styles/tailwind.css existed in the repo but was never imported anywhere, so
// neither Tailwind's layers nor anything else in that file had any effect --
// every page styled itself with an inline <style> block instead. It now
// carries the app's base theme tokens, focus-visible rings, reduced-motion
// handling and the responsive breakpoints, all of which need it to load.
import './styles/tailwind.css'
import { initPrefs } from './lib/prefs'

// Theme and motion are written onto <html> before React renders, so the first
// frame is already in the reader's chosen theme rather than flashing the
// default and correcting itself.
initPrefs()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>,
)