/** "updated 12 s ago" for polling screens; re-renders on its own so the age stays honest between polls. */
import { useEffect, useState } from "react";
import { fmtAgo, fmtDateTime } from "../../lib/format";

export function Updated({ at }: { at: number }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 5_000);
    return () => clearInterval(id);
  }, []);
  if (!at) return null;
  const iso = new Date(at).toISOString();
  return <span title={fmtDateTime(iso)}>updated {fmtAgo(iso, now)}</span>;
}
