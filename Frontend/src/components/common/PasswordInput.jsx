import { forwardRef, useState } from 'react';
import { FiEye, FiEyeOff } from 'react-icons/fi';

// forwardRef is required here, not just convenience - react-hook-form's register() returns a
// real ref it attaches to the input DOM node directly, so wrapping without forwarding it would
// silently break form state tracking for every password field that uses this component.
const PasswordInput = forwardRef(function PasswordInput({ className = '', ...props }, ref) {
  const [visible, setVisible] = useState(false);

  return (
    <div className="password-input-wrap">
      <input ref={ref} type={visible ? 'text' : 'password'} className={className} {...props} />
      <button
        type="button"
        className="password-toggle"
        onClick={() => setVisible((v) => !v)}
        tabIndex={-1}
        aria-label={visible ? 'Hide password' : 'Show password'}
      >
        {visible ? <FiEyeOff /> : <FiEye />}
      </button>
    </div>
  );
});

export default PasswordInput;
