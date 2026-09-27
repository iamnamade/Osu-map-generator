export type GeneratorIconName =
  | "brand"
  | "terminal"
  | "workspace"
  | "audio"
  | "background"
  | "difficulties"
  | "job"
  | "lock"
  | "upload"
  | "download"
  | "game"
  | "editor"
  | "package"
  | "copy"
  | "help"
  | "settings"
  | "docs"
  | "check"
  | "warning"
  | "error"
  | "arrow-right"
  | "refresh";

const ICON_PATHS: Record<GeneratorIconName, string> = {
  brand:
    '<path d="M12 3.5a8.5 8.5 0 1 0 8.5 8.5A8.51 8.51 0 0 0 12 3.5Zm0 4a4.5 4.5 0 1 1-4.5 4.5A4.5 4.5 0 0 1 12 7.5Z"/><path d="M12 0.75v3M12 20.25v3M0.75 12h3M20.25 12h3M4.22 4.22l2.12 2.12M17.66 17.66l2.12 2.12M19.78 4.22l-2.12 2.12M6.34 17.66l-2.12 2.12"/>',
  terminal:
    '<rect x="3.5" y="5" width="17" height="14" rx="2"/><path d="m7.25 10 2.5 2-2.5 2"/><path d="M12 14h4.75"/>',
  workspace:
    '<path d="M3.5 5.5h5l1.5 1.5h10v11H3.5z"/><path d="M3.5 9h16.5"/>',
  audio:
    '<path d="M8 18V7l8-1.5V16"/><circle cx="8" cy="18" r="2"/><circle cx="16" cy="16" r="2"/>',
  background:
    '<rect x="3.5" y="5" width="17" height="14" rx="2"/><path d="m6.5 16 3.5-4 3 3 2.5-2.5 2 3.5"/><circle cx="9" cy="9" r="1.5"/>',
  difficulties:
    '<path d="M5 18V12M10 18V8M15 18V5M20 18V10"/>',
  job:
    '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5v5l3 2"/>',
  lock:
    '<rect x="5" y="10" width="14" height="10" rx="2"/><path d="M8 10V7.75A4 4 0 0 1 12 3.75a4 4 0 0 1 4 4V10"/>',
  upload:
    '<path d="M12 16V6"/><path d="m8.5 9.5 3.5-3.5 3.5 3.5"/><path d="M4.5 18.5h15"/>',
  download:
    '<path d="M12 5.5v10"/><path d="m8.5 12 3.5 3.5 3.5-3.5"/><path d="M4.5 18.5h15"/>',
  game:
    '<rect x="4" y="8" width="16" height="8" rx="3"/><path d="M8 12h4M10 10v4"/><circle cx="16.5" cy="11" r="1"/><circle cx="18.5" cy="13" r="1"/>',
  editor:
    '<path d="M5 18.5h4l8.75-8.75-4-4L5 14.5z"/><path d="m12.75 6.75 4 4"/>',
  package:
    '<path d="M4.5 8.5 12 4l7.5 4.5v7L12 20l-7.5-4.5z"/><path d="M4.5 8.5 12 13l7.5-4.5"/><path d="M12 13v7"/>',
  copy:
    '<rect x="8" y="8" width="10" height="12" rx="2"/><rect x="5" y="4" width="10" height="12" rx="2"/>',
  help:
    '<circle cx="12" cy="12" r="8.5"/><path d="M9.75 9.25a2.6 2.6 0 1 1 4.07 2.16c-.91.67-1.57 1.17-1.57 2.34"/><circle cx="12" cy="17.1" r="0.8" fill="currentColor" stroke="none"/>',
  settings:
    '<circle cx="12" cy="12" r="2.5"/><path d="M12 2.75v2.1M12 19.15v2.1M4.93 4.93l1.48 1.48M17.59 17.59l1.48 1.48M2.75 12h2.1M19.15 12h2.1M4.93 19.07l1.48-1.48M17.59 6.41l1.48-1.48"/>',
  docs:
    '<path d="M7 4.5h8l2 2V19.5H7z"/><path d="M15 4.5v3h3"/><path d="M9.5 11.5h5M9.5 14.5h5"/>',
  check:
    '<circle cx="12" cy="12" r="8.5"/><path d="m8.5 12.25 2.25 2.25 4.75-5"/>',
  warning:
    '<path d="M12 3.5 21 19H3z"/><path d="M12 9v4.5"/><circle cx="12" cy="16.25" r="0.75" fill="currentColor" stroke="none"/>',
  error:
    '<circle cx="12" cy="12" r="8.5"/><path d="m9 9 6 6M15 9l-6 6"/>',
  "arrow-right":
    '<path d="M5 12h14"/><path d="m14 7 5 5-5 5"/>',
  refresh:
    '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3"/><path d="M19.5 3.75V7.5h-3.75"/>',
};

export function renderIcon(
  name: GeneratorIconName,
  className = "",
  title: string | undefined = undefined,
): string {
  const paths = ICON_PATHS[name];
  const titleMarkup = title ? `<title>${title}</title>` : "";
  const classAttribute = className ? ` ${className}` : "";
  return `
    <svg
      class="generator-icon${classAttribute}"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="1.6"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="${title ? "false" : "true"}"
      ${title ? 'role="img"' : ""}
    >
      ${titleMarkup}
      ${paths}
    </svg>
  `;
}
