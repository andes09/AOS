import { CSSProperties, ReactNode, useState } from 'react'
import { ChevronUp, ChevronDown, ChevronsUpDown } from 'lucide-react'

export interface TableColumn<T> {
  key: string
  header: ReactNode
  render: (row: T, index: number) => ReactNode
  sortable?: boolean
  width?: number | string
  align?: 'left' | 'center' | 'right'
}

interface TableProps<T> {
  columns: TableColumn<T>[]
  data: T[]
  rowKey: (row: T, index: number) => string | number
  stickyHeader?: boolean
  maxHeight?: number | string
  emptyState?: ReactNode
  style?: CSSProperties
}

type SortDir = 'asc' | 'desc' | null

export function Table<T>({
  columns,
  data,
  rowKey,
  stickyHeader = true,
  maxHeight,
  emptyState,
  style,
}: TableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<SortDir>(null)

  const handleSort = (key: string) => {
    if (sortKey !== key) {
      setSortKey(key)
      setSortDir('asc')
    } else if (sortDir === 'asc') {
      setSortDir('desc')
    } else if (sortDir === 'desc') {
      setSortKey(null)
      setSortDir(null)
    }
  }

  const thBase: CSSProperties = {
    fontFamily: 'var(--font-sans)',
    fontSize: 'var(--text-xs)',
    fontWeight: 'var(--font-weight-semibold)' as CSSProperties['fontWeight'],
    color: 'var(--color-text-secondary)',
    textTransform: 'uppercase',
    letterSpacing: '0.04em',
    padding: '6px 12px',
    background: 'var(--color-bg-secondary)',
    borderBottom: '1px solid var(--color-border)',
    whiteSpace: 'nowrap',
    userSelect: 'none',
  }

  const tdBase: CSSProperties = {
    fontFamily: 'var(--font-sans)',
    fontSize: 'var(--text-sm)',
    color: 'var(--color-text-primary)',
    padding: '7px 12px',
    borderBottom: '1px solid var(--color-border-subtle)',
    verticalAlign: 'middle',
  }

  return (
    <div
      style={{
        border: '1px solid var(--color-border)',
        borderRadius: 'var(--radius-lg)',
        overflow: 'hidden',
        background: 'var(--color-bg-elevated)',
        boxShadow: 'var(--shadow-sm)',
        ...style,
      }}
    >
      <div style={{ overflowX: 'auto', overflowY: maxHeight ? 'auto' : 'visible', maxHeight }}>
        <table
          style={{
            width: '100%',
            borderCollapse: 'collapse',
            tableLayout: 'auto',
          }}
        >
          <thead
            style={
              stickyHeader
                ? { position: 'sticky', top: 0, zIndex: 1 }
                : undefined
            }
          >
            <tr>
              {columns.map(col => (
                <th
                  key={col.key}
                  style={{
                    ...thBase,
                    textAlign: col.align ?? 'left',
                    width: col.width,
                    cursor: col.sortable ? 'pointer' : 'default',
                  }}
                  onClick={col.sortable ? () => handleSort(col.key) : undefined}
                >
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                    {col.header}
                    {col.sortable && (
                      <span style={{ color: 'var(--color-text-muted)', display: 'inline-flex' }}>
                        {sortKey === col.key && sortDir === 'asc' ? (
                          <ChevronUp size={12} />
                        ) : sortKey === col.key && sortDir === 'desc' ? (
                          <ChevronDown size={12} />
                        ) : (
                          <ChevronsUpDown size={12} />
                        )}
                      </span>
                    )}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.length === 0 ? (
              <tr>
                <td colSpan={columns.length} style={{ ...tdBase, textAlign: 'center', padding: '32px 12px' }}>
                  {emptyState ?? (
                    <span style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)' }}>
                      No data
                    </span>
                  )}
                </td>
              </tr>
            ) : (
              data.map((row, i) => (
                <tr
                  key={rowKey(row, i)}
                  style={{ transition: 'background 0.1s' }}
                  onMouseEnter={e => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
                  onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                >
                  {columns.map(col => (
                    <td
                      key={col.key}
                      style={{ ...tdBase, textAlign: col.align ?? 'left' }}
                    >
                      {col.render(row, i)}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
