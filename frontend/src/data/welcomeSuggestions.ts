/**
 * Static welcome-screen suggestions for the empty-state launcher.
 *
 * Uses Assistant UI's `SuggestionConfig` shape:
 * `{ title: string; label: string; prompt: string }`.
 *
 * Categories, descriptions, and runtime skill integration are not yet
 * included — keep this list basic. Extend by appending to the array;
 * ChatScreen renders all entries without code changes.
 */
export const WELCOME_SUGGESTIONS = [
  {
    title: "Explain code",
    label: "step-by-step walkthrough",
    prompt: "Explain what this code does, step by step:\n\n",
  },
  {
    title: "Fix a bug",
    label: "diagnose and repair",
    prompt: "Help me diagnose and fix this issue:\n\n",
  },
  {
    title: "Refactor",
    label: "improve readability",
    prompt: "Refactor this code for clarity and maintainability:\n\n",
  },
  {
    title: "Write tests",
    label: "unit or integration",
    prompt: "Write tests for the following code:\n\n",
  },
];
