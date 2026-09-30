/** STUB — "Ask the system" drawer (read-only Q&A agent via POST /api/ask). Being implemented. */
export function AskDrawer({ onClose }: { onClose: () => void }) {
  return (
    <div className="overlay" onClick={onClose}>
      <aside className="drawer" onClick={(e) => e.stopPropagation()} aria-label="Ask the system">
        <div className="row between">
          <h2>Ask the system</h2>
          <button className="btn small" type="button" onClick={onClose}>
            Close
          </button>
        </div>
        <p className="muted">Being built.</p>
      </aside>
    </div>
  );
}
