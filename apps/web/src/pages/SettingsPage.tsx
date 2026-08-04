import { useState, useEffect } from 'react'
import { useClerk } from '@clerk/clerk-react'
import { useApi } from '../lib/api'
import { useAppRole } from '../hooks/useAppRole'
import { Card, CardHeader, CardBody } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Input } from '../components/ui/Input'
import { Select } from '../components/ui/Select'
import { Badge } from '../components/ui/Badge'

interface InviteResponse {
  id: string
  email: string
  role: string
  inviteLink: string
  expiresAt: string
  status: string
}

interface InvitationItem {
  id: string
  email: string
  role: string
  status: string
  inviteLink: string
  expiresAt: string
  createdAt: string
}

export function SettingsPage({ onClose }: { onClose?: () => void } = {}) {
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState('lead')
  const [inviteSending, setInviteSending] = useState(false)
  const [inviteMsg, setInviteMsg] = useState<string | null>(null)
  const [inviteLink, setInviteLink] = useState<string | null>(null)
  const [invitations, setInvitations] = useState<InvitationItem[]>([])
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const { get, del, post } = useApi()
  const { appRole } = useAppRole()
  const isLead = appRole === 'lead' || appRole === 'exec' || appRole === 'admin'
  const { signOut } = useClerk()
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  async function handleDeleteAccount() {
    setDeleting(true)
    setDeleteError(null)
    try {
      await del('/api/users/me')
      await signOut({ redirectUrl: '/' })
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : 'Failed to delete account')
      setDeleting(false)
    }
  }

  async function fetchInvitations() {
    try {
      const data = await get<{ invitations: InvitationItem[] }>('/api/invitations')
      setInvitations(data.invitations)
    } catch {
      // non-fatal
    }
  }

  async function handleSendInvite() {
    if (!inviteEmail.trim()) return
    setInviteSending(true)
    setInviteMsg(null)
    setInviteLink(null)
    try {
      const data = await post<InviteResponse>('/api/invitations', { email: inviteEmail.trim(), role: inviteRole })
      setInviteLink(data.inviteLink)
      setInviteEmail('')
      setInviteMsg(null)
      await fetchInvitations()
    } catch (err) {
      setInviteMsg(err instanceof Error ? err.message : 'Failed to create invitation')
    } finally {
      setInviteSending(false)
    }
  }

  async function handleRevokeInvite(id: string) {
    try {
      await del(`/api/invitations/${id}`)
      setInvitations(prev => prev.filter(i => i.id !== id))
    } catch {
      // ignore
    }
  }

  function handleCopyLink(link: string, id: string) {
    navigator.clipboard.writeText(link).then(() => {
      setCopiedId(id)
      setTimeout(() => setCopiedId(null), 2000)
    })
  }

  useEffect(() => {
    if (isLead) {
      fetchInvitations()
    }
  }, [isLead])

  const sectionGap = { marginTop: 16 }

  return (
    <div style={{ maxWidth: 640, margin: '0 auto', fontFamily: 'var(--font-sans)' }}>
      {/* In the modal the dialog header already says "Settings"; only show this
          heading when rendered as a standalone page. */}
      {!onClose && (
        <h1 style={{ color: 'var(--color-text-primary)', fontSize: 'var(--text-xl)', fontWeight: 700, margin: '0 0 24px' }}>
          Settings
        </h1>
      )}

      {/* Invite Team Members */}
      {isLead && (
        <Card>
          <CardHeader>
            <span style={{ color: 'var(--color-text-primary)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-base)', fontWeight: 600 }}>
              Invite Team Members
            </span>
          </CardHeader>
          <CardBody>
            <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)', margin: '0 0 16px' }}>
              Send a signup link to a teammate. They'll be added to your Omada team when they accept.
            </p>

            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8, alignItems: 'flex-end' }}>
              <Input
                type="email"
                placeholder="teammate@company.com"
                value={inviteEmail}
                onChange={e => setInviteEmail(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleSendInvite()}
                containerStyle={{ flex: 1, minWidth: 200 }}
              />
              <Select
                value={inviteRole}
                onChange={e => setInviteRole(e.target.value)}
                containerStyle={{ width: 100 }}
              >
                <option value="lead">Lead</option>
                <option value="exec">Exec</option>
              </Select>
              <Button
                variant="primary"
                size="sm"
                onClick={handleSendInvite}
                disabled={inviteSending || !inviteEmail.trim()}
              >
                {inviteSending ? 'Generating…' : 'Generate Link'}
              </Button>
            </div>

            {inviteMsg && (
              <div style={{ color: 'var(--color-danger)', fontSize: 'var(--text-sm)', marginBottom: 8 }}>{inviteMsg}</div>
            )}

            {inviteLink && (
              <div style={{
                background: 'var(--color-bg-secondary)',
                border: '1px solid var(--color-border)',
                borderRadius: 'var(--radius-md)',
                padding: '8px 12px',
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                marginBottom: 12,
              }}>
                <span style={{ color: 'var(--color-accent)', fontSize: 'var(--text-xs)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {inviteLink}
                </span>
                <Button size="sm" variant="ghost" onClick={() => handleCopyLink(inviteLink, 'new')}>
                  {copiedId === 'new' ? 'Copied!' : 'Copy'}
                </Button>
              </div>
            )}

            {invitations.length > 0 && (
              <div style={{ borderTop: '1px solid var(--color-border)', paddingTop: 12, marginTop: 4 }}>
                <div style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-xs)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>
                  Pending Invites
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {invitations.filter(i => i.status === 'pending').map(inv => (
                    <div key={inv.id} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ color: 'var(--color-text-primary)', fontSize: 'var(--text-sm)', flex: 1 }}>{inv.email}</span>
                      <Badge variant="default">{inv.role}</Badge>
                      <Button size="sm" variant="ghost" onClick={() => handleCopyLink(inv.inviteLink, inv.id)}>
                        {copiedId === inv.id ? 'Copied!' : 'Copy'}
                      </Button>
                      <Button size="sm" variant="danger" onClick={() => handleRevokeInvite(inv.id)}>
                        Revoke
                      </Button>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </CardBody>
        </Card>
      )}

      {/* Delete Account */}
      <Card style={{ ...(isLead ? sectionGap : {}), borderColor: 'var(--color-danger)' }}>
        <CardHeader>
          <span style={{ color: 'var(--color-danger)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-base)', fontWeight: 600 }}>
            Delete Account
          </span>
        </CardHeader>
        <CardBody>
          <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)', margin: '0 0 12px' }}>
            Permanently delete your account and all associated data. This cannot be undone.
          </p>
          {!deleteOpen ? (
            <Button
              variant="danger"
              size="sm"
              onClick={() => { setDeleteOpen(true); setDeleteConfirm(''); setDeleteError(null) }}
            >
              Delete Account
            </Button>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <p style={{ color: 'var(--color-text-primary)', fontSize: 'var(--text-sm)', margin: 0 }}>
                Type <strong>DELETE</strong> to confirm.
              </p>
              <Input
                type="text"
                placeholder="DELETE"
                value={deleteConfirm}
                onChange={e => setDeleteConfirm(e.target.value)}
                disabled={deleting}
              />
              <div style={{ display: 'flex', gap: 8 }}>
                <Button
                  variant="danger"
                  size="sm"
                  onClick={handleDeleteAccount}
                  disabled={deleting || deleteConfirm !== 'DELETE'}
                >
                  {deleting ? 'Deleting…' : 'Permanently Delete'}
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => { setDeleteOpen(false); setDeleteConfirm(''); setDeleteError(null) }}
                  disabled={deleting}
                >
                  Cancel
                </Button>
              </div>
              {deleteError && (
                <div style={{ color: 'var(--color-danger)', fontSize: 'var(--text-sm)' }}>
                  {deleteError}
                </div>
              )}
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  )
}
