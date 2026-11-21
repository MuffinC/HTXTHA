// A small set of inline SVG icons (no icon font or CDN: the app runs fully offline).
// Icons are decorative (aria-hidden); every status also carries visible text.
const PATHS = {
  check: 'M4 10.5l4 4 8-9',
  cross: 'M5 5l10 10M15 5L5 15',
  alert: 'M10 3l8 14H2L10 3zm0 5v4m0 2.5v.5',
  info: 'M10 2a8 8 0 100 16 8 8 0 000-16zm0 5v.5M10 9v5',
  shield: 'M10 2l7 3v5c0 4-3 7-7 8-4-1-7-4-7-8V5l7-3z',
  upload: 'M10 13V3m0 0L6 7m4-4l4 4M3 13v3h14v-3',
  file: 'M5 2h7l4 4v12H5V2zm7 0v4h4',
  spinner: '', // drawn specially below: ring + arc
  clock: 'M10 2a8 8 0 100 16 8 8 0 000-16zm0 4v4l3 2',
  eye: 'M1 10s3-6 9-6 9 6 9 6-3 6-9 6-9-6-9-6zm9-3a3 3 0 100 6 3 3 0 000-6z',
  close: 'M5 5l10 10M15 5L5 15',
  page: 'M5 2h10v16H5V2zm3 4h4M8 9h4m-4 3h3',
  plug: 'M7 2v4m6-4v4M5 6h10v3a5 5 0 01-10 0V6zm5 8v4',
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({ name, className }: { name: IconName; className?: string }) {
  return (
    <svg
      className={`icon icon-${name}${className ? ` ${className}` : ''}`}
      viewBox="0 0 20 20"
      width="16"
      height="16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {name === 'spinner' ? (
        <>
          <circle cx="10" cy="10" r="7" strokeOpacity="0.25" />
          <path d="M10 3a7 7 0 017 7" />
        </>
      ) : (
        <path d={PATHS[name]} />
      )}
    </svg>
  );
}
