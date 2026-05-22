import { useState, useRef, useEffect, KeyboardEvent } from 'react'

interface MultiSelectProps {
  label?: string
  note?: string
  placeholder?: string
  options: string[]
  selected: string[]
  onChange: (v: string[]) => void
  max?: number
  allowCustom?: boolean
}

export function MultiSelect({
  label,
  note,
  placeholder = 'Search…',
  options,
  selected,
  onChange,
  max,
  allowCustom,
}: MultiSelectProps) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const containerRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    function handleMouseDown(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
        setQuery('')
      }
    }
    document.addEventListener('mousedown', handleMouseDown)
    return () => document.removeEventListener('mousedown', handleMouseDown)
  }, [])

  const filtered = options.filter(
    o => o.toLowerCase().includes(query.toLowerCase()) && !selected.includes(o),
  )
  const showCustom =
    allowCustom &&
    query.trim().length > 0 &&
    !options.some(o => o.toLowerCase() === query.trim().toLowerCase()) &&
    !selected.some(s => s.toLowerCase() === query.trim().toLowerCase())

  function toggle(opt: string) {
    if (selected.includes(opt)) {
      onChange(selected.filter(s => s !== opt))
    } else {
      if (max && selected.length >= max) return
      onChange([...selected, opt])
    }
    setQuery('')
    inputRef.current?.focus()
  }

  function addCustom() {
    const val = query.trim()
    if (!val) return
    if (max && selected.length >= max) return
    onChange([...selected, val])
    setQuery('')
    inputRef.current?.focus()
  }

  function removeAt(i: number) {
    onChange(selected.filter((_, idx) => idx !== i))
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Backspace' && query === '' && selected.length > 0) {
      onChange(selected.slice(0, -1))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (showCustom) {
        addCustom()
      } else if (filtered.length > 0) {
        toggle(filtered[0])
      }
    } else if (e.key === 'Escape') {
      setOpen(false)
      setQuery('')
    }
  }

  const atMax = max !== undefined && selected.length >= max

  return (
    <div ref={containerRef} style={{ position: 'relative', width: '100%' }}>
      {label && (
        <div style={{ marginBottom: 6, display: 'flex', alignItems: 'baseline', gap: 4 }}>
          <span style={{
            fontSize: 'var(--text-sm)',
            fontWeight: 600,
            color: 'var(--color-text-primary)',
            fontFamily: 'var(--font-sans)',
          }}>{label}</span>
          {note && (
            <span style={{
              fontSize: 'var(--text-xs)',
              color: 'var(--color-text-muted)',
              fontFamily: 'var(--font-sans)',
            }}>{note}</span>
          )}
        </div>
      )}

      {/* Trigger */}
      <div
        onClick={() => { setOpen(true); setTimeout(() => inputRef.current?.focus(), 0) }}
        style={{
          minHeight: 38,
          border: `1px solid ${open ? 'var(--color-accent)' : 'var(--color-border)'}`,
          borderRadius: 'var(--radius-md)',
          background: 'var(--color-bg-primary)',
          padding: '4px 8px',
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          gap: 4,
          cursor: 'text',
          boxShadow: open ? '0 0 0 2px rgba(12,102,228,0.12)' : 'none',
          transition: 'border-color 0.15s, box-shadow 0.15s',
        }}
      >
        {selected.map((s, i) => (
          <span
            key={s}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 3,
              background: 'var(--color-bg-secondary)',
              border: '1px solid var(--color-border)',
              borderRadius: 'var(--radius-sm)',
              padding: '1px 6px',
              fontSize: 'var(--text-xs)',
              color: 'var(--color-text-primary)',
              fontFamily: 'var(--font-sans)',
              lineHeight: '20px',
            }}
          >
            {s}
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); removeAt(i) }}
              style={{
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                padding: 0,
                lineHeight: 1,
                color: 'var(--color-text-muted)',
                fontSize: 12,
                display: 'flex',
                alignItems: 'center',
              }}
            >×</button>
          </span>
        ))}
        <input
          ref={inputRef}
          value={query}
          onChange={e => { setQuery(e.target.value); setOpen(true) }}
          onKeyDown={handleKeyDown}
          onFocus={() => setOpen(true)}
          placeholder={selected.length === 0 ? placeholder : ''}
          disabled={atMax}
          style={{
            border: 'none',
            outline: 'none',
            background: 'transparent',
            fontSize: 'var(--text-sm)',
            color: 'var(--color-text-primary)',
            fontFamily: 'var(--font-sans)',
            flex: 1,
            minWidth: 80,
            padding: '2px 0',
          }}
        />
        {max !== undefined && (
          <span style={{
            fontSize: 'var(--text-xs)',
            color: atMax ? 'var(--color-accent)' : 'var(--color-text-muted)',
            fontFamily: 'var(--font-sans)',
            marginLeft: 'auto',
            flexShrink: 0,
            paddingLeft: 4,
          }}>
            {selected.length}/{max}
          </span>
        )}
      </div>

      {/* Dropdown */}
      {open && (filtered.length > 0 || showCustom || (query === '' && options.length > 0)) && (
        <div style={{
          position: 'absolute',
          top: 'calc(100% + 4px)',
          left: 0,
          right: 0,
          background: '#ffffff',
          border: '1px solid var(--color-border)',
          borderRadius: 'var(--radius-md)',
          boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
          zIndex: 200,
          maxHeight: 220,
          overflowY: 'auto',
        }}>
          {(query === '' ? options.filter(o => !selected.includes(o)) : filtered).map(opt => {
            const isSelected = selected.includes(opt)
            const disabled = atMax && !isSelected
            return (
              <div
                key={opt}
                onClick={() => { if (!disabled) toggle(opt) }}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  padding: '7px 10px',
                  cursor: disabled ? 'not-allowed' : 'pointer',
                  background: 'transparent',
                  opacity: disabled ? 0.45 : 1,
                  transition: 'background 0.1s',
                }}
                onMouseEnter={e => { if (!disabled) (e.currentTarget as HTMLElement).style.background = 'var(--color-bg-secondary)' }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'transparent' }}
              >
                <span style={{
                  width: 14,
                  height: 14,
                  border: `1.5px solid ${isSelected ? 'var(--color-accent)' : 'var(--color-border)'}`,
                  borderRadius: 3,
                  background: isSelected ? 'var(--color-accent)' : 'transparent',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                }}>
                  {isSelected && (
                    <svg width="8" height="6" viewBox="0 0 8 6" fill="none">
                      <path d="M1 3L3 5L7 1" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  )}
                </span>
                <span style={{
                  fontSize: 'var(--text-sm)',
                  color: 'var(--color-text-primary)',
                  fontFamily: 'var(--font-sans)',
                }}>{opt}</span>
              </div>
            )
          })}

          {showCustom && (
            <div
              onClick={addCustom}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '7px 10px',
                cursor: atMax ? 'not-allowed' : 'pointer',
                opacity: atMax ? 0.45 : 1,
                borderTop: filtered.length > 0 ? '1px solid var(--color-border)' : 'none',
              }}
              onMouseEnter={e => { if (!atMax) (e.currentTarget as HTMLElement).style.background = 'var(--color-bg-secondary)' }}
              onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'transparent' }}
            >
              <span style={{
                fontSize: 'var(--text-sm)',
                color: 'var(--color-accent)',
                fontFamily: 'var(--font-sans)',
              }}>
                + Add custom: &ldquo;{query.trim()}&rdquo;
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
