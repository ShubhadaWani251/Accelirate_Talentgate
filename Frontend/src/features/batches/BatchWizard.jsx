import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import ConfigureBatchStep from './ConfigureBatchStep';
import UploadStep from './UploadStep';
import ReviewStep from './ReviewStep';
import InviteConfirmationStep from './InviteConfirmationStep';

const STEPS = [
  { key: 'configure', label: '1. Configure Batch' },
  { key: 'upload', label: '2. Upload Excel' },
  { key: 'review', label: '3. Review' },
  { key: 'invite', label: '4. Send Invite' },
];

export default function BatchWizard() {
  const navigate = useNavigate();
  const [stepKey, setStepKey] = useState('configure');
  const [batch, setBatch] = useState(null);
  const [finalizeSummary, setFinalizeSummary] = useState(null);

  const stepIndex = STEPS.findIndex((s) => s.key === stepKey);

  return (
    <div className="page-wide">
      <h3>Bulk Candidate Upload &amp; Duplicate Review</h3>
      <div className="wizard-steps">
        {STEPS.map((s, i) => (
          <span key={s.key} className={`wstep ${i === stepIndex ? 'active' : i < stepIndex ? 'done' : ''}`}>
            {s.label}
          </span>
        ))}
      </div>

      {stepKey === 'configure' && (
        <ConfigureBatchStep
          onCreated={(createdBatch) => {
            setBatch(createdBatch);
            setStepKey('upload');
          }}
        />
      )}

      {stepKey === 'upload' && batch && (
        <UploadStep batch={batch} onUploaded={() => setStepKey('review')} />
      )}

      {stepKey === 'review' && batch && (
        <ReviewStep
          batch={batch}
          onFinalized={(summary) => {
            setFinalizeSummary(summary);
            setStepKey('invite');
          }}
        />
      )}

      {stepKey === 'invite' && finalizeSummary && (
        <InviteConfirmationStep
          summary={finalizeSummary}
          onBack={() => setStepKey('review')}
          onSent={() => navigate(`/batches/${finalizeSummary.batch_id}`)}
        />
      )}
    </div>
  );
}
