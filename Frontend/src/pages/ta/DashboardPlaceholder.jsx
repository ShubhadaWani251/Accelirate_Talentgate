import { Link } from 'react-router-dom';

export default function TaDashboardPlaceholder() {
  return (
    <div>
      <h3>Staffing User Dashboard</h3>
      <p style={{ color: 'var(--muted)', fontSize: 13 }}>
        Your batches overview lands here in a later phase.
      </p>
      <div className="btn-row" style={{ display: 'flex', gap: 10 }}>
        <Link to="/batches/new" className="btn primary" style={{ width: 'auto', textDecoration: 'none' }}>
          + Upload New Candidates
        </Link>
        <Link to="/batches" className="btn" style={{ textDecoration: 'none' }}>
          View Batches
        </Link>
      </div>
    </div>
  );
}
