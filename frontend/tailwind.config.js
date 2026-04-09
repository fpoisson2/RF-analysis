/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Design system: easily customizable brand colors
        brand: {
          50: 'var(--color-brand-50, #f0fdf4)',
          100: 'var(--color-brand-100, #dcfce7)',
          200: 'var(--color-brand-200, #bbf7d0)',
          300: 'var(--color-brand-300, #86efac)',
          400: 'var(--color-brand-400, #4ade80)',
          500: 'var(--color-brand-500, #22c55e)',
          600: 'var(--color-brand-600, #16a34a)',
          700: 'var(--color-brand-700, #15803d)',
          800: 'var(--color-brand-800, #166534)',
          900: 'var(--color-brand-900, #14532d)',
        },
        surface: {
          0: 'var(--color-surface-0, #030712)',
          1: 'var(--color-surface-1, #0a0f1a)',
          2: 'var(--color-surface-2, #111827)',
          3: 'var(--color-surface-3, #1f2937)',
          4: 'var(--color-surface-4, #374151)',
        },
      },
      fontFamily: {
        sans: ['var(--font-sans, "Inter", system-ui, sans-serif)'],
        mono: ['var(--font-mono, "JetBrains Mono", monospace)'],
      },
      borderRadius: {
        DEFAULT: 'var(--radius, 0.5rem)',
      },
    },
  },
  plugins: [],
}
