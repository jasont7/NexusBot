import type { Config } from 'tailwindcss';

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#0a0a0a',
        surface: '#141414',
        'surface-hover': '#1e1e1e',
        border: '#2a2a2a',
        'border-hover': '#444',
        text: '#e0e0e0',
        'text-dim': '#888',
        accent: '#4da6ff',
        'accent-dim': '#2a6cb3',
        success: '#44cc66',
        error: '#ff4444',
        warning: '#ffd700',
        purple: '#bb88ff',
        cyan: '#66dddd',
        orange: '#ffaa44',
      },
      fontFamily: {
        mono: ['SF Mono', 'Monaco', 'Cascadia Code', 'Fira Code', 'monospace'],
      },
    },
  },
  plugins: [],
} satisfies Config;
