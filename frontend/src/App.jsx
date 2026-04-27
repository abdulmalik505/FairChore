import { useState, useEffect, useRef, useCallback } from 'react';
import './App.css';

// ─── CONSTANTS ────────────────────────────────────────────────────────────────

const MEMBER_COLORS = ['#1CB59E', '#FF6B6B', '#845EC2', '#F9A825', '#2196F3', '#FF9500'];

const ALGORITHMS = [
  { key: 'round-robin',           label: 'Round-Robin',       desc: 'Whoever has done the least work picks first and takes the chore they mind least. Repeats until all chores are claimed. Simple and fair — no one ends up envying anyone else by more than a single chore.' },
  { key: 'top-trading',           label: 'Top-Trading Cycle', desc: 'Starts with a rough split, then swaps chores between people who would prefer each other\'s pile. Keeps trading until no swap helps. Same fairness guarantee as Round-Robin but often produces happier outcomes when preferences differ a lot.' },
  { key: 'bag-filling-practical', label: 'Bag-Filling',       desc: 'Bundles the chores into roughly equal-weight piles, then hands the heaviest pile to whoever has done the least so far. Best when you care most about keeping everyone\'s total workload similar.' },
];

const RATING_LEVELS = [
  { val: 1, emoji: '🙂', label: 'Fine with it'      },
  { val: 2, emoji: '😐', label: 'Neutral'            },
  { val: 3, emoji: '😕', label: "Don't like it"      },
  { val: 4, emoji: '😤', label: 'Strongly dislike'   },
];


// ─── AUTH / STORAGE HELPERS ──────────────────────────────────────────────────

function getAuth() {
  try { return JSON.parse(localStorage.getItem('fairchore_auth') || 'null'); }
  catch { return null; }
}
function saveAuth(data) { localStorage.setItem('fairchore_auth', JSON.stringify(data)); }
function clearAuth()    { localStorage.removeItem('fairchore_auth'); }

// Done-state is now stored in the database (assignment_history.completed_at).
// Toggle via POST/DELETE /api/assignments/<id>/complete.
// No localStorage for done-state — removed.

// Helper: find a user's entry in a history round
function myEntryFromRound(round, uid) {
  return round?.assignments?.find(a => a.member_id === uid) || null;
}

// Helper: check if a chore (by assignment_id) is done
function isDoneChore(chore) { return !!chore.completed_at; }

// ─── API ─────────────────────────────────────────────────────────────────────

async function apiFetch(path, opts = {}, onUnauth) {
  const auth = getAuth();
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  if (auth?.token) headers['Authorization'] = `Bearer ${auth.token}`;
  const res = await fetch(path, { ...opts, headers });
  if (res.status === 401) { clearAuth(); if (onUnauth) onUnauth(); throw new Error('Unauthorized'); }
  return res;
}

// ─── UTILS ───────────────────────────────────────────────────────────────────

function getInitial(n)       { return (n || '?').charAt(0).toUpperCase(); }
function getMemberColor(i)   { return MEMBER_COLORS[i % MEMBER_COLORS.length]; }
function getGreeting() {
  const h = new Date().getHours();
  return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening';
}

// Removed: userChoresFromAlloc — current allocation now comes from /api/history (database).

