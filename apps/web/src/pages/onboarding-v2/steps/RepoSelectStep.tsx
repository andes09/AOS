/**
 * Step 5 — repo_select. Searchable, paginated list from `listGithubRepos`
 * ("Connect this repo" / "Skip for now"). If GitHub was never connected/was
 * skipped earlier, this step is already marked done server-side and
 * `currentStep` skips past it — the `repoAvailable` guard below is a defensive
 * fallback for that case.
 *
 * Path-aware: the import path connects the repo the project already lives in;
 * the chat path (greenfield) additionally offers "create a new repo" when the
 * install can create one (`canCreate` — an Organization install with
 * experimental.repo_create on; personal accounts are connect-only, see
 * github_app_repo_create_constraint).
 */
import { useMemo, useState } from 'react'
import { useRepoSelect } from '../../../features/onboarding-v2'
import type { PlanSource } from '../../../features/onboarding-v2'
import { Alert, Btn, C, Spinner } from '../theme'

export function RepoSelectStep({
  repoAvailable,
  onboardingPath,
  canCreate,
  ownerLogin,
}: {
  repoAvailable: boolean
  onboardingPath: PlanSource | null
  canCreate: boolean
  ownerLogin: string | null
}) {
  const { repos, page, setPage, selectRepo, skip, createRepo } = useRepoSelect()
  const [search, setSearch] = useState('')
  const [newName, setNewName] = useState('')
  const [isPrivate, setIsPrivate] = useState(true)

  const showCreate = canCreate && onboardingPath === 'chat'

  const filtered = useMemo(() => {
    const list = repos.data ?? []
    if (!search.trim()) return list
    const needle = search.trim().toLowerCase()
    return list.filter(r => r.fullName.toLowerCase().includes(needle))
  }, [repos.data, search])

  if (!repoAvailable) return null

  const subtitle = onboardingPath === 'import'
    ? 'Connect the repo this project lives in — or skip and connect one later.'
    : showCreate
      ? 'Create a repo for this project, or connect one you already made — or skip.'
      : 'Pick the repo this project lives in — or skip and connect one later.'

  const nameValid = /^[A-Za-z0-9._-]+$/.test(newName.trim())

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 22, animation: 'fadeUp 0.22s ease both' }}>
      <div>
        <h2 style={{ fontSize: 21, fontWeight: 700, color: C.t1, letterSpacing: '-0.3px', marginBottom: 5 }}>Connect a repo</h2>
        <p style={{ fontSize: 14, color: C.t2, lineHeight: 1.55 }}>{subtitle}</p>
      </div>

      {showCreate && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: '16px', borderRadius: 10, border: `1.5px solid ${C.border}`, background: C.bg0 }}>
          <div style={{ fontSize: 13.5, fontWeight: 700, color: C.t1 }}>Create a new repo</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {ownerLogin && <span style={{ fontSize: 13, color: C.t3, whiteSpace: 'nowrap' }}>{ownerLogin} /</span>}
            <input
              value={newName}
              onChange={e => setNewName(e.target.value)}
              placeholder="my-project"
              style={{
                flex: 1, minWidth: 0, fontSize: 13.5, color: C.t1, padding: '9px 12px',
                borderRadius: 8, border: `1.5px solid ${C.border}`, fontFamily: 'inherit',
              }}
            />
          </div>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5, color: C.t2, cursor: 'pointer' }}>
            <input type="checkbox" checked={isPrivate} onChange={e => setIsPrivate(e.target.checked)} />
            Private repository
          </label>
          {createRepo.isError && <Alert>{(createRepo.error as Error)?.message ?? 'Creating that repo failed.'}</Alert>}
          <Btn
            size="sm"
            onClick={() => createRepo.mutate({ name: newName.trim(), isPrivate })}
            disabled={!nameValid || createRepo.isPending}
            style={{ alignSelf: 'flex-start' }}
          >
            {createRepo.isPending ? <><Spinner size={13} color="rgba(255,255,255,0.85)" /> Creating…</> : 'Create & connect'}
          </Btn>
        </div>
      )}

      {showCreate && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: C.t3, fontSize: 12 }}>
          <div style={{ flex: 1, height: 1, background: C.border }} />
          or connect an existing repo
          <div style={{ flex: 1, height: 1, background: C.border }} />
        </div>
      )}

      <input
        value={search}
        onChange={e => setSearch(e.target.value)}
        placeholder="Search repos…"
        style={{
          width: '100%', fontSize: 13.5, color: C.t1, padding: '9px 12px',
          borderRadius: 8, border: `1.5px solid ${C.border}`, fontFamily: 'inherit',
        }}
      />

      {repos.isLoading && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: C.t3, fontSize: 13 }}>
          <Spinner size={14} /> Loading repos…
        </div>
      )}

      {repos.isError && <Alert>Couldn't load your repos. Try again, or skip for now.</Alert>}

      {!repos.isLoading && !repos.isError && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 320, overflowY: 'auto' }}>
          {filtered.length === 0 && (
            <div style={{ fontSize: 13, color: C.t3, padding: '10px 0' }}>No repos match "{search}".</div>
          )}
          {filtered.map(repo => (
            <div
              key={repo.id}
              style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
                padding: '10px 14px', borderRadius: 8, border: `1px solid ${C.border}`, background: C.bg0,
              }}
            >
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 13.5, fontWeight: 600, color: C.t1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{repo.fullName}</div>
                <div style={{ fontSize: 11.5, color: C.t3 }}>{repo.private ? 'Private' : 'Public'}</div>
              </div>
              <Btn
                size="sm"
                variant="outline"
                onClick={() => selectRepo.mutate(repo.fullName)}
                disabled={selectRepo.isPending}
              >
                Connect this repo
              </Btn>
            </div>
          ))}
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        {page > 1 && (
          <Btn variant="ghost" size="sm" onClick={() => setPage(p => Math.max(1, p - 1))}>Previous</Btn>
        )}
        {(repos.data?.length ?? 0) >= 30 && (
          <Btn variant="ghost" size="sm" onClick={() => setPage(p => p + 1)}>More repos</Btn>
        )}
      </div>

      {selectRepo.isError && <Alert>{(selectRepo.error as Error)?.message ?? 'Connecting that repo failed.'}</Alert>}

      <Btn variant="ghost" onClick={() => skip.mutate()} disabled={skip.isPending} style={{ alignSelf: 'flex-start' }}>
        {skip.isPending ? 'Skipping…' : 'Skip for now'}
      </Btn>
    </div>
  )
}
