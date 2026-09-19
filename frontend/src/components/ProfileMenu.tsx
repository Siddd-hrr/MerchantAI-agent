import { useEffect, useId, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { clearAuthSession, getStoredProfile } from '../lib/authSession'

function avatarInitial(): string {
  const profile = getStoredProfile()
  const source = profile?.display_name?.trim() || profile?.email?.trim() || 'M'
  return source.charAt(0).toUpperCase()
}

export function ProfileMenu() {
  const navigate = useNavigate()
  const menuId = useId()
  const rootRef = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const [initial, setInitial] = useState(avatarInitial)

  useEffect(() => {
    setInitial(avatarInitial())
  }, [])

  useEffect(() => {
    if (!open) return

    function onPointerDown(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false)
      }
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false)
    }

    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  function onLogout() {
    setOpen(false)
    clearAuthSession()
    navigate('/', { replace: true })
  }

  return (
    <div className="profile-menu" ref={rootRef}>
      <button
        type="button"
        className="profile-menu-trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={menuId}
        aria-label="Account menu"
        onClick={() => setOpen((value) => !value)}
      >
        <span className="profile-menu-avatar" aria-hidden="true">
          {initial}
        </span>
      </button>

      {open ? (
        <div className="profile-menu-dropdown" id={menuId} role="menu">
          <Link
            to="/home/profile"
            role="menuitem"
            className="profile-menu-item"
            onClick={() => setOpen(false)}
          >
            Profile
          </Link>
          <button type="button" role="menuitem" className="profile-menu-item" onClick={onLogout}>
            Logout
          </button>
        </div>
      ) : null}
    </div>
  )
}