// ─── LOGO ────────────────────────────────────────────────────────────────────
// SVG icon: two overlapping task checkboxes forming a "split" — representing
// fair division. Used on the welcome screen, home header, and about page.
function AppLogo({ size = 56 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 56 56" fill="none" xmlns="http://www.w3.org/2000/svg">
      {/* Background circle */}
      <circle cx="28" cy="28" r="28" fill="#1CB59E" />
      {/* Left half — task list */}
      <rect x="10" y="16" width="15" height="3" rx="1.5" fill="white" opacity="0.55" />
      <rect x="10" y="22" width="15" height="3" rx="1.5" fill="white" opacity="0.55" />
      <rect x="10" y="28" width="15" height="3" rx="1.5" fill="white" opacity="0.55" />
      {/* Right half — task list */}
      <rect x="31" y="16" width="15" height="3" rx="1.5" fill="white" opacity="0.55" />
      <rect x="31" y="22" width="15" height="3" rx="1.5" fill="white" opacity="0.55" />
      <rect x="31" y="28" width="15" height="3" rx="1.5" fill="white" opacity="0.55" />
      {/* Centre divider */}
      <rect x="27" y="13" width="2" height="22" rx="1" fill="white" opacity="0.3" />
      {/* Checkmark on left */}
      <path d="M13 37 L16 40 L22 34" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
      {/* Checkmark on right */}
      <path d="M34 37 L37 40 L43 34" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function AppLogoSmall({ size = 32 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 56 56" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle cx="28" cy="28" r="28" fill="rgba(255,255,255,0.15)" />
      <rect x="10" y="18" width="14" height="2.5" rx="1.25" fill="white" opacity="0.7" />
      <rect x="10" y="24" width="14" height="2.5" rx="1.25" fill="white" opacity="0.7" />
      <rect x="32" y="18" width="14" height="2.5" rx="1.25" fill="white" opacity="0.7" />
      <rect x="32" y="24" width="14" height="2.5" rx="1.25" fill="white" opacity="0.7" />
      <rect x="27" y="14" width="2" height="20" rx="1" fill="white" opacity="0.3" />
      <path d="M12 34 L15 37 L20 31" stroke="white" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M34 34 L37 37 L42 31" stroke="white" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// ─── SMALL COMPONENTS ────────────────────────────────────────────────────────

function Spinner({ size = 20, color = '#fff' }) {
  return <span className="spinner" style={{ width: size, height: size, borderTopColor: color }} />;
}

function ErrorBanner({ message, onDismiss }) {
  const ref = useRef(onDismiss);
  useEffect(() => { ref.current = onDismiss; });
  useEffect(() => { if (!message) return; const t = setTimeout(() => ref.current(), 3000); return () => clearTimeout(t); }, [message]);
  if (!message) return null;
  return <div className="error-banner" onClick={onDismiss}>⚠ {message}</div>;
}

function Avatar({ name, size = 44, colorIndex = 0 }) {
  return (
    <div className="avatar" style={{
      width: size, height: size, fontSize: size * 0.4,
      background: getMemberColor(colorIndex),
    }}>
      {getInitial(name)}
    </div>
  );
}

function BackButton({ onBack, light }) {
  return <button className={`back-btn ${light ? 'light' : ''}`} onClick={onBack}>‹</button>;
}

function BottomNav({ active, onNavigate, choresBadge = 0 }) {
  const tabs = [
    { key: 'home',     label: 'Home',     icon: '🏠' },
    { key: 'chores',   label: 'Chores',   icon: '✅', badge: choresBadge },
    { key: 'settings', label: 'Settings', icon: '⚙️' },
  ];
  return (
    <nav className="tab-bar">
      {tabs.map(t => (
        <button key={t.key} className={`tab-item ${active === t.key ? 'active' : ''}`}
          onClick={() => onNavigate(t.key)}>
          <span className="tab-icon" style={{ position: 'relative' }}>
            {t.icon}
            {t.badge > 0 && (
              <span style={{
                position: 'absolute', top: -4, right: -6,
                background: '#B5403F', color: '#fff',
                borderRadius: '50%', fontSize: 10, fontWeight: 700,
                width: 16, height: 16, display: 'flex',
                alignItems: 'center', justifyContent: 'center', lineHeight: 1,
              }}>
                {t.badge > 9 ? '9+' : t.badge}
              </span>
            )}
          </span>
          <span className="tab-label">{t.label}</span>
        </button>
      ))}
    </nav>
  );
}

// 3-colour burden palette used everywhere in the app for consistency.
// green  = at or below fair share (doing their part or less)
// 6-step gradient anchored to fair share (100%):
//   well below   <  85   teal
//   slightly low 85–95   pale green
//   on target    95–110  green
//   slight over  110–130 amber-yellow
//   over         130–170 orange
//   way over     >170    coral
// Distinct hues at every step so 85% and 122% are visibly different.
function getBurdenBarColor(percentage) {
  if (percentage <  85) return '#4FA3B5';   // teal — under fair share
  if (percentage <  95) return '#7FBF74';   // pale green — slightly under
  if (percentage <= 110) return '#4F9E5B';  // green — on target
  if (percentage <= 130) return '#D9B23A';  // amber-yellow — slight over
  if (percentage <= 170) return '#C77800';  // orange — over
  return '#B5403F';                          // coral — way over
}

function BentoButton({ icon, label, sub, variant = 'teal', onClick }) {
  return (
    <button className={`bento-btn bento-${variant}`} onClick={onClick}>
      <span className="bento-icon">{icon}</span>
      <span className="bento-label">{label}</span>
      {sub && <span className="bento-sub">{sub}</span>}
    </button>
  );
}

function CtaBanner({ icon, title, sub, actionLabel, onAction, variant = 'amber' }) {
  return (
    <button className={`cta-banner cta-${variant}`} onClick={onAction}>
      <div className="cta-icon">{icon}</div>
      <div className="cta-text">
        <div className="cta-title">{title}</div>
        {sub && <div className="cta-sub">{sub}</div>}
      </div>
      {actionLabel && <span className="cta-arrow">{actionLabel} ›</span>}
    </button>
  );
}

// ─── BURDEN BALANCE BARS ────────────────────────────────────────────────────

function BurdenBars({ balance }) {
  // Cumulative since the household started — single source of truth that
  // matches the column the algorithm uses to order picking turns.
  const data = balance?.members || balance?.weekly || [];
  if (data.length === 0) return null;
  const maxPct = Math.max(...data.map(d => d.percentage), 100);
  return (
    <div className="burden-section">
      <div className="burden-header">
        <h3 className="burden-title">Burden balance</h3>
      </div>
      <div className="burden-bars">
        {data.map((d, i) => {
          const barW = Math.max(4, Math.round(d.percentage / maxPct * 100));
          return (
            <div key={d.member_id} className="burden-row">
              <Avatar name={d.name} size={32} colorIndex={i} />
              <div className="burden-bar-area">
                <div className="burden-bar-track">
                  <div
                    className="burden-bar-fill"
                    style={{ width: `${barW}%`, background: getBurdenBarColor(d.percentage) }}
                  />
                  <div className="burden-fair-line" />
                </div>
                <span className="burden-bar-pct">{d.percentage.toFixed(0)}%</span>
              </div>
            </div>
          );
        })}
      </div>
      <p className="burden-legend">
        Lifetime workload share · 100% = equal share · bar width relative to most-burdened member
      </p>
      <p className="burden-legend burden-legend-note">
        🌱 Bars naturally even out over more allocations — the algorithm gives lighter loads to whoever has done the most.
      </p>
    </div>
  );
}

// ─── SCREEN: WELCOME ────────────────────────────────────────────────────────

function WelcomeScreen({ onNavigate }) {
  return (
    <div className="screen screen-welcome fade-in">
      <div className="welcome-content">
        <div className="welcome-logo"><AppLogo size={80} /></div>
        <h1 className="welcome-title">FairChore</h1>
        <p className="welcome-sub">Everyone does their fair share.</p>
      </div>
      <div className="welcome-actions">
        <button className="btn btn-teal" onClick={() => onNavigate('register')}>Get Started</button>
        <button className="btn btn-ghost-white" onClick={() => onNavigate('login')}>Sign In</button>
      </div>
    </div>
  );
}

// ─── SCREEN: LOGIN ──────────────────────────────────────────────────────────

function LoginScreen({ onNavigate, onAuth }) {
  const [email, setEmail]       = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState('');

  async function handleLogin(e) {
    e.preventDefault(); setError(''); setLoading(true);
    try {
      const res  = await fetch('/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Login failed');
      saveAuth({ token: data.token, user: data.user });
      onAuth(data.user);
    } catch (err) { setError(err.message); setLoading(false); }
  }

  return (
    <div className="screen screen-auth fade-in">
      <ErrorBanner message={error} onDismiss={() => setError('')} />
      <div className="auth-header">
        <BackButton onBack={() => onNavigate('welcome')} />
        <h1 className="auth-title">Welcome back</h1>
        <p className="auth-sub">Sign in to your account</p>
      </div>
      <form className="auth-form" onSubmit={handleLogin}>
        <div className="field"><label className="field-label">Email</label>
          <input className="field-input" type="email" placeholder="you@example.com" value={email} onChange={e => setEmail(e.target.value)} autoComplete="email" required />
        </div>
        <div className="field"><label className="field-label">Password</label>
          <input className="field-input" type="password" placeholder="••••••••" value={password} onChange={e => setPassword(e.target.value)} autoComplete="current-password" required />
        </div>
        <button className="btn btn-teal" type="submit" disabled={loading}>
          {loading ? <Spinner /> : 'Sign In'}
        </button>
      </form>
      <div className="auth-links">
        <button className="link-btn" onClick={() => onNavigate('register')}>
          Don't have an account? <strong>Register</strong>
        </button>
      </div>
    </div>
  );
}

// ─── SCREEN: REGISTER ───────────────────────────────────────────────────────

function RegisterScreen({ onNavigate, onAuth }) {
  const [name, setName]         = useState('');
  const [email, setEmail]       = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState('');

  async function handleRegister(e) {
    e.preventDefault(); setError(''); setLoading(true);
    try {
      const res  = await fetch('/api/register', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, email, password }) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Registration failed');
      saveAuth({ token: data.token, user: data.user });
      onAuth(data.user);
    } catch (err) { setError(err.message); setLoading(false); }
  }

  return (
    <div className="screen screen-auth fade-in">
      <ErrorBanner message={error} onDismiss={() => setError('')} />
      <div className="auth-header">
        <BackButton onBack={() => onNavigate('welcome')} />
        <h1 className="auth-title">Create Account</h1>
        <p className="auth-sub">Join FairChore today</p>
      </div>
      <form className="auth-form" onSubmit={handleRegister}>
        <div className="field"><label className="field-label">Your Name</label>
          <input className="field-input" type="text" placeholder="Alex" value={name} onChange={e => setName(e.target.value)} required />
        </div>
        <div className="field"><label className="field-label">Email</label>
          <input className="field-input" type="email" placeholder="you@example.com" value={email} onChange={e => setEmail(e.target.value)} autoComplete="email" required />
        </div>
        <div className="field"><label className="field-label">Password</label>
          <input className="field-input" type="password" placeholder="At least 6 characters" value={password} onChange={e => setPassword(e.target.value)} required />
        </div>
        <button className="btn btn-teal" type="submit" disabled={loading}>
          {loading ? <Spinner /> : 'Create Account'}
        </button>
      </form>
      <div className="auth-links">
        <button className="link-btn" onClick={() => onNavigate('login')}>
          Already have an account? <strong>Sign in</strong>
        </button>
      </div>
    </div>
  );
}

// ─── SCREEN: HOME (Trust Dashboard) ─────────────────────────────────────────

function HomeScreen({
  user, household, households, readiness, balance,
  loading, onNavigate, myPreferences, allocHistory, onToggleDone,
}) {
  const isAdmin = household && household.admin_id === user?.id;
  const members = household?.members || [];
  const myReady = readiness.find(r => r.id === user?.id)?.ready;
  const pendingCount = readiness.filter(r => !r.ready).length;
  const allReady = readiness.length > 0 && pendingCount === 0;

  // Detect whether !myReady is because of a newly-added unrated chore vs never set.
  // myPreferences is { chore_id: { score, is_capable } }. If some chores have score=0
  // but others are rated, it means new chores were added after last save.
  const activeChores = household?.chores?.filter(c => c.is_active) || [];
  const ratedCount   = activeChores.filter(c => (myPreferences?.[c.id]?.score ?? 0) > 0).length;
  const unratedCount = activeChores.length - ratedCount;
  const hasRatedBefore = ratedCount > 0;  // at least one chore rated = not a first-timer
  const hid = household?.id;
  const uid = user?.id;

  // Current allocation = the first (most recent) entry in allocHistory that has this user.
  // allocHistory comes from /api/history (database), not localStorage.
  const currentRound = (allocHistory || []).find(r => r.assignments?.some(a => a.member_id === uid)) || null;
  const myCurrentEntry = currentRound ? myEntryFromRound(currentRound, uid) : null;
  const myCurrentChores = myCurrentEntry?.chores || [];  // [{id, title}]

  // Done state comes from DB (completed_at on each chore in allocHistory).
  // No localStorage for done-state.

  const [noAllocToast, setNoAllocToast] = useState(false);

  function handleViewResults() {
    if (allocHistory?.length) {
      onNavigate('results');
    } else {
      setNoAllocToast(true);
      setTimeout(() => setNoAllocToast(false), 2500);
    }
  }

  function formatAllocationDate(ts) {
    if (!ts) return '';
    const d = new Date(ts);
    return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
  }

  const ALGO_LABEL = {
    'round-robin': 'Round-Robin', 'top-trading': 'Top-Trading',
    'bag-filling-practical': 'Bag-Filling', 'bag-filling-paper': 'Bag-Filling (Paper)',
  };

  return (
    <div className="screen screen-home fade-in">
      <header className="home-header glass-header">
        <div>
          <p className="home-greeting">{getGreeting()},</p>
          <h1 className="home-name">{user?.username || user?.name} 👋</h1>
        </div>
        <div className="home-logo-sm"><AppLogoSmall size={34} /></div>
      </header>

      <div className="screen-scroll">
        {loading ? (
          <div className="center-pad"><Spinner size={36} color="#1CB59E" /></div>
        ) : !households?.length ? (
          <div className="empty-household-card">
            <div className="empty-household-icon">🏠</div>
            <h2 className="empty-household-title">You're not in a household yet</h2>
            <p className="empty-household-sub">Join or create one to get started.</p>
            <button className="btn btn-teal" onClick={() => onNavigate('join')}>Join a Household</button>
            <button className="btn btn-ghost" style={{ marginTop: 12 }} onClick={() => onNavigate('create')}>Create New</button>
          </div>
        ) : (
          <>
            {/* CTA Banners */}
            {!myReady && hasRatedBefore && unratedCount > 0 && (
              <CtaBanner icon="🆕"
                title={`${unratedCount} new chore${unratedCount !== 1 ? 's' : ''} to rate`}
                sub="Rate the new chore so the next allocation includes your preference."
                actionLabel="Rate" variant="amber" onAction={() => onNavigate('preferences')} />
            )}
            {!myReady && !hasRatedBefore && (
              <CtaBanner icon="⭐" title="Set your preferences" sub="Rate each chore so the split is fair for everyone."
                actionLabel="Start" variant="amber" onAction={() => onNavigate('preferences')} />
            )}
            {myReady && isAdmin && pendingCount > 0 && (
              <CtaBanner icon="⏳" title={`Waiting on ${pendingCount} member${pendingCount !== 1 ? 's' : ''}`}
                sub="They haven't set preferences yet." variant="navy" onAction={() => onNavigate('settings')} />
            )}
            {myReady && isAdmin && allReady && !currentRound && (
              <CtaBanner icon="⚡" title="Everyone is ready!" sub="Run a fair allocation now."
                actionLabel="Allocate" variant="teal" onAction={() => onNavigate('allocate-confirm')} />
            )}

            {/* Effort Balance */}
            <BurdenBars balance={balance} />

            {/* No-allocation toast */}
            {noAllocToast && (
              <div style={{
                position: 'fixed', bottom: 90, left: '50%', transform: 'translateX(-50%)',
                background: '#333', color: '#fff', padding: '10px 20px', borderRadius: 20,
                fontSize: 14, zIndex: 1000, whiteSpace: 'nowrap',
              }}>
                No allocation has been run yet.
              </div>
            )}

            {/* Action Center */}
            <div className="bento-grid">
              {isAdmin && (
                <BentoButton icon="+" label="Add Chore" variant="outline"
                  onClick={() => onNavigate('add-chore')} />
              )}
              {isAdmin && (
                <BentoButton icon="⚡" label="Allocate" sub={currentRound ? 'Re-run' : 'Start'}
                  variant="teal" onClick={() => onNavigate('allocate-confirm')} />
              )}
              <BentoButton icon="⭐" label="Preferences" sub={myReady ? 'Update' : 'Set now'}
                variant={myReady ? 'outline' : 'amber'} onClick={() => onNavigate('preferences')} />
              <BentoButton icon="📊" label="Previous Allocation" sub="View results"
                variant="outline" onClick={handleViewResults} />
            </div>

            {/* ── Current Allocation (from /api/history database) ── */}
            <div className="section-card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
                <h3 className="section-card-title" style={{ margin: 0 }}>Current allocation</h3>
                {currentRound?.round_ts && (
                  <span style={{ fontSize: 12, color: 'var(--sub)' }}>{formatAllocationDate(currentRound.round_ts)}</span>
                )}
              </div>
              {!currentRound ? (
                <p className="empty-sm">No allocation confirmed yet.</p>
              ) : myCurrentChores.length === 0 ? (
                <p className="empty-sm">🎉 No chores assigned to you this allocation!</p>
              ) : (
                <>
                  {myCurrentChores.map(chore => {
                    const isDone = isDoneChore(chore);
                    return (
                      <div key={chore.assignment_id}
                        className={`chore-card ${isDone ? 'done' : ''}`}
                        onClick={() => onToggleDone && onToggleDone(chore.assignment_id, isDone)}>
                        <div className={`chore-check ${isDone ? 'checked' : ''}`}>
                          {isDone && <span className="ck">✓</span>}
                        </div>
                        <div className="chore-info">
                          <span className="chore-name">{chore.title}</span>
                          <span className="chore-hint">{isDone ? 'Completed ✓' : 'Tap to mark done'}</span>
                        </div>
                      </div>
                    );
                  })}
                </>
              )}
            </div>

            {/* Past allocations are viewable in the Chores screen (My Chores tab). */}
          </>
        )}
      </div>
      <BottomNav active="home" onNavigate={onNavigate} choresBadge={unratedCount} />
    </div>
  );
}

// ─── SCREEN: CHORES (Unified Hub) ───────────────────────────────────────────

function ChoresScreen({
  user, household, allocHistory, readiness, onNavigate, onUnauth, onRefresh, onToggleDone,
}) {
  const [tab, setTab]                   = useState('mine');
  const [managing, setManaging]         = useState(false);
  // Per-allocation expand/collapse override. Closed allocations are collapsed
  // by default; clicking the header flips the override for that round only.
  const [expandedOverride, setExpandedOverride] = useState(new Set());
  const toggleExpanded = (ts) => setExpandedOverride(prev => {
    const next = new Set(prev);
    if (next.has(ts)) next.delete(ts); else next.add(ts);
    return next;
  });
  const uid = user?.id;
  const isAdmin = household && household.admin_id === uid;
  const allChores      = (household?.chores || []).filter(c => c.is_active);
  const inactiveChores = (household?.chores || []).filter(c => !c.is_active);

  const onUnauthRef = useRef(onUnauth);
  useEffect(() => { onUnauthRef.current = onUnauth; });

  async function deleteChore(choreId) {
    try {
      await apiFetch(`/api/chores/${choreId}`, { method: 'DELETE' }, onUnauthRef.current);
      onRefresh();
    } catch (e) { /* swallow */ }
  }

  async function activateChore(choreId) {
    try {
      await apiFetch(`/api/chores/${choreId}/activate`, { method: 'PATCH' }, onUnauthRef.current);
      onRefresh();
    } catch (e) { /* swallow */ }
  }

  // Build per-user rounds: all rounds containing this user, newest first.
  // Each round: { allocationNum, round_ts, date_label, algorithm, chores: [{id,title,assignment_id,completed_at}] }
  const myRounds = (allocHistory || [])
    .map((round, idx) => {
      const entry = myEntryFromRound(round, uid);
      if (!entry) return null;
      return {
        allocationNum: (allocHistory.length - idx),
        isCurrent: idx === 0,
        round_ts: round.round_ts,
        date_label: round.date_label,
        algorithm: round.algorithm,
        chores: entry.chores,
      };
    })
    .filter(Boolean);

  // Chores that have ever been allocated (completed or not). Each chore is
  // allocated exactly once, so anything not in this set is genuinely unassigned
  // and waiting for the next /allocate run.
  const allocatedChoreIds = new Set(
    (allocHistory || []).flatMap(r =>
      r.assignments.flatMap(a => a.chores.map(c => c.id))
    )
  );
  const unassignedChores = allChores.filter(c => !allocatedChoreIds.has(c.id));

  const ALGO_LABEL = {
    'round-robin': 'Round-Robin', 'top-trading': 'Top-Trading',
    'bag-filling-practical': 'Bag-Filling',
  };

  if (!household) {
    return (
      <div className="screen fade-in">
        <div className="page-header"><h1 className="page-title">Chores</h1></div>
        <div className="empty-state">
          <div className="empty-icon">📋</div>
          <p className="empty-title">Join a household first</p>
        </div>
        <BottomNav active="chores" onNavigate={onNavigate} />
      </div>
    );
  }

  return (
    <div className="screen screen-chores fade-in">
      <div className="page-header glass-header-sm">
        <h1 className="page-title">Chores</h1>
      </div>

      {/* Toggle */}
      <div className="filter-pills">
        <button className={`pill ${tab === 'mine' ? 'active' : ''}`} onClick={() => setTab('mine')}>My Chores</button>
        <button className={`pill ${tab === 'all' ? 'active' : ''}`} onClick={() => setTab('all')}>All Chores</button>
      </div>

      <div className="screen-scroll">

        {/* ── MY CHORES TAB: all allocations, newest first ── */}
        {tab === 'mine' && (
          myRounds.length === 0 ? (
            <div className="empty-state">
              <div className="empty-icon">⏳</div>
              <p className="empty-title">Nothing assigned yet</p>
              <p className="empty-sub">Wait for an admin to run and confirm an allocation.</p>
            </div>
          ) : (
            myRounds.map(round => {
              const total   = round.chores.length;
              const doneN   = round.chores.filter(isDoneChore).length;
              const allDone = total > 0 && doneN === total;
              const status  = round.isCurrent
                ? { label: 'In progress', color: '#1E7F75', bg: 'rgba(30,127,117,0.10)' }
                : allDone
                  ? { label: 'Closed',      color: '#4F9E5B', bg: 'rgba(79,158,91,0.10)' }
                  : { label: 'Overdue',     color: '#C77800', bg: 'rgba(199,120,0,0.10)' };
              // Closed (all-done) allocations collapse by default; current and
              // overdue stay open. Clicking the header flips that for one round.
              const defaultCollapsed = allDone && !round.isCurrent;
              const overridden       = expandedOverride.has(round.round_ts);
              const collapsed        = overridden ? !defaultCollapsed : defaultCollapsed;
              return (
                <div key={round.round_ts} className={`alloc-block ${collapsed ? 'collapsed' : ''}`}>
                  <button className="allocblk-header" onClick={() => toggleExpanded(round.round_ts)}>
                    <span className="allocblk-header-left">
                      <span className="allocblk-chevron">{collapsed ? '▸' : '▾'}</span>
                      <span className={`allocblk-title ${round.isCurrent ? 'current' : ''}`}>
                        {round.isCurrent ? 'Current allocation' : `Allocation ${round.allocationNum}`}
                      </span>
                      <span className="allocblk-badge" style={{ color: status.color, background: status.bg }}>
                        {status.label}
                      </span>
                    </span>
                    <span className="allocblk-header-right">
                      <span className="allocblk-meta">{round.date_label}</span>
                    </span>
                  </button>

                  {!collapsed && (
                    total === 0 ? (
                      <p className="allocblk-empty">No chores in this allocation</p>
                    ) : (
                      round.chores.map(chore => {
                        const isDone = isDoneChore(chore);
                        // Tap-to-toggle works for ANY allocation the user owns —
                        // current, overdue, or even closed (in case they want
                        // to undo a mistakenly-marked completion).
                        const hint = isDone
                          ? 'Tap to undo'
                          : round.isCurrent ? 'Tap to complete' : 'Overdue — tap to mark done';
                        return (
                          <div key={chore.assignment_id}
                            className={`task-card ${isDone ? 'done' : ''}`}
                            onClick={() => onToggleDone(chore.assignment_id, isDone)}>
                            <div className={`chore-check ${isDone ? 'checked' : ''}`}>
                              {isDone && <span className="ck">✓</span>}
                            </div>
                            <div className="chore-info">
                              <span className="chore-name">{chore.title}</span>
                              <span className="chore-hint" style={{ color: !round.isCurrent && !isDone ? '#C77800' : undefined }}>
                                {hint}
                              </span>
                            </div>
                          </div>
                        );
                      })
                    )
                  )}
                </div>
              );
            })
          )
        )}

        {/* ── ALL CHORES TAB: current allocation + past undone, grouped by member ── */}
        {tab === 'all' && (
          <>
            {allChores.length === 0 && allocHistory.length === 0 ? (
              <div className="empty-state">
                <div className="empty-icon">📋</div>
                <p className="empty-title">No chores added yet</p>
                {isAdmin && <button className="btn btn-teal" style={{ marginTop: 16 }}
                  onClick={() => onNavigate('add-chore')}>+ Add Chore</button>}
              </div>
            ) : (
              <>
                {isAdmin && (
                  <div className="sub-heading-row">
                    <h3 className="sub-heading">All Chores</h3>
                    <button className="manage-btn" onClick={() => setManaging(m => !m)}>
                      {managing ? 'Done' : 'Manage'}
                    </button>
                  </div>
                )}

                {/* Per-member view: current allocation + past undone chores */}
                {(household?.members || []).map((member, mi) => {
                  const isOwner = member.id === uid;

                  // Collect all chores for this member across all allocations,
                  // but only show: current allocation (all) + past allocations (undone only).
                  const allMemberChores = (allocHistory || []).flatMap((round, idx) => {
                    const entry = round.assignments?.find(a => a.member_id === member.id);
                    if (!entry) return [];
                    const chores = idx === 0
                      ? entry.chores  // current allocation: show all
                      : entry.chores.filter(c => !c.completed_at);  // past allocations: undone only
                    return chores.map(c => ({
                      ...c,
                      allocationNum: allocHistory.length - idx,
                      isCurrent: idx === 0,
                      round_ts: round.round_ts,
                      date_label: round.date_label,
                    }));
                  });

                  if (allMemberChores.length === 0) return null;

                  return (
                    <div key={member.id} className="chore-group">
                      <div className="chore-group-header">
                        <Avatar name={member.name} size={26} colorIndex={mi} />
                        <span className="chore-group-name">{member.name}</span>
                        <span className="chore-group-count">
                          {allMemberChores.filter(c => !c.completed_at).length} pending
                        </span>
                      </div>
                      {allMemberChores.map(chore => {
                        const isDone = isDoneChore(chore);
                        return (
                          <div key={chore.assignment_id}
                            className={`task-card ${isDone ? 'done' : ''}`}
                            onClick={() => isOwner ? onToggleDone(chore.assignment_id, isDone) : null}
                            style={!isOwner ? { cursor: 'default' } : {}}>
                            <div className={`chore-check ${isDone ? 'checked' : ''}`}>
                              {isDone && <span className="ck">✓</span>}
                            </div>
                            <div className="chore-info">
                              <span className="chore-name">{chore.title}</span>
                              <span className="chore-hint" style={{ color: !chore.isCurrent && !isDone ? '#C77800' : undefined }}>
                                {isDone ? 'Completed'
                                  : chore.isCurrent ? (isOwner ? 'Tap to complete' : 'In progress')
                                  : `Overdue from allocation ${chore.allocationNum}`}
                              </span>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  );
                })}

                {/* Unassigned active chores */}
                {unassignedChores.length > 0 && (
                  <div className="chore-group">
                    <div className="chore-group-header">
                      <span className="chore-group-name" style={{ color: '#8E8E93' }}>Unassigned</span>
                      <span className="chore-group-count">{unassignedChores.length}</span>
                    </div>
                    {unassignedChores.map(c => (
                      <div key={c.id} className="chore-flat-row">
                        <span className="chore-flat-bullet" style={{ color: '#8E8E93' }}>●</span>
                        <span className="chore-flat-title">{c.title}</span>
                        {managing && isAdmin
                          ? <button className="chore-delete-btn" onClick={() => deleteChore(c.id)}>×</button>
                          : <span className="pending-badge">Unassigned</span>}
                      </div>
                    ))}
                    {isAdmin && !managing && (
                      <button className="btn btn-allocate" style={{ marginTop: 8 }}
                        onClick={() => onNavigate('allocate-confirm')}>⚡ Allocate Now</button>
                    )}
                  </div>
                )}

                {/* Inactive chores — visible to admin in manage mode */}
                {isAdmin && managing && inactiveChores.length > 0 && (
                  <div className="chore-group" style={{ marginTop: 12 }}>
                    <div className="chore-group-header">
                      <span className="chore-group-name" style={{ color: '#8E8E93' }}>Inactive</span>
                      <span className="chore-group-count">{inactiveChores.length}</span>
                    </div>
                    {inactiveChores.map(c => (
                      <div key={c.id} className="chore-flat-row" style={{ opacity: 0.6 }}>
                        <span className="chore-flat-bullet" style={{ color: '#8E8E93' }}>○</span>
                        <span className="chore-flat-title">{c.title}</span>
                        <button onClick={() => activateChore(c.id)}
                          style={{ marginLeft: 'auto', fontSize: 12, padding: '4px 10px',
                            background: '#1CB59E', color: '#fff', border: 'none',
                            borderRadius: 8, cursor: 'pointer', fontWeight: 600 }}>
                          Activate
                        </button>
                      </div>
                    ))}
                  </div>
                )}

                {isAdmin && (
                  <button className="btn btn-ghost" style={{ marginTop: 16 }}
                    onClick={() => onNavigate('add-chore')}>+ Add New Chore</button>
                )}
              </>
            )}
          </>
        )}
      </div>
      <BottomNav active="chores" onNavigate={onNavigate} choresBadge={0} />
    </div>
  );
}

// ─── SCREEN: SETTINGS (Admin & Profile) ─────────────────────────────────────

function SettingsScreen({
  user, household, households, readiness,
  onNavigate, onSignOut, onSwitchHousehold, onUnauth, onRefresh, onUpdateUser,
}) {
  const [settingsView, setSettingsView] = useState('menu');
  const [copied, setCopied] = useState(false);

  const loadA11y = () => {
    try { return JSON.parse(localStorage.getItem('fairchore_a11y') || '{}'); }
    catch { return {}; }
  };

  const [highContrast, setHighContrast] = useState(() => localStorage.getItem('fairchore_hc') === '1');
  const [textSize,     setTextSize]     = useState(() => loadA11y().textSize || 'default');
  const [reduceMotion, setReduceMotion] = useState(() => !!loadA11y().reduceMotion);
  const [colorBlind,   setColorBlind]   = useState(() => !!loadA11y().colorBlind);

  const [confirmAdmin, setConfirmAdmin] = useState(null);
  const [adminLoading, setAdminLoading] = useState(false);
  const [adminError,   setAdminError]   = useState('');
  const [joinCode,  setJoinCode]  = useState('');
  const [joinLoading, setJoinLoading] = useState(false);
  const [joinMsg,   setJoinMsg]   = useState('');
  const [joinError, setJoinError] = useState('');

  const [showEdit,    setShowEdit]    = useState(false);
  const [editName,    setEditName]    = useState(user?.username || user?.name || '');
  const [editEmail,   setEditEmail]   = useState(user?.email || '');
  const [saveLoading, setSaveLoading] = useState(false);
  const [saveMsg,     setSaveMsg]     = useState('');
  const [saveError,   setSaveError]   = useState('');

  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [deleteError,   setDeleteError]   = useState('');

  const members = household?.members || [];
  const isAdmin = household && household.admin_id === user?.id;

  function saveA11y(patch) {
    const cur = loadA11y();
    localStorage.setItem('fairchore_a11y', JSON.stringify({ ...cur, ...patch }));
  }

  function toggleHC() {
    const next = !highContrast;
    setHighContrast(next);
    localStorage.setItem('fairchore_hc', next ? '1' : '0');
    document.documentElement.classList.toggle('high-contrast', next);
    saveA11y({ highContrast: next });
  }

  function applyTextSize(size) {
    setTextSize(size);
    saveA11y({ textSize: size });
    const map = { small: '0.9em', default: '1em', large: '1.15em' };
    document.documentElement.style.fontSize = map[size] || '1em';
  }

  function toggleReduceMotion() {
    const next = !reduceMotion;
    setReduceMotion(next);
    saveA11y({ reduceMotion: next });
    document.body.classList.toggle('reduce-motion', next);
  }

  function toggleColorBlind() {
    const next = !colorBlind;
    setColorBlind(next);
    saveA11y({ colorBlind: next });
    document.body.classList.toggle('colorblind', next);
  }

  async function handleSaveProfile(e) {
    e.preventDefault();
    if (!editName.trim() || !editEmail.trim()) return;
    setSaveLoading(true); setSaveMsg(''); setSaveError('');
    try {
      const res = await apiFetch('/api/account', {
        method: 'PATCH',
        body: JSON.stringify({ name: editName.trim(), email: editEmail.trim() }),
      }, onUnauth);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed');
      if (onUpdateUser) onUpdateUser({ name: data.name, email: data.email });
      setSaveMsg('Profile updated!');
      setShowEdit(false);
    } catch (err) { setSaveError(err.message); }
    finally { setSaveLoading(false); }
  }

  async function handleDeleteAccount() {
    setDeleteLoading(true); setDeleteError('');
    try {
      const res = await apiFetch('/api/account', { method: 'DELETE' }, onUnauth);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed');
      localStorage.clear();
      onSignOut();
    } catch (err) { setDeleteError(err.message); }
    finally { setDeleteLoading(false); }
  }

  function copyCode() {
    navigator.clipboard.writeText(household?.join_code || '').then(() => {
      setCopied(true); setTimeout(() => setCopied(false), 2000);
    });
  }

  async function handleMakeAdmin(member) {
    setAdminLoading(true); setAdminError('');
    try {
      const res = await apiFetch(`/api/households/${household.id}/admin`, {
        method: 'PATCH',
        body: JSON.stringify({ new_admin_id: member.id }),
      }, onUnauth);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed');
      setConfirmAdmin(null);
      if (onRefresh) await onRefresh();
    } catch (err) { setAdminError(err.message); }
    finally { setAdminLoading(false); }
  }

  async function handleJoin(e) {
    e.preventDefault();
    if (!joinCode.trim()) return;
    setJoinLoading(true); setJoinMsg(''); setJoinError('');
    try {
      const res = await apiFetch('/api/households/join', {
        method: 'POST',
        body: JSON.stringify({ code: joinCode.toUpperCase() }),
      }, onUnauth);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Not found');
      setJoinMsg(`Joined ${data.name}!`);
      setJoinCode('');
      if (onRefresh) await onRefresh();
    } catch (err) { setJoinError(err.message); }
    finally { setJoinLoading(false); }
  }

  // ── Sub-screen: Profile ──
  if (settingsView === 'profile') return (
    <div className="screen screen-settings fade-in">
      <div className="settings-subheader">
        <button className="settings-back-btn" onClick={() => setSettingsView('menu')}>‹ Settings</button>
        <span className="settings-subheader-title">Profile</span>
      </div>
      <div className="screen-scroll">

        {/* Avatar + name hero */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '28px 0 24px' }}>
          <div style={{ position: 'relative' }}>
            <Avatar name={user?.username || user?.name} size={80} colorIndex={0} />
          </div>
          <span style={{ fontSize: 22, fontWeight: 800, marginTop: 14, color: 'var(--text)', letterSpacing: '-0.3px' }}>
            {user?.username || user?.name}
          </span>
          <span style={{ fontSize: 14, color: 'var(--sub)', marginTop: 3 }}>{user?.email}</span>
          {household && (
            <span style={{
              marginTop: 10, background: 'rgba(28,181,158,0.12)', color: '#1CB59E',
              borderRadius: 20, padding: '3px 14px', fontSize: 13, fontWeight: 600,
            }}>
              {household.name}
              {household.admin_id === user?.id && ' · Admin'}
            </span>
          )}
        </div>

        {/* Account details — same field/field-input pattern as the rest of the app */}
        <p className="settings-section-title">Account details</p>
        <div className="profile-card">
          <form onSubmit={handleSaveProfile} className="profile-form">
            <div className="field">
              <label className="field-label">Display name</label>
              <input className="field-input" type="text" placeholder="Your name"
                value={editName} onChange={e => setEditName(e.target.value)} maxLength={80} />
            </div>
            <div className="field">
              <label className="field-label">Email address</label>
              <input className="field-input" type="email" placeholder="you@example.com"
                value={editEmail} onChange={e => setEditEmail(e.target.value)} maxLength={120} />
            </div>
            {saveError && <div className="profile-msg error">{saveError}</div>}
            {saveMsg   && <div className="profile-msg success">✓ {saveMsg}</div>}
            <button className="btn btn-teal" type="submit"
              disabled={saveLoading || !editName.trim() || !editEmail.trim()}>
              {saveLoading ? <Spinner size={16} color="#fff" /> : 'Save changes'}
            </button>
          </form>
        </div>

        {/* Households summary */}
        {households && households.length > 0 && (
          <>
            <p className="settings-section-title">Your households</p>
            <div className="a11y-card" style={{ padding: 0, overflow: 'hidden' }}>
              {households.map((h, i) => (
                <div key={h.id} style={{
                  display: 'flex', alignItems: 'center', padding: '12px 16px',
                  borderBottom: i < households.length - 1 ? '1px solid var(--border)' : 'none',
                }}>
                  <span style={{ fontSize: 18, marginRight: 12 }}>🏠</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>{h.name}</div>
                    <div style={{ fontSize: 12, color: 'var(--sub)' }}>
                      Code: {h.join_code} · {h.member_count} member{h.member_count !== 1 ? 's' : ''}
                    </div>
                  </div>
                  {h.admin_id === user?.id && (
                    <span style={{ fontSize: 11, background: '#1CB59E', color: '#fff',
                      borderRadius: 10, padding: '2px 8px', fontWeight: 600 }}>Admin</span>
                  )}
                </div>
              ))}
            </div>
          </>
        )}

        <div className="a11y-card" style={{ marginTop: 24 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>Delete account</div>
              <div style={{ fontSize: 12, color: 'var(--sub)', marginTop: 2 }}>Permanently removes you from all households</div>
            </div>
            <button onClick={() => { setConfirmDelete(true); setDeleteError(''); }}
              style={{ background: 'rgba(181,64,63,0.10)', border: 'none', color: '#B5403F',
                fontSize: 13, fontWeight: 600, cursor: 'pointer', padding: '7px 14px',
                borderRadius: 8, fontFamily: 'inherit', whiteSpace: 'nowrap' }}>
              Delete
            </button>
          </div>
          {confirmDelete && (
            <div style={{ marginTop: 14, paddingTop: 14, borderTop: '1px solid var(--border)' }}>
              <p style={{ fontSize: 13, color: '#B5403F', margin: '0 0 12px', lineHeight: 1.5 }}>
                This will permanently delete your account and remove you from all households. This cannot be undone.
              </p>
              {deleteError && <p style={{ color: '#B5403F', fontSize: 13, margin: '0 0 8px' }}>{deleteError}</p>}
              <div className="confirm-actions">
                <button className="btn-confirm-cancel" onClick={() => setConfirmDelete(false)}>Cancel</button>
                <button onClick={handleDeleteAccount} disabled={deleteLoading}
                  style={{ padding: '8px 16px', background: '#B5403F', color: '#fff',
                    border: 'none', borderRadius: 8, fontWeight: 600, cursor: 'pointer',
                    fontSize: 14, display: 'flex', alignItems: 'center', gap: 6, fontFamily: 'inherit' }}>
                  {deleteLoading ? <Spinner size={14} color="#fff" /> : 'Delete permanently'}
                </button>
              </div>
            </div>
          )}
        </div>

        <div style={{ height: 80 }} />
      </div>
    </div>
  );

  // ── Sub-screen: Households ──
  if (settingsView === 'households') return (
    <div className="screen screen-settings fade-in">
      <div className="settings-subheader">
        <button className="settings-back-btn" onClick={() => setSettingsView('menu')}>‹ Settings</button>
        <span className="settings-subheader-title">Households</span>
      </div>
      <div className="screen-scroll">
        {households && households.length > 0 && (
          <>
            <h3 className="settings-section-title">Your Households</h3>
            <div className="household-list">
              {households.map(h => (
                <button key={h.id}
                  className={`household-switch-btn ${household?.id === h.id ? 'active' : ''}`}
                  onClick={() => household?.id !== h.id && onSwitchHousehold(h.id)}>
                  <span className="household-switch-name">{h.name}</span>
                  <span className="household-switch-meta">{h.member_count} member{h.member_count !== 1 ? 's' : ''}</span>
                  {household?.id === h.id
                    ? <span className="household-switch-check">✓</span>
                    : <span className="household-switch-switch">Switch</span>}
                </button>
              ))}
            </div>
          </>
        )}

        <h3 className="settings-section-title" style={{ marginTop: 20 }}>Join Another Household</h3>
        <form className="join-inline-form" onSubmit={handleJoin}>
          <input className="join-inline-input" type="text" placeholder="Enter join code"
            value={joinCode} onChange={e => setJoinCode(e.target.value.toUpperCase())}
            maxLength={6} autoComplete="off" />
          <button className="join-inline-btn btn-teal" type="submit" disabled={joinLoading || !joinCode.trim()}>
            {joinLoading ? <Spinner size={16} color="#fff" /> : 'Join'}
          </button>
        </form>
        {joinMsg   && <p className="join-inline-success">{joinMsg}</p>}
        {joinError && <p className="join-inline-error">{joinError}</p>}

        {household ? (
          <>
            <h3 className="settings-section-title" style={{ marginTop: 20 }}>
              {household.name}
            </h3>
            <div className="join-code-card" onClick={copyCode}>
              <span className="join-code-label">Join Code</span>
              <span className="join-code-value">{household.join_code}</span>
              <span className="join-code-hint">{copied ? '✓ Copied!' : 'Tap to copy'}</span>
            </div>

            <h3 className="settings-section-title" style={{ marginTop: 16 }}>Members</h3>
            {adminError && <p className="join-inline-error">{adminError}</p>}
            <div className="members-list">
              {members.map((m, i) => {
                const r = readiness.find(x => x.id === m.id);
                const isThisAdmin = m.id === household.admin_id;
                return (
                  <div key={m.id} className="member-row">
                    <Avatar name={m.name} size={38} colorIndex={i} />
                    <div className="member-row-info">
                      <span className="member-row-name">{m.name}</span>
                      <span className={`member-row-status ${r?.ready ? 'ready' : 'pending'}`}>
                        {r?.ready ? '✓ Prefs set' : '⏱ Pending'}
                      </span>
                    </div>
                    {isThisAdmin
                      ? <span className="admin-pill">Admin</span>
                      : isAdmin && (
                          <button className="make-admin-btn"
                            onClick={() => { setConfirmAdmin(m); setAdminError(''); }}>
                            Make Admin
                          </button>
                        )
                    }
                  </div>
                );
              })}
            </div>

            {confirmAdmin && (
              <div className="confirm-dialog">
                <p className="confirm-text">
                  Make <strong>{confirmAdmin.name}</strong> the new admin? You will lose admin access.
                </p>
                <div className="confirm-actions">
                  <button className="btn-confirm-cancel" onClick={() => setConfirmAdmin(null)}>Cancel</button>
                  <button className="btn-confirm-ok" onClick={() => handleMakeAdmin(confirmAdmin)} disabled={adminLoading}>
                    {adminLoading ? <Spinner size={14} color="#fff" /> : 'Confirm'}
                  </button>
                </div>
              </div>
            )}
          </>
        ) : (
          <div className="empty-state-sm" style={{ marginTop: 24 }}>
            <p>No household yet.</p>
            <button className="btn btn-teal" style={{ marginTop: 12 }} onClick={() => onNavigate('join')}>
              Join or Create
            </button>
          </div>
        )}
        <div style={{ height: 80 }} />
      </div>
    </div>
  );

  // ── Sub-screen: Accessibility ──
  if (settingsView === 'accessibility') return (
    <div className="screen screen-settings fade-in">
      <div className="settings-subheader">
        <button className="settings-back-btn" onClick={() => setSettingsView('menu')}>‹ Settings</button>
        <span className="settings-subheader-title">Accessibility</span>
      </div>
      <div className="screen-scroll">

        <p className="a11y-group-header">TEXT</p>
        <div className="a11y-card">
          <span className="settings-label">Text size</span>
          <div style={{ display: 'flex', gap: 6, marginTop: 10 }}>
            {['Small', 'Default', 'Large'].map(label => {
              const val = label.toLowerCase();
              const active = textSize === val;
              return (
                <button key={val} onClick={() => applyTextSize(val)}
                  style={{ flex: 1, padding: '7px 0', borderRadius: 20,
                    border: `1.5px solid ${active ? '#4CAF50' : '#E0E0E0'}`,
                    background: active ? '#4CAF50' : '#fff',
                    color: active ? '#fff' : 'var(--text)',
                    fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit' }}>
                  {label}
                </button>
              );
            })}
          </div>
        </div>

        <p className="a11y-group-header">DISPLAY</p>
        {[
          { label: 'High contrast',     checked: highContrast, onChange: toggleHC },
          { label: 'Colour-blind mode', checked: colorBlind,   onChange: toggleColorBlind },
        ].map(({ label, checked, onChange }) => (
          <div key={label} className="a11y-card a11y-row">
            <span className="settings-label">{label}</span>
            <label className="toggle-switch">
              <input type="checkbox" checked={checked} onChange={onChange} />
              <span className="toggle-track"><span className="toggle-thumb" /></span>
            </label>
          </div>
        ))}

        <p className="a11y-group-header">MOTION</p>
        <div className="a11y-card a11y-row">
          <span className="settings-label">Reduce motion</span>
          <label className="toggle-switch">
            <input type="checkbox" checked={reduceMotion} onChange={toggleReduceMotion} />
            <span className="toggle-track"><span className="toggle-thumb" /></span>
          </label>
        </div>

        <div style={{ height: 80 }} />
      </div>
    </div>
  );

  // ── Sub-screen: About ──
  if (settingsView === 'about') return (
    <div className="screen screen-settings fade-in">
      <div className="settings-subheader">
        <button className="settings-back-btn" onClick={() => setSettingsView('menu')}>‹ Settings</button>
        <span className="settings-subheader-title">About</span>
      </div>
      <div className="screen-scroll">

        {/* Hero */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '32px 0 24px' }}>
          <AppLogo size={72} />
          <h2 style={{ fontSize: 26, fontWeight: 800, color: 'var(--text)', margin: '16px 0 8px', letterSpacing: '-0.5px' }}>FairChore</h2>
          <p style={{ fontSize: 15, color: 'var(--sub)', textAlign: 'center', lineHeight: 1.6, maxWidth: 260 }}>
            Stop arguing about chores. Start splitting them fairly.
          </p>
        </div>

        {/* What it does */}
        <div className="a11y-card" style={{ marginBottom: 12 }}>
          <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)', margin: '0 0 8px' }}>What is FairChore?</h3>
          <p style={{ fontSize: 13, color: 'var(--sub)', lineHeight: 1.65, margin: 0 }}>
            FairChore is a smart household chore manager that uses proven mathematical
            algorithms to split chores in a way that everyone can agree is genuinely fair —
            not just by turns, but by how much each person actually dislikes each task.
          </p>
        </div>

        {/* How it works */}
        <div className="a11y-card" style={{ marginBottom: 12 }}>
          <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)', margin: '0 0 12px' }}>How it works</h3>
          {[
            { icon: '⭐', title: 'Rate your chores', desc: 'Tell us how much you like or dislike each task — honestly.' },
            { icon: '⚡', title: 'Run a fair split', desc: 'The algorithm assigns chores so no one ends up with more than their fair share.' },
            { icon: '📊', title: 'Track over time', desc: 'Workload history ensures the next round balances out any previous imbalance.' },
          ].map(({ icon, title, desc }) => (
            <div key={title} style={{ display: 'flex', gap: 12, marginBottom: 14 }}>
              <span style={{ fontSize: 22, flexShrink: 0 }}>{icon}</span>
              <div>
                <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>{title}</div>
                <div style={{ fontSize: 13, color: 'var(--sub)', marginTop: 2, lineHeight: 1.5 }}>{desc}</div>
              </div>
            </div>
          ))}
        </div>

        {/* Fairness guarantee */}
        <div className="a11y-card" style={{ marginBottom: 12, background: 'rgba(28,181,158,0.07)' }}>
          <h3 style={{ fontSize: 14, fontWeight: 700, color: '#1CB59E', margin: '0 0 6px' }}>Fairness guarantee</h3>
          <p style={{ fontSize: 13, color: 'var(--sub)', lineHeight: 1.65, margin: 0 }}>
            Every allocation satisfies <strong>Envy-Freeness up to One Chore (EF1)</strong>:
            no one would prefer anyone else's bundle of chores, except possibly by one task.
            This is the gold standard of algorithmic fairness for task allocation.
          </p>
        </div>

        <div style={{ textAlign: 'center', padding: '12px 0 4px' }}>
          <p style={{ fontSize: 12, color: 'var(--sub)', margin: 0 }}>Version 1.0 · Built for household fairness</p>
        </div>

        <div style={{ height: 80 }} />
      </div>
    </div>
  );

  // ── Main menu ──
  const menuRows = [
    { icon: '👤', label: 'Profile',           view: 'profile' },
    { icon: '🏠', label: 'Your Households',   view: 'households' },
    { icon: '♿', label: 'Accessibility',     view: 'accessibility' },
    { icon: '📋', label: 'About',             view: 'about' },
  ];

  return (
    <div className="screen screen-settings fade-in">
      <div className="page-header glass-header-sm">
        <h1 className="page-title">Settings</h1>
      </div>
      <div className="screen-scroll">

        {/* Profile preview row */}
        <div className="settings-profile-preview">
          <Avatar name={user?.username || user?.name} size={48} colorIndex={0} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)',
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {user?.username || user?.name}
            </div>
            <div style={{ fontSize: 13, color: 'var(--sub)',
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {user?.email}
            </div>
          </div>
        </div>

        <div style={{ marginTop: 20 }}>
          {menuRows.map((row, i) => (
            <button key={row.view} className="settings-menu-row"
              style={{ borderRadius: i === 0 ? '12px 12px 0 0' : i === menuRows.length - 1 ? '0 0 12px 12px' : 0 }}
              onClick={() => setSettingsView(row.view)}>
              <span className="settings-menu-icon">{row.icon}</span>
              <span className="settings-menu-label">{row.label}</span>
              <span className="settings-menu-chevron">›</span>
            </button>
          ))}
        </div>

        <button className="btn" onClick={onSignOut}
          style={{ marginTop: 24, background: '#B5403F', color: '#fff' }}>
          Sign Out
        </button>

        <div style={{ height: 100 }} />
      </div>
      <BottomNav active="settings" onNavigate={onNavigate} />
    </div>
  );
}

// ─── SCREEN: PREFERENCES (Soft-Budget Ratings) ─────────────────────────────

function PreferencesScreen({ household, allocHistory, onNavigate, onUnauth, onRefresh }) {
  // Only show UNALLOCATED active chores. A chore that has ever been allocated
  // (completed or not) is excluded — each chore is one-shot. To "redo" something
  // the admin adds it again as a new chore.
  const allocatedChoreIds = new Set(
    (allocHistory || []).flatMap(round =>
      round.assignments.flatMap(a => a.chores.map(c => c.id))
    )
  );
  const chores = (household?.chores || []).filter(c => c.is_active && !allocatedChoreIds.has(c.id));
  const n = chores.length;
  const householdId = household?.id;

  const [ratings, setRatings] = useState(() => {
    const init = {};
    chores.forEach(c => { init[c.id] = 0; }); // 0 = unrated
    return init;
  });
  const [loading, setLoading]    = useState(false);
  const [loadingExisting, setLE] = useState(true);
  const [error, setError]        = useState('');

  const onUnauthRef = useRef(onUnauth);
  useEffect(() => { onUnauthRef.current = onUnauth; });

  // Load existing preferences and recover 1–4 from stored 100-sum scores
  useEffect(() => {
    if (!householdId || n === 0) { setLE(false); return; }
    let cancelled = false;
    (async () => {
      try {
        const res = await apiFetch(`/api/households/${householdId}/my-preferences`, {}, onUnauthRef.current);
        const data = await res.json();
        if (cancelled) return;
        if (res.ok && data && Object.keys(data).length > 0) {
          const avg = 100 / n;
          const recovered = {};
          chores.forEach(c => {
            const raw = data[String(c.id)];
            if (!raw || raw.score === 0) { recovered[c.id] = 0; return; }
            const ratio = raw.score / avg;
            if (ratio >= 1.25)      recovered[c.id] = 4;
            else if (ratio >= 0.95) recovered[c.id] = 3;
            else if (ratio >= 0.70) recovered[c.id] = 2;
            else                    recovered[c.id] = 1;
          });
          setRatings(recovered);
        }
      } catch (e) { /* ignore */ }
      finally { if (!cancelled) setLE(false); }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line
  }, [householdId, n]);

  // Two-tier cap validation
  const topCount   = Object.values(ratings).filter(v => v === 4).length;
  const upperCount = Object.values(ratings).filter(v => v >= 3).length;
  const maxTop     = Math.max(1, Math.floor(n / 3));
  const maxUpper   = Math.max(2, Math.floor((n * 2) / 3));
  const capExceeded = n >= 3 && (topCount > maxTop || upperCount > maxUpper);
  const capTier1   = n >= 3 && topCount > maxTop;
  const capTier2   = n >= 3 && !capTier1 && upperCount > maxUpper;
  const capMessage = capTier1
    ? `Lower a few 😤 ratings — max ${maxTop} allowed`
    : `Too many high ratings — rate at least ${n - maxUpper} chores as 🙂 or 😐`;

  async function handleSave() {
    setLoading(true); setError('');
    try {
      const payload = {};
      Object.entries(ratings).forEach(([id, v]) => { if (v > 0) payload[id] = v; });
      const res = await apiFetch(`/api/households/${household.id}/preferences`, {
        method: 'POST',
        body: JSON.stringify({ ratings: payload }),
      }, onUnauthRef.current);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to save');
      if (onRefresh) await onRefresh();
      onNavigate('home');
    } catch (err) { setError(err.message); setLoading(false); }
  }

  // Sort: unrated (val=0) first, then rated in original order
  const sortedChores = [...chores].sort((a, b) => {
    const aRated = (ratings[a.id] || 0) > 0;
    const bRated = (ratings[b.id] || 0) > 0;
    if (aRated === bRated) return 0;
    return aRated ? 1 : -1;
  });

  if (n === 0) {
    const hasActiveChores = (household?.chores || []).some(c => c.is_active);
    return (
      <div className="screen screen-prefs fade-in">
        <div className="prefs-header">
          <BackButton onBack={() => onNavigate('home')} light />
          <h1 className="prefs-title">{hasActiveChores ? 'All chores assigned' : 'No chores yet'}</h1>
          <p className="prefs-sub">
            {hasActiveChores
              ? 'All active chores are already in an allocation. Add a new chore, or the admin can activate one from the library.'
              : 'Ask your admin to add chores first.'}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="screen screen-prefs fade-in">
      <ErrorBanner message={error} onDismiss={() => setError('')} />
      <div className="prefs-header">
        <BackButton onBack={() => onNavigate('home')} light />
        <h1 className="prefs-title">Rate upcoming chores</h1>
        <p className="prefs-sub">Only unassigned chores shown — these will be in the next allocation.</p>
      </div>

      <div className="screen-scroll prefs-scroll">
        {loadingExisting ? (
          <div className="center-pad"><Spinner size={32} color="#1CB59E" /></div>
        ) : (() => {
          const unratedChores = sortedChores.filter(c => (ratings[c.id] || 0) === 0);
          const ratedChores   = sortedChores.filter(c => (ratings[c.id] || 0) > 0);
          const renderChore = chore => {
            const val = ratings[chore.id] || 0;
            const lvl = val > 0 ? RATING_LEVELS[val - 1] : null;
            return (
              <div key={chore.id} className="pref-card">
                <div className="pref-card-top">
                  <span className="pref-chore-name">
                    {chore.title}
                    {val === 0 && <span className="new-badge">Needs rating</span>}
                  </span>
                  {lvl && <span className={`pref-sentiment rate-${val}`}>{lvl.emoji} {lvl.label}</span>}
                </div>
                <div className="rating-row">
                  {RATING_LEVELS.map(l => (
                    <button key={l.val} type="button"
                      className={`rating-pill ${val === l.val ? 'active' : ''}`}
                      onClick={() => setRatings(r => ({ ...r, [chore.id]: l.val }))}
                      aria-label={l.label}
                    >
                      <span className="rating-emoji">{l.emoji}</span>
                    </button>
                  ))}
                </div>
              </div>
            );
          };
          return (
            <>
              {unratedChores.length > 0 && (
                <>
                  <p className="burden-rating-label" style={{ color: '#FF9500' }}>
                    Needs rating ({unratedChores.length})
                  </p>
                  {unratedChores.map(renderChore)}
                </>
              )}
              {ratedChores.length > 0 && (
                <>
                  <p className="burden-rating-label" style={{ marginTop: unratedChores.length > 0 ? 16 : 0 }}>
                    Already rated ({ratedChores.length})
                  </p>
                  {ratedChores.map(renderChore)}
                </>
              )}
            </>
          );
        })()}
        <div style={{ height: 120 }} />
      </div>

      {capExceeded && (
        <div className="cap-warning-float">
          {capMessage}
        </div>
      )}

      <div className="prefs-save-wrap">
        <button className="btn btn-teal" onClick={handleSave} disabled={loading || loadingExisting || capExceeded}>
          {loading ? <Spinner /> : 'Save My Ratings'}
        </button>
      </div>
    </div>
  );
}

// ─── PANEL: ADD CHORE ───────────────────────────────────────────────────────

function AddChoreScreen({ household, onNavigate, onUnauth, onRefresh }) {
  const members = household?.members || [];
  const [title, setTitle]       = useState('');
  const [desc, setDesc]         = useState('');
  // my_rating removed — admin rates via Preferences screen like all other members
  const [caps, setCaps]         = useState(() => {
    const init = {};
    members.forEach(m => { init[m.id] = true; });
    return init;
  });
  const [loading, setLoading]       = useState(false);
  const [error, setError]           = useState('');
  const [suggestions, setSuggestions] = useState([]);  // [{title, last_state}]
  const [showSugg, setShowSugg]       = useState(false);
  const householdId = household?.id;

  // Load every chore title ever used in this household for the dropdown.
  useEffect(() => {
    if (!householdId) return;
    (async () => {
      try {
        const res = await apiFetch(`/api/households/${householdId}/chore-titles`, {}, onUnauth);
        const data = await res.json();
        if (res.ok && Array.isArray(data)) setSuggestions(data);
      } catch { /* ignore */ }
    })();
  }, [householdId, onUnauth]);

  // Filter suggestions by what the user has typed (case-insensitive prefix
  // match first, then substring match). Hide the exact title if already typed.
  const norm = title.trim().toLowerCase();
  const filteredSuggestions = norm.length === 0
    ? suggestions.slice(0, 8)
    : suggestions
        .filter(s => s.title.toLowerCase().includes(norm))
        .sort((a, b) => {
          const ai = a.title.toLowerCase().startsWith(norm) ? 0 : 1;
          const bi = b.title.toLowerCase().startsWith(norm) ? 0 : 1;
          return ai - bi;
        })
        .slice(0, 8);

  // Tell the user whether their typed title would inherit existing prefs.
  const exactMatch = suggestions.find(s => s.title.toLowerCase() === norm);
  const inheritHint = exactMatch
    ? `✨ Will inherit existing scores — ready to allocate immediately.`
    : norm.length > 0
      ? `New name — every member will need to rate it before the next allocation.`
      : null;

  // When the typed title matches an existing chore, pre-fill the capability
  // toggles from that chore's stored capabilities. Lets the admin SEE the
  // inherited defaults and edit them before saving.
  const templateChore = exactMatch
    ? (household?.chores || []).find(c => c.id === exactMatch.last_chore_id)
    : null;
  useEffect(() => {
    if (!templateChore) return;
    const next = {};
    members.forEach(m => {
      const cap = templateChore.capabilities?.[String(m.id)];
      next[m.id] = cap === undefined ? true : !!cap;
    });
    setCaps(next);
  }, [templateChore?.id]); // eslint-disable-line

  function pickSuggestion(s) {
    setTitle(s.title);
    setShowSugg(false);
  }

  async function handleAdd(e) {
    e.preventDefault();
    if (!title.trim()) return;
    setLoading(true); setError('');
    try {
      const capabilities = {};
      Object.entries(caps).forEach(([uid, val]) => { capabilities[uid] = val; });
      // Do NOT send my_rating — admin rates via the Preferences screen like everyone else.
      // Auto-rating on add bypassed the two-tier cap and confused the preference state.
      const res = await apiFetch(`/api/households/${household.id}/chores`, {
        method: 'POST',
        body: JSON.stringify({ title: title.trim(), description: desc.trim(), capabilities }),
      }, onUnauth);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed');
      await onRefresh();
      // Navigate to home so the "Rate your new chore" banner is shown.
      // Going to chores would show the stale old allocation, which is misleading.
      onNavigate('home');
    } catch (err) { setError(err.message); setLoading(false); }
  }

  return (
    <div className="screen screen-auth fade-in">
      <div className="auth-header">
        <BackButton onBack={() => onNavigate('chores')} />
        <h1 className="auth-title">Add a Chore</h1>
        <p className="auth-sub">New chore for {household?.name}</p>
      </div>
      <form className="auth-form" onSubmit={handleAdd}>
        {error && <div className="inline-error">{error}</div>}
        <div className="field">
          <label className="field-label">Chore Name</label>
          <div className="title-autocomplete-wrap">
            <input className="field-input field-input-lg" placeholder="e.g. Clean bathroom"
              value={title}
              onChange={e => { setTitle(e.target.value); setShowSugg(true); }}
              onFocus={() => setShowSugg(true)}
              onBlur={() => setTimeout(() => setShowSugg(false), 150)}
              autoFocus autoComplete="off" />
            {showSugg && filteredSuggestions.length > 0 && (
              <div className="title-suggestions">
                {filteredSuggestions.map(s => (
                  <button key={s.title} type="button" className="title-suggestion"
                    onMouseDown={() => pickSuggestion(s)}>
                    {s.title}
                    <span className="ts-meta">
                      {s.last_state === 'inactive'  && 'In library — pre-rated, ready to use'}
                      {s.last_state === 'active'    && 'Already in pool, awaiting next allocation'}
                      {s.last_state === 'assigned'  && 'Currently assigned — will create a fresh copy'}
                      {s.last_state === 'completed' && 'Done previously — will inherit ratings'}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
          {inheritHint && (
            <p style={{
              fontSize: 12, marginTop: 6, marginBottom: 0,
              color: exactMatch ? '#1CB59E' : 'var(--sub)',
            }}>{inheritHint}</p>
          )}
        </div>
        <div className="field">
          <label className="field-label">Description (optional)</label>
          <textarea className="field-input field-textarea" placeholder="Any details or instructions..."
            value={desc} onChange={e => setDesc(e.target.value)} rows={3} />
        </div>
        <div className="field">
          <div style={{ background: 'rgba(30,127,117,0.08)', borderRadius: 8, padding: '8px 12px',
            fontSize: 12, color: '#555', lineHeight: 1.45 }}>
            💡 Re-using a past name inherits its ratings instantly. New names need everyone to rate first.
          </div>
        </div>
        <div className="caps-section">
          <p className="field-label caps-label-tight">Who can do this chore?</p>
          <p className="caps-hint">
            Tap a name to toggle. Green = can do, grey = can't.
            {templateChore && ' Pre-filled from the existing chore.'}
          </p>
          <div className="caps-chip-row">
            {members.map(m => {
              const capable = caps[m.id] !== false;
              return (
                <button key={m.id} type="button"
                  className={`cap-chip ${capable ? 'capable' : 'incapable'}`}
                  onClick={() => setCaps(c => ({ ...c, [m.id]: !capable }))}>
                  {m.name}
                </button>
              );
            })}
          </div>
        </div>
        <button className="btn btn-teal" type="submit" disabled={loading || !title.trim()}>
          {loading ? <Spinner /> : 'Add Chore'}
        </button>
      </form>
    </div>
  );
}

// ─── SCREEN: ALLOCATE CONFIRM ───────────────────────────────────────────────

function AllocateConfirmScreen({ household, readiness, allocHistory, onNavigate, onUnauth, onResults }) {
  // Persist algorithm selection in sessionStorage so navigating away and back
  // doesn't reset the choice back to the default.
  const [algorithm, setAlgorithm] = useState(
    () => sessionStorage.getItem('fairchore_algo') || 'round-robin'
  );
  const [running, setRunning] = useState(false);
  const [error, setError]     = useState('');
  const householdId = household?.id;
  const pendingCount = readiness.filter(r => !r.ready).length;
  // Pool = active chores that have NEVER been allocated (mirrors backend rule).
  // Currently-assigned and completed chores must NOT show up here — they're
  // not eligible for the next allocation.
  const allocatedChoreIds = new Set(
    (allocHistory || []).flatMap(r =>
      r.assignments.flatMap(a => a.chores.map(c => c.id))
    )
  );
  const allocatableChores = (household?.chores || [])
    .filter(c => c.is_active && !allocatedChoreIds.has(c.id));

  function handleSetAlgorithm(key) {
    setAlgorithm(key);
    sessionStorage.setItem('fairchore_algo', key);
  }

  async function handleAllocate() {
    setRunning(true); setError('');
    onNavigate('loading');
    try {
      const res = await apiFetch(`/api/households/${householdId}/allocate`, {
        method: 'POST',
        body: JSON.stringify({ algorithm }),
      }, onUnauth);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Allocation failed');
      onResults(data);
      onNavigate('results');
    } catch (err) {
      console.error('Allocation error:', err);
      setError(err.message); setRunning(false); onNavigate('allocate-confirm');
    }
  }

  return (
    <div className="screen screen-alloc fade-in">
      <ErrorBanner message={error} onDismiss={() => setError('')} />
      <div className="alloc-header">
        <BackButton onBack={() => onNavigate('home')} light />
        <h1 className="alloc-title">Run allocation</h1>
        <p className="alloc-sub">Choose an algorithm and allocate the chores below.</p>
      </div>
      <div className="screen-scroll alloc-body">
        <h3 className="alloc-section-label">Algorithm</h3>
        <div className="algo-list">
          {ALGORITHMS.map(a => (
            <button key={a.key} className={`algo-card ${algorithm === a.key ? 'active' : ''}`}
              onClick={() => handleSetAlgorithm(a.key)}>
              <div className="algo-card-row">
                <span className="algo-card-label">{a.label}</span>
                {algorithm === a.key && <span className="algo-card-check">✓</span>}
              </div>
              <span className="algo-card-desc">{a.desc}</span>
            </button>
          ))}
        </div>

        {/* Chores about to be allocated — only the unallocated pool */}
        <h3 className="alloc-section-label">
          Chores to allocate <span className="alloc-count">({allocatableChores.length})</span>
        </h3>
        {allocatableChores.length === 0 ? (
          <p className="alloc-warning">
            ⚠ No new chores to allocate. Add a fresh chore (or activate one from the library)
            before running an allocation.
          </p>
        ) : (
          <div className="alloc-chip-row">
            {allocatableChores.map(c => (
              <span key={c.id} className="alloc-chip">{c.title}</span>
            ))}
          </div>
        )}

        <h3 className="alloc-section-label">Member readiness</h3>
        <div className="readiness-list">
          {readiness.map((m, i) => (
            <div key={m.id} className="readiness-row">
              <Avatar name={m.name} size={36} colorIndex={i} />
              <span className="readiness-name">{m.name}</span>
              <span className={`readiness-badge ${m.ready ? 'ready' : 'pending'}`}>
                {m.ready ? '✓ Ready' : '⏱ Pending'}
              </span>
            </div>
          ))}
        </div>
        {pendingCount > 0 && (
          <div className="alloc-warning danger">
            🚫 <strong>Cannot allocate yet.</strong> {pendingCount} member{pendingCount !== 1 ? 's' : ''} {pendingCount === 1 ? 'hasn\'t' : 'haven\'t'} rated every chore in the pool.
            Everyone must rate every chore so the algorithm has real preferences to work with.
          </div>
        )}
      </div>
      <div className="alloc-actions">
        <button className="btn btn-alloc-big" onClick={handleAllocate}
          disabled={running || pendingCount > 0 || allocatableChores.length === 0}
          title={
            pendingCount > 0 ? 'All members must rate all chores first'
            : allocatableChores.length === 0 ? 'No new chores in the pool'
            : ''
          }>
          {running ? <Spinner size={22} color="#122042" /> : '⚡ Run Fair Allocation'}
        </button>
      </div>
    </div>
  );
}

// ─── SCREEN: LOADING ────────────────────────────────────────────────────────

function LoadingScreen() {
  return (
    <div className="screen screen-loading fade-in">
      <div className="loading-content">
        <div className="loading-pulse" />
        <h2 className="loading-title">Working it out...</h2>
        <p className="loading-sub">Finding the fairest split for everyone</p>
        <div className="loading-dots"><span /><span /><span /></div>
      </div>
    </div>
  );
}

// ─── SCREEN: RESULTS ────────────────────────────────────────────────────────

// Results-screen fair-share badge colour — same 3-colour palette as burden bars.
function getBurdenColor(ratio) {
  if (ratio <= 1.25) return '#4CAF50';
  if (ratio <= 1.60) return '#FFA726';
  return '#EF5350';
}

// Convert a normalised 100-sum score back to an emoji for display.
// Uses ratio to household average (100 / numChores) so thresholds scale
// correctly regardless of how many chores the household has.
// This is the ONLY score→emoji function in the app — do not add alternatives.
function scoreToEmoji(score, numChores) {
  const n = (numChores && numChores > 0) ? numChores : 1;
  const avg = 100 / n;
  const ratio = (score ?? 0) / avg;
  if (ratio >= 1.3) return '😤';  // clearly above average dislike
  if (ratio >= 0.9) return '😕';  // around or above average
  if (ratio >= 0.6) return '😐';  // below average
  return '🙂';                    // notably low dislike
}

function ResultsScreen({ results, onNavigate, onConfirm, household, user, myPreferences }) {
  const [expandedMember, setExpandedMember] = useState(null);

  if (!results) {
    return (
      <div className="screen screen-results fade-in" style={{ justifyContent: 'center', alignItems: 'center' }}>
        <div className="loading-content">
          <span style={{ fontSize: 40 }}>📋</span>
          <p style={{ color: '#999', textAlign: 'center', fontSize: 14 }}>No allocation yet.<br/>Run one from home to get started.</p>
        </div>
      </div>
    );
  }

  const isHistoryView = !!results.from_history;

  const alloc      = results.allocation || [];
  const allMembers = household?.members || [];
  const burdens    = alloc.map(a => a.burden || 0);
  const avgBurden  = burdens.length > 0 ? burdens.reduce((s, b) => s + b, 0) / burdens.length : 0;

  // scores is keyed by memberName -> choreTitle -> score (raw 100-sum integers)
  let allScores = results.scores || {};
  // In history view, supplement with the current user's stored preferences so
  // the emoji per chore still renders (we have their scores from myPreferences).
  const myName = user?.username || user?.name;
  if (isHistoryView && myPreferences && myName) {
    const myScoreMap = {};
    (household?.chores || []).forEach(c => {
      const pref = myPreferences[String(c.id)];
      if (pref?.score !== undefined) myScoreMap[c.title] = pref.score;
    });
    allScores = { ...allScores, [myName]: myScoreMap };
  }

  // Chores in THIS allocation only — drawn from the allocation result, not the
  // full active-chore set. So "Cannot do" never lists chores that weren't part
  // of this round (Shopping etc.) that the member happens to be incapable of.
  const allocationChoreTitles = new Set(
    (alloc || []).flatMap(a => (a.chores || []).map(c => c?.title ?? c))
  );
  const choreList = (household?.chores || []).filter(c => c.is_active);
  const allocationChoreObjs = choreList.filter(c => allocationChoreTitles.has(c.title));
  function getRestrictions(memberId) {
    return allocationChoreObjs
      .filter(c => c.capabilities && c.capabilities[String(memberId)] === false)
      .map(c => c.title);
  }

  // Build chore title -> id map (for myPreferences lookup which is keyed by chore_id)
  const choreTitleToId = {};
  choreList.forEach(c => { choreTitleToId[c.title] = c.id; });

  // Get a member's score for a chore from allocation scores (by name + title)
  function getScore(memberName, choreTitle) {
    return allScores[memberName]?.[choreTitle];
  }


  // Fair share badge based on ratio to average — includes % display
  function getFairShareBadge(burden) {
    if (avgBurden === 0) return null;
    const ratio = burden / avgBurden;
    const pct = Math.round(ratio * 100);
    const bg = getBurdenColor(ratio);
    const label = pct <= 125 ? `Fair share · ${pct}%` : pct <= 160 ? `Slightly above · ${pct}%` : `Above fair share · ${pct}%`;
    return { label, bg };
  }

  // Load label based on ratio to average burden across this allocation.
  // Uses avgBurden (computed above) so "light"/"fair"/"heavy" is relative, not absolute.
  function getLoadLabel(burden) {
    if (avgBurden === 0) return 'no load';
    const ratio = burden / avgBurden;
    if (ratio <= 0.70) return 'light load';
    if (ratio <= 1.35) return 'fair load';
    return 'heavy load';
  }

  const hasScores = Object.keys(allScores).length > 0;

  return (
    <div className="screen screen-results fade-in">
      <div className="results-header">
        <BackButton onBack={() => onNavigate('home')} light />
        <h1 className="results-title">{isHistoryView ? 'Past allocation' : 'Chores split! 🎉'}</h1>
        <p className="results-sub">{isHistoryView ? (results.date_label || 'Previous round') : "Here's what's fair for everyone."}</p>
      </div>
      <div className="screen-scroll">
        <div className="metrics-row">
          <div className="metric-box">
            <span className="metric-label">Method</span>
            <span className="metric-value-sm">{ALGORITHMS.find(a => a.key === results.algorithm)?.label || results.algorithm}</span>
          </div>
        </div>

        {allMembers.map((member, i) => {
          const memberItem   = alloc.find(a => a.member_id === member.id);
          const isCurrentUser = user && member.id === user.id;
          const showExpanded  = expandedMember === member.id;

          const memberName = member.name;
          const firstName  = memberName.split(' ')[0];
          const burden     = memberItem?.burden || 0;
          const chores     = memberItem?.chores || [];
          const choreCount = memberItem?.chore_count || 0;
          const restrictions = getRestrictions(member.id);
          const badge      = getFairShareBadge(burden);
          const loadLabel  = getLoadLabel(burden);

          return (
            <div key={member.id} className="result-card"
              style={isCurrentUser ? { borderLeft: '4px solid #1CB59E' } : {}}>

              {/* Card header */}
              <div className="result-card-header">
                <Avatar name={memberName} size={40} colorIndex={i} />
                <div className="result-member-block">
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span className="result-member-name">{memberName}</span>
                    {isCurrentUser && (
                      <span style={{ fontSize: '11px', background: '#1CB59E', color: '#fff',
                        padding: '2px 8px', borderRadius: 12, fontWeight: 600 }}>You</span>
                    )}
                  </div>
                  <span className="result-member-meta">
                    {choreCount} chore{choreCount !== 1 ? 's' : ''} · {loadLabel}
                  </span>
                </div>
              </div>

              {/* Chore list */}
              {chores.length === 0 ? (
                <p style={{ color: '#999', fontSize: '13px', margin: '12px 0 0 0', fontStyle: 'italic' }}>
                  No chores assigned
                </p>
              ) : (
                <ul className="result-chores">
                  {chores.map(c => {
                    const title = c?.title ?? c;
                    const cid   = c?.id ?? title;
                    const choreScore = isCurrentUser ? allScores[memberName]?.[title] : undefined;
                    return (
                      <li key={cid} className="result-chore-item">
                        <span className="result-bullet" style={{ color: '#222' }}>●</span>{' '}
                        {title}
                        {isCurrentUser && choreScore !== undefined && (
                          <span style={{ marginLeft: 6, fontSize: '15px' }}>
                            {scoreToEmoji(choreScore, choreList.length)}
                          </span>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}

              {restrictions.length > 0 && (
                <p className="result-restrictions">⚠ Cannot do: {restrictions.join(', ')}</p>
              )}

              {/* Fair share badge */}
              {!isHistoryView && badge && memberItem && (
                <div>
                  <div style={{ marginTop: 12, padding: '5px 12px', background: badge.bg,
                    color: '#fff', borderRadius: 12, fontSize: '12px', fontWeight: 600,
                    display: 'inline-block' }}>
                    {badge.label}
                  </div>
                  <p style={{ fontSize: 11, color: '#aaa', margin: '4px 0 0', fontStyle: 'italic' }}>
                    fair share = equal split between all members
                  </p>
                </div>
              )}

              {/* Show comparison button + panel (only for other members, not current user) */}
              {chores.length > 0 && hasScores && !isCurrentUser && (
                <>
                  <button
                    onClick={() => setExpandedMember(showExpanded ? null : member.id)}
                    style={{ marginTop: 12, padding: '8px 12px', fontSize: '14px',
                      background: 'rgba(28, 181, 158, 0.1)', border: 'none', borderRadius: 6,
                      cursor: 'pointer', width: '100%', textAlign: 'center',
                      color: '#1CB59E', fontWeight: 500 }}
                  >
                    {showExpanded ? '▼ ' : '▶ '} Show comparison
                  </button>

                  {showExpanded && (
                    <div style={{ marginTop: 12, padding: '12px',
                      background: 'rgba(28, 181, 158, 0.08)', borderRadius: 6, fontSize: '13px' }}>
                      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                        <thead>
                          <tr>
                            <th style={{ padding: '6px 0', textAlign: 'left', fontSize: '11px',
                              color: '#888', fontWeight: 600, width: '40%' }}>Chore</th>
                            <th style={{ padding: '6px 0', textAlign: 'center', fontSize: '11px',
                              color: '#888', fontWeight: 600, width: '30%' }}>{firstName}</th>
                            <th style={{ padding: '6px 0', textAlign: 'center', fontSize: '11px',
                              color: '#888', fontWeight: 600, width: '30%' }}>You</th>
                          </tr>
                        </thead>
                        <tbody>
                          {chores.map(choreObj => {
                            const choreName = choreObj?.title ?? choreObj;
                            const choreKey  = choreObj?.id ?? choreName;
                            const memberScore = getScore(memberItem.member, choreName);
                            const myName = user?.username || user?.name;
                            const myScore = getScore(myName, choreName);
                            const n = choreList.length;

                            return (
                              <tr key={choreKey}
                                style={{ borderBottom: '1px solid rgba(28, 181, 158, 0.2)' }}>
                                <td style={{ padding: '10px 0', textAlign: 'left' }}>{choreName}</td>
                                <td style={{ padding: '10px 4px', textAlign: 'center' }}>
                                  {memberScore !== undefined ? (
                                    <div style={{ display: 'flex', flexDirection: 'column',
                                      alignItems: 'center', gap: 3 }}>
                                      <span style={{ fontSize: '28px', lineHeight: '1' }}>
                                        {scoreToEmoji(memberScore, n)}
                                      </span>
                                      <span style={{ fontSize: '10px', color: '#666' }}>
                                        {firstName}
                                      </span>
                                    </div>
                                  ) : (
                                    <span style={{ fontSize: '10px', color: '#999' }}>not rated</span>
                                  )}
                                </td>
                                <td style={{ padding: '10px 0', textAlign: 'center' }}>
                                  <div style={{ display: 'flex', flexDirection: 'column',
                                    alignItems: 'center', gap: 3 }}>
                                    {myScore !== undefined ? (
                                      <span style={{ fontSize: '28px', lineHeight: '1' }}>
                                        {scoreToEmoji(myScore, n)}
                                      </span>
                                    ) : (
                                      <span style={{ fontSize: '10px', color: '#999' }}>not rated</span>
                                    )}
                                    <span style={{ fontSize: '10px', color: '#666' }}>You</span>
                                  </div>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                </>
              )}
            </div>
          );
        })}

        {/* Fairness summary — short, concrete, names the actual reason */}
        {!isHistoryView && (() => {
          const ef1Ok = !!results.metrics?.ef1;
          const reasons = [];

          // 1. Some members got 0 chores → fewer chores than members
          const choresInRound = (alloc || []).reduce((s, a) => s + (a.chore_count || 0), 0);
          const empties = (alloc || []).filter(a => (a.chore_count || 0) === 0);
          if (empties.length > 0 && choresInRound < (alloc || []).length) {
            reasons.push(`Only ${choresInRound} chore${choresInRound === 1 ? '' : 's'} for ${alloc.length} people — ${empties.length === 1 ? empties[0].member + ' got nothing this round' : empties.length + ' people got nothing this round'}.`);
          }

          // 2. Capability constraint forced the assignment
          const capabilityForced = (alloc || []).some(a =>
            getRestrictions(a.member_id).length > 0 && (a.chore_count || 0) > 0
          );
          if (capabilityForced) {
            reasons.push('Some chores can only be done by certain people — those constraints shaped the split.');
          }

          // 3. Past contribution rebalanced the round
          const overloaded = (alloc || [])
            .filter(a => avgBurden > 0 && (a.burden || 0) / avgBurden >= 1.4)
            .sort((a, b) => (a.past_burden || 0) - (b.past_burden || 0));
          if (overloaded.length > 0) {
            const m = overloaded[0];
            const pastNote = (m.past_burden || 0) === 0
              ? 'starting fresh'
              : 'lightest cumulative load coming in';
            reasons.push(`${m.member} got more than fair share this round — ${pastNote}, so the algorithm rebalances toward them.`);
          }

          // 4. Strong preference disagreement — algorithm exploited it
          const choreCount = allocationChoreObjs.length;
          if (reasons.length === 0 && choreCount >= 2 && ef1Ok) {
            reasons.push('Different people minded different chores, so the algorithm matched each chore to whoever minds it least.');
          }

          return (
            <div style={{ marginTop: 24, padding: '14px 16px',
              background: ef1Ok ? 'rgba(79,158,91,0.10)' : 'rgba(199,120,0,0.10)',
              borderRadius: 10,
              border: `1px solid ${ef1Ok ? 'rgba(79,158,91,0.35)' : 'rgba(199,120,0,0.35)'}` }}>
              <p style={{ margin: 0, color: ef1Ok ? '#2E7D32' : '#C77800',
                fontWeight: 600, fontSize: 14, lineHeight: 1.45 }}>
                {ef1Ok
                  ? '✓ Fair split — no one is more than one chore worse off than anyone else.'
                  : '⚠ Best the algorithm could do under the constraints — not perfectly even.'}
              </p>
              {reasons.length > 0 && (
                <ul style={{ margin: '8px 0 0', paddingLeft: 18, color: '#444',
                  fontSize: 13, lineHeight: 1.5 }}>
                  {reasons.map((r, i) => <li key={i}>{r}</li>)}
                </ul>
              )}
            </div>
          );
        })()}

        <div style={{ height: 24 }} />
        {isHistoryView ? (
          <button className="btn btn-ghost" onClick={() => onNavigate('home')}>
            Back to home
          </button>
        ) : (
          <>
            <p style={{ fontSize: 12, color: 'var(--sub)', textAlign: 'center', margin: '0 0 10px', lineHeight: 1.5 }}>
              Confirming saves this allocation to the database.
            </p>
            <button className="btn btn-navy" onClick={() => onConfirm(results)}>
              Confirm allocation
            </button>
            <button className="btn btn-ghost" style={{ marginTop: 12 }}
              onClick={() => onNavigate('allocate-confirm')}>
              Try a different algorithm
            </button>
          </>
        )}
        <div style={{ height: 40 }} />
      </div>
    </div>
  );
}

// ─── SCREEN: JOIN ───────────────────────────────────────────────────────────

function JoinScreen({ onNavigate, onUnauth, onRefresh }) {
  const [code, setCode]       = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState('');

  async function handleJoin(e) {
    e.preventDefault(); setError(''); setLoading(true);
    try {
      const res = await apiFetch('/api/households/join', { method: 'POST', body: JSON.stringify({ code: code.toUpperCase() }) }, onUnauth);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Not found');
      await onRefresh();
      onNavigate('home');
    } catch (err) { setError(err.message); setLoading(false); }
  }

  return (
    <div className="screen screen-auth fade-in">
      <div className="auth-header">
        <BackButton onBack={() => onNavigate('home')} />
        <h1 className="auth-title">Join a Household</h1>
        <p className="auth-sub">Enter the code your admin shared</p>
      </div>
      <form className="auth-form" onSubmit={handleJoin}>
        <input className="join-code-input" type="text" placeholder="ABC123" maxLength={6}
          value={code} onChange={e => setCode(e.target.value.toUpperCase())} autoComplete="off" autoFocus />
        {error && <div className="error-card">Code not found. Check with your admin.</div>}
        <button className="btn btn-teal" type="submit" disabled={loading || code.length < 4}>
          {loading ? <Spinner /> : 'Join'}
        </button>
      </form>
    </div>
  );
}

// ─── SCREEN: CREATE ─────────────────────────────────────────────────────────

function CreateScreen({ onNavigate, onUnauth, onRefresh }) {
  const [name, setName]       = useState('');
  const [loading, setLoading] = useState(false);
  const [created, setCreated] = useState(null);
  const [error, setError]     = useState('');

  async function handleCreate(e) {
    e.preventDefault(); setError(''); setLoading(true);
    try {
      const res = await apiFetch('/api/households', { method: 'POST', body: JSON.stringify({ name }) }, onUnauth);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed');
      setCreated(data); await onRefresh();
    } catch (err) { setError(err.message); setLoading(false); }
  }

  if (created) {
    return (
      <div className="screen screen-auth fade-in">
        <div className="success-card">
          <div className="success-icon">🎉</div>
          <h2 className="success-title">Household created!</h2>
          <p className="success-sub">Your join code is</p>
          <div className="success-code">{created.join_code}</div>
          <p className="success-hint">Share this with your housemates</p>
          <button className="btn btn-teal" style={{ marginTop: 24 }} onClick={() => onNavigate('home')}>
            Go to Home
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="screen screen-auth fade-in">
      <ErrorBanner message={error} onDismiss={() => setError('')} />
      <div className="auth-header">
        <BackButton onBack={() => onNavigate('home')} />
        <h1 className="auth-title">Create a Household</h1>
        <p className="auth-sub">Give your household a name</p>
      </div>
      <form className="auth-form" onSubmit={handleCreate}>
        <div className="field"><label className="field-label">Household Name</label>
          <input className="field-input" type="text" placeholder="e.g. Flat 42, The Smith Family"
            value={name} onChange={e => setName(e.target.value)} required />
        </div>
        <button className="btn btn-teal" type="submit" disabled={loading || !name.trim()}>
          {loading ? <Spinner /> : 'Create'}
        </button>
      </form>
    </div>
  );
}

// ─── ROOT APP ───────────────────────────────────────────────────────────────

export default function App() {
  const [screen, setScreen]             = useState('welcome');
  const [user, setUser]                 = useState(null);
  const [households, setHouseholds]     = useState([]);
  const [household, setHousehold]       = useState(null);
  const [readiness, setReadiness]       = useState([]);
  // latestAllocation removed — current allocation data comes from allocHistory (database).
  const [allocResults, setAllocResults] = useState(null);
  const [balance, setBalance]           = useState(null);
  const [myPreferences, setMyPreferences] = useState(null);
  const [allocHistory, setAllocHistory] = useState([]);  // from /api/history (database)
  const [householdsLoaded, setHouseholdsLoaded] = useState(false);  // false until first fetch finishes

  const nav = useCallback(s => {
    // Clear stale dry-run results when starting a new allocation flow
    if (s === 'allocate-confirm') setAllocResults(null);
    setScreen(s);
  }, []);

  const handleUnauth = useCallback(() => {
    clearAuth(); setUser(null); setHousehold(null); setHouseholds([]); setReadiness([]);
    setAllocHistory([]); setBalance(null); setMyPreferences(null);
    setHouseholdsLoaded(false); setScreen('welcome');
  }, []);

  const fetchReadiness = useCallback(async (hId) => {
    if (!hId) { setReadiness([]); return; }
    try {
      const res = await apiFetch(`/api/households/${hId}/preferences-ready`, {}, handleUnauth);
      const data = await res.json();
      if (Array.isArray(data)) setReadiness(data);
    } catch (e) { /* swallow */ }
  }, [handleUnauth]);

  const fetchBalance = useCallback(async (hId) => {
    if (!hId) { setBalance(null); return; }
    try {
      const res = await apiFetch(`/api/households/${hId}/burden-balance`, {}, handleUnauth);
      const data = await res.json();
      setBalance(data);
    } catch (e) { /* swallow */ }
  }, [handleUnauth]);

  const fetchMyPreferences = useCallback(async (hId) => {
    if (!hId) { setMyPreferences(null); return; }
    try {
      const res = await apiFetch(`/api/households/${hId}/my-preferences`, {}, handleUnauth);
      const data = await res.json();
      setMyPreferences(data);
    } catch (e) { /* swallow */ }
  }, [handleUnauth]);

  const fetchHistory = useCallback(async (hId) => {
    if (!hId) { setAllocHistory([]); return; }
    try {
      const res = await apiFetch(`/api/households/${hId}/history`, {}, handleUnauth);
      const data = await res.json();
      if (Array.isArray(data)) setAllocHistory(data);
    } catch (e) { /* swallow */ }
  }, [handleUnauth]);

  const fetchHouseholds = useCallback(async () => {
    try {
      const res  = await apiFetch('/api/households', {}, handleUnauth);
      const list = await res.json();
      if (!Array.isArray(list)) return;
      setHouseholds(list);
      if (list.length > 0) {
        const hRes  = await apiFetch(`/api/households/${list[0].id}`, {}, handleUnauth);
        const hData = await hRes.json();
        if (hRes.ok) {
          setHousehold(hData);
          fetchHistory(hData.id);
          fetchReadiness(hData.id);
          fetchBalance(hData.id);
          fetchMyPreferences(hData.id);
          fetchHistory(hData.id);
        }
      } else {
        setHousehold(null); setAllocHistory([]); setReadiness([]); setBalance(null); setMyPreferences(null);
      }
    } catch (err) {
      if (err.message !== 'Unauthorized') console.error(err);
    } finally {
      setHouseholdsLoaded(true);
    }
  }, [handleUnauth, fetchReadiness, fetchBalance, fetchMyPreferences, fetchHistory]);

  const fetchRef = useRef(fetchHouseholds);
  useEffect(() => { fetchRef.current = fetchHouseholds; });

  // On mount: restore auth + all a11y prefs
  useEffect(() => {
    const auth = getAuth();
    if (auth?.user) { setUser(auth.user); setScreen('home'); fetchRef.current(); }
    if (localStorage.getItem('fairchore_hc') === '1') {
      document.documentElement.classList.add('high-contrast');
    }
    try {
      const a11y = JSON.parse(localStorage.getItem('fairchore_a11y') || '{}');
      const sizeMap = { small: '0.9em', large: '1.15em' };
      if (a11y.textSize && sizeMap[a11y.textSize]) {
        document.documentElement.style.fontSize = sizeMap[a11y.textSize];
      }
      if (a11y.reduceMotion) document.body.classList.add('reduce-motion');
      if (a11y.colorBlind)   document.body.classList.add('colorblind');
    } catch { /* ignore */ }
  }, []);

  const handleUpdateUser = useCallback(({ name, email }) => {
    setUser(prev => {
      const next = { ...prev, username: name, name, email };
      const auth = getAuth();
      if (auth) saveAuth({ ...auth, user: next });
      return next;
    });
  }, []);

  const handleAuth = useCallback(u => { setUser(u); setScreen('home'); fetchHouseholds(); }, [fetchHouseholds]);
  const handleRefresh = useCallback(async () => { await fetchHouseholds(); }, [fetchHouseholds]);

  const toggleAssignmentDone = useCallback(async (assignmentId, currentlyDone) => {
    const method = currentlyDone ? 'DELETE' : 'POST';
    try {
      await apiFetch(`/api/assignments/${assignmentId}/complete`, { method }, handleUnauth);
      if (household?.id) await fetchHistory(household.id);
    } catch (e) { console.error(e); }
  }, [handleUnauth, fetchHistory, household?.id]);

  const switchHousehold = useCallback(async (hId) => {
    try {
      const hRes = await apiFetch(`/api/households/${hId}`, {}, handleUnauth);
      const hData = await hRes.json();
      if (hRes.ok) {
        setHousehold(hData);
        fetchReadiness(hId);
        fetchBalance(hId);
        fetchMyPreferences(hId);
        fetchHistory(hId);
        setScreen('home');
      }
    } catch (err) { console.error(err); }
  }, [handleUnauth, fetchReadiness, fetchBalance, fetchMyPreferences, fetchHistory]);

  const confirmAlloc = useCallback(async results => {
    if (!household?.id || !results) return;
    const hid = household.id;
    try {
      // POST the allocation to the backend — this is what saves to the database.
      // Until this point, nothing has been written (allocate was a dry run).
      const res = await apiFetch(`/api/households/${hid}/allocate/confirm`, {
        method: 'POST',
        body: JSON.stringify({
          algorithm: results.algorithm,
          allocation: results.allocation,
          scores: results.scores || {},
          metrics: results.metrics || {},
        }),
      }, handleUnauth);
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error || 'Confirm failed');
      }
      // Refresh history from database — the new round will now appear
      await fetchHistory(hid);
      await fetchBalance(hid);
      setAllocResults(null);
      nav('home');
    } catch (e) {
      alert(`Could not save allocation: ${e.message}`);
    }
  }, [household?.id, handleUnauth, fetchHistory, fetchBalance, nav]);

  const handleAllocResults = useCallback(results => {
    // Store allocation in React state only — not in the database (dry run).
    // The database save happens only when the user clicks "Confirm allocation".
    setAllocResults(results);
  }, []);

  const common = { onNavigate: nav, onUnauth: handleUnauth };

  return (
    <div className="app-root">
      <div className="phone-frame">
        <div className="btn-silent"></div>
        <div className="btn-volume-up"></div>
        <div className="btn-volume-down"></div>
        <div className="btn-power"></div>
        <div className="phone-screen-wrap">
          <div className="dynamic-island"></div>
          <div className="phone-screen">
            <div className="screen-content">
              {screen === 'welcome' && <WelcomeScreen {...common} />}
              {screen === 'login' && <LoginScreen {...common} onAuth={handleAuth} />}
              {screen === 'register' && <RegisterScreen {...common} onAuth={handleAuth} />}
              {screen === 'home' && (
                <HomeScreen {...common} user={user} household={household} households={households}
                  readiness={readiness} balance={balance}
                  myPreferences={myPreferences} allocHistory={allocHistory}
                  onToggleDone={toggleAssignmentDone}
                  loading={!householdsLoaded && !!user} />
              )}
              {screen === 'chores' && (
                <ChoresScreen {...common} user={user} household={household}
                  allocHistory={allocHistory} readiness={readiness}
                  onRefresh={handleRefresh} onToggleDone={toggleAssignmentDone} />
              )}
              {screen === 'settings' && (
                <SettingsScreen {...common} user={user} household={household} households={households}
                  readiness={readiness} onSignOut={handleUnauth} onRefresh={handleRefresh}
                  onSwitchHousehold={switchHousehold} onUpdateUser={handleUpdateUser} />
              )}
              {screen === 'preferences' && (
                <PreferencesScreen {...common} household={household} allocHistory={allocHistory}
                  onRefresh={async () => {
                    if (household?.id) { await fetchReadiness(household.id); await fetchMyPreferences(household.id); }
                  }} />
              )}
              {screen === 'add-chore' && (
                <AddChoreScreen {...common} household={household} onRefresh={handleRefresh} />
              )}
              {screen === 'join' && <JoinScreen {...common} onRefresh={handleRefresh} />}
              {screen === 'create' && <CreateScreen {...common} onRefresh={handleRefresh} />}
              {screen === 'allocate-confirm' && (
                <AllocateConfirmScreen {...common} household={household} readiness={readiness}
                  allocHistory={allocHistory} onResults={handleAllocResults} />
              )}
              {screen === 'loading' && <LoadingScreen />}
              {screen === 'results' && (
                <ResultsScreen {...common}
                  results={allocResults || (allocHistory[0] ? {
                    algorithm: allocHistory[0].algorithm,
                    allocation: allocHistory[0].assignments.map(a => ({
                      member_id: a.member_id, member: a.member,
                      chores: a.chores, burden: 0, chore_count: a.chores.length,
                    })),
                    scores: allocHistory[0].scores || {},
                    metrics: allocHistory[0].metrics || {},
                    from_history: true,
                    date_label: allocHistory[0].date_label,
                  } : null)}
                  onConfirm={confirmAlloc} household={household} user={user} myPreferences={myPreferences} />
              )}
            </div>
          </div>
          <div className="home-indicator"></div>
        </div>
      </div>
    </div>
  );
}
