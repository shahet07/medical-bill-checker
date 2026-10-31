// Line icons for the website (24×24, drawn with the current text color).
const PATHS: Record<string, string> = {
  duplicate: "M8 8h11v11H8zM5 16V5h11",
  mismatch: "M5 9h14M5 15h14M16 5L8 19",
  denied: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM8.5 8.5l7 7M15.5 8.5l-7 7",
  network: "M12 4v4M5 20v-3a3 3 0 0 1 3-3h8a3 3 0 0 1 3 3v3M12 14v6M9 4h6v4H9z",
  missing: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5M10 12.5a2 2 0 1 1 2.6 1.9c-.4.2-.6.5-.6.9v.2M12 18h.01",
  payment: "M3 7h18v10H3zM3 11h18M7 15h3",
  unbundled: "M4 6h7v5H4zM13 13h7v5h-7zM11 8.5h2.5a1.5 1.5 0 0 1 1.5 1.5v3",
  itemized: "M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01",
  letter: "M4 6h16v12H4zM4 7l8 6 8-6",
  phone: "M6 3h3l2 5-2.5 1.5a11 11 0 0 0 6 6L16 13l5 2v3a2 2 0 0 1-2 2A16 16 0 0 1 4 5a2 2 0 0 1 2-2z",
  refund: "M9 14L4 9l5-5M4 9h11a5 5 0 0 1 0 10h-3",
  radar: "M12 12l6-6M12 3a9 9 0 1 0 9 9M12 7a5 5 0 1 0 5 5M12 11a1 1 0 1 0 0 2 1 1 0 0 0 0-2z",
  ask: "M4 5h16v11H9l-5 4zM9 10h.01M12 10h.01M15 10h.01",
  words: "M4 5h6a2 2 0 0 1 2 2v13a2 2 0 0 0-2-2H4zM20 5h-6a2 2 0 0 0-2 2v13a2 2 0 0 1 2-2h6z",
  lock: "M6 11h12v9H6zM9 11V8a3 3 0 0 1 6 0v3",
  clock: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v5l3 2",
  trash: "M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0M3 3l18 18",
  device: "M8 2h8a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2zM11 18h2",
  upload: "M12 16V4M7 9l5-5 5 5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3",
  eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z",
  send: "M4 12l16-8-6 16-2.5-6.5zM11.5 13.5L20 4",
  chevron: "M6 9l6 6 6-6",
};

export default function Icon(props: { name: string; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={"icon " + (props.className ?? "")} aria-hidden="true" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
      <path d={PATHS[props.name]} />
    </svg>
  );
}
