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
          dark: '#08090d',
          card: '#10131b',
          cardBorder: '#1c2233',
          header: '#131826',
          cyan: '#00e5ff',
          neonGreen: '#00e676',
          gold: '#ffd700',
          orange: '#ff9100',
          red: '#ff5252',
          muted: '#8a95aa',
          hover: '#192033',
        }
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'Courier New', 'monospace'],
      }
    },
  },
  plugins: [],
}
