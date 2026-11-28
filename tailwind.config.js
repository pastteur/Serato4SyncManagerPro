/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        serato: {
          dark: '#05070c',
          card: '#0d121d',
          cardBorder: '#1b2438',
          header: '#0a0e18',
          cyan: '#00e5ff',
          neonGreen: '#00e676',
          gold: '#ffd700',
          orange: '#ff9100',
          red: '#ff5252',
          muted: '#8a95aa',
          hover: '#162033',
          purple: '#a855f7',
        }
      },
      boxShadow: {
        'glow-cyan': '0 0 20px -5px rgba(0, 229, 255, 0.35)',
        'glow-emerald': '0 0 20px -5px rgba(0, 230, 118, 0.30)',
        'glow-amber': '0 0 20px -5px rgba(255, 193, 7, 0.30)',
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'Courier New', 'monospace'],
      }
    },
  },
  plugins: [],
}
