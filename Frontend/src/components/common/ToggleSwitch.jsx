// Shared Active/Inactive switch (Question status, User account status).
export default function ToggleSwitch({ checked, onChange, activeLabel = 'Active', inactiveLabel = 'Inactive' }) {
  return (
    <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
      <span
        onClick={() => onChange(!checked)}
        style={{
          width: 38, height: 21, borderRadius: 999, position: 'relative', transition: 'background .15s ease',
          background: checked ? 'var(--green)' : 'var(--line-soft)', flexShrink: 0,
        }}
      >
        <span
          style={{
            position: 'absolute', top: 2, left: checked ? 19 : 2, width: 17, height: 17, borderRadius: '50%',
            background: '#fff', transition: 'left .15s ease', boxShadow: '0 1px 3px rgba(0,0,0,.25)',
          }}
        />
      </span>
      <span style={{ fontSize: 12.5, fontWeight: 600, color: checked ? 'var(--green)' : 'var(--muted)' }}>
        {checked ? activeLabel : inactiveLabel}
      </span>
    </label>
  );
}
