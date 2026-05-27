import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  DndContext,
  DragEndEvent,
  DragOverlay,
  DragStartEvent,
  PointerSensor,
  useSensor,
  useSensors,
  useDroppable,
} from '@dnd-kit/core'
import {
  SortableContext,
  verticalListSortingStrategy,
  useSortable,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import type { Ticket } from '../../types/sprint'

interface TicketListProps {
  tickets: Ticket[]
  droppedIds: Set<string>
  onDropTicket: (ticketId: string) => void
  onRestoreTicket: (ticketId: string) => void
}

function confidenceDot(confidence: number): string {
  if (confidence > 0.75) return 'var(--color-success)'
  if (confidence >= 0.5) return 'var(--color-warning)'
  return 'var(--color-danger)'
}

function intensityColor(weight: number): { bg: string; fg: string } {
  if (weight >= 0.7) return { bg: 'var(--color-accent)', fg: 'var(--color-bg-primary, #fff)' }
  if (weight >= 0.4) return { bg: 'var(--color-accent-subtle)', fg: 'var(--color-accent)' }
  return { bg: 'var(--color-bg-tertiary)', fg: 'var(--color-text-secondary)' }
}

function SkillPills({ skillVector }: { skillVector?: Record<string, number> }) {
  if (!skillVector) return null
  const entries = Object.entries(skillVector)
    .filter(([, w]) => typeof w === 'number' && w >= 0.2)
    .sort((a, b) => b[1] - a[1])
  if (entries.length === 0) return null
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
      {entries.map(([skill, weight]) => {
        const { bg, fg } = intensityColor(weight)
        const pct = Math.max(0, Math.min(1, weight)) * 100
        return (
          <span
            key={skill}
            title={`${skill}: ${weight.toFixed(2)}`}
            style={{
              position: 'relative',
              display: 'inline-flex',
              alignItems: 'center',
              padding: '1px 6px',
              borderRadius: 9999,
              border: '1px solid var(--color-border)',
              fontFamily: 'var(--font-sans)',
              fontSize: 'var(--text-xs)',
              color: fg,
              background: 'var(--color-bg-secondary)',
              overflow: 'hidden',
              lineHeight: 1.4,
            }}
          >
            <span
              aria-hidden
              style={{
                position: 'absolute',
                left: 0,
                top: 0,
                bottom: 0,
                width: `${pct}%`,
                background: bg,
                opacity: 0.55,
                zIndex: 0,
              }}
            />
            <span style={{ position: 'relative', zIndex: 1, fontWeight: 600 }}>{skill}</span>
          </span>
        )
      })}
    </div>
  )
}

function MatchedIdentifiers({ identifiers }: { identifiers?: string[] }) {
  if (!identifiers || identifiers.length === 0) return null
  return (
    <div style={{ marginTop: 12 }}>
      <div style={{
        color: 'var(--color-text-muted)',
        fontFamily: 'var(--font-sans)',
        fontSize: 'var(--text-xs)',
        fontWeight: 700,
        textTransform: 'uppercase',
        letterSpacing: '0.06em',
        marginBottom: 6,
      }}>
        Matched identifiers
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
        {identifiers.map(token => (
          <Link
            key={token}
            to={`/app/settings/glossary?token=${encodeURIComponent(token)}`}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              padding: '2px 7px',
              borderRadius: 9999,
              background: 'var(--color-accent-subtle)',
              color: 'var(--color-accent)',
              fontFamily: 'var(--font-mono, var(--font-sans))',
              fontSize: 'var(--text-xs)',
              textDecoration: 'none',
              border: '1px solid transparent',
            }}
          >
            {token}
          </Link>
        ))}
      </div>
    </div>
  )
}

interface TicketDetailDrawerProps {
  ticket: Ticket
  onClose: () => void
}

function TicketDetailDrawer({ ticket, onClose }: TicketDetailDrawerProps) {
  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.35)',
        zIndex: 100,
        display: 'flex',
        justifyContent: 'flex-end',
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          width: 420,
          maxWidth: '90vw',
          height: '100%',
          background: 'var(--color-bg-primary)',
          borderLeft: '1px solid var(--color-border)',
          padding: 20,
          overflowY: 'auto',
          boxShadow: '-8px 0 24px rgba(0,0,0,0.18)',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
          <div>
            <div style={{ color: 'var(--color-accent)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-xs)', fontWeight: 700 }}>
              {ticket.ticket_id}
            </div>
            <div style={{ color: 'var(--color-text-primary)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)', marginTop: 4 }}>
              {ticket.title}
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--color-text-muted)',
              cursor: 'pointer',
              fontSize: 18,
              padding: 0,
              lineHeight: 1,
            }}
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <div style={{
          marginTop: 14,
          color: 'var(--color-text-secondary)',
          fontFamily: 'var(--font-sans)',
          fontSize: 'var(--text-xs)',
          display: 'flex',
          gap: 12,
          flexWrap: 'wrap',
        }}>
          <span>Assigned to: <strong>{ticket.developer_name || ticket.developer_id}</strong></span>
          <span>{ticket.story_points} pts</span>
        </div>

        {ticket.skill_vector && Object.keys(ticket.skill_vector).length > 0 && (
          <div style={{ marginTop: 14 }}>
            <div style={{
              color: 'var(--color-text-muted)',
              fontFamily: 'var(--font-sans)',
              fontSize: 'var(--text-xs)',
              fontWeight: 700,
              textTransform: 'uppercase',
              letterSpacing: '0.06em',
              marginBottom: 6,
            }}>
              Required skills
            </div>
            <SkillPills skillVector={ticket.skill_vector} />
          </div>
        )}

        <MatchedIdentifiers identifiers={ticket.matched_identifiers} />
      </div>
    </div>
  )
}

