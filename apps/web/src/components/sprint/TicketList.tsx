import { useState } from 'react'
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

function TicketRow({ ticket }: { ticket: Ticket }) {
  const dotColour = ticket.confidence > 0.75 ? '#4ade80' : ticket.confidence >= 0.5 ? '#fbbf24' : '#ef4444'
  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      padding: '0.5rem 0.625rem',
      background: '#1e2030',
      borderRadius: 4,
      marginBottom: 4,
      cursor: 'grab',
      borderLeft: '2px solid #6366f1',
      userSelect: 'none',
    }}>
      <span style={{ color: '#6366f1', fontSize: 11, fontWeight: 700, whiteSpace: 'nowrap' }}>
        {ticket.ticket_id}
      </span>
      <span style={{
        color: '#e2e8f0',
        fontSize: 12,
        flex: 1,
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
      }}>
        {ticket.title}
      </span>
      <span style={{ color: '#94a3b8', fontSize: 11, whiteSpace: 'nowrap' }}>{ticket.developer_name || ticket.developer_id}</span>
      <span style={{ color: '#64748b', fontSize: 11, whiteSpace: 'nowrap' }}>{ticket.story_points}pts</span>
      <span style={{ width: 8, height: 8, borderRadius: '50%', background: dotColour, flexShrink: 0 }} />
    </div>
  )
}

function SortableTicketRow({ ticket }: { ticket: Ticket }) {
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
      <TicketRow ticket={ticket} />
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
        background: isOver ? '#2d2f45' : '#0f1117',
        borderRadius: 6,
        padding: '0.75rem',
        border: `2px dashed ${isOver ? '#6366f1' : '#2d2f45'}`,
        minHeight: 80,
        transition: 'background 0.15s, border-color 0.15s',
      }}
    >
      <div style={{
        color: '#a5b4fc', fontSize: 11, fontWeight: 700,
        textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8,
      }}>
        {label}
      </div>
      {children}
      {isEmpty && <div style={{ color: '#374151', fontSize: 12 }}>{emptyText}</div>}
    </div>
  )
}

export function TicketList({ tickets, droppedIds, onDropTicket, onRestoreTicket }: TicketListProps) {
  const [activeId, setActiveId] = useState<string | null>(null)
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
    // over.id may be the zone id OR a ticket id inside the zone
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
            {inSprint.map(t => <SortableTicketRow key={t.ticket_id} ticket={t} />)}
          </SortableContext>
        </DroppableZone>

        <DroppableZone id="removed-zone" label="What-If: Removed" isEmpty={removed.length === 0} emptyText="Drag tickets here to model impact">
          <SortableContext items={removed.map(t => t.ticket_id)} strategy={verticalListSortingStrategy}>
            {removed.map(t => <SortableTicketRow key={t.ticket_id} ticket={t} />)}
          </SortableContext>
        </DroppableZone>
      </div>

      <DragOverlay>
        {activeTicket && <TicketRow ticket={activeTicket} />}
      </DragOverlay>
    </DndContext>
  )
}
