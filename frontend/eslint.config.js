// Lint config focused on one job: making the Rules of Hooks enforceable.
//
// A `useState` declared after a conditional `return` in Analysis.tsx crashed
// the entire application whenever the loaded report became null -- React
// counted five hooks on one render and four on the next, threw "Rendered fewer
// hooks than expected", and the root ErrorBoundary replaced the whole UI with
// "Something went wrong". `tsc -b` and `vite build` both passed the entire
// time, because neither has any concept of hook ordering. Nothing in the
// toolchain could have caught it.
//
// react-hooks/rules-of-hooks catches exactly that, statically, in a second.
// It is wired into `npm run build` so it cannot be skipped by forgetting to
// run a separate command.

import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import jsxA11y from "eslint-plugin-jsx-a11y";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "node_modules"] },
  {
    files: ["src/**/*.{ts,tsx}"],
    // The TypeScript parser has to be set explicitly. Without it ESLint uses
    // espree, which cannot parse `interface`, `!` non-null assertions or type
    // annotations, and every file fails with a parsing error before any rule
    // gets a chance to run -- which looks like a lint failure but is really
    // the linter never having read the code.
    languageOptions: {
      parser: tseslint.parser,
      ecmaVersion: 2022,
      sourceType: "module",
      globals: globals.browser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    plugins: { "react-hooks": reactHooks, "jsx-a11y": jsxA11y },
    rules: {
      // The two that matter here. Errors, not warnings: a hooks-order
      // violation is a guaranteed crash, not a style preference.
      "react-hooks/rules-of-hooks": "error",
      // Exhaustive-deps stays a warning -- it catches real staleness bugs but
      // also fires on intentional patterns, and turning it into a build
      // blocker on an existing codebase would just get it disabled.
      "react-hooks/exhaustive-deps": "warn",

      // Accessibility. Added because the app had zero alt attributes, zero
      // tabIndex, and icon-only buttons whose only label was a native `title`
      // tooltip -- which screen readers do not reliably announce and touch
      // users never see at all.
      //
      // These are the rules whose violations are genuine barriers rather than
      // stylistic. They are errors so `npm run build` cannot regress them;
      // fixing by eye alone is what let the gap open in the first place.
      ...jsxA11y.flatConfigs.recommended.rules,
      "jsx-a11y/alt-text": "error",
      "jsx-a11y/anchor-has-content": "error",
      "jsx-a11y/aria-props": "error",
      "jsx-a11y/aria-role": "error",
      "jsx-a11y/role-has-required-aria-props": "error",
      "jsx-a11y/no-redundant-roles": "error",
      // An element given a click handler must be reachable and operable by
      // keyboard. This is the rule that catches a <div onClick> acting as a
      // button.
      "jsx-a11y/click-events-have-key-events": "error",
      "jsx-a11y/no-static-element-interactions": "error",
      "jsx-a11y/interactive-supports-focus": "error",
    },
  },
);
