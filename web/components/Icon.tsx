const paths = {
  eye:
    "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Zm13 0a3 3 0 1 1-6 0 3 3 0 0 1 6 0",
  eyeOff:
    "m3 3 18 18M10 5h2c6 0 10 7 10 7s-1 2-3 4M6 6c-3 2-4 6-4 6s4 7 10 7c2 0 3-1 4-1M9 9a4 4 0 0 0 6 6",
  terminal: "m5 7 5 5-5 5m8 0h6M3 3h18v18H3Z",
  settings:
    "M9 3h6l1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1ZM15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0",
  logout: "M9 4H4v16h5m5-13 5 5-5 5M8 12h13",
  chat: "M21 11a8 8 0 0 1-8 8H8l-5 3V11a9 9 0 0 1 18 0ZM7 10h10M7 14h6",
  home: "m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1Z",
  play: "m9 5 11 7-11 7Z",
  chart: "M4 19V9m8 10V4m8 15v-6M2 22h20",
  arrow: "M5 12h14m-5-5 5 5-5 5",
  back: "M19 12H5m5-5-5 5 5 5",
  check: "m5 12 4 4L19 6",
  close: "m6 6 12 12M6 18 18 6",
  info: "M12 16v-4m0-4h.01M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
  code: "m8 6-6 6 6 6m8-12 6 6-6 6m-3-15-2 18",
  clock: "M12 8v4l3 2m7-2a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
  layers: "m12 3 10 5-10 5L2 8Zm-10 9 10 5 10-5M2 16l10 5 10-5",
  download: "M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5",
  compare: "M4 4h6v16H4zm10 0h6v16h-6",
  pause: "M7 5v14M17 5v14",
  restart: "M3 10a9 9 0 1 1 2 9M3 4v6h6",
  training:
    "M4 17a9 9 0 0 1 14-12l3 3M21 3v5h-5M20 7a9 9 0 0 1-14 12l-3-3M3 21v-5h5",
  plus: "M12 5v14M5 12h14",
  stop: "M6 6h12v12H6Z",
} as const;

export function Icon(
  { name, size = 20 }: { name: keyof typeof paths; size?: number },
) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="1.75"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name]} />
    </svg>
  );
}
