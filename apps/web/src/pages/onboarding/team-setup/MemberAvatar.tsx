interface MemberAvatarProps {
  name: string
  size?: number
}

function getInitials(name: string): string {
  return name
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map(w => w[0].toUpperCase())
    .join('')
}

function getHue(name: string): number {
  let sum = 0
  for (let i = 0; i < name.length; i++) {
    sum += name.charCodeAt(i)
  }
  return sum % 360
}

export function MemberAvatar({ name, size = 36 }: MemberAvatarProps) {
  const initials = getInitials(name) || '?'
  const hue = getHue(name)

  return (
    <div
      style={{
        width: size,
        height: size,
        borderRadius: '50%',
        background: `oklch(0.94 0.02 ${hue})`,
        border: `1.5px solid oklch(0.86 0.04 ${hue})`,
        color: `oklch(0.38 0.08 ${hue})`,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontFamily: 'var(--font-sans)',
        fontWeight: 700,
        fontSize: size * 0.38,
        flexShrink: 0,
        userSelect: 'none',
      }}
    >
      {initials}
    </div>
  )
}