function TicketRow({ ticket, onClick }: { ticket: Ticket; onClick?: (e: React.MouseEvent) => void }) {
  return (
    <div
      onClick={onClick}
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 4,
        padding: '6px 10px',
        background: 'var(--color-bg-elevated)',
        borderRadius: 'var(--radius-sm)',
        marginBottom: 4,
        cursor: 'grab',
        borderLeft: '2px solid var(--color-accent)',
        userSelect: 'none',
        border: '1px solid var(--color-border)',
        borderLeftWidth: 2,
        borderLeftColor: 'var(--color-accent)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ color: 'var(--color-accent)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-xs)', fontWeight: 700, whiteSpace: 'nowrap' }}>
          {ticket.ticket_id}
        </span>
        <span style={{
          color: 'var(--color-text-primary)',
          fontFamily: 'var(--font-sans)',
          fontSize: 'var(--text-xs)',
          flex: 1,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}>
          {ticket.title}
        </span>
        <span style={{ color: 'var(--color-text-secondary)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-xs)', whiteSpace: 'nowrap' }}>
          {ticket.developer_name || ticket.developer_id}
        </span>
        <span style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-xs)', whiteSpace: 'nowrap' }}>
          {ticket.story_points}pts
        </span>
        <span style={{ width: 8, height: 8, borderRadius: '50%', background: confidenceDot(ticket.confidence), flexShrink: 0 }} />
      </div>
      <SkillPills skillVector={ticket.skill_vector} />
    </div>
  )
}

function SortableTicketRow({ ticket, onSelect }: { ticket: Ticket; onSelect: (t: Ticket) => void }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: ticket.ticket_id,
  })
  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.4 : 1 }}
      {...attributes}
      {...listeners}
    >
      <TicketRow
        ticket={ticket}
        onClick={e => {
          // PointerSensor uses an 8px activation distance, so a plain click never
          // starts a drag — safe to treat as a "select" gesture.
          if (isDragging) return
          e.stopPropagation()
          onSelect(ticket)
        }}
      />
    </div>
  )
}

function DroppableZone({
  id, label, children, isEmpty, emptyText,
}: {
  id: string; label: string; children: React.ReactNode; isEmpty: boolean; emptyText: string
}) {
  const { setNodeRef, isOver } = useDroppable({ id })
  return (
    <div
      ref={setNodeRef}
      style={{
        flex: 1,
        background: isOver ? 'var(--color-accent-subtle)' : 'var(--color-bg-secondary)',
        borderRadius: 'var(--radius-md)',
        padding: '10px',
        border: `2px dashed ${isOver ? 'var(--color-accent)' : 'var(--color-border)'}`,
        minHeight: 80,
        transition: 'background 0.15s, border-color 0.15s',
      }}
    >
      <div style={{
        color: 'var(--color-text-muted)',
        fontFamily: 'var(--font-sans)',
        fontSize: 'var(--text-xs)',
        fontWeight: 700,
        textTransform: 'uppercase',
        letterSpacing: '0.06em',
        marginBottom: 8,
      }}>
        {label}
      </div>
      {children}
      {isEmpty && (
        <div style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-xs)' }}>
          {emptyText}
        </div>
      )}
    </div>
  )
}

export function TicketList({ tickets, droppedIds, onDropTicket, onRestoreTicket }: TicketListProps) {
  const [activeId, setActiveId] = useState<string | null>(null)
  const [selectedTicket, setSelectedTicket] = useState<Ticket | null>(null)
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }))

  const inSprint = tickets.filter(t => !droppedIds.has(t.ticket_id))
  const removed = tickets.filter(t => droppedIds.has(t.ticket_id))
  const activeTicket = tickets.find(t => t.ticket_id === activeId)

  function handleDragStart(e: DragStartEvent) {
    setActiveId(String(e.active.id))
  }

  function handleDragEnd(e: DragEndEvent) {
    const { active, over } = e
    setActiveId(null)
    if (!over) return
    const ticketId = String(active.id)
    const overId = String(over.id)
    const overIsRemovedZone = overId === 'removed-zone' || removed.some(t => t.ticket_id === overId)
    const overIsSprintZone = overId === 'sprint-zone' || inSprint.some(t => t.ticket_id === overId)
    if (overIsRemovedZone && !droppedIds.has(ticketId)) {
      onDropTicket(ticketId)
    } else if (overIsSprintZone && droppedIds.has(ticketId)) {
      onRestoreTicket(ticketId)
    }
  }

  return (
    <DndContext sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, height: '100%' }}>
        <DroppableZone id="sprint-zone" label="In Sprint" isEmpty={inSprint.length === 0} emptyText="No tickets in sprint">
          <SortableContext items={inSprint.map(t => t.ticket_id)} strategy={verticalListSortingStrategy}>
            {inSprint.map(t => <SortableTicketRow key={t.ticket_id} ticket={t} onSelect={setSelectedTicket} />)}
          </SortableContext>
        </DroppableZone>

        <DroppableZone id="removed-zone" label="What-If: Removed" isEmpty={removed.length === 0} emptyText="Drag tickets here to model impact">
          <SortableContext items={removed.map(t => t.ticket_id)} strategy={verticalListSortingStrategy}>
            {removed.map(t => <SortableTicketRow key={t.ticket_id} ticket={t} onSelect={setSelectedTicket} />)}
          </SortableContext>
        </DroppableZone>
      </div>

      <DragOverlay>
        {activeTicket && <TicketRow ticket={activeTicket} />}
      </DragOverlay>

      {selectedTicket && (
        <TicketDetailDrawer ticket={selectedTicket} onClose={() => setSelectedTicket(null)} />
      )}
    </DndContext>
  )
}
