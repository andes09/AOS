/**
 * Step 5 — repo_select. Searchable, paginated list from `listGithubRepos`
 * (finally wired up here — see useRepoSelect), "Connect this repo" / "Skip
 * for now". If GitHub was never connected/was skipped earlier, this step is
 * already marked done server-side and `currentStep` skips past it — the
 * `repoAvailable` guard below is a defensive fallback for that case.
 */
import { useMemo, useState } from 'react'
import { useRepoSelect } from '../../../features/onboarding-v2'
import { Alert, Btn, C, Spinner } from '../theme'

export function RepoSelectStep({ repoAvailable }: { repoAvailable: boolean }) {
  const { repos, page, setPage, selectRepo, skip } = useRepoSelect()
  const [search, setSearch] = useState('')

  const filtered = useMemo(() => {
    const list = repos.data ?? []
    if (!search.trim()) return list
    const needle = search.trim().toLowerCase()
    return list.filter(r => r.fullName.toLowerCase().includes(needle))
  }, [repos.data, search])

  if (!repoAvailable) return null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 22, animation: 'fadeUp 0.22s ease both' }}>
      <div>
        <h2 style={{ fontSize: 21, fontWeight: 700, color: C.t1, letterSpacing: '-0.3px', marginBottom: 5 }}>Connect a repo</h2>
        <p style={{ fontSize: 14, color: C.t2, lineHeight: 1.55 }}>Pick the repo this project lives in — or skip and connect one later.</p>
      </div>

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
