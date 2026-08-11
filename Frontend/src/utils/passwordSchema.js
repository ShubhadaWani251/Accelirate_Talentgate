import * as yup from 'yup';

// Mirrors Backend/api/validators.py ComplexityValidator (min_length=10) - keep in sync.
export const passwordSchema = yup
  .string()
  .min(10, 'At least 10 characters')
  .matches(/[A-Z]/, 'Must include an uppercase letter')
  .matches(/[a-z]/, 'Must include a lowercase letter')
  .matches(/[0-9]/, 'Must include a digit')
  .matches(/[^A-Za-z0-9]/, 'Must include a special character (e.g. !@#$%^&*)')
  .required('New password is required');

export const PASSWORD_HINT =
  'At least 10 characters, with an uppercase letter, a lowercase letter, a digit, and a special character.';

// Pulls the first useful message out of a DRF error response - handles both the plain
// {detail: "..."} shape and field-error shapes like {new_password: ["..."]}.
export function extractErrorMessage(err, fields = ['new_password', 'confirm_password', 'current_password', 'otp']) {
  const data = err.response?.data;
  if (!data) return 'Something went wrong. Please try again.';
  for (const field of fields) {
    if (data[field]?.[0]) return data[field][0];
  }
  return data.detail || 'Something went wrong. Please try again.';
}
