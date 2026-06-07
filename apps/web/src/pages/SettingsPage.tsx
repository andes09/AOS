import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useApi, ApiError } from '../lib/api'
import { useAppRole } from '../hooks/useAppRole'
import { Card, CardHeader, CardBody } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Input } from '../components/ui/Input'
import { Select } from '../components/ui/Select'
import { Badge } from '../components/ui/Badge'
import { useFeature } from '../featureFlags'

interface SlackConfig {
  configured: boolean
  channel: string | null
  alertTypes: string[]
  isActive: boolean
}

const ALERT_TYPE_LABELS: Record<string, string> = {
  high_risk_dependency: 'High-risk dependency',
  sprint_at_risk: 'Sprint at risk',
  retro_action_overdue: 'Retro action overdue',
}
const ALL_ALERT_TYPES = ['high_risk_dependency', 'sprint_at_risk', 'retro_action_overdue']

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

export function SettingsPage() {
  const showSlackAlerts = useFeature('slack_alerts')
  const showGlossary = useFeature('skill_based_assignment')
  const [anthropicKey, setAnthropicKey] = useState('')
  const [anthropicConfigured, setAnthropicConfigured] = useState<boolean | null>(null)
  const [anthropicSaving, setAnthropicSaving] = useState(false)
  const [anthropicMessage, setAnthropicMessage] = useState<string | null>(null)
  const [slackConfig, setSlackConfig] = useState<SlackConfig | null>(null)
  const [slackWebhook, setSlackWebhook] = useState('')
  const [slackChannel, setSlackChannel] = useState('')
  const [slackAlertTypes, setSlackAlertTypes] = useState<string[]>(ALL_ALERT_TYPES)
  const [slackSaving, setSlackSaving] = useState(false)
  const [slackMsg, setSlackMsg] = useState<string | null>(null)
  const [slackValidationError, setSlackValidationError] = useState<string | null>(null)
  const [slackTesting, setSlackTesting] = useState(false)
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState('lead')
  const [inviteSending, setInviteSending] = useState(false)
  const [inviteMsg, setInviteMsg] = useState<string | null>(null)
  const [inviteLink, setInviteLink] = useState<string | null>(null)
  const [invitations, setInvitations] = useState<InvitationItem[]>([])
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const { get, del, post, put } = useApi()
  const { appRole } = useAppRole()
  const isLead = appRole === 'lead' || appRole === 'exec' || appRole === 'admin'

  async function fetchAnthropicStatus() {
    try {
      const data = await get<{ configured: boolean }>('/api/settings/anthropic-key/status')
      setAnthropicConfigured(data.configured)
    } catch {
      setAnthropicConfigured(false)
    }
  }

  async function fetchSlackConfig() {
    try {
      const data = await get<SlackConfig>('/api/teams/default/slack')
      setSlackConfig(data)
      if (data.configured) {
        setSlackAlertTypes(data.alertTypes)
        if (data.channel) setSlackChannel(data.channel)
      }
    } catch {
      setSlackConfig({ configured: false, channel: null, alertTypes: [], isActive: false })
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
    fetchAnthropicStatus()
    fetchSlackConfig()
    fetchInvitations()
  }, [])

  async function handleSaveSlack() {
    if (!slackWebhook.trim()) return
    setSlackSaving(true)
    setSlackMsg(null)
    setSlackValidationError(null)
    try {
      await put('/api/teams/default/slack', {
        webhookUrl: slackWebhook.trim(),
        channel: slackChannel.trim() || null,
        alertTypes: slackAlertTypes,
      })
      setSlackMsg('Slack config saved.')
      await fetchSlackConfig()
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setSlackValidationError(err.message)
      } else {
        setSlackMsg(err instanceof Error ? err.message : 'Failed to save Slack config')
      }
    } finally {
      setSlackSaving(false)
    }
  }

  async function handleTestSlack() {
    setSlackTesting(true)
    setSlackMsg(null)
    try {
      await post('/api/teams/default/slack/test', {})
      setSlackMsg('Test message sent')
    } catch {
      setSlackMsg('Failed to send test')
    } finally {
      setSlackTesting(false)
    }
  }

  async function handleDeleteSlack() {
    setSlackSaving(true)
    setSlackMsg(null)
    try {
      await del('/api/teams/default/slack')
      setSlackMsg('Slack config removed.')
      setSlackWebhook('')
      setSlackChannel('')
      setSlackAlertTypes(ALL_ALERT_TYPES)
      await fetchSlackConfig()
    } catch (err) {
      setSlackMsg(err instanceof Error ? err.message : 'Failed to remove Slack config')
    } finally {
      setSlackSaving(false)
    }
  }

  async function handleSaveAnthropicKey() {
    if (!anthropicKey.trim()) return
    setAnthropicSaving(true)
    setAnthropicMessage(null)
    try {
      await post('/api/settings/anthropic-key', { key: anthropicKey.trim() })
      setAnthropicMessage('API key saved.')
      setAnthropicKey('')
      setAnthropicConfigured(true)
    } catch (err) {
      setAnthropicMessage(err instanceof Error ? err.message : 'Failed to save key')
    } finally {
      setAnthropicSaving(false)
    }
  }

  const sectionGap = { marginTop: 16 }

  return (
    <div style={{ maxWidth: 640, margin: '0 auto', fontFamily: 'var(--font-sans)' }}>
      <h1 style={{ color: 'var(--color-text-primary)', fontSize: 'var(--text-xl)', fontWeight: 700, marginBottom: 24, margin: '0 0 24px' }}>
        Settings
      </h1>

      {/* Anthropic API Key */}
      <Card>
        <CardHeader>
          <span style={{ color: 'var(--color-text-primary)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-base)', fontWeight: 600 }}>
            Anthropic API Key
          </span>
          {anthropicConfigured !== null && (
            <Badge variant={anthropicConfigured ? 'success' : 'default'}>
              {anthropicConfigured ? 'Configured' : 'Not configured'}
            </Badge>
          )}
        </CardHeader>
        <CardBody>
          <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)', margin: '0 0 12px' }}>
            Required for Sprint Planning and Retro Prep.
          </p>
          <div style={{ display: 'flex', gap: 8 }}>
            <Input
              type="password"
              placeholder="sk-ant-..."
              value={anthropicKey}
              onChange={e => setAnthropicKey(e.target.value)}
              containerStyle={{ flex: 1 }}
            />
            <Button
              variant="primary"
              size="sm"
              onClick={handleSaveAnthropicKey}
              disabled={anthropicSaving || !anthropicKey.trim()}
            >
              {anthropicSaving ? 'Saving...' : 'Save Key'}
            </Button>
          </div>
          {anthropicMessage && (
            <div style={{
              color: anthropicMessage === 'API key saved.' ? 'var(--color-success)' : 'var(--color-danger)',
              fontSize: 'var(--text-sm)',
              marginTop: 8,
            }}>
              {anthropicMessage}
            </div>
          )}
        </CardBody>
      </Card>

      {/* Invite Team Members */}
      {isLead && (
        <Card style={sectionGap}>
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

      {/* Team Glossary */}
      {isLead && showGlossary && (
        <Card style={sectionGap}>
          <CardHeader>
            <span style={{ color: 'var(--color-text-primary)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-base)', fontWeight: 600 }}>
              Team Glossary
            </span>
          </CardHeader>
          <CardBody>
            <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)', margin: '0 0 12px' }}>
              Identifiers your team has used in past tickets, mapped to skills.
            </p>
            <Link
              to="/app/settings/glossary"
              style={{
                color: 'var(--color-accent)',
                fontFamily: 'var(--font-sans)',
                fontSize: 'var(--text-sm)',
                fontWeight: 500,
                textDecoration: 'none',
              }}
            >
              Manage glossary →
            </Link>
          </CardBody>
        </Card>
      )}

      {/* Calibration Suggestions */}
      {isLead && (
        <Card style={sectionGap}>
          <CardHeader>
            <span style={{ color: 'var(--color-text-primary)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-base)', fontWeight: 600 }}>
              Calibration Suggestions
            </span>
          </CardHeader>
          <CardBody>
            <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)', margin: '0 0 12px' }}>
              Sprint Brain learns from your overrides and proposes skill/identifier recalibrations.
            </p>
            <Link
              to="/app/settings/calibration"
              style={{
                color: 'var(--color-accent)',
                fontFamily: 'var(--font-sans)',
                fontSize: 'var(--text-sm)',
                fontWeight: 500,
                textDecoration: 'none',
              }}
            >
              Review suggestions →
            </Link>
          </CardBody>
        </Card>
      )}

      {/* Slack Alerts */}
      {showSlackAlerts && (
      <Card style={sectionGap}>
        <CardHeader>
          <span style={{ color: 'var(--color-text-primary)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-base)', fontWeight: 600 }}>
            Slack Alerts
          </span>
          {slackConfig !== null && (
            <Badge variant={slackConfig.configured && slackConfig.isActive ? 'success' : 'default'}>
              {slackConfig.configured && slackConfig.isActive ? 'Active' : 'Not configured'}
            </Badge>
          )}
        </CardHeader>
        <CardBody>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <Input
              label="Webhook URL"
              type="text"
              placeholder="https://hooks.slack.com/services/..."
              value={slackWebhook}
              onChange={e => { setSlackWebhook(e.target.value); setSlackValidationError(null) }}
              error={slackValidationError ?? undefined}
            />
            <Input
              label="Channel (optional)"
              type="text"
              placeholder="#engineering-alerts"
              value={slackChannel}
              onChange={e => setSlackChannel(e.target.value)}
            />

            <div>
              <div style={{ color: 'var(--color-text-primary)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)', fontWeight: 500, marginBottom: 6 }}>
                Alert types
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {ALL_ALERT_TYPES.map(type => (
                  <label key={type} style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                    <input
                      type="checkbox"
                      checked={slackAlertTypes.includes(type)}
                      onChange={e => {
                        if (e.target.checked) setSlackAlertTypes(a => [...a, type])
                        else setSlackAlertTypes(a => a.filter(t => t !== type))
                      }}
                    />
                    <span style={{ color: 'var(--color-text-primary)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)' }}>
                      {ALERT_TYPE_LABELS[type]}
                    </span>
                  </label>
                ))}
              </div>
            </div>

            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <Button
                variant="primary"
                size="sm"
                onClick={handleSaveSlack}
                disabled={slackSaving || !slackWebhook.trim()}
              >
                {slackSaving ? 'Saving...' : 'Save'}
              </Button>
              {slackConfig?.configured && (
                <>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={handleTestSlack}
                    disabled={slackTesting}
                  >
                    {slackTesting ? 'Sending...' : 'Test'}
                  </Button>
                  <Button
                    variant="danger"
                    size="sm"
                    onClick={handleDeleteSlack}
                    disabled={slackSaving}
                  >
                    Remove
                  </Button>
                </>
              )}
            </div>
            {slackMsg && (
              <div style={{
                fontSize: 'var(--text-sm)',
                color: slackMsg.includes('saved') || slackMsg.includes('sent') ? 'var(--color-success)' : 'var(--color-danger)',
              }}>
                {slackMsg}
              </div>
            )}
          </div>
        </CardBody>
      </Card>
      )}
    </div>
  )
}
