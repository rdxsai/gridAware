const ICONS = {
  data_center: `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
      <rect x="3" y="3" width="18" height="6" rx="1.4"/>
      <rect x="3" y="10.5" width="18" height="6" rx="1.4"/>
      <rect x="3" y="18" width="18" height="3.2" rx="1"/>
      <line x1="6" y1="6" x2="6.01" y2="6"/>
      <line x1="6" y1="13.5" x2="6.01" y2="13.5"/>
      <line x1="9.5" y1="6" x2="14" y2="6"/>
      <line x1="9.5" y1="13.5" x2="14" y2="13.5"/>
    </svg>`,

  battery: `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
      <rect x="2" y="7" width="16" height="10" rx="2"/>
      <line x1="22" y1="11" x2="22" y2="13"/>
      <polyline points="11 9 8 13.5 12 13.5 9 17"/>
    </svg>`,

  generator: `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="8.5"/>
      <path d="M9 7.5h4a2.5 2.5 0 0 1 0 5h-2.5a2.5 2.5 0 0 0 0 5H15"/>
      <line x1="12" y1="5" x2="12" y2="7.5"/>
      <line x1="12" y1="17.5" x2="12" y2="20"/>
    </svg>`,

  reactive_support: `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
      <line x1="2" y1="12" x2="9" y2="12"/>
      <line x1="15" y1="12" x2="22" y2="12"/>
      <line x1="9" y1="5" x2="9" y2="19"/>
      <line x1="15" y1="5" x2="15" y2="19"/>
    </svg>`,

  slack: `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
      <path d="M9 2v6"/>
      <path d="M15 2v6"/>
      <path d="M5 8h14l-1.5 6a3.5 3.5 0 0 1-3.4 2.7h-4.2A3.5 3.5 0 0 1 6.5 14L5 8z"/>
      <path d="M12 16.7V22"/>
    </svg>`,
};

export function iconSvg(kind) {
  return ICONS[kind] || "";
}
