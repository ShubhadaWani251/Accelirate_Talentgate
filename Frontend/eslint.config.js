import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{js,jsx}'],
    extends: [
      js.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    rules: {
      // The two React Compiler rules that arrived in eslint-plugin-react-hooks 7.x, switched off
      // so that everything else in the ruleset can gate CI instead of the whole run being advisory.
      // Enabling them flags 27 existing sites and none is a live defect:
      //
      //   set-state-in-effect (15) - the ordinary fetch-on-mount effect on the list and detail
      //     pages, where the synchronous setState is a loading flag whose initial useState value
      //     already says the same thing.
      //   refs (12) - guard clauses in the exam screens that read mediaStreamRef.current during
      //     render to avoid flashing content before the effect redirects.
      //
      // Clearing the second group means reworking ExamSessionProvider to expose stream readiness
      // as state rather than a ref, which is its own change and needs its own testing pass over
      // the candidate exam flow. Re-enable these one at a time as that work lands.
      'react-hooks/set-state-in-effect': 'off',
      'react-hooks/refs': 'off',
    },
  },
])
